"""Generate + POST a router routing-schema (chat) that splits inbound WA
traffic between champion and candidate by phone last digit.

Architecture
------------

Inbound WA messages currently land directly on the champion chat schema
(e.g. CO_ schema id=110). To run an A/B test, we want a thin "router"
schema in front: it inspects the caller phone (`${user}` channel-var)
and dispatches to either the champion or the candidate flow.

Generated payload (page "main"):

    start
      ↓
    js  — sets ${ab_variant} ∈ {"candidate","champion"} from last digit
      ↓
    switch ${ab_variant}
       ├── case "candidate" → schema(candidate_schema_id)
       └── default          → schema(champion_schema_id)

The cross-schema jump uses Webitel's dedicated `schema` node type
(visible in the visual editor as a block titled "Schema" with a
chain-link icon). Its body shape mirrors `joinQueue`'s queue ref:

    "schema": {
      "schema": { "id": <int>, "name": "<schema name>" },
      "async":  false,
      "break":  false
    }

This is distinct from `customModule`, which only invokes pages within
the same payload (UUID).

CLI
---

    python -m app.router_schema preview CO_           # dump to stdout
    python -m app.router_schema setup   CO_ --confirm # POST + save
    python -m app.router_schema show    CO_           # fetch live router
    python -m app.router_schema unlink  CO_           # drop link from
                                                      # companies.json (does
                                                      # NOT delete in Webitel)
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import wa_bot_config as wabc
from . import webitel_schema_io as wio
from .data import Company, load_companies
from .webitel import WebitelClient, WebitelError


DEFAULT_CANDIDATE_DIGITS = (0, 1, 2)


# --- ID helpers -------------------------------------------------------------

def _new_node_id() -> str:
    """Webitel uses 16-char lowercase hex for node ids."""
    return secrets.token_hex(8)


def _new_port_id() -> str:
    """Ports use UUID4 (with dashes) in the live payload."""
    return str(uuid.uuid4())


def _new_conn_id() -> str:
    return secrets.token_hex(8)


# --- Node builders ----------------------------------------------------------

def _input_port(port_id: str) -> dict:
    return {
        "id": port_id,
        "label": port_id,
        "type": "in",
        "socket": {"name": "socket"},
        "multipleConnections": True,
        "showControl": True,
        "control": None,
    }


def _output_port(port_id: str, position: int) -> dict:
    return {
        "id": port_id,
        "label": port_id,
        "type": "out",
        "socket": {"name": "socket"},
        "position": position,
        "goto": False,
        "multipleConnections": False,
    }


def _make_node(
    *,
    label: str,
    page_id: str,
    schema: dict,
    n_outputs: int = 1,
    n_inputs: int = 1,
    description: Optional[str] = None,
) -> tuple[dict, list[str], list[str]]:
    """Return (node, input_port_ids, output_port_ids)."""
    nid = _new_node_id()
    in_ids = [_new_port_id() for _ in range(n_inputs)]
    out_ids = [_new_port_id() for _ in range(n_outputs)]
    node = {
        "id": nid,
        "label": label,
        "pageId": page_id,
        "description": description,
        "inputs": {pid: _input_port(pid) for pid in in_ids},
        "outputs": {
            pid: _output_port(pid, i) for i, pid in enumerate(out_ids)
        },
        "commons": {"break": False, "limit": None},
        "controls": {},
        "schema": schema,
        "tag": f"{label}__{nid}",
    }
    return node, in_ids, out_ids


def _make_connection(
    src_node: dict, src_port: str,
    tgt_node: dict, tgt_port: str,
    page_id: str,
) -> dict:
    return {
        "id": _new_conn_id(),
        "pageId": page_id,
        "source": src_node["id"],
        "sourceOutput": src_port,
        "target": tgt_node["id"],
        "targetInput": tgt_port,
    }


# --- Payload generator ------------------------------------------------------

def _js_split_body(candidate_digits: list[int], variable_name: str) -> str:
    """Body of the js node that classifies the inbound caller into a cohort.
    Reads the configured channel var (default `${user}`), extracts the last
    digit, returns the cohort label.

    NB: a previous version called a non-existent `_setChannelVar(...)` to
    also expose the last digit as a channel-var. Webitel's JS engine
    raises ReferenceError on that name, the whole script aborts before
    `return`, and the cohort variable stays empty (silently — no alert).
    Only `_getChannelVar` is supported in this JS context. To set extra
    channel-vars, use a separate `set` or `js` node downstream.
    """
    digits_lit = "[" + ", ".join(f'"{int(d)}"' for d in sorted(set(candidate_digits))) + "]"
    return (
        "var phone = String(_getChannelVar('" + variable_name + "') || '');\n"
        "var lastDigit = phone.length > 0 ? phone.charAt(phone.length - 1) : '';\n"
        "var candidateDigits = " + digits_lit + ";\n"
        "var isCandidate = candidateDigits.indexOf(lastDigit) >= 0;\n"
        "return isCandidate ? 'candidate' : 'champion';"
    )


def _schema_node_body(target_id: int, target_name: str) -> dict:
    """Body of a `schema` node — Webitel's cross-schema invocation primitive
    for chat flows (visible in the editor as the chain-link "Schema" block).
    Mirrors `joinQueue` shape: a nested ref object with id+name, plus the
    standard async/break flags."""
    return {
        "schema": {"id": int(target_id), "name": str(target_name or "")},
        "async": False,
        "break": False,
    }


def build_router_payload(
    champion_id: int,
    candidate_id: int,
    candidate_digits: Optional[list[int]] = None,
    *,
    variable_name: str = "user",
    champion_name: str = "",
    candidate_name: str = "",
) -> dict:
    """Produce a `payload` dict (nodes/connections/positions/pages) for a
    router chat-schema."""
    digits = list(candidate_digits or DEFAULT_CANDIDATE_DIGITS)
    page_id = "main"

    start, _, start_outs = _make_node(
        label="start", page_id=page_id, schema={},
        n_inputs=0, n_outputs=1,
    )
    js, js_ins, js_outs = _make_node(
        label="js", page_id=page_id,
        schema={
            "data": _js_split_body(digits, variable_name),
            "setVar": "ab_variant",
        },
    )
    switch, sw_ins, sw_outs = _make_node(
        label="switch", page_id=page_id,
        schema={
            "variable": "${ab_variant}",
            "case": [
                {"text": "candidate"},
                {"text": "default"},
            ],
        },
        n_outputs=2,
    )

    cand, cand_ins, _ = _make_node(
        label="schema", page_id=page_id,
        description=f"A/B router → CANDIDATE schema id={candidate_id}",
        schema=_schema_node_body(candidate_id, candidate_name),
    )
    champ, champ_ins, _ = _make_node(
        label="schema", page_id=page_id,
        description=f"A/B router → CHAMPION schema id={champion_id}",
        schema=_schema_node_body(champion_id, champion_name),
    )

    nodes = [start, js, switch, cand, champ]
    connections = [
        _make_connection(start, start_outs[0], js, js_ins[0], page_id),
        _make_connection(js, js_outs[0], switch, sw_ins[0], page_id),
        _make_connection(switch, sw_outs[0], cand, cand_ins[0], page_id),
        _make_connection(switch, sw_outs[1], champ, champ_ins[0], page_id),
    ]
    positions = {
        start["id"]: {"x": 0, "y": 0},
        js["id"]: {"x": 280, "y": 0},
        switch["id"]: {"x": 560, "y": 0},
        cand["id"]: {"x": 880, "y": -120},
        champ["id"]: {"x": 880, "y": 120},
    }
    return {
        "nodes": nodes,
        "connections": connections,
        "positions": positions,
        "pages": [{"id": "main", "name": "main"}],
    }


def build_router_schema_object(
    name: str,
    champion_id: int,
    candidate_id: int,
    candidate_digits: Optional[list[int]] = None,
    *,
    variable_name: str = "user",
    champion_name: str = "",
    candidate_name: str = "",
) -> dict:
    """Full schema object ready for `WebitelClient.create_schema`.

    NB: Webitel rejects `tags` on chat-schema POST (HTTP 500
    `store.sql_routing_schema.save.app_error`) — the field isn't even
    present in the live API response shape — so we omit it. `schema` must
    be present (empty list is fine; Webitel recompiles from `payload`).
    """
    return {
        "name": name,
        "type": "chat",
        "editor": True,
        "schema": [],
        "payload": build_router_payload(
            champion_id, candidate_id, candidate_digits,
            variable_name=variable_name,
            champion_name=champion_name,
            candidate_name=candidate_name,
        ),
    }


# --- Persistence -------------------------------------------------------------

def get_router_schema(company_key: str) -> tuple[Optional[str], Optional[int]]:
    info = wabc.load_raw().get(company_key, {})
    wa = ((info.get("bots") or {}).get("whatsapp") or {})
    name = wa.get("router_schema_name")
    sid = wa.get("router_schema_id")
    try:
        sid = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        sid = None
    return (str(name) if name else None, sid)


def set_router_schema(company_key: str, schema_id: int, schema_name: str) -> None:
    raw = wabc.load_raw()
    info = raw.setdefault(company_key, {})
    bots = info.setdefault("bots", {})
    wa = bots.setdefault("whatsapp", {})
    wa["router_schema_id"] = int(schema_id)
    wa["router_schema_name"] = str(schema_name)
    wabc.save_raw(raw)


def clear_router_schema(company_key: str) -> None:
    raw = wabc.load_raw()
    wa = ((raw.get(company_key) or {}).get("bots") or {}).get("whatsapp") or {}
    changed = False
    for k in ("router_schema_id", "router_schema_name"):
        if k in wa:
            wa.pop(k, None)
            changed = True
    if changed:
        wabc.save_raw(raw)


# --- Top-level API -----------------------------------------------------------

def _company(company_key: str) -> Company:
    for c in load_companies():
        if c.key == company_key:
            return c
    raise KeyError(f"company {company_key!r} not in companies.json")


def _client(company: Company) -> WebitelClient:
    if not company.webitel_host or not company.webitel_access_token:
        raise WebitelError(
            f"company {company.key} has no webitel_host/webitel_access_token"
        )
    return WebitelClient(company.webitel_host, company.webitel_access_token)


def _default_router_name(champion_name: str) -> str:
    if champion_name and "prod" in champion_name:
        return champion_name.replace("prod", "router")
    if champion_name:
        return f"{champion_name}-router"
    return "router"


def _candidate_digits_for(company_key: str) -> list[int]:
    """Pull from bot_cfg's ab_split block; default {0,1,2}."""
    try:
        from .audit_storage import get_ab_split
        cfg = wabc.load_config(company_key)
        ab = get_ab_split(cfg or {})
        digits = list(ab.get("candidate_digits") or [])
    except Exception:
        digits = []
    out: list[int] = []
    for d in digits:
        try:
            di = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= di <= 9 and di not in out:
            out.append(di)
    return out or list(DEFAULT_CANDIDATE_DIGITS)


def preview(company_key: str) -> dict:
    """Build the router schema body without POSTing. Returns the body."""
    champ_name, champ_id = wabc.get_prod_schema(company_key)
    cand_name, cand_id = wabc.get_candidate_schema(company_key)
    if not champ_id or not cand_id:
        raise ValueError(
            f"{company_key}: need both champion and candidate schema ids "
            f"(champion={champ_id}, candidate={cand_id}). "
            f"Run `python -m app.calibration_apply clone-candidate {company_key}` "
            f"first."
        )
    digits = _candidate_digits_for(company_key)
    name = _default_router_name(champ_name or "")
    return build_router_schema_object(
        name, int(champ_id), int(cand_id), digits,
        champion_name=champ_name or "",
        candidate_name=cand_name or "",
    )


def setup(company_key: str, *, confirm: bool, name_override: Optional[str] = None) -> dict:
    """Generate the router schema and POST it to Webitel. Persists the
    new schema id under `bots.whatsapp.router_schema_*` in companies.json.
    Snapshots the request body locally before sending.
    """
    body = preview(company_key)
    if name_override:
        body["name"] = name_override

    # Snapshot the body we're about to send.
    company = _company(company_key)
    snap_dir = wio.snapshots_root() / company_key
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snap_path = snap_dir / f"router-create_{ts}.json"
    snap_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not confirm:
        return {
            "posted": False,
            "name": body["name"],
            "snapshot_path": str(snap_path),
            "reason": "dry-run (no --confirm)",
        }

    existing_name, existing_id = get_router_schema(company_key)
    if existing_id:
        raise ValueError(
            f"{company_key} already has a router schema "
            f"(id={existing_id}, name={existing_name!r}). Use `unlink` first "
            f"or delete it manually in Webitel UI."
        )

    client = _client(company)
    created = client.create_schema(body)
    new_id = int(created.get("id"))
    new_name = str(created.get("name") or body["name"])
    set_router_schema(company_key, new_id, new_name)
    return {
        "posted": True,
        "router_schema_id": new_id,
        "router_schema_name": new_name,
        "snapshot_path": str(snap_path),
    }


def show(company_key: str) -> Optional[dict]:
    name, sid = get_router_schema(company_key)
    if not sid:
        return None
    client = _client(_company(company_key))
    return client.get_schema(int(sid))


# --- CLI --------------------------------------------------------------------

def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="router_schema")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prev = sub.add_parser("preview",
        help="Print the router schema body that would be POSTed (no write)")
    p_prev.add_argument("company_key")

    p_setup = sub.add_parser("setup",
        help="POST the router schema to Webitel and link it in companies.json")
    p_setup.add_argument("company_key")
    p_setup.add_argument("--confirm", action="store_true",
        help="Required to actually POST. Without it, only generates+snapshots.")
    p_setup.add_argument("--name", default=None,
        help="Override the generated router schema name.")

    p_show = sub.add_parser("show",
        help="Fetch the live router schema from Webitel and print")
    p_show.add_argument("company_key")

    p_unlink = sub.add_parser("unlink",
        help="Drop router_schema_id/name from companies.json. Does NOT "
             "delete the schema in Webitel — clean up there manually.")
    p_unlink.add_argument("company_key")

    args = parser.parse_args(argv)

    if args.cmd == "preview":
        body = preview(args.company_key)
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "setup":
        try:
            res = setup(
                args.company_key,
                confirm=bool(args.confirm),
                name_override=args.name,
            )
        except (ValueError, KeyError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except WebitelError as e:
            print(f"webitel error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if not res.get("posted"):
            print(
                "\nDry run — body snapshotted but NOT sent to Webitel.\n"
                "Re-run with --confirm to POST and link.",
                file=sys.stderr,
            )
        return 0

    if args.cmd == "show":
        try:
            obj = show(args.company_key)
        except (KeyError, WebitelError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if obj is None:
            print(f"{args.company_key}: no router schema linked")
            return 1
        # Drop the bulky compiled `schema` field for readability.
        obj_pretty = {k: v for k, v in obj.items() if k != "schema"}
        print(json.dumps(obj_pretty, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "unlink":
        clear_router_schema(args.company_key)
        print(f"{args.company_key}: router_schema_* fields cleared in companies.json")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
