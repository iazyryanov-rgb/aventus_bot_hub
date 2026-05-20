"""Per-company testers list — internal QA people we use to dry-run bots.

Stored at `data/testers/<COMPANY_KEY>.json` with shape:

    {
      "default_tester_id": "<id>" | "",
      "testers": [
        {
          "id": "...",                # auto-derived from name + phone tail
          "display_name": "...",
          "phone_e164": "+57...",
          "destination": "57...",     # digits only, used by bots as ${destination}
          "active": true | false,     # mirrors the router schema switch
          "notes": "..."              # auto-filled with set-node position
        },
        ...
      ]
    }

The list is read-only from the hub's perspective — it gets reconciled
against the company's Webitel router schema via `sync_from_router()`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import data_dir


def testers_path(company_key: str) -> Path:
    return data_dir() / "testers" / f"{company_key}.json"


def load_testers(company_key: str) -> dict:
    p = testers_path(company_key)
    if not p.exists():
        return {"default_tester_id": "", "testers": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"default_tester_id": "", "testers": []}
    if not isinstance(data, dict):
        return {"default_tester_id": "", "testers": []}
    data.setdefault("default_tester_id", "")
    if not isinstance(data.get("testers"), list):
        data["testers"] = []
    return data


def save_testers(company_key: str, data: dict) -> None:
    p = testers_path(company_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9А-Яа-яЁё]+", "_", (s or "").strip()).strip("_")


def make_tester_id(display_name: str, destination: str) -> str:
    name = _slug(display_name) or "tester"
    tail = "".join(ch for ch in (destination or "") if ch.isdigit())[-8:]
    return f"{name}_{tail}" if tail else name


def upsert_tester(company_key: str, tester: dict) -> dict:
    data = load_testers(company_key)
    testers = data["testers"]
    if not tester.get("id"):
        tester = {
            **tester,
            "id": make_tester_id(
                tester.get("display_name", ""),
                tester.get("destination", "") or tester.get("phone_e164", ""),
            ),
        }
    for i, existing in enumerate(testers):
        if existing.get("id") == tester["id"]:
            testers[i] = tester
            break
    else:
        testers.append(tester)
    save_testers(company_key, data)
    return tester


def delete_tester(company_key: str, tester_id: str) -> None:
    data = load_testers(company_key)
    data["testers"] = [t for t in data["testers"] if t.get("id") != tester_id]
    if data.get("default_tester_id") == tester_id:
        data["default_tester_id"] = ""
    save_testers(company_key, data)


def set_default_tester(company_key: str, tester_id: str) -> None:
    data = load_testers(company_key)
    if any(t.get("id") == tester_id for t in data["testers"]):
        data["default_tester_id"] = tester_id
        save_testers(company_key, data)


def get_default_tester(company_key: str) -> dict | None:
    data = load_testers(company_key)
    did = data.get("default_tester_id") or ""
    if not did:
        return None
    for t in data.get("testers") or []:
        if t.get("id") == did:
            return t
    return None


def _digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _phone_key(tester: dict) -> str:
    """Digit-only key used to match a local tester against a router
    switch case. Prefers `phone_e164`, falls back to `destination`."""
    return _digits(tester.get("phone_e164")) or _digits(tester.get("destination"))


def sync_from_router(company_key: str) -> dict:
    """Reconcile local testers.json against the company's Webitel router
    schema. The schema is the source of truth — its `testers` page's
    switch on `${user}` lists the active testers.

    Per-tester behaviour:
      * Phone present in schema AND in local list → update destination
        from the schema's set node, mark active=True, refresh notes
        with the set-node position.
      * Phone present in schema, missing locally → create a new entry
        with display_name='No name tester', phone_e164='+<digits>',
        destination from the schema, active=True.
      * Phone in local list but missing from the schema → leave the
        record intact, set active=False.

    Returns a small report dict (counts + lists of affected phones).
    """
    from .router_testers_sync import fetch_router_testers

    schema_entries = fetch_router_testers(company_key)
    by_phone = {e["phone"]: e for e in schema_entries}

    data = load_testers(company_key)
    testers = data.get("testers") or []

    matched_phones: set[str] = set()
    created: list[str] = []
    updated: list[str] = []
    deactivated: list[str] = []

    for tester in testers:
        phone = _phone_key(tester)
        if phone and phone in by_phone:
            entry = by_phone[phone]
            tester["destination"] = entry["destination"]
            tester["active"] = True
            x, y = entry["set_pos"]
            tester["notes"] = f"set@({x:.0f},{y:.0f})"
            matched_phones.add(phone)
            updated.append(phone)
        else:
            tester["active"] = False
            if phone:
                deactivated.append(phone)

    for phone, entry in by_phone.items():
        if phone in matched_phones:
            continue
        x, y = entry["set_pos"]
        new_tester = {
            "id": make_tester_id("No name tester", phone),
            "display_name": "No name tester",
            "phone_e164": f"+{phone}",
            "destination": entry["destination"],
            "active": True,
            "notes": f"set@({x:.0f},{y:.0f})",
        }
        testers.append(new_tester)
        created.append(phone)

    data["testers"] = testers
    save_testers(company_key, data)
    return {
        "schema_count": len(schema_entries),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
    }
