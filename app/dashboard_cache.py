"""Per-company dashboard snapshot cache.

Lives at `data/dashboard_cache/<company_key>.json`. Survives rebuilds because
`build.py` overlays source onto dist without wiping unknown subfolders.

Format:
{
  "snapshots": {
    "<period_days>": {
      "ts_ms": int,                       # when this snapshot was taken
      "dialogs_total": int,
      "calls_total": int,
      "agents": {"online": int, "pause": int, "total": int},
      "buckets": ["dd.mm", ...],          # x-axis labels (period-aligned)
      "d_counts": [int, ...],
      "c_counts": [int, ...]
    }
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir


def cache_dir() -> Path:
    p = data_dir() / "dashboard_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path(company_key: str) -> Path:
    return cache_dir() / f"{company_key}.json"


def load_cache(company_key: str) -> dict:
    path = cache_path(company_key)
    if not path.exists():
        return {"snapshots": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"snapshots": {}}
    data.setdefault("snapshots", {})
    return data


def save_cache(company_key: str, cache: dict) -> None:
    path = cache_path(company_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def get_snapshot(cache: dict, period_days: int) -> dict | None:
    return (cache.get("snapshots") or {}).get(str(period_days))


GC_AGE_MS = 14 * 24 * 3600 * 1000  # 14 days


def put_snapshot(cache: dict, period_days: int, snapshot: dict) -> None:
    snaps = cache.setdefault("snapshots", {})
    snaps[str(period_days)] = snapshot
    # GC: drop snapshots that haven't been touched in 14 days. Avoids the
    # cache file growing forever as the user changes period/sector combos.
    now_ms = int(snapshot.get("ts_ms") or 0)
    if now_ms:
        for k in list(snaps.keys()):
            ts = int((snaps[k] or {}).get("ts_ms") or 0)
            if ts and now_ms - ts > GC_AGE_MS:
                del snaps[k]
