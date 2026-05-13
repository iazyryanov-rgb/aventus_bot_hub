"""Weekly champion-vs-candidate cohort review.

The traffic split is set up once per company in the Webitel router config:
phones whose last digit is in `candidate_digits` (default {0,1,2}) hit the
candidate WhatsApp schema; the rest hit the champion. This module mirrors
that split locally on collected chats and computes outcome metrics for
each cohort.

`compute_weekly_metrics(co_key, since_ms, until_ms)`:
  * Pulls dialogs for the period via `chat_audit_data.collect_period`
    (already has CRM + payment join for CO/CO2).
  * Splits records by `phone_last_digit ∈ candidate_digits`.
  * Returns per-cohort: count, classification rates (close/prolong/
    partial), bot_only_rate.

`should_promote(metrics, target_goal, min_lift, min_n)`:
  * Decision rule for whether the candidate beats the champion enough
    to warrant promotion. Conservative defaults; tweak via CLI.

`auto_promote(co_key, ...)`:
  * Run the full pipeline: compute metrics → decide → if positive,
    call `calibration_apply.promote_candidate`. Always returns a
    PromoteDecision dataclass for logging/UI.

CLI lives in `calibration_apply.py` (subcommands `weekly-review` and
`auto-promote`) so a single binary entry point drives the whole loop.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import calibration_apply as ca
from .audit_storage import get_ab_split
from .chat_audit_data import ChatRecord, collect_period
from .data import Company, load_companies
from .paths import data_dir
from .wa_bot_config import load_config


DEFAULT_CANDIDATE_DIGITS = (0, 1, 2)


# --- Cohort split -----------------------------------------------------------

def get_candidate_digits(company_key: str) -> set[int]:
    """Read candidate_digits from the bot config's `ab_split` block, fall
    back to {0,1,2} if not configured. The Webitel-side router uses the
    same set."""
    cfg = load_config(company_key)
    ab = get_ab_split(cfg or {})
    digits = ab.get("candidate_digits") or list(DEFAULT_CANDIDATE_DIGITS)
    out: set[int] = set()
    for d in digits:
        try:
            di = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= di <= 9:
            out.add(di)
    return out or set(DEFAULT_CANDIDATE_DIGITS)


def _classify_cohort(record: ChatRecord, candidate_digits: set[int]) -> Optional[str]:
    """Return 'champion' | 'candidate' | None. None when phone_last_digit
    is missing/non-numeric, in which case we can't bucket and skip."""
    d = record.phone_last_digit
    if not d or not d.isdigit():
        return None
    return "candidate" if int(d) in candidate_digits else "champion"


SEGMENTS = ("NEW", "REP", "unknown")


def _classify_segment(record: ChatRecord) -> str:
    """Map a chat to the client segment used in segment-aware promotion
    decisions. NEW = first-time client (one open loan, no closed history),
    REP = returning client (≥1 closed loan in history). The CRM exposes this
    directly as `loan_type` ∈ {NEW, REP}; anything else is `unknown` and gets
    a separate, neutral bucket."""
    lt = ((record.crm or {}).get("loan_type") or "").strip().upper()
    if lt == "NEW":
        return "NEW"
    if lt == "REP":
        return "REP"
    return "unknown"


# --- Metrics ----------------------------------------------------------------

@dataclass
class CohortMetrics:
    n: int = 0
    with_payment_data: int = 0
    close: int = 0          # full payment landed
    prolong: int = 0        # extension/renewal paid
    partial: int = 0        # some money in, loan still active
    none: int = 0           # no payment in window
    bot_only: int = 0
    agent_handled: int = 0

    @property
    def close_rate(self) -> float:
        return self.close / self.n if self.n else 0.0

    @property
    def prolong_rate(self) -> float:
        return self.prolong / self.n if self.n else 0.0

    @property
    def any_pay_rate(self) -> float:
        if not self.n:
            return 0.0
        return (self.close + self.prolong + self.partial) / self.n

    @property
    def bot_only_rate(self) -> float:
        return self.bot_only / self.n if self.n else 0.0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "with_payment_data": self.with_payment_data,
            "close": self.close,
            "prolong": self.prolong,
            "partial": self.partial,
            "none": self.none,
            "bot_only": self.bot_only,
            "agent_handled": self.agent_handled,
            "close_rate": round(self.close_rate, 4),
            "prolong_rate": round(self.prolong_rate, 4),
            "any_pay_rate": round(self.any_pay_rate, 4),
            "bot_only_rate": round(self.bot_only_rate, 4),
        }


def _compute_cohort_metrics(records: Iterable[ChatRecord]) -> CohortMetrics:
    m = CohortMetrics()
    for r in records:
        m.n += 1
        if r.handler == "bot_only":
            m.bot_only += 1
        elif r.handler == "agent_handled":
            m.agent_handled += 1
        pay = r.payment or {}
        cls = (pay.get("classification") or "").lower()
        if pay:
            m.with_payment_data += 1
        if cls == "close":
            m.close += 1
        elif cls == "prolong":
            m.prolong += 1
        elif cls == "partial":
            m.partial += 1
        else:
            m.none += 1
    return m


# --- Top-level entrypoints --------------------------------------------------

@dataclass
class SegmentedMetrics:
    """Per-segment slice of one cohort. Keys mirror SEGMENTS — `NEW`,
    `REP`, `unknown`. NEW maps to the close_rate goal, REP to prolong_rate;
    we keep `unknown` for visibility but never use it in PROMOTE decisions."""
    new: CohortMetrics = field(default_factory=CohortMetrics)
    rep: CohortMetrics = field(default_factory=CohortMetrics)
    unknown: CohortMetrics = field(default_factory=CohortMetrics)

    def get(self, segment: str) -> CohortMetrics:
        s = (segment or "").upper()
        if s == "NEW":
            return self.new
        if s == "REP":
            return self.rep
        return self.unknown

    def to_dict(self) -> dict:
        return {
            "NEW": self.new.to_dict(),
            "REP": self.rep.to_dict(),
            "unknown": self.unknown.to_dict(),
        }


@dataclass
class WeeklyMetrics:
    company_key: str
    since_ms: int
    until_ms: int
    candidate_digits: list[int]
    champion: CohortMetrics = field(default_factory=CohortMetrics)
    candidate: CohortMetrics = field(default_factory=CohortMetrics)
    champion_segments: SegmentedMetrics = field(default_factory=SegmentedMetrics)
    candidate_segments: SegmentedMetrics = field(default_factory=SegmentedMetrics)
    unclassified: int = 0  # chats without phone_last_digit

    def to_dict(self) -> dict:
        return {
            "company_key": self.company_key,
            "since_ms": self.since_ms,
            "until_ms": self.until_ms,
            "candidate_digits": self.candidate_digits,
            "champion": self.champion.to_dict(),
            "candidate": self.candidate.to_dict(),
            "champion_segments": self.champion_segments.to_dict(),
            "candidate_segments": self.candidate_segments.to_dict(),
            "unclassified": self.unclassified,
        }


def _company(company_key: str) -> Company:
    for c in load_companies():
        if c.key == company_key:
            return c
    raise KeyError(f"company {company_key!r} not in companies.json")


def compute_weekly_metrics(
    company_key: str,
    since_ms: int,
    until_ms: int,
    *,
    chat_limit: int = 5000,
    candidate_digits: Optional[set[int]] = None,
) -> WeeklyMetrics:
    """Pull chats over [since_ms, until_ms), bucket by candidate_digits,
    compute per-cohort outcomes. `chat_limit` caps the Webitel pull (5k by
    default — a week of typical traffic)."""
    company = _company(company_key)
    digits = candidate_digits or get_candidate_digits(company_key)

    records, _meta = collect_period(
        company, since_ms, until_ms, limit=chat_limit,
    )

    champ_recs: list[ChatRecord] = []
    cand_recs: list[ChatRecord] = []
    unclassified = 0
    for r in records:
        cohort = _classify_cohort(r, digits)
        if cohort == "candidate":
            cand_recs.append(r)
        elif cohort == "champion":
            champ_recs.append(r)
        else:
            unclassified += 1

    def _segmented(records: list[ChatRecord]) -> SegmentedMetrics:
        buckets: dict[str, list[ChatRecord]] = {s: [] for s in SEGMENTS}
        for rec in records:
            buckets[_classify_segment(rec)].append(rec)
        return SegmentedMetrics(
            new=_compute_cohort_metrics(buckets["NEW"]),
            rep=_compute_cohort_metrics(buckets["REP"]),
            unknown=_compute_cohort_metrics(buckets["unknown"]),
        )

    return WeeklyMetrics(
        company_key=company_key,
        since_ms=since_ms,
        until_ms=until_ms,
        candidate_digits=sorted(digits),
        champion=_compute_cohort_metrics(champ_recs),
        candidate=_compute_cohort_metrics(cand_recs),
        champion_segments=_segmented(champ_recs),
        candidate_segments=_segmented(cand_recs),
        unclassified=unclassified,
    )


# --- Promote decision -------------------------------------------------------

@dataclass
class PromoteDecision:
    company_key: str
    metrics: WeeklyMetrics
    target_goal: str          # prolong | fully_pay | both
    min_lift: float           # 0..1 absolute rate diff
    min_n: int                # per-cohort threshold
    promote: bool = False
    reason: str = ""
    # Cohort rates used in the decision (so the log captures them)
    champion_rate: float = 0.0
    candidate_rate: float = 0.0
    lift: float = 0.0

    def to_dict(self) -> dict:
        return {
            "company_key": self.company_key,
            "target_goal": self.target_goal,
            "min_lift": self.min_lift,
            "min_n": self.min_n,
            "promote": self.promote,
            "reason": self.reason,
            "champion_rate": round(self.champion_rate, 4),
            "candidate_rate": round(self.candidate_rate, 4),
            "lift": round(self.lift, 4),
            "metrics": self.metrics.to_dict(),
        }


def _segment_rate(seg: CohortMetrics, goal: str) -> float:
    g = (goal or "").lower()
    if g == "prolong":
        return seg.prolong_rate
    if g == "fully_pay":
        return seg.close_rate
    return seg.any_pay_rate


def _segment_for_goal(goal: str) -> Optional[str]:
    """Which segment is the natural cohort for this business goal:
      fully_pay → NEW (we push first-time clients to close),
      prolong   → REP (we push returning clients to extend).
    For `both`, both segments are checked, so this returns None."""
    g = (goal or "").lower()
    if g == "fully_pay":
        return "NEW"
    if g == "prolong":
        return "REP"
    return None


def should_promote(
    metrics: WeeklyMetrics,
    *,
    target_goal: str = "fully_pay",
    min_lift: float = 0.02,
    min_n: int = 50,
) -> PromoteDecision:
    """Segment-aware promotion rule. Promote only if the candidate's rate
    on the segment that owns the business goal is >= champion's by at
    least `min_lift`, and both cohorts within that segment have >= `min_n`
    chats with payment data. For `target_goal=both`, *both* NEW and REP
    must independently clear the bar — protects against Simpson's paradox
    (overall lift driven by mix change rather than per-segment improvement).
    """
    decision = PromoteDecision(
        company_key=metrics.company_key,
        metrics=metrics,
        target_goal=target_goal,
        min_lift=min_lift,
        min_n=min_n,
    )

    g = (target_goal or "").lower()
    seg_label = _segment_for_goal(g)

    # Build the (segment, champ_rate, cand_rate, champ_n, cand_n) tuples
    # we need to evaluate for this goal.
    if seg_label is None:
        # `both` — evaluate NEW + REP independently.
        targets = [
            ("NEW", "fully_pay"),
            ("REP", "prolong"),
        ]
    else:
        targets = [(seg_label, g)]

    # Headline rates for the log: pick the worst (lowest lift) segment so
    # the operator sees the constraint that drove the decision. For single-
    # segment goals there's only one row to pick.
    worst_lift = None
    worst_row = None
    insufficient_segments: list[str] = []
    failing_segments: list[str] = []

    for seg_name, goal_name in targets:
        champ_seg = metrics.champion_segments.get(seg_name)
        cand_seg = metrics.candidate_segments.get(seg_name)
        champ_rate = _segment_rate(champ_seg, goal_name)
        cand_rate = _segment_rate(cand_seg, goal_name)
        lift = cand_rate - champ_rate
        if (
            champ_seg.with_payment_data < min_n
            or cand_seg.with_payment_data < min_n
        ):
            insufficient_segments.append(
                f"{seg_name}({goal_name}) "
                f"champ_n={champ_seg.with_payment_data} "
                f"cand_n={cand_seg.with_payment_data}"
            )
            continue
        if lift < min_lift:
            failing_segments.append(
                f"{seg_name}({goal_name}) lift={lift:+.1%}"
            )
        if worst_lift is None or lift < worst_lift:
            worst_lift = lift
            worst_row = (seg_name, goal_name, champ_rate, cand_rate, lift)

    # Surface the headline numbers (segment that decided the call)
    if worst_row is not None:
        _, _, decision.champion_rate, decision.candidate_rate, decision.lift = worst_row

    if insufficient_segments:
        decision.promote = False
        decision.reason = (
            "insufficient sample: " + "; ".join(insufficient_segments)
            + f" (min_n={min_n} per segment)"
        )
        return decision

    if failing_segments:
        decision.promote = False
        decision.reason = (
            "insufficient lift: " + "; ".join(failing_segments)
            + f" (need >= {min_lift:.1%} per segment)"
        )
        return decision

    decision.promote = True
    if seg_label is None:
        decision.reason = (
            f"candidate beats champion by >= {min_lift:.1%} on BOTH "
            f"NEW (fully_pay) and REP (prolong) segments"
        )
    else:
        decision.reason = (
            f"candidate {target_goal} rate on {seg_label} beats champion "
            f"by {decision.lift:+.1%} (>= min_lift {min_lift:.1%})"
        )
    return decision


# --- Auto-promote pipeline --------------------------------------------------

@dataclass
class AutoPromoteResult:
    decision: PromoteDecision
    promoted: bool = False
    promote_error: Optional[str] = None
    promote_log: Optional[dict] = None
    log_path: Optional[str] = None


def _review_log_dir(company_key: str) -> Path:
    return data_dir() / "audit_history" / company_key / "_weekly_review"


def _write_review_log(record: dict, company_key: str, *, dry_run: bool) -> str:
    folder = _review_log_dir(company_key)
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = "_dry-run" if dry_run else ""
    path = folder / f"{ts}{suffix}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(path)


def auto_promote(
    company_key: str,
    since_ms: int,
    until_ms: int,
    *,
    target_goal: str = "fully_pay",
    min_lift: float = 0.02,
    min_n: int = 50,
    chat_limit: int = 5000,
    dry_run: bool = False,
) -> AutoPromoteResult:
    """Compute metrics → decide → if positive and not dry_run, promote."""
    metrics = compute_weekly_metrics(
        company_key, since_ms, until_ms,
        chat_limit=chat_limit,
    )
    decision = should_promote(
        metrics,
        target_goal=target_goal,
        min_lift=min_lift,
        min_n=min_n,
    )
    res = AutoPromoteResult(decision=decision)

    if decision.promote and not dry_run:
        try:
            promote_res = ca.promote_candidate(company_key)
        except Exception as e:
            res.promote_error = f"{type(e).__name__}: {e}"
        else:
            res.promoted = bool(promote_res.ok)
            res.promote_error = promote_res.error
            res.promote_log = {
                "champion_id": promote_res.champion_id,
                "candidate_id": promote_res.candidate_id,
                "snapshot_before": promote_res.snapshot_champion_before,
                "snapshot_after": promote_res.snapshot_champion_after,
                "new_updated_at": promote_res.new_updated_at,
            }

    log_record = {
        "ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "company_key": company_key,
        "decision": decision.to_dict(),
        "promoted": res.promoted,
        "promote_error": res.promote_error,
        "promote_log": res.promote_log,
        "dry_run": dry_run,
    }
    try:
        res.log_path = _write_review_log(log_record, company_key, dry_run=dry_run)
    except OSError:
        pass
    return res
