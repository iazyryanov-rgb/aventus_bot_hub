"""Daily auto-calibration cycle: AI audit → preview → apply (candidate).

This is the closing piece of the audit→edit loop. After each scheduled
chat-audit run for a company, `run_cycle()` is invoked with the resulting
audit dict. The cycle:

  1. Pushes the audit's `recommendations` into the company's pending queue
     (so they are persisted with audit_id back-link, just like operator-
     queued ones).
  2. Loads the per-company cycle config from
     `data/calibration_cycle/<company_key>.json` — if disabled, exits.
  3. Resolves the candidate schema id from companies.json
     (`bots.whatsapp.candidate_schema_id`). If none — exits with a clear
     reason; operator must run `clone-candidate` first.
  4. Calls `calibration_apply.preview()` against the **candidate** schema,
     filtered by `target_goal` and `min_lift_pct` from cycle config.
  5. Picks the top-N supported recs (by `expected_lift_pct` desc — preview
     already sorts) up to `max_changes_per_run`.
  6. Calls `calibration_apply.apply()`. On success, drops applied rec_ids
     from pending so they don't get re-applied next cycle.

Per-company cycle config shape (`data/calibration_cycle/<co>.json`):

    {
      "enabled": true,
      "target_goal": "fully_pay",       // prolong | fully_pay | both
      "max_changes_per_run": 3,
      "min_lift_pct": 5,
      "dry_run": false                  // when true: preview+apply(dry_run)
                                        // useful for staging
    }

A single in-memory threading.Lock per company prevents two cycles racing
for the same Webitel candidate (the daily audit scheduler only runs one
audit per company concurrently anyway, but the lock is cheap insurance).

A small CLI is included for one-off runs / debugging:

    python -m app.calibration_cycle run CO_ <audit_id>
    python -m app.calibration_cycle config CO_
    python -m app.calibration_cycle config CO_ --enabled true \\
        --target-goal fully_pay --max-changes-per-run 3 --min-lift-pct 5
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import calibration_apply as ca
from . import calibration_compiler as cc
from .audit_storage import add_to_pending, load_audit
from .paths import data_dir
from .wa_bot_config import get_candidate_schema
from .webitel import WebitelError


# --- Per-company cycle config ----------------------------------------------

DEFAULT_CYCLE_CONFIG: dict = {
    "enabled": False,
    "target_goal": "fully_pay",
    "max_changes_per_run": 3,
    "min_lift_pct": 5,
    # approval_mode controls what cycle does after preview picks top-N:
    #   "auto"  — apply immediately (subject to `dry_run`)
    #   "gated" — queue picks for operator approval; `approve` CLI applies
    #   "off"   — only push to audit_pending, no preview/queue/apply
    "approval_mode": "auto",
    # When True, the actual write step is skipped (apply runs in dry_run).
    # Orthogonal to approval_mode: a gated+dry_run setup queues items but
    # `approve` would no-op-with-log. Useful for shadow-running gated mode.
    "dry_run": False,
    # large_change_guard: refuse to apply patches whose `after` text differs
    # from `before` by more than this percentage of the larger length.
    # In `auto` mode a tripped guard auto-pauses the cycle (sets enabled=false
    # and writes paused_reason). In `gated` mode the patch is still queued
    # but marked with a warning the operator must consciously approve.
    "large_change_threshold_pct": 30,
    # schema_drift_guard: detect non-API edits to the candidate schema.
    # `webitel_api_user_whitelist` lists the Webitel users the cycle has
    # permission to see as `updated_by`. Anything else means someone edited
    # via the Webitel UI under their own account → cycle pauses + alerts.
    # Combined with state-tracking (updated_at compared with recorded value
    # after each apply), this catches both name-mismatch drift and silent
    # edits under the same API account.
    "webitel_api_user_whitelist": ["HQ_access"],
}


def _cycle_config_path(company_key: str) -> Path:
    return data_dir() / "calibration_cycle" / f"{company_key}.json"


def load_cycle_config(company_key: str) -> dict:
    path = _cycle_config_path(company_key)
    if not path.exists():
        return dict(DEFAULT_CYCLE_CONFIG)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CYCLE_CONFIG)
    if not isinstance(raw, dict):
        return dict(DEFAULT_CYCLE_CONFIG)
    return {**DEFAULT_CYCLE_CONFIG, **raw}


def save_cycle_config(company_key: str, cfg: dict) -> None:
    path = _cycle_config_path(company_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULT_CYCLE_CONFIG, **(cfg or {})}
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# --- Cycle state file (last-known schema version per company) -------------

def _state_path(company_key: str) -> Path:
    return data_dir() / "calibration_cycle" / f"{company_key}_state.json"


def load_cycle_state(company_key: str) -> dict:
    path = _state_path(company_key)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cycle_state(company_key: str, state: dict) -> None:
    path = _state_path(company_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _record_known_updated_at(
    company_key: str, schema_id: int, updated_at: str, updated_by: str,
) -> None:
    """Update the cycle-state file to remember the schema version we just
    saw/wrote. Called after a successful apply (auto mode) or successful
    queue (gated mode — schema unchanged but record what we observed)."""
    state = load_cycle_state(company_key)
    state["candidate_schema_id"] = int(schema_id)
    state["last_known_updated_at"] = str(updated_at or "")
    state["last_known_updated_by"] = str(updated_by or "")
    state["recorded_at_ms"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    save_cycle_state(company_key, state)


# --- schema_drift_guard (G4) -----------------------------------------------

def _check_schema_drift(
    company_key: str,
    full_object: dict,
    candidate_schema_id: int,
    whitelist: list,
) -> Optional[str]:
    """Return a human-readable drift reason if the candidate schema appears
    to have been edited outside this cycle, else None.

    Two checks:
      1. `updated_by.name` is not in the whitelist (someone logged in under
         their own Webitel account and edited via UI).
      2. Live `updated_at` doesn't match the value we recorded after our
         last apply (silent edit under the API account, or first cycle —
         in which case state is empty and this check is skipped).
    """
    updated_by = (full_object.get("updated_by") or {}).get("name") or ""
    live_updated_at = str(full_object.get("updated_at") or "")
    state = load_cycle_state(company_key)
    last_known = str(state.get("last_known_updated_at") or "")
    last_schema_id = int(state.get("candidate_schema_id") or 0)

    wl = list(whitelist or [])
    if updated_by and wl and updated_by not in wl:
        return (
            f"candidate id={candidate_schema_id} last edited by "
            f"'{updated_by}' (not in whitelist {wl}). Likely a manual UI "
            f"edit — review and call `unpause` to resume."
        )

    # State-based check applies only when state is for the same schema
    # and we have a recorded value to compare with.
    if last_schema_id == int(candidate_schema_id) and last_known:
        if live_updated_at and live_updated_at != last_known:
            return (
                f"candidate id={candidate_schema_id} updated_at moved "
                f"({last_known} → {live_updated_at}) but no apply log "
                f"on our side. Someone edited via UI under the same API "
                f"account — review and call `unpause` to resume."
            )
    return None


# --- large_change_guard (G4) -----------------------------------------------

def _change_pct(before: str, after: str) -> float:
    """Magnitude of the patch as % of the longer string. 0.0 means
    identical; 1.0 means complete replacement of the longer side."""
    b = before or ""
    a = after or ""
    longer = max(len(b), len(a))
    if longer == 0:
        return 0.0
    if not b:
        return 1.0  # adding text from nothing — count as full
    if not a:
        return 1.0  # deleting all text — count as full
    # Cheap distance: |len_diff| + symmetric_diff of unique chars / longer
    # is too crude; use simple length-ratio + character-overlap check.
    len_diff = abs(len(a) - len(b)) / longer
    # Extra penalty if the strings barely overlap as substrings.
    short_in_long = (b in a) or (a in b)
    if short_in_long:
        return len_diff
    return max(len_diff, 0.5)  # disjoint texts → at least 50%


def _classify_patch_size(plans, threshold_pct: int) -> tuple[list, list]:
    """Split planned patches into (small, large) based on `_change_pct` and
    `threshold_pct`. `large` ones tripped the guard."""
    threshold = max(0.0, min(1.0, float(threshold_pct) / 100.0))
    small, large = [], []
    for pp in plans:
        pct = _change_pct(pp.before, pp.after)
        if pct > threshold:
            large.append((pp, pct))
        else:
            small.append((pp, pct))
    return small, large


def _pause_cycle(company_key: str, reason: str) -> None:
    cfg = load_cycle_config(company_key)
    cfg["enabled"] = False
    cfg["paused_at_ms"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    cfg["paused_reason"] = reason
    save_cycle_config(company_key, cfg)


# --- Approval queue (gated mode) -------------------------------------------

def _approval_queue_path(company_key: str) -> Path:
    return data_dir() / "calibration_cycle" / f"{company_key}_approval_queue.json"


def load_approval_queue(company_key: str) -> list[dict]:
    path = _approval_queue_path(company_key)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return list(items or [])


def _save_approval_queue(company_key: str, items: list[dict]) -> None:
    path = _approval_queue_path(company_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _new_queue_id() -> str:
    import secrets
    return secrets.token_hex(6)


def _queue_planned_patches(
    company_key: str,
    plans: list,  # list[ca.PlannedPatch]
    *,
    audit_id: str,
    candidate_schema_id: int,
    large_warning_rec_ids: Optional[set] = None,
) -> list[dict]:
    """Append planned patches to the approval queue. Returns the appended
    items (with fresh `queue_id`s).

    `large_warning_rec_ids` — rec_ids whose change_pct exceeded the
    large_change_threshold; queued items get `large_change_warning=true`.
    """
    existing = load_approval_queue(company_key)
    seen = {(it.get("audit_id"), it.get("rec_id")) for it in existing}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    warn_set = set(large_warning_rec_ids or [])
    appended: list[dict] = []
    for pp in plans:
        key = (audit_id, pp.rec_id)
        if key in seen:
            continue
        item = {
            "queue_id": _new_queue_id(),
            "queued_at_ms": now_ms,
            "audit_id": audit_id,
            "candidate_schema_id": int(candidate_schema_id),
            "rec_id": pp.rec_id,
            "applies_to": pp.applies_to,
            "page_name": pp.target.page_name,
            "node_id": pp.target.node_id,
            "json_path": pp.target.json_path,
            "before": pp.before,
            "after": pp.after,
            "rationale": pp.rationale,
            "goal": pp.goal,
            "expected_lift_pct": int(pp.expected_lift_pct),
            "kind": pp.kind,
            "large_change_warning": pp.rec_id in warn_set,
        }
        existing.append(item)
        appended.append(item)
        seen.add(key)
    _save_approval_queue(company_key, existing)
    return appended


def _drop_from_queue(company_key: str, queue_ids: list[str]) -> int:
    items = load_approval_queue(company_key)
    keep = [it for it in items if it.get("queue_id") not in queue_ids]
    removed = len(items) - len(keep)
    if removed:
        _save_approval_queue(company_key, keep)
    return removed


@dataclass
class ApprovalDecision:
    company_key: str
    approved: list[str] = field(default_factory=list)
    applied_rec_ids: list[str] = field(default_factory=list)
    apply_ok: bool = False
    apply_error: Optional[str] = None
    snapshot_before: Optional[str] = None
    snapshot_after: Optional[str] = None
    log_path: Optional[str] = None
    dry_run: bool = False


def approve_pending(
    company_key: str,
    queue_ids: list[str],
    *,
    dry_run: Optional[bool] = None,
    strict_before: bool = True,
) -> ApprovalDecision:
    """Apply the queue items whose `queue_id` is in `queue_ids`. Removes
    them from the queue on successful apply (or on dry_run, if `dry_run`
    True). Failed applies leave items in the queue for inspection.

    `dry_run` defaults to the value in cycle config.
    `strict_before` (default True) — refuses the patch if the live value
        at the target path differs from the recommendation's `before`.
        Pass False to force the overwrite (destructive: ignores whatever
        is live now and writes `after` regardless).
    """
    cfg = load_cycle_config(company_key)
    if dry_run is None:
        dry_run = bool(cfg.get("dry_run"))

    items = load_approval_queue(company_key)
    by_qid = {it.get("queue_id"): it for it in items}
    selected = [by_qid[qid] for qid in queue_ids if qid in by_qid]
    if not selected:
        return ApprovalDecision(
            company_key=company_key,
            apply_error="no matching queue_ids",
            dry_run=bool(dry_run),
        )

    # Group by candidate_schema_id (in practice always the same — single
    # candidate per company — but be defensive).
    by_target: dict[int, list[dict]] = {}
    for it in selected:
        by_target.setdefault(int(it.get("candidate_schema_id") or 0), []).append(it)

    decision = ApprovalDecision(company_key=company_key, dry_run=bool(dry_run))

    for target_id, group in by_target.items():
        if not target_id:
            decision.apply_error = "queue item missing candidate_schema_id"
            return decision

        # Re-build a recommendations list (matches preview's expected shape).
        recs = [
            {
                "rec_id": it["rec_id"],
                "applies_to": it["applies_to"],
                "before": it["before"],
                "after": it["after"],
                "rationale": it.get("rationale", ""),
                "goal": it.get("goal", "neither"),
                "expected_lift_pct": int(it.get("expected_lift_pct") or 0),
                "kind": it.get("kind", "text"),
                "linked_findings": [],
            }
            for it in group
        ]

        try:
            preview = ca.preview(
                company_key,
                schema_id=target_id,
                recommendations=recs,
            )
        except Exception as e:
            decision.apply_error = f"preview failed: {type(e).__name__}: {e}"
            return decision

        approved_rec_ids = [pp.rec_id for pp in preview.supported]
        try:
            res = ca.apply(
                company_key, preview, approved_rec_ids,
                dry_run=bool(dry_run),
                strict_before=bool(strict_before),
            )
        except Exception as e:
            decision.apply_error = f"apply failed: {type(e).__name__}: {e}"
            return decision

        decision.apply_ok = bool(res.ok)
        decision.apply_error = res.error
        decision.applied_rec_ids.extend(res.applied_rec_ids)
        decision.snapshot_before = res.snapshot_path_before
        decision.snapshot_after = res.snapshot_path_after
        decision.log_path = res.log_path
        decision.approved = list(queue_ids)

        if res.ok:
            applied_set = set(res.applied_rec_ids)
            qids_to_drop = [
                it["queue_id"] for it in group
                if it["rec_id"] in applied_set
            ]
            _drop_from_queue(company_key, qids_to_drop)
            if not dry_run:
                ca.remove_from_pending(company_key, list(applied_set))
                # Update drift-baseline with the post-apply updated_at.
                try:
                    _record_known_updated_at(
                        company_key, int(target_id),
                        str(res.new_updated_at or ""),
                        "HQ_access",
                    )
                except OSError:
                    pass
                # G5 — record CRM-result baseline.
                try:
                    from . import crm_distribution_guard as cdg
                    cdg.record_baseline(
                        company_key,
                        applied_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                        audit_id=group[0].get("audit_id", ""),
                        rec_ids=list(applied_set),
                    )
                except Exception:
                    pass
    return decision


def reject_pending(company_key: str, queue_ids: list[str]) -> int:
    """Drop items from the queue without applying. Returns the count
    actually removed."""
    return _drop_from_queue(company_key, queue_ids)


def process_pending_now(company_key: str) -> "CycleResult":
    """Process the audit_pending queue against the candidate schema:
    preview → top-N (by config) → in gated mode queue items, in auto
    mode apply. Same guards as the scheduled run_cycle (drift, large-
    change, dry_run). Doesn't touch pending until a successful auto-apply.

    Operator path:
      1. AI audit → "Взять в исправления" → items go to audit_pending.
      2. Open Калибровка tab → click "Apply pending now".
      3. Items appear in the approval queue (gated mode).
      4. Approve in UI → applied to candidate.
    """
    from .audit_storage import get_pending_corrections

    result = CycleResult(company_key=company_key)
    lock = _lock_for(company_key)
    if not lock.acquire(blocking=False):
        result.skipped = True
        result.reason = "another cycle is already running for this company"
        return result
    try:
        cfg = load_cycle_config(company_key)
        result.dry_run = bool(cfg.get("dry_run"))
        result.approval_mode = str(cfg.get("approval_mode") or "auto").lower()

        if not cfg.get("enabled"):
            result.skipped = True
            result.reason = "calibration_cycle disabled in config"
            return result

        if result.approval_mode == "off":
            result.skipped = True
            result.reason = "approval_mode=off; no preview/queue/apply"
            _safely_log(result, "process_pending")
            return result

        pending = get_pending_corrections(company_key)
        if not pending:
            result.skipped = True
            result.reason = "audit_pending queue is empty"
            return result

        cand_name, cand_id = get_candidate_schema(company_key)
        if not cand_id:
            result.skipped = True
            result.reason = (
                "no candidate schema linked in companies.json; run "
                "`clone-candidate` first"
            )
            _safely_log(result, "process_pending")
            return result
        result.candidate_schema_id = int(cand_id)

        # Convert pending → recommendation shape preview() expects.
        recs = [{
            "id": p.get("rec_id") or "",
            "applies_to": p.get("applies_to") or "",
            "before": p.get("before") or "",
            "after": p.get("after") or "",
            "rationale": p.get("rationale") or "",
            "linked_findings": p.get("linked_findings") or [],
            "goal": p.get("goal") or "neither",
            "expected_lift_pct": int(p.get("expected_lift_pct") or 0),
            "kind": p.get("kind") or "text",
        } for p in pending]

        try:
            preview = ca.preview(
                company_key,
                schema_id=int(cand_id),
                recommendations=recs,
                target_goal=cfg.get("target_goal"),
                min_expected_lift_pct=int(cfg.get("min_lift_pct") or 0),
            )
        except cc_errors_UnknownPattern as e:  # type: ignore[name-defined]
            result.reason = f"unknown pattern on candidate: {e}"
            _safely_log(result, "process_pending")
            return result
        except WebitelError as e:
            result.reason = f"Webitel GET failed: {e}"
            _safely_log(result, "process_pending")
            return result
        except Exception as e:  # noqa: BLE001
            result.reason = f"preview failed: {type(e).__name__}: {e}"
            _safely_log(result, "process_pending")
            return result

        result.supported_count = len(preview.supported)
        result.unsupported_count = len(preview.unsupported)

        # Schema-drift guard
        whitelist = list(
            cfg.get("webitel_api_user_whitelist") or ["HQ_access"]
        )
        drift_reason = _check_schema_drift(
            company_key, preview.full_object, int(cand_id), whitelist,
        )
        if drift_reason:
            try:
                _pause_cycle(company_key, f"schema_drift: {drift_reason}")
            except OSError:
                pass
            result.apply_error = f"schema_drift: {drift_reason}"
            result.cycle_paused = True
            result.schema_drift_detected = True
            _safely_log(result, "process_pending")
            return result

        if not preview.supported:
            result.skipped = True
            result.reason = (
                f"no supported recs after filters "
                f"(unsupported={len(preview.unsupported)})"
            )
            _safely_log(result, "process_pending")
            return result

        top_n = max(1, int(cfg.get("max_changes_per_run") or 1))
        top_plans = preview.supported[:top_n]
        result.approved_rec_ids = [pp.rec_id for pp in top_plans]

        # Large-change guard
        threshold_pct = int(cfg.get("large_change_threshold_pct") or 30)
        _small, _large = _classify_patch_size(top_plans, threshold_pct)
        large_warns: list[dict] = [
            {"rec_id": pp.rec_id, "applies_to": pp.applies_to,
             "change_pct": round(pct, 2)}
            for pp, pct in _large
        ]
        result.large_change_warnings = large_warns
        if result.approval_mode == "auto" and large_warns:
            top_recs = ", ".join(w["rec_id"] for w in large_warns)
            reason = (
                f"large_change_guard tripped: "
                f"{len(large_warns)} patch(es) over {threshold_pct}% threshold "
                f"({top_recs}). Cycle auto-paused."
            )
            try:
                _pause_cycle(company_key, reason)
            except OSError:
                pass
            result.apply_error = reason
            result.cycle_paused = True
            _safely_log(result, "process_pending")
            return result

        # Gated → queue, don't apply.
        if result.approval_mode == "gated":
            try:
                queued = _queue_planned_patches(
                    company_key, top_plans,
                    audit_id="process_pending_now",
                    candidate_schema_id=int(cand_id),
                    large_warning_rec_ids={w["rec_id"] for w in large_warns},
                )
            except OSError as e:
                result.apply_error = f"could not write approval queue: {e}"
                _safely_log(result, "process_pending")
                return result
            result.queued_items = queued
            result.queued_count = len(queued)
            try:
                _record_known_updated_at(
                    company_key, int(cand_id),
                    str(preview.expected_updated_at or ""),
                    str((preview.full_object.get("updated_by") or {}).get("name") or ""),
                )
            except OSError:
                pass
            _safely_log(result, "process_pending")
            return result

        # Auto → apply (subject to dry_run).
        try:
            apply_res = ca.apply(
                company_key, preview, result.approved_rec_ids,
                dry_run=result.dry_run,
            )
        except Exception as e:  # noqa: BLE001
            result.apply_error = f"{type(e).__name__}: {e}"
            _safely_log(result, "process_pending")
            return result

        result.apply_ok = bool(apply_res.ok)
        result.apply_error = apply_res.error
        result.applied_rec_ids = list(apply_res.applied_rec_ids)
        result.snapshot_before = apply_res.snapshot_path_before
        result.snapshot_after = apply_res.snapshot_path_after

        if apply_res.ok and not result.dry_run and apply_res.applied_rec_ids:
            try:
                ca.remove_from_pending(
                    company_key, apply_res.applied_rec_ids,
                )
            except OSError:
                pass
            try:
                _record_known_updated_at(
                    company_key, int(cand_id),
                    str(apply_res.new_updated_at or ""),
                    "HQ_access",
                )
            except OSError:
                pass
            try:
                from . import crm_distribution_guard as cdg
                cdg.record_baseline(
                    company_key,
                    applied_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                    audit_id="process_pending_now",
                    rec_ids=list(apply_res.applied_rec_ids),
                )
            except Exception:
                pass

        _safely_log(result, "process_pending")
        return result
    finally:
        lock.release()


# Local alias for the cc.UnknownPattern import — keeps the function above
# decoupled from import order.
cc_errors_UnknownPattern = cc.UnknownPattern


# --- Per-company concurrency guard -----------------------------------------

_locks_guard = threading.Lock()
_company_locks: dict[str, threading.Lock] = {}


def _lock_for(company_key: str) -> threading.Lock:
    with _locks_guard:
        return _company_locks.setdefault(company_key, threading.Lock())


# --- Result -----------------------------------------------------------------

@dataclass
class CycleResult:
    company_key: str
    skipped: bool = False
    reason: str = ""
    candidate_schema_id: Optional[int] = None
    pending_added: int = 0
    supported_count: int = 0
    unsupported_count: int = 0
    approved_rec_ids: list[str] = field(default_factory=list)
    applied_rec_ids: list[str] = field(default_factory=list)
    apply_ok: bool = False
    apply_error: Optional[str] = None
    snapshot_before: Optional[str] = None
    snapshot_after: Optional[str] = None
    log_path: Optional[str] = None
    dry_run: bool = False
    approval_mode: str = "auto"  # auto | gated | off
    queued_count: int = 0
    queued_items: list[dict] = field(default_factory=list)
    large_change_warnings: list[dict] = field(default_factory=list)
    cycle_paused: bool = False  # set when any guard auto-paused
    schema_drift_detected: bool = False


# --- Cycle log --------------------------------------------------------------

def _cycle_log_dir(company_key: str) -> Path:
    return data_dir() / "audit_history" / company_key / "_cycle"


def _write_cycle_log(result: CycleResult, *, audit_id: str) -> str:
    folder = _cycle_log_dir(result.company_key)
    folder.mkdir(parents=True, exist_ok=True)
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )
    record = {
        "ts_ms": ts_ms,
        "company_key": result.company_key,
        "audit_id": audit_id,
        "candidate_schema_id": result.candidate_schema_id,
        "skipped": result.skipped,
        "reason": result.reason,
        "pending_added": result.pending_added,
        "supported_count": result.supported_count,
        "unsupported_count": result.unsupported_count,
        "approved_rec_ids": result.approved_rec_ids,
        "applied_rec_ids": result.applied_rec_ids,
        "apply_ok": result.apply_ok,
        "apply_error": result.apply_error,
        "snapshot_before": result.snapshot_before,
        "snapshot_after": result.snapshot_after,
        "dry_run": result.dry_run,
    }
    suffix = "_dry-run" if result.dry_run else ""
    path = folder / f"{ts}{suffix}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(path)


# --- run_cycle --------------------------------------------------------------

def run_cycle(
    company_key: str,
    audit_result: dict,
    *,
    audit_meta: Optional[dict] = None,
) -> CycleResult:
    """Run one calibration cycle for a company. Safe to call from the
    scheduler — never raises; failures land in `result.apply_error` /
    `result.reason`.

    `audit_result` is the dict returned by `chat_audit.run_audit()`. The
    `_meta.audit_id` and `_meta.ts_ms` fields are used to back-link
    pending recommendations to their source audit. `audit_meta` overrides
    these if supplied (CLI replay path).
    """
    result = CycleResult(company_key=company_key)
    lock = _lock_for(company_key)
    if not lock.acquire(blocking=False):
        result.skipped = True
        result.reason = "another cycle is already running for this company"
        return result
    try:
        cfg = load_cycle_config(company_key)
        result.dry_run = bool(cfg.get("dry_run"))
        result.approval_mode = str(cfg.get("approval_mode") or "auto").lower()

        if not cfg.get("enabled"):
            result.skipped = True
            result.reason = "calibration_cycle disabled in config"
            return result

        recs = list((audit_result or {}).get("recommendations") or [])
        if not recs:
            result.skipped = True
            result.reason = "audit returned no recommendations"
            return result

        meta = dict((audit_result or {}).get("_meta") or {})
        if audit_meta:
            meta.update(audit_meta)
        audit_id = str(meta.get("audit_id") or "")
        push_meta = {
            "audit_id": audit_id,
            "ts_ms": meta.get("ts_ms") or 0,
            "model_kind": meta.get("model_kind") or "",
        }

        try:
            result.pending_added = add_to_pending(company_key, recs, push_meta)
        except OSError as e:
            result.skipped = True
            result.reason = f"could not write pending queue: {e}"
            return result

        # Mode `off`: only push to pending, skip preview/queue/apply entirely.
        if result.approval_mode == "off":
            result.skipped = True
            result.reason = "approval_mode=off; pending updated, no preview"
            _safely_log(result, audit_id)
            return result

        cand_name, cand_id = get_candidate_schema(company_key)
        if not cand_id:
            result.skipped = True
            result.reason = (
                "no candidate schema linked in companies.json; run "
                "`clone-candidate` first"
            )
            _safely_log(result, audit_id)
            return result
        result.candidate_schema_id = int(cand_id)

        # Preview against the **candidate** (we never auto-edit champion).
        # Use the just-written audit's recs directly — equivalent to
        # picking them from pending, but explicit.
        try:
            preview = ca.preview(
                company_key,
                schema_id=int(cand_id),
                recommendations=recs,
                target_goal=cfg.get("target_goal"),
                min_expected_lift_pct=int(cfg.get("min_lift_pct") or 0),
            )
        except cc.UnknownPattern as e:
            result.reason = f"unknown pattern on candidate schema: {e}"
            _safely_log(result, audit_id)
            return result
        except WebitelError as e:
            result.reason = f"Webitel GET failed: {e}"
            _safely_log(result, audit_id)
            return result
        except Exception as e:  # last-resort safety net
            result.reason = f"preview failed: {type(e).__name__}: {e}"
            _safely_log(result, audit_id)
            return result

        result.supported_count = len(preview.supported)
        result.unsupported_count = len(preview.unsupported)

        # G4 — schema_drift_guard. Did anyone edit the candidate schema
        # outside our cycle? If yes — pause + alert. (Skip on first cycle
        # when state is empty — the first run establishes the baseline.)
        whitelist = list(cfg.get("webitel_api_user_whitelist") or ["HQ_access"])
        drift_reason = _check_schema_drift(
            company_key, preview.full_object, int(cand_id), whitelist,
        )
        if drift_reason:
            try:
                _pause_cycle(company_key, f"schema_drift: {drift_reason}")
            except OSError:
                pass
            result.apply_error = f"schema_drift: {drift_reason}"
            result.cycle_paused = True
            result.schema_drift_detected = True
            _safely_log(result, audit_id)
            return result

        if not preview.supported:
            result.skipped = True
            result.reason = (
                f"no supported recs after filters "
                f"(unsupported={len(preview.unsupported)})"
            )
            _safely_log(result, audit_id)
            return result

        # Top-N by expected_lift_pct (preview is pre-sorted descending).
        top_n = max(1, int(cfg.get("max_changes_per_run") or 1))
        top_plans = preview.supported[:top_n]
        result.approved_rec_ids = [pp.rec_id for pp in top_plans]

        # G4 — large_change_guard. In auto mode, any patch above threshold
        # auto-pauses the cycle. In gated mode, the patch is still queued
        # but the operator gets a flag warning them to read carefully.
        threshold_pct = int(cfg.get("large_change_threshold_pct") or 30)
        _small, _large = _classify_patch_size(top_plans, threshold_pct)
        large_warns: list[dict] = [
            {"rec_id": pp.rec_id, "applies_to": pp.applies_to,
             "change_pct": round(pct, 2)}
            for pp, pct in _large
        ]
        result.large_change_warnings = large_warns

        if result.approval_mode == "auto" and large_warns:
            top_recs = ", ".join(w["rec_id"] for w in large_warns)
            reason = (
                f"large_change_guard tripped: "
                f"{len(large_warns)} patch(es) over {threshold_pct}% threshold "
                f"({top_recs}). Cycle auto-paused."
            )
            try:
                _pause_cycle(company_key, reason)
            except OSError:
                pass
            result.apply_error = reason
            result.cycle_paused = True
            _safely_log(result, audit_id)
            return result

        # Mode `gated`: queue picks for operator approval, do NOT apply.
        if result.approval_mode == "gated":
            try:
                queued = _queue_planned_patches(
                    company_key, top_plans,
                    audit_id=audit_id,
                    candidate_schema_id=int(cand_id),
                    large_warning_rec_ids={w["rec_id"] for w in large_warns},
                )
            except OSError as e:
                result.apply_error = f"could not write approval queue: {e}"
                _safely_log(result, audit_id)
                return result
            result.queued_items = queued
            result.queued_count = len(queued)
            # Record current schema state — schema unchanged in gated mode,
            # but baseline matters for next cycle's drift check.
            try:
                _record_known_updated_at(
                    company_key, int(cand_id),
                    str(preview.expected_updated_at or ""),
                    str((preview.full_object.get("updated_by") or {}).get("name") or ""),
                )
            except OSError:
                pass
            _safely_log(result, audit_id)
            return result

        # Mode `auto`: apply immediately (subject to dry_run).
        try:
            apply_res = ca.apply(
                company_key, preview, result.approved_rec_ids,
                dry_run=result.dry_run,
            )
        except Exception as e:
            result.apply_error = f"{type(e).__name__}: {e}"
            _safely_log(result, audit_id)
            return result

        result.apply_ok = bool(apply_res.ok)
        result.apply_error = apply_res.error
        result.applied_rec_ids = list(apply_res.applied_rec_ids)
        result.snapshot_before = apply_res.snapshot_path_before
        result.snapshot_after = apply_res.snapshot_path_after

        # On a real (non-dry) successful apply, drop applied recs from
        # pending so they don't accumulate forever.
        if apply_res.ok and not result.dry_run and apply_res.applied_rec_ids:
            try:
                ca.remove_from_pending(company_key, apply_res.applied_rec_ids)
            except OSError:
                pass

        # Update drift-baseline state with the new (post-apply) updated_at.
        if apply_res.ok and not result.dry_run:
            try:
                _record_known_updated_at(
                    company_key, int(cand_id),
                    str(apply_res.new_updated_at or ""),
                    "HQ_access",  # we just wrote via API
                )
            except OSError:
                pass
            # G5 — record CRM-result baseline for post-apply shift check.
            try:
                from . import crm_distribution_guard as cdg
                cdg.record_baseline(
                    company_key,
                    applied_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                    audit_id=audit_id,
                    rec_ids=list(apply_res.applied_rec_ids),
                )
            except Exception:
                pass

        _safely_log(result, audit_id)
        return result
    finally:
        lock.release()


def _safely_log(result: CycleResult, audit_id: str) -> None:
    try:
        result.log_path = _write_cycle_log(result, audit_id=audit_id)
    except OSError:
        pass


# --- CLI --------------------------------------------------------------------

def _parse_bool(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"expected bool, got {value!r}")


def _print_result(r: CycleResult) -> None:
    print(f"company:           {r.company_key}")
    print(f"candidate_schema:  {r.candidate_schema_id}")
    print(f"skipped:           {r.skipped}")
    if r.reason:
        print(f"reason:            {r.reason}")
    print(f"pending_added:     {r.pending_added}")
    print(f"supported:         {r.supported_count}")
    print(f"unsupported:       {r.unsupported_count}")
    print(f"approved:          {r.approved_rec_ids}")
    print(f"applied:           {r.applied_rec_ids}")
    print(f"apply_ok:          {r.apply_ok}")
    if r.apply_error:
        print(f"apply_error:       {r.apply_error}")
    print(f"snapshot_before:   {r.snapshot_before}")
    print(f"snapshot_after:    {r.snapshot_after}")
    print(f"dry_run:           {r.dry_run}")
    print(f"log:               {r.log_path}")


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="calibration_cycle")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser(
        "run",
        help="Replay a cycle off a saved audit history record",
    )
    p_run.add_argument("company_key")
    p_run.add_argument("audit_id")

    p_cfg = sub.add_parser(
        "config",
        help="Show or update the per-company cycle config",
    )
    p_cfg.add_argument("company_key")
    p_cfg.add_argument("--enabled", type=_parse_bool, default=None)
    p_cfg.add_argument(
        "--target-goal",
        choices=("prolong", "fully_pay", "both"),
        default=None,
    )
    p_cfg.add_argument("--max-changes-per-run", type=int, default=None)
    p_cfg.add_argument("--min-lift-pct", type=int, default=None)
    p_cfg.add_argument("--dry-run", type=_parse_bool, default=None)
    p_cfg.add_argument(
        "--approval-mode",
        choices=("auto", "gated", "off"),
        default=None,
        help="auto = apply top-N immediately; gated = queue for approval; "
             "off = only push to pending, no preview",
    )

    p_pending = sub.add_parser(
        "pending",
        help="List items awaiting approval (gated mode)",
    )
    p_pending.add_argument("company_key")

    p_approve = sub.add_parser(
        "approve",
        help="Apply queued items by queue_id",
    )
    p_approve.add_argument("company_key")
    p_approve.add_argument("queue_ids", nargs="+")
    p_approve.add_argument("--dry-run", type=_parse_bool, default=None)

    p_reject = sub.add_parser(
        "reject",
        help="Drop queued items by queue_id without applying",
    )
    p_reject.add_argument("company_key")
    p_reject.add_argument("queue_ids", nargs="+")

    p_clear = sub.add_parser(
        "clear-pending",
        help="Drop all queued items for a company",
    )
    p_clear.add_argument("company_key")

    p_unpause = sub.add_parser(
        "unpause",
        help="Re-enable a cycle that was auto-paused by large_change_guard "
             "(or any other auto-pause trip). Clears paused_at_ms and "
             "paused_reason; sets enabled=true.",
    )
    p_unpause.add_argument("company_key")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        audit = load_audit(args.company_key, args.audit_id)
        if audit is None:
            print(
                f"audit_id {args.audit_id!r} not found for {args.company_key!r}",
                file=sys.stderr,
            )
            return 2
        audit_payload = audit.get("audit") or {}
        meta = {
            "audit_id": audit.get("audit_id") or args.audit_id,
            "ts_ms": audit.get("ts_ms") or 0,
            "model_kind": audit.get("model_kind") or "",
        }
        res = run_cycle(args.company_key, audit_payload, audit_meta=meta)
        _print_result(res)
        return 0 if (res.apply_ok or res.skipped) else 2

    if args.cmd == "config":
        cfg = load_cycle_config(args.company_key)
        changed = False
        if args.enabled is not None:
            cfg["enabled"] = args.enabled
            changed = True
        if args.target_goal is not None:
            cfg["target_goal"] = args.target_goal
            changed = True
        if args.max_changes_per_run is not None:
            cfg["max_changes_per_run"] = max(1, int(args.max_changes_per_run))
            changed = True
        if args.min_lift_pct is not None:
            cfg["min_lift_pct"] = max(0, int(args.min_lift_pct))
            changed = True
        if args.dry_run is not None:
            cfg["dry_run"] = args.dry_run
            changed = True
        if args.approval_mode is not None:
            cfg["approval_mode"] = args.approval_mode
            changed = True
        if changed:
            save_cycle_config(args.company_key, cfg)
            print(f"saved {_cycle_config_path(args.company_key)}")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "pending":
        items = load_approval_queue(args.company_key)
        if not items:
            print(f"{args.company_key}: approval queue is empty")
            return 0
        for it in items:
            print(
                f"  [{it.get('queue_id')}] audit={it.get('audit_id')!r} "
                f"goal={it.get('goal')} lift={it.get('expected_lift_pct')}% "
                f"kind={it.get('kind')}\n"
                f"    rec_id={it.get('rec_id')} → "
                f"{it.get('applies_to')}\n"
                f"    page={it.get('page_name')} node={it.get('node_id')} "
                f"path={it.get('json_path')}\n"
                f"    before={(it.get('before') or '')[:80]!r}\n"
                f"    after ={(it.get('after') or '')[:80]!r}\n"
                f"    rationale: {(it.get('rationale') or '')[:120]}"
            )
        print(f"\nTotal: {len(items)} item(s)")
        return 0

    if args.cmd == "approve":
        decision = approve_pending(
            args.company_key, list(args.queue_ids),
            dry_run=args.dry_run,
        )
        out = {
            "approved": decision.approved,
            "applied_rec_ids": decision.applied_rec_ids,
            "apply_ok": decision.apply_ok,
            "apply_error": decision.apply_error,
            "snapshot_before": decision.snapshot_before,
            "snapshot_after": decision.snapshot_after,
            "log_path": decision.log_path,
            "dry_run": decision.dry_run,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if decision.apply_ok else 2

    if args.cmd == "reject":
        n = reject_pending(args.company_key, list(args.queue_ids))
        print(f"{args.company_key}: removed {n} item(s) from approval queue")
        return 0

    if args.cmd == "clear-pending":
        items = load_approval_queue(args.company_key)
        if not items:
            print(f"{args.company_key}: approval queue already empty")
            return 0
        n = _drop_from_queue(args.company_key, [it["queue_id"] for it in items])
        print(f"{args.company_key}: removed {n} item(s)")
        return 0

    if args.cmd == "unpause":
        cfg = load_cycle_config(args.company_key)
        was_paused = bool(cfg.get("paused_reason") or cfg.get("paused_at_ms"))
        cfg["enabled"] = True
        cfg.pop("paused_at_ms", None)
        cfg.pop("paused_reason", None)
        save_cycle_config(args.company_key, cfg)
        msg = "unpaused" if was_paused else "enabled (was not paused)"
        print(f"{args.company_key}: {msg}")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
