"""G5 — CRM-distribution shift guard (stub).

Purpose
-------
After each successful candidate apply, snapshot the BEFORE distribution of
`contact_result` slugs across recent CRM communication_history rows, then
24-48h later compare the candidate-cohort distribution to that baseline.
A sharp shift (e.g. `promise_of_payment` rate drops, `wrong_number` rate
jumps) is the fastest possible signal that AI broke something — much
faster than the +14d payment outcome we use in weekly_review.

Status
------
**Stub.** The interface is implemented and `record_baseline` / `clear`
work end-to-end, but `compute_cohort_distribution` raises
NotImplementedError for all companies right now. Filling it in requires
per-company CRM SQL:

  CO_ / CO2_ (prod_credito365_api / prod_tuparcero_api):
    1. JOIN communication_history.final_node_id → action_tree node →
       contact_result slug. Mapping lives in `app/action_trees.py` (see
       node attributes — they encode the result_slug).
    2. JOIN communication_history.phone_id → phone.phone_number to get
       the actual digits, filter by last digit ∈ candidate_digits.

  AR_ / PE_ — different CRM schemas, separate work.

Baseline file
-------------
`data/calibration_cycle/<co>_crm_baseline.json` shape:

    {
      "applied_at_ms": <ms>,
      "audit_id": "<id>",
      "applied_rec_ids": ["..."],
      "baseline_window_days": 7,
      "baseline_distribution": {
        "<contact_result_slug>": <count>,
        ...
      }
    }

Entry points
------------
- `record_baseline(company_key, applied_at_ms, audit_id, rec_ids,
                   baseline_window_days=7)` — call right after a
  successful apply (auto mode) or approve (gated mode).

- `check_post_apply_shift(company_key, post_window_hours=48,
                          shift_threshold_pct=20.0) -> ShiftReport`
  Returns a structured report with per-slug deltas. If the cycle is
  configured to `enabled=true` and a shift exceeds threshold, the
  caller (a scheduler-fired alert template, TBD) should pause the
  cycle and Telegram-alert.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import data_dir


# --- Persistence ------------------------------------------------------------

def _baseline_path(company_key: str) -> Path:
    return data_dir() / "calibration_cycle" / f"{company_key}_crm_baseline.json"


def load_baseline(company_key: str) -> Optional[dict]:
    path = _baseline_path(company_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_baseline(company_key: str, data: dict) -> None:
    path = _baseline_path(company_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_baseline(company_key: str) -> None:
    path = _baseline_path(company_key)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


# --- Distribution computation (stub) ---------------------------------------

def compute_cohort_distribution(
    company_key: str,
    since_ms: int,
    until_ms: int,
    *,
    candidate_digits: Optional[set[int]] = None,
    cohort: str = "all",  # "candidate" | "champion" | "all"
) -> dict[str, int]:
    """Histogram of `contact_result` slugs in [since, until], optionally
    restricted to the candidate or champion phone-cohort.

    NOT YET IMPLEMENTED — see module docstring for what's needed.
    """
    raise NotImplementedError(
        f"compute_cohort_distribution: per-company CRM SQL not implemented. "
        f"For {company_key}, JOIN communication_history.final_node_id → "
        f"action_tree node slug and communication_history.phone_id → "
        f"phone.phone_number, filter by last digit ∈ candidate_digits. "
        f"Schema reference: app/crm_results_count.py + "
        f"app/action_trees.py."
    )


# --- Public API -------------------------------------------------------------

def record_baseline(
    company_key: str,
    *,
    applied_at_ms: int,
    audit_id: str,
    rec_ids: list[str],
    baseline_window_days: int = 7,
) -> Optional[dict]:
    """Snapshot the pre-apply CRM-result distribution. Safe to call from
    the cycle/approve hot path — returns None and writes a marker-only
    record if the SQL isn't implemented yet for this company.
    """
    until_ms = applied_at_ms
    since_ms = applied_at_ms - baseline_window_days * 86_400_000
    record = {
        "applied_at_ms": int(applied_at_ms),
        "audit_id": audit_id,
        "applied_rec_ids": list(rec_ids),
        "baseline_window_days": int(baseline_window_days),
        "since_ms": since_ms,
        "until_ms": until_ms,
        "baseline_distribution": {},
        "implemented": False,
    }
    try:
        dist = compute_cohort_distribution(
            company_key, since_ms, until_ms, cohort="all",
        )
        record["baseline_distribution"] = dist
        record["implemented"] = True
    except NotImplementedError:
        # Stub mode — keep the record but mark it as un-snapshotted, so
        # `check_post_apply_shift` knows to skip and the operator can see
        # in the file that we know an apply happened but didn't measure it.
        pass
    except Exception:
        return None
    _save_baseline(company_key, record)
    return record


@dataclass
class ShiftReport:
    company_key: str
    has_baseline: bool = False
    has_post_data: bool = False
    skipped_reason: str = ""
    baseline_total: int = 0
    post_total: int = 0
    deltas_pct: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    threshold_pct: float = 20.0

    @property
    def tripped(self) -> bool:
        return bool(self.flags)

    def to_dict(self) -> dict:
        return {
            "company_key": self.company_key,
            "has_baseline": self.has_baseline,
            "has_post_data": self.has_post_data,
            "skipped_reason": self.skipped_reason,
            "baseline_total": self.baseline_total,
            "post_total": self.post_total,
            "deltas_pct": {k: round(v, 2) for k, v in self.deltas_pct.items()},
            "flags": self.flags,
            "threshold_pct": self.threshold_pct,
            "tripped": self.tripped,
        }


def check_post_apply_shift(
    company_key: str,
    *,
    post_window_hours: int = 48,
    shift_threshold_pct: float = 20.0,
) -> ShiftReport:
    """Compare candidate-cohort distribution in the [applied_at,
    applied_at+window] window with the recorded baseline.

    Returns a ShiftReport. `tripped` is True when any monitored slug
    moved by more than `shift_threshold_pct`. Caller decides whether to
    pause the cycle / alert based on `tripped`.
    """
    report = ShiftReport(
        company_key=company_key,
        threshold_pct=shift_threshold_pct,
    )
    baseline = load_baseline(company_key)
    if baseline is None:
        report.skipped_reason = "no baseline recorded — has any apply happened?"
        return report
    if not baseline.get("implemented"):
        report.skipped_reason = (
            "compute_cohort_distribution not implemented for this company yet"
        )
        return report

    report.has_baseline = True
    applied_at_ms = int(baseline.get("applied_at_ms") or 0)
    if not applied_at_ms:
        report.skipped_reason = "baseline missing applied_at_ms"
        return report

    post_until = applied_at_ms + post_window_hours * 3600 * 1000
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if now_ms < applied_at_ms + 3600 * 1000:
        report.skipped_reason = "less than 1h since apply — too early to compare"
        return report
    post_until = min(post_until, now_ms)

    try:
        post = compute_cohort_distribution(
            company_key, applied_at_ms, post_until, cohort="candidate",
        )
    except NotImplementedError:
        report.skipped_reason = "compute_cohort_distribution stub"
        return report
    except Exception as e:
        report.skipped_reason = f"distribution query failed: {e}"
        return report

    report.has_post_data = True
    base = baseline.get("baseline_distribution") or {}
    base_total = sum(int(v) for v in base.values()) or 1
    post_total = sum(int(v) for v in post.values()) or 1
    report.baseline_total = base_total
    report.post_total = post_total

    # Track every slug that exists on either side.
    all_slugs = set(base.keys()) | set(post.keys())
    for slug in all_slugs:
        b_share = (base.get(slug, 0) / base_total) * 100.0
        p_share = (post.get(slug, 0) / post_total) * 100.0
        delta = p_share - b_share
        report.deltas_pct[slug] = delta
        if abs(delta) >= shift_threshold_pct:
            direction = "↑" if delta > 0 else "↓"
            report.flags.append(
                f"{slug}: {b_share:.1f}% → {p_share:.1f}% ({direction}{abs(delta):.1f}pp)"
            )
    return report
