"""End-to-end test of a company's action tree against a real client.

Flow:
  1. Pick a phone of a client with an active loan and 90+ DPD via DB.
  2. Fetch CRM data for that phone via the company's `crm_host`.
  3. Walk the action tree and enumerate every possible result-leaf path
     (contact_type → contact_result → optional promise_type / amount).
  4. For each leaf, build the POST body using the tree's `produces` map +
     bot-kind side-roots (direction/phone/comment/loan_id/collector_id/
     call_type) and POST it to `crm_results_host`.
  5. Return per-path status (OK / error reason) plus the loan's admin URL
     so the user can click through to the CRM to verify.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from .action_trees import (
    enumerate_main_paths,
    get_configured_text,
    get_format_choice,
    get_tree,
    resolve_value_source,
)
from .crm_field_types import lookup_value_by_type
from .crm_lookup import call_crm_by_phone, fetch_active_loan_phone_dpd90
from .crm_results import get_body_schema, post_result
from .data import Company, load_raw


SIDE_ROOTS = (
    "loan_id", "collector_id", "call_type",
    "direction", "phone", "comment",
)


def _path_label(path: list[tuple[str, Optional[dict]]]) -> str:
    bits: list[str] = []
    for _vn, val in path:
        if val is None:
            continue
        bits.append(val.get("label") or val.get("value") or "")
    return " / ".join([b for b in bits if b])


def _resolve_filling(
    company: Company,
    var_name: str,
    var_def: dict,
    crm_payload: dict,
    company_info: dict,
) -> tuple[Optional[str], Optional[str]]:
    # promise_date is user_input — for tests we synthesize today+7 days.
    src = var_def.get("value_source")
    if src == "user_input" and var_name == "promise_date":
        fmt = get_format_choice(
            company.key, var_name, "DD.MM.YYYY"
        )
        py_fmt = fmt.replace("DD", "%d").replace("MM", "%m").replace("YYYY", "%Y")
        py_fmt = py_fmt.replace("HH", "%H").replace("mm", "%M")
        return (datetime.now() + timedelta(days=7)).strftime(py_fmt), None
    return resolve_value_source(
        company.key, var_name, var_def, crm_payload, company_info
    )


def _build_body(
    company: Company,
    tree_def: dict,
    bot_kind: str,
    path: list[tuple[str, Optional[dict]]],
    crm_payload: dict,
    company_info: dict,
    phone_override: str,
) -> tuple[dict, list[str]]:
    """Build the POST body for one leaf path. Returns (body, warnings)."""
    variables = tree_def.get("variables") or {}
    body: dict = {}
    warnings: list[str] = []

    # 1. Main path — asking and filling vars contribute via `produces`.
    for var_name, chosen in path:
        var_def = variables.get(var_name) or {}
        field = var_def.get("produces")
        if not field:
            continue
        if chosen is not None:
            body[field] = chosen.get("value")
        else:
            value, err = _resolve_filling(
                company, var_name, var_def, crm_payload, company_info
            )
            if err:
                warnings.append(f"{field}: {err}")
            if value is not None:
                body[field] = value

    # 2. Side-roots — pick the value with matching bot_kind and resolve.
    for root in SIDE_ROOTS:
        rdef = variables.get(root)
        if not rdef:
            continue
        match = next(
            (
                v
                for v in (rdef.get("values") or [])
                if v.get("bot_kind") == bot_kind
            ),
            None,
        )
        if not match:
            continue
        nxt_name = match.get("next_variable")
        if not nxt_name:
            continue
        nv = variables.get(nxt_name) or {}
        field = nv.get("produces")
        if not field:
            continue
        value, err = _resolve_filling(
            company, nxt_name, nv, crm_payload, company_info
        )
        if err:
            warnings.append(f"{field}: {err}")
        if value is not None:
            body[field] = value

    # 3. Override phone_number with the actual phone we tested against.
    body["phone_number"] = phone_override
    return body, warnings


def run_test(
    company: Company,
    bot_kind: str,
) -> dict:
    """Execute the full test flow. Returns a dict:
        {
          "phone": str | None,
          "loan_url": str | None,
          "results": [
              {
                "label": str,
                "ok": bool,
                "error": str | None,
                "warnings": [str],
                "body": dict,
                "status": int,
                "response": str,
              },
              ...
          ],
          "fatal": str | None,   # set when we couldn't even start
        }
    """
    out: dict = {"phone": None, "loan_url": None, "results": [], "fatal": None}

    tree_def = get_tree(company.key)
    if not tree_def:
        out["fatal"] = "Дерево действий не описано для этой компании"
        return out

    schema = get_body_schema(company.key)
    if not schema:
        out["fatal"] = "Схема тела результата не описана для этой компании"
        return out

    phone, err = fetch_active_loan_phone_dpd90(company)
    if err:
        out["fatal"] = err
        return out
    out["phone"] = phone

    info = load_raw().get(company.key, {})
    crm_host = (info.get("crm_host") or "").strip()
    header_name = (info.get("crm_token_header") or "").strip()
    header_value = (info.get("crm_access_token") or "").strip()
    if not crm_host:
        out["fatal"] = "crm_host не задан"
        return out

    status, body_text, err = call_crm_by_phone(
        crm_host, header_name, header_value, phone
    )
    if err:
        out["fatal"] = f"GET CRM: {err}"
        return out
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as e:
        out["fatal"] = f"CRM ответил не JSON: {e}"
        return out
    if not isinstance(payload, dict):
        out["fatal"] = "CRM ответ — не объект"
        return out

    loan_url = lookup_value_by_type(company.key, payload, "admin.loan_url")
    out["loan_url"] = str(loan_url) if loan_url else None

    paths = enumerate_main_paths(tree_def, root_var="contact_type")
    for path in paths:
        label = _path_label(path)
        body, warnings = _build_body(
            company, tree_def, bot_kind, path, payload, info, phone
        )
        status_code, resp, post_err = post_result(company, body)
        ok = post_err is None and 200 <= status_code < 300
        out["results"].append({
            "label": label,
            "ok": ok,
            "error": post_err,
            "warnings": warnings,
            "body": body,
            "status": status_code,
            "response": resp,
        })

    return out
