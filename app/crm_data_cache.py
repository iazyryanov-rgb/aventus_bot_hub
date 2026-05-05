"""Per-company cache of the latest CRM response by phone.

Only the most recent snapshot is kept (no history). Lives at
`data/crm_data_cache/<company_key>.json` and survives rebuilds because
`build.py` overlays source onto dist without wiping unknown subfolders.

Snapshot shape:
{
  "ts_ms": 1730000000000,
  "phone": "5731...",
  "http_code": 200,
  "rows": [["dotted.key", "type", "value"], ...]
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .paths import data_dir


def cache_dir() -> Path:
    p = data_dir() / "crm_data_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path(company_key: str) -> Path:
    return cache_dir() / f"{company_key}.json"


def load_snapshot(company_key: str) -> Optional[dict]:
    path = cache_path(company_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_snapshot(company_key: str, snapshot: dict) -> None:
    path = cache_path(company_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
