"""Read/write the `testers` page inside a router schema (e.g. CO_'s id=127).

The router has a `testers` page that overrides `${test_owner}` and
`${test_area}` for known tester phones BEFORE the A/B-split decision is
made. Layout per tester slot:

    switch ${user}
      ├── case "<phone-1>"  → set(test_owner=<name>, test_area=<area>) ─┐
      ├── case "<phone-2>"  → set(test_owner=..., test_area=...)        ├→ set(_test_context_)
      ├── ...                                                            ┘
      └── case "default"   → set(_real_client_base_)

All testers funnel into one common "test context" set node
(de3029a0) — sets process_name=...test, dpd=22, etc. The default case
goes to a separate "real client base" set node (a7c36650).

This module gives the hub:
  * `list_testers(co_key)` → list[RouterTester]
  * `save_testers(co_key, testers, ...)` → snapshot+push the full router
    schema with the testers page rebuilt from `testers`.
  * `available_test_areas(co_key)` → values from the main-page switch on
    `${test_owner}` (e.g. ['bot_prod','bot_candidate','agent','default']).

Stable node anchors (preserved across rebuilds — keeps Webitel UI happy):
  * `start` of testers page (single)
  * `switch ${user}`
  * `set` for the default real-client base (process_name has 'prod' in it)
  * `set` for the common test override (process_name has 'test' in it)

Tester nodes (per-phone set nodes + the connections + per-case ports
on the switch) are recreated on every save.
"""
from __future__ import annotations

import secrets
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

from . import webitel_schema_io as wio
from .data import Company, load_companies
from .router_schema import get_router_schema
from .webitel import WebitelClient, WebitelConflict, WebitelError


TEST_AREA_OPTIONS = ("bot_prod", "bot_candidate", "agent", "default")


# --- Data ------------------------------------------------------------------

@dataclass
class RouterTester:
    phone: str         # full digits, e.g. "573122562287"
    test_owner: str    # e.g. "Ivan"
    test_area: str     # one of TEST_AREA_OPTIONS
    destination: str = ""  # what the bot uses as `${destination}` for this
    # tester. Usually equals `phone`, but the hub model allows pointing the
    # bot at a different number (e.g. when a tester signs in from a foreign
    # SIM but should be routed against a fixed CO loan).

    def to_dict(self) -> dict:
        return {
            "phone": self.phone,
            "test_owner": self.test_owner,
            "test_area": self.test_area,
            "destination": self.destination,
        }


# --- Internal helpers (page node anchors) ----------------------------------

def _testers_page_id(payload: dict) -> Optional[str]:
    for p in payload.get("pages") or []:
        if (p.get("name") or "").lower() == "testers":
            return p.get("id")
    return None


def _node_by_id(payload: dict, nid: str) -> Optional[dict]:
    for n in payload.get("nodes") or []:
        if n.get("id") == nid:
            return n
    return None


def _find_anchors(payload: dict, page_id: str) -> dict:
    """Return {'start': node, 'switch': node, 'real_base': node,
    'test_ctx': node} — the four nodes we preserve across rebuilds.

    Identification rules:
      - start  : label=start, single on page
      - switch : label=switch with variable like '${user}' / 'user'
      - real_base : set with `process_name` value containing 'prod'
      - test_ctx  : set with `process_name` value containing 'test'
    """
    anchors: dict = {}
    for n in payload.get("nodes") or []:
        if n.get("pageId") != page_id:
            continue
        label = n.get("label")
        sch = n.get("schema") or {}
        if label == "start":
            anchors["start"] = n
        elif label == "switch":
            var = str(sch.get("variable") or "")
            if "user" in var:
                anchors["switch"] = n
        elif label == "set":
            vals = sch.get("set") or []
            for kv in vals:
                if str(kv.get("key")) == "process_name":
                    pn = str(kv.get("value") or "")
                    if "test" in pn.lower():
                        anchors["test_ctx"] = n
                    elif "prod" in pn.lower():
                        anchors["real_base"] = n
                    break
    return anchors


# --- Read ------------------------------------------------------------------

def _client_for(co_key: str) -> tuple[Company, WebitelClient]:
    co = next((c for c in load_companies() if c.key == co_key), None)
    if co is None:
        raise KeyError(f"company {co_key!r} not in companies.json")
    if not co.webitel_host or not co.webitel_access_token:
        raise WebitelError(f"company {co_key} has no webitel host/token")
    return co, WebitelClient(co.webitel_host, co.webitel_access_token)


def _resolve_router_id(co_key: str) -> int:
    name, sid = get_router_schema(co_key)
    if not sid:
        raise KeyError(
            f"{co_key} has no router_schema_id; run "
            "`python -m app.router_schema setup CO_ --confirm` first"
        )
    return int(sid)


def list_testers(co_key: str) -> list[RouterTester]:
    """Read live router schema, parse testers from its testers page."""
    _, client = _client_for(co_key)
    sid = _resolve_router_id(co_key)
    full = client.get_schema(sid)
    payload = full.get("payload") or {}
    pid = _testers_page_id(payload)
    if not pid:
        return []
    anchors = _find_anchors(payload, pid)
    sw = anchors.get("switch")
    if sw is None:
        return []

    nodes_by_id = {n["id"]: n for n in payload.get("nodes") or []}
    sw_outs = sw.get("outputs") or {}
    cases = (sw.get("schema") or {}).get("case") or []

    # Map switch case index → output port id by `position`.
    out_by_position: dict[int, str] = {}
    for pid_, port in sw_outs.items():
        try:
            pos = int(port.get("position") or 0)
            out_by_position[pos] = pid_
        except (TypeError, ValueError):
            continue

    testers: list[RouterTester] = []
    for i, case in enumerate(cases):
        case_text = str(case.get("text") or "")
        if case_text == "default":
            continue
        port_id = out_by_position.get(i)
        if not port_id:
            continue
        # Find the connection from this port → set node.
        target_set = None
        for c in payload.get("connections") or []:
            if (c.get("source") == sw["id"]
                    and c.get("sourceOutput") == port_id):
                tn = nodes_by_id.get(c.get("target"))
                if tn and tn.get("label") == "set":
                    target_set = tn
                    break
        if target_set is None:
            continue
        sch = target_set.get("schema") or {}
        kv = {str(it.get("key")): str(it.get("value") or "")
              for it in (sch.get("set") or [])}
        testers.append(RouterTester(
            phone=case_text,
            test_owner=kv.get("test_owner", ""),
            test_area=kv.get("test_area", ""),
            destination=kv.get("destination", ""),
        ))
    return testers


def available_test_areas(co_key: str) -> list[str]:
    """Read the main-page switch on `${test_owner}` to get the active
    enum of test_area values. Falls back to TEST_AREA_OPTIONS if the
    main-page switch can't be located."""
    try:
        _, client = _client_for(co_key)
        sid = _resolve_router_id(co_key)
        full = client.get_schema(sid)
    except (KeyError, WebitelError):
        return list(TEST_AREA_OPTIONS)
    payload = full.get("payload") or {}
    main_pid = "main"
    for n in payload.get("nodes") or []:
        if n.get("pageId") != main_pid:
            continue
        if n.get("label") != "switch":
            continue
        sch = n.get("schema") or {}
        var = str(sch.get("variable") or "")
        if "test_owner" not in var:
            continue
        cases = [str(c.get("text") or "") for c in sch.get("case") or []]
        if cases:
            return cases
    return list(TEST_AREA_OPTIONS)


# --- Write -----------------------------------------------------------------

def _new_node_id() -> str:
    return secrets.token_hex(8)


def _new_port_id() -> str:
    return str(uuid.uuid4())


def _new_conn_id() -> str:
    return secrets.token_hex(8)


def _input_port(pid: str) -> dict:
    return {
        "id": pid,
        "label": pid,
        "type": "in",
        "socket": {"name": "socket"},
        "multipleConnections": True,
        "showControl": True,
        "control": None,
    }


def _output_port(pid: str, position: int, type_: str = "out") -> dict:
    """Build an output socket spec for a Webitel switch/set node.

    For switch nodes, `type_` MUST equal the matching `case.text` value —
    otherwise Webitel can't route to the right branch and falls back to
    default for everything. Default `"out"` is fine for set/js nodes that
    have a single passthrough output."""
    return {
        "id": pid,
        "label": pid,
        "type": type_,
        "socket": {"name": "socket"},
        "position": position,
        "goto": False,
        "multipleConnections": False,
    }


def _make_tester_set_node(
    page_id: str, *, test_owner: str, test_area: str,
    destination: str = "",
) -> tuple[dict, str, str]:
    """Build a fresh `set` node for one tester. Returns (node, in_port_id,
    out_port_id). `destination` controls the bot's `${destination}` for
    this tester — leave empty to fall back to the upstream value."""
    nid = _new_node_id()
    in_id = _new_port_id()
    out_id = _new_port_id()
    return ({
        "id": nid,
        "label": "set",
        "pageId": page_id,
        "description": None,
        "inputs": {in_id: _input_port(in_id)},
        "outputs": {out_id: _output_port(out_id, 0)},
        "commons": {"break": False, "limit": None},
        "controls": {},
        "schema": {
            # `user` is also overridden so that downstream CRM lookup
            # (`crm_lookup_url` uses `{user}` placeholder) hits the loan
            # attached to the tester's chosen destination phone, not the
            # tester's real handset phone. Without this override, the CRM
            # query would still be made against `${user}` (= the sender
            # phone), and the tester would see their own real-loan data
            # instead of the test loan they pointed `destination` at.
            "set": [
                {"key": "test_owner", "value": str(test_owner)},
                {"key": "test_area", "value": str(test_area)},
                {"key": "destination", "value": str(destination)},
                {"key": "user", "value": str(destination)},
            ],
        },
        "tag": f"set__{nid}",
    }, in_id, out_id)


def _connection(
    src_id: str, src_port: str, tgt_id: str, tgt_port: str, page_id: str,
) -> dict:
    return {
        "id": _new_conn_id(),
        "pageId": page_id,
        "source": src_id,
        "sourceOutput": src_port,
        "target": tgt_id,
        "targetInput": tgt_port,
    }


def _rebuild_testers_payload(
    payload: dict, page_id: str, testers: list[RouterTester],
) -> dict:
    """Take the existing payload, drop everything tester-specific, re-add
    set-nodes + switch cases + connections from `testers`. Anchors
    (start, switch, real_base, test_ctx) are preserved by-id."""
    new_payload = deepcopy(payload)
    anchors = _find_anchors(new_payload, page_id)
    required = ("start", "switch", "real_base", "test_ctx")
    for k in required:
        if k not in anchors:
            raise WebitelError(
                f"testers page is missing the {k} anchor — refusing to "
                "rebuild blindly. Restore the page in Webitel UI to a "
                "known-good state and try again."
            )

    start = anchors["start"]
    sw = anchors["switch"]
    real_base = anchors["real_base"]
    test_ctx = anchors["test_ctx"]

    keep_ids = {start["id"], sw["id"], real_base["id"], test_ctx["id"]}
    # Drop all per-tester nodes (any node on this page that's not anchor).
    new_nodes = [
        n for n in new_payload.get("nodes") or []
        if n.get("pageId") != page_id or n.get("id") in keep_ids
    ]
    # Drop all connections sourced from / targeting nodes on this page —
    # except the few we want to keep (start→switch, switch→real_base for
    # default, set→test_ctx wires we will re-add explicitly).
    ids_on_page = {
        n["id"] for n in new_payload.get("nodes") or []
        if n.get("pageId") == page_id
    }
    new_connections = [
        c for c in new_payload.get("connections") or []
        if c.get("source") not in ids_on_page
        and c.get("target") not in ids_on_page
    ]
    new_positions = dict(new_payload.get("positions") or {})

    # Rebuild switch outputs + cases. One port per tester + 1 default.
    out_ids: list[str] = []
    cases: list[dict] = []
    for t in testers:
        out_ids.append(_new_port_id())
        cases.append({"text": str(t.phone)})
    default_port = _new_port_id()
    out_ids.append(default_port)
    cases.append({"text": "default"})

    # Replace switch.outputs and switch.schema.case.
    # For Webitel switch nodes the routing decision is made by matching
    # the case text against each output's `type` field — so each output
    # MUST carry the matching case text as type, otherwise traffic falls
    # through to default for every tester.
    sw_node_idx = next(
        i for i, n in enumerate(new_nodes) if n["id"] == sw["id"]
    )
    new_sw = deepcopy(sw)
    new_sw["outputs"] = {
        oid: _output_port(oid, pos, type_=str(cases[pos]["text"]))
        for pos, oid in enumerate(out_ids)
    }
    sch = dict(new_sw.get("schema") or {})
    sch["case"] = cases
    new_sw["schema"] = sch
    new_nodes[sw_node_idx] = new_sw

    # Reset switch input port
    sw_in_id = next(iter((sw.get("inputs") or {}).keys()), None) or _new_port_id()

    # 1) start → switch (always one connection).
    start_out = next(iter((start.get("outputs") or {}).keys()), None)
    if start_out:
        new_connections.append(_connection(
            start["id"], start_out, sw["id"], sw_in_id, page_id,
        ))

    # 2) For each tester case → fresh set node → real_base.
    # We route testers through `real_base` (prod context) instead of the
    # legacy `test_ctx` because test_ctx hardcodes destination to a sample
    # phone — that overrides our per-tester `destination` and breaks the
    # use case "tester writes from their handset phone but we want CRM to
    # be queried by a custom destination phone". Real flow + override = ok.
    real_base_in_for_testers = next(iter((real_base.get("inputs") or {}).keys()), None)
    if real_base_in_for_testers is None:
        raise WebitelError(
            "real_base anchor has no input port — can't wire testers"
        )

    base_y = -160
    for idx, t in enumerate(testers):
        node, in_id, out_id = _make_tester_set_node(
            page_id, test_owner=t.test_owner, test_area=t.test_area,
            destination=t.destination or t.phone,
        )
        new_nodes.append(node)
        new_positions[node["id"]] = {
            "x": 500.0,
            "y": base_y + idx * 130.0,
        }
        # switch[case-port] → tester-set
        new_connections.append(_connection(
            sw["id"], out_ids[idx], node["id"], in_id, page_id,
        ))
        # tester-set → real_base
        new_connections.append(_connection(
            node["id"], out_id, real_base["id"], real_base_in_for_testers, page_id,
        ))

    # 3) Default case → real_base.
    real_base_in = next(iter((real_base.get("inputs") or {}).keys()), None)
    if real_base_in is None:
        raise WebitelError(
            "real_base anchor has no input port — can't wire default"
        )
    new_connections.append(_connection(
        sw["id"], default_port, real_base["id"], real_base_in, page_id,
    ))

    new_payload["nodes"] = new_nodes
    new_payload["connections"] = new_connections
    new_payload["positions"] = new_positions
    return new_payload


def save_testers(
    co_key: str,
    testers: list[RouterTester],
    *,
    snapshot_label: str = "testers-edit",
) -> dict:
    """Rebuild the testers page in router schema with `testers` and push.
    Returns a dict with snapshot paths + new updated_at."""
    co, client = _client_for(co_key)
    sid = _resolve_router_id(co_key)
    full = client.get_schema(sid)
    payload = full.get("payload") or {}
    pid = _testers_page_id(payload)
    if not pid:
        raise WebitelError("router schema has no `testers` page")

    snap_before = wio.make_snapshot(
        co_key, sid, full, label=f"{snapshot_label}-before",
    )
    new_payload = _rebuild_testers_payload(payload, pid, testers)
    try:
        resp = wio.push_payload(
            client, sid, new_payload,
            expected_updated_at=str(full.get("updated_at") or ""),
            base_object=full,
        )
    except WebitelConflict as e:
        return {
            "ok": False,
            "snapshot_before": str(snap_before),
            "error": f"conflict: {e}",
        }
    except WebitelError as e:
        return {
            "ok": False,
            "snapshot_before": str(snap_before),
            "error": f"PUT failed: {e}",
        }
    snap_after = wio.make_snapshot(
        co_key, sid, resp or full, label=f"{snapshot_label}-after",
    )
    return {
        "ok": True,
        "router_schema_id": sid,
        "snapshot_before": str(snap_before),
        "snapshot_after": str(snap_after),
        "new_updated_at": str((resp or {}).get("updated_at") or ""),
        "tester_count": len(testers),
    }
