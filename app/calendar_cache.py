"""On-disk cache of Webitel calendar `accepts` (working schedules).

Calendars rarely change — caching them across worker invocations cuts
dashboard refresh time substantially. Each company has its own cache file
under `data/calendar_cache/<KEY>.json`.

Schema:
    {
      "<calendar_id>": {
        "ts": <unix-seconds when cached>,
        "accepts": [...]   # raw response from /calendars/{id}.accepts
      },
      ...
    }
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from .paths import data_dir


DEFAULT_TTL_SECONDS = 6 * 3600


def _path(company_key: str) -> Path:
    return data_dir() / "calendar_cache" / f"{company_key}.json"


def _load(company_key: str) -> dict:
    p = _path(company_key)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(company_key: str, data: dict) -> None:
    p = _path(company_key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def get_calendar_accepts(
    company_key: str,
    calendar_id: int,
    fetch_fn: Callable[[int], dict],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Optional[list]:
    """Return cached `accepts` for the calendar, fetching only if missing
    or expired. Returns None if the fetch failed and no cached copy exists."""
    cache = _load(company_key)
    key = str(int(calendar_id))
    entry = cache.get(key)
    now = time.time()
    if entry and (now - float(entry.get("ts") or 0)) < ttl_seconds:
        return entry.get("accepts") or []
    try:
        raw = fetch_fn(int(calendar_id))
    except Exception:
        # Fall back to stale cache if we have it.
        return entry.get("accepts") if entry else None
    accepts = raw.get("accepts") or []
    cache[key] = {"ts": now, "accepts": accepts}
    _save(company_key, cache)
    return accepts
