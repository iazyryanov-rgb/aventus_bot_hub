"""Persistence for AI-audit results, pending corrections queue, and the
A/B-split candidate config that calibration produces.

Layout under `data/`:

  audit_history/<COMPANY_KEY>/<YYYYMMDD_HHMMSS>.json
      — one file per audit run (full result + meta).

  audit_pending/<COMPANY_KEY>.json
      — running list of recommendations the operator has marked as
        "take into corrections" but not yet applied via calibration.
        Shape:
          {
            "items": [
              {
                "rec_id": "r1",
                "applies_to": "...",
                "before": "...",
                "after": "...",
                "rationale": "...",
                "linked_findings": [...],
                "source_audit_id": "20260505_193045",
                "source_audit_ts_ms": 1715893845000,
                "source_model": "sonnet",
                "added_at_ms": 1715893900000
              },
              ...
            ]
          }

The candidate bot config produced by calibration is stored inside the
existing `data/wa_bot_config/<COMPANY_KEY>.json` under a top-level
`ab_split` key (so it travels with the rest of the bot config). Shape:

    "ab_split": {
        "enabled": true,
        "candidate_digits": [0, 1, 2],
        "candidate_corrections": [ ...same shape as pending items... ],
        "applied_at_ms": 1715893905000,
        "applied_by_audit_ids": ["20260505_193045", ...]
    }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import data_dir


# ---------------------------------------------------------------------------
# Audit history
# ---------------------------------------------------------------------------

def _history_dir(company_key: str) -> Path:
    return data_dir() / "audit_history" / company_key


def make_audit_id(ts_ms: Optional[int] = None) -> str:
    if ts_ms is None:
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    dt = datetime.fromtimestamp(ts_ms / 1000)
    return dt.strftime("%Y%m%d_%H%M%S")


def save_audit_result(
    company_key: str,
    audit: dict,
    *,
    period_days: int,
    model_kind: str,
    elapsed_s: Optional[float] = None,
    chat_limit: int = 0,
    lang: str = "ENG",
) -> str:
    """Write the audit result to a per-company history dir. Returns the
    audit_id (used to trace recommendations back to their origin)."""
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    audit_id = make_audit_id(ts_ms)
    record = {
        "audit_id": audit_id,
        "company_key": company_key,
        "ts_ms": ts_ms,
        "period_days": period_days,
        "model_kind": model_kind,
        "chat_limit": chat_limit,
        "elapsed_s": float(elapsed_s) if isinstance(elapsed_s, (int, float)) else None,
        "lang": lang,
        "audit": audit,
    }
    folder = _history_dir(company_key)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{audit_id}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return audit_id


def list_audit_ids(company_key: str, limit: int = 50) -> list[str]:
    folder = _history_dir(company_key)
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.json"), reverse=True)
    return [p.stem for p in files[:limit]]


def load_audit(company_key: str, audit_id: str) -> Optional[dict]:
    path = _history_dir(company_key) / f"{audit_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Pending corrections queue
# ---------------------------------------------------------------------------

def _pending_path(company_key: str) -> Path:
    return data_dir() / "audit_pending" / f"{company_key}.json"


def get_pending_corrections(company_key: str) -> list[dict]:
    path = _pending_path(company_key)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return list(items or [])


def _save_pending(company_key: str, items: list[dict]) -> None:
    path = _pending_path(company_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_to_pending(
    company_key: str,
    recommendations: list[dict],
    audit_meta: dict,
) -> int:
    """Append `recommendations` to the company's pending pool, deduplicating
    on (audit_id, rec_id). Returns the count actually added (post-dedup)."""
    items = get_pending_corrections(company_key)
    seen = {(it.get("source_audit_id"), it.get("rec_id")) for it in items}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    audit_id = audit_meta.get("audit_id") or ""
    audit_ts = audit_meta.get("ts_ms") or now_ms
    model_kind = audit_meta.get("model_kind") or ""
    added = 0
    for rec in recommendations:
        rid = rec.get("id") or ""
        key = (audit_id, rid)
        if key in seen:
            continue
        seen.add(key)
        # Goal-aware fields are optional for backward compat with audits
        # produced before the OUTPUT_SCHEMA was extended; default sensibly.
        try:
            lift = int(rec.get("expected_lift_pct") or 0)
        except (TypeError, ValueError):
            lift = 0
        items.append({
            "rec_id": rid,
            "applies_to": rec.get("applies_to") or "",
            "before": rec.get("before") or "",
            "after": rec.get("after") or "",
            "rationale": rec.get("rationale") or "",
            "linked_findings": list(rec.get("linked_findings") or []),
            "goal": str(rec.get("goal") or "neither"),
            "expected_lift_pct": max(0, min(100, lift)),
            "kind": str(rec.get("kind") or "text"),
            "source_audit_id": audit_id,
            "source_audit_ts_ms": audit_ts,
            "source_model": model_kind,
            "added_at_ms": now_ms,
        })
        added += 1
    _save_pending(company_key, items)
    return added


def clear_pending(company_key: str) -> None:
    _save_pending(company_key, [])


# ---------------------------------------------------------------------------
# A/B split candidate config (lives inside wa_bot_config json)
# ---------------------------------------------------------------------------

DEFAULT_AB_SPLIT = {
    "enabled": False,
    "candidate_digits": [0, 1, 2],
    "candidate_corrections": [],
    "applied_at_ms": 0,
    "applied_by_audit_ids": [],
}


def get_ab_split(bot_cfg: dict) -> dict:
    cur = (bot_cfg or {}).get("ab_split") or {}
    if not isinstance(cur, dict):
        cur = {}
    out = {**DEFAULT_AB_SPLIT, **cur}
    digits = out.get("candidate_digits") or []
    out["candidate_digits"] = sorted({
        int(d) for d in digits if isinstance(d, (int, str)) and str(d).isdigit()
        and 0 <= int(d) <= 9
    })
    return out


def set_ab_split(bot_cfg: dict, ab_split: dict) -> dict:
    bot_cfg["ab_split"] = {**DEFAULT_AB_SPLIT, **(ab_split or {})}
    digits = bot_cfg["ab_split"].get("candidate_digits") or []
    bot_cfg["ab_split"]["candidate_digits"] = sorted({
        int(d) for d in digits if isinstance(d, (int, str)) and str(d).isdigit()
        and 0 <= int(d) <= 9
    })
    return bot_cfg
