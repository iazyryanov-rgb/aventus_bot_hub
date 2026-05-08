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
          "environment": "prod" | "staging",
          "test_owner_key": "...",    # human owner of the test account
          "company": "...",
          "notes": "..."
        },
        ...
      ]
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import data_dir


ENVIRONMENTS = ("prod", "staging")


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
