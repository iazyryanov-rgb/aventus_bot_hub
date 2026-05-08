"""Minimal append-only error log so the .exe (which runs windowed and
has no console) can surface failures the operator might want to see.

Logs land at `data/logs/<topic>.log` — one file per topic. Lines are
single-line JSON so they're greppable but still parseable.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import data_dir


def _logs_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log(topic: str, event: str, **fields: Any) -> None:
    """Append a JSON line to `data/logs/<topic>.log`. Topic should be a
    short module slug ('dashboard', 'audit', 'cycle')."""
    rec = {
        "ts": int(time.time() * 1000),
        "event": event,
    }
    for k, v in fields.items():
        try:
            json.dumps(v)
            rec[k] = v
        except (TypeError, ValueError):
            rec[k] = repr(v)
    path = _logs_dir() / f"{topic}.log"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def dashboard_log(company_key: str, event: str, detail: str = "") -> None:
    log("dashboard", event, company=company_key, detail=detail[:500])
