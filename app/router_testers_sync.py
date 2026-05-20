"""Read-only sync from a company's Webitel router schema to the local
testers list.

The router schema has a `testers` page with a switch on `${user}`, one
case per active tester phone. Each non-default case routes to a `set`
node that carries the tester's `destination` override.

This module ONLY reads the schema — it never writes back. The local
`data/testers/<company>.json` reflects what the schema says: active
testers come from switch cases, removed testers stay in the JSON
flagged `active=False`.
"""
from __future__ import annotations

from typing import Optional

from .data import load_companies, load_raw
from .webitel import WebitelClient, WebitelError


def _testers_page_id(payload: dict) -> Optional[str]:
    for p in payload.get("pages") or []:
        if (p.get("name") or "").lower() == "testers":
            return p.get("id")
    return None


def _user_switch(payload: dict, page_id: str) -> Optional[dict]:
    for n in payload.get("nodes") or []:
        if n.get("pageId") != page_id or n.get("label") != "switch":
            continue
        var = str((n.get("schema") or {}).get("variable") or "")
        if "user" in var:
            return n
    return None


def fetch_router_testers(company_key: str) -> list[dict]:
    """Read the router schema's testers page. Returns a list of dicts:

        { phone: <digits>, destination: <digits>, set_pos: (x, y),
          set_node_id: <id> }

    `phone` is the switch-case text (the routing decision key).
    `destination` is taken from the set node's `set[*].value` where
    `key=='destination'` (empty string when missing/blank).
    `set_pos` is the (x, y) of the set node from `payload.positions` —
    saved into the local tester's notes so the operator can locate the
    entry in the visual editor.

    Raises `WebitelError` when the company is missing
    `bots.whatsapp.router_schema_id`, the schema has no `testers` page,
    or no switch on `${user}` can be found.
    """
    co = next((c for c in load_companies() if c.key == company_key), None)
    if co is None:
        raise KeyError(f"company {company_key!r} not in companies.json")
    if not co.webitel_host or not co.webitel_access_token:
        raise WebitelError(f"{company_key} has no webitel host/token")

    info = load_raw().get(company_key, {}) or {}
    wa = ((info.get("bots") or {}).get("whatsapp") or {})
    sid = wa.get("router_schema_id")
    if not sid:
        raise WebitelError(
            f"{company_key}: bots.whatsapp.router_schema_id is empty — "
            "set it in companies.json first"
        )

    client = WebitelClient(co.webitel_host, co.webitel_access_token)
    full = client.get_schema(int(sid))
    payload = full.get("payload") or {}
    pid = _testers_page_id(payload)
    if not pid:
        raise WebitelError(
            f"router schema id={sid} has no `testers` page"
        )
    sw = _user_switch(payload, pid)
    if sw is None:
        raise WebitelError(
            f"router schema id={sid} testers page has no switch on `${{user}}`"
        )

    nodes_by_id = {n["id"]: n for n in payload.get("nodes") or []}
    positions = payload.get("positions") or {}

    cases_by_port: dict[str, str] = {}
    for port_id, port in (sw.get("outputs") or {}).items():
        cases_by_port[port_id] = str(port.get("type") or "")

    out: list[dict] = []
    seen: set[str] = set()
    for c in payload.get("connections") or []:
        if c.get("source") != sw["id"]:
            continue
        case_text = cases_by_port.get(c.get("sourceOutput", ""), "").strip()
        if not case_text or case_text in ("default", "out"):
            continue
        if not case_text.isdigit():
            continue
        if case_text in seen:
            continue
        seen.add(case_text)
        target = nodes_by_id.get(c.get("target"))
        if target is None or target.get("label") != "set":
            continue
        dest = ""
        for kv in (target.get("schema") or {}).get("set") or []:
            if str(kv.get("key")) == "destination":
                dest = "".join(
                    ch for ch in str(kv.get("value") or "") if ch.isdigit()
                )
                break
        pos = positions.get(target["id"]) or {}
        try:
            x = float(pos.get("x", 0) or 0)
            y = float(pos.get("y", 0) or 0)
        except (TypeError, ValueError):
            x = y = 0.0
        out.append({
            "phone": case_text,
            "destination": dest,
            "set_pos": (x, y),
            "set_node_id": target["id"],
        })
    return out
