"""Apply the new Alert-page payload to a target Webitel chat schema.

Workflow:
  1. fetch full schema by id;
  2. find the Alert page (by name, falling back to the conventional
     uuid if needed);
  3. strip every existing node/connection/position belonging to that
     page from `payload`;
  4. inject the 3 new nodes (start → js → httpRequest), 2 connections,
     3 positions produced by `alert_page_builder.build_alert_page`;
  5. snapshot the pre-edit object;
  6. push via `webitel_schema_io.push_payload` with conflict-check;
  7. snapshot the post-edit object;
  8. update `calibration_cycle` state baseline so the schema_drift_guard
     doesn't trip on the next cycle (this is OUR edit — legitimate).

The caller is expected to confirm: business-page `customModule.moduleId`
references stay valid because we keep the page id unchanged. All upstream
call sites continue to work.

CLI:

    python -m app.alert_page_apply preview CO_ candidate
        # dump the new Alert page payload (nodes/conns/positions) to stdout
    python -m app.alert_page_apply apply   CO_ candidate --confirm
        # PUT to Webitel; without --confirm = dry-run with snapshot
    python -m app.alert_page_apply apply   CO_ champion  --confirm
        # apply to champion (rare; usually promote via cycle)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Optional

from . import alert_page_builder as apb
from . import webitel_schema_io as wio
from .data import Company, load_companies
from .wa_bot_config import get_candidate_schema, get_prod_schema
from .webitel import WebitelClient, WebitelConflict, WebitelError


ALERT_PAGE_UUID_FALLBACK = "5a1402d5-58e5-45a8-8822-3d07658d1eb3"


def _company(company_key: str) -> Company:
    for c in load_companies():
        if c.key == company_key:
            return c
    raise KeyError(f"company {company_key!r} not in companies.json")


def _client(co: Company) -> WebitelClient:
    if not co.webitel_host or not co.webitel_access_token:
        raise WebitelError(f"company {co.key} has no webitel host/token")
    return WebitelClient(co.webitel_host, co.webitel_access_token)


def _resolve_target_schema(
    company_key: str, role: str,
) -> tuple[int, str]:
    """role ∈ {champion, candidate}. Returns (schema_id, schema_name)."""
    role = role.lower()
    if role == "champion":
        name, sid = get_prod_schema(company_key)
    elif role == "candidate":
        name, sid = get_candidate_schema(company_key)
    else:
        raise ValueError(f"unknown role {role!r}; use champion|candidate")
    if not sid:
        raise KeyError(
            f"{company_key} has no {role} schema id in companies.json"
        )
    return int(sid), str(name or "")


def _find_alert_page_id(payload: dict) -> Optional[str]:
    pages = payload.get("pages") or []
    for p in pages:
        if (p.get("name") or "").lower() == "alert":
            return p.get("id")
    # Fall back to the well-known UUID seen in all 4 prod-bots.
    for p in pages:
        if p.get("id") == ALERT_PAGE_UUID_FALLBACK:
            return p.get("id")
    return None


def _strip_alert_page(payload: dict, alert_pid: str) -> dict:
    """Return a copy of `payload` with every node/connection on the
    Alert page removed and the corresponding `positions` entries
    dropped. The `pages` entry stays — call sites still resolve to it
    via customModule.moduleId."""
    nodes = payload.get("nodes") or []
    conns = payload.get("connections") or []
    positions = payload.get("positions") or {}

    keep_node_ids = {n.get("id") for n in nodes if n.get("pageId") != alert_pid}
    new_nodes = [n for n in nodes if n.get("id") in keep_node_ids]
    new_conns = [
        c for c in conns
        if c.get("source") in keep_node_ids
        and c.get("target") in keep_node_ids
    ]
    new_positions = {
        nid: pos for nid, pos in positions.items() if nid in keep_node_ids
    }
    return {
        **payload,
        "nodes": new_nodes,
        "connections": new_conns,
        "positions": new_positions,
    }


def build_replacement_payload(
    base_payload: dict,
    *,
    schema_id: int,
    schema_role: str,
) -> tuple[dict, str]:
    """Compute the new payload (Alert page replaced) without touching
    Webitel. Returns (new_payload, alert_page_id)."""
    alert_pid = _find_alert_page_id(base_payload)
    if not alert_pid:
        raise ValueError("no Alert page found in payload (nor fallback uuid)")

    stripped = _strip_alert_page(base_payload, alert_pid)
    new_nodes, new_conns, new_positions = apb.build_alert_page(
        alert_pid, schema_id=schema_id, schema_role=schema_role,
    )

    merged_payload = {
        **stripped,
        "nodes": list(stripped["nodes"]) + new_nodes,
        "connections": list(stripped["connections"]) + new_conns,
        "positions": {**stripped["positions"], **new_positions},
    }
    return merged_payload, alert_pid


def apply(
    company_key: str,
    role: str,
    *,
    confirm: bool = False,
    snapshot_label: str = "alert-page-replace",
) -> dict:
    """Build, snapshot, optionally PUT. Returns a dict with all relevant
    paths/ids for the operator to review."""
    co = _company(company_key)
    schema_id, schema_name = _resolve_target_schema(company_key, role)
    client = _client(co)

    full = client.get_schema(schema_id)
    base_payload = full.get("payload") or {}
    new_payload, alert_pid = build_replacement_payload(
        base_payload, schema_id=schema_id, schema_role=role,
    )

    snap_before = wio.make_snapshot(
        company_key, schema_id, full,
        label=f"{snapshot_label}-before",
    )

    if not confirm:
        # Persist the would-be payload as a snapshot too, so the
        # operator can diff before approving.
        from pathlib import Path
        from .paths import data_dir
        prev_dir = data_dir() / "webitel_schema_snapshots" / company_key
        prev_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        preview_path = prev_dir / f"{schema_id}_{ts}_alert-page-replace-preview.json"
        preview_obj = {**full, "payload": new_payload}
        preview_path.write_text(
            json.dumps(preview_obj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "posted": False,
            "company_key": company_key,
            "schema_id": schema_id,
            "schema_name": schema_name,
            "schema_role": role,
            "alert_page_id": alert_pid,
            "snapshot_before": str(snap_before),
            "preview_path": str(preview_path),
            "reason": "dry-run (no --confirm)",
        }

    expected_updated_at = str(full.get("updated_at") or "")
    try:
        resp = wio.push_payload(
            client, schema_id, new_payload,
            expected_updated_at=expected_updated_at,
            base_object=full,
        )
    except WebitelConflict as e:
        return {
            "posted": False,
            "company_key": company_key,
            "schema_id": schema_id,
            "snapshot_before": str(snap_before),
            "error": f"conflict: {e}",
        }
    except WebitelError as e:
        return {
            "posted": False,
            "company_key": company_key,
            "schema_id": schema_id,
            "snapshot_before": str(snap_before),
            "error": f"PUT failed: {e}",
        }

    snap_after = wio.make_snapshot(
        company_key, schema_id, resp or full,
        label=f"{snapshot_label}-after",
    )

    # Update calibration_cycle drift baseline so the next cycle doesn't
    # trip schema_drift_guard on our legitimate edit.
    try:
        from . import calibration_cycle as cc
        cc._record_known_updated_at(
            company_key, schema_id,
            str((resp or {}).get("updated_at") or ""),
            "HQ_access",
        )
    except Exception:
        pass

    return {
        "posted": True,
        "company_key": company_key,
        "schema_id": schema_id,
        "schema_name": schema_name,
        "schema_role": role,
        "alert_page_id": alert_pid,
        "snapshot_before": str(snap_before),
        "snapshot_after": str(snap_after),
        "new_updated_at": str((resp or {}).get("updated_at") or ""),
    }


def _cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="alert_page_apply")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_prev = sub.add_parser("preview", help="Print the Alert-page replacement payload (no write)")
    p_prev.add_argument("company_key")
    p_prev.add_argument("role", choices=("candidate", "champion"))

    p_apply = sub.add_parser("apply", help="Apply the new Alert page (snapshots + push)")
    p_apply.add_argument("company_key")
    p_apply.add_argument("role", choices=("candidate", "champion"))
    p_apply.add_argument("--confirm", action="store_true",
        help="Required to actually PUT. Without it, snapshots-only.")

    args = p.parse_args(argv)

    if args.cmd == "preview":
        # Build off live fetch but don't snapshot
        co = _company(args.company_key)
        sid, _ = _resolve_target_schema(args.company_key, args.role)
        client = _client(co)
        full = client.get_schema(sid)
        new_payload, alert_pid = build_replacement_payload(
            full.get("payload") or {},
            schema_id=sid, schema_role=args.role,
        )
        # Show only the alert-page nodes for readability.
        alert_nodes = [n for n in new_payload["nodes"] if n.get("pageId") == alert_pid]
        alert_conns = [
            c for c in new_payload["connections"]
            if c.get("pageId") == alert_pid
        ]
        out = {
            "company_key": args.company_key,
            "schema_id": sid,
            "schema_role": args.role,
            "alert_page_id": alert_pid,
            "new_alert_nodes": alert_nodes,
            "new_alert_connections": alert_conns,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "apply":
        try:
            res = apply(
                args.company_key, args.role,
                confirm=bool(args.confirm),
            )
        except (KeyError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except WebitelError as e:
            print(f"webitel: {e}", file=sys.stderr)
            return 2
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if not res.get("posted"):
            print(
                "\nDry run — snapshots written but Webitel NOT modified.\n"
                "Re-run with --confirm to PUT.",
                file=sys.stderr,
            )
        return 0 if res.get("posted") else 1

    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
