"""Orchestrate AI-recommendation → Webitel-payload patches.

Glue layer between:

  * `audit_pending` — recommendations the operator queued from chat audits.
  * `calibration_compiler` — locator + invariants from the webitel-schema skill.
  * `webitel_schema_io` — fetch/snapshot/push.
  * `audit_storage` — for back-linking the apply event into audit history.

Two public entry points:

  * `preview(company_key, ...)` returns a planned patch set: which
    recommendations are supported, which aren't, and a chain of patches
    against a fresh payload snapshot. No write, no side effects.

  * `apply(company_key, preview, approved_rec_ids, ...)` consumes the
    preview, applies the approved patches in order, validates invariants,
    and PUTs the result. Conflict-checked via `updated_at`.

The intended UI flow:

    pre  = preview("CO_")
    show pre.supported  (with diffs) and pre.unsupported (with reasons)
    user picks subset → apply_rec_ids
    res  = apply("CO_", pre, apply_rec_ids)
    if res.ok: clear matching items from pending; record in audit_history.

A small CLI is included for dry-run testing without UI:
    python -m app.calibration_apply preview CO_
    python -m app.calibration_apply apply  CO_ <rec_id> [<rec_id> ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import calibration_compiler as cc
from . import webitel_schema_io as wio
from .audit_storage import (
    DEFAULT_AB_SPLIT,
    _history_dir,  # private but stable; we add an apply-log file alongside
    get_pending_corrections,
    _save_pending,
)
from .data import load_companies, Company
from .paths import data_dir
from .wa_bot_config import (
    clear_candidate_schema,
    get_candidate_schema,
    get_prod_schema,
    set_candidate_schema,
)
from .webitel import WebitelClient, WebitelConflict, WebitelError


# --- Data classes -----------------------------------------------------------

@dataclass
class PlannedPatch:
    rec_id: str
    applies_to: str
    target: cc.NodePath
    before: str
    after: str
    rationale: str = ""
    goal: str = "neither"           # prolong | fully_pay | both | neither
    expected_lift_pct: int = 0      # 0..100
    kind: str = "text"              # text | structural


@dataclass
class UnsupportedRec:
    rec_id: str
    applies_to: str
    reason: str  # human-readable


@dataclass
class ApplyPreview:
    company_key: str
    schema_id: int
    schema_name: str
    pattern: str
    expected_updated_at: str
    full_object: dict
    payload: dict
    supported: list[PlannedPatch]
    unsupported: list[UnsupportedRec]
    invariant_errors: list[str]  # invariants of the FETCHED payload (sanity)


@dataclass
class ApplyResult:
    ok: bool
    company_key: str
    schema_id: int
    applied_rec_ids: list[str] = field(default_factory=list)
    snapshot_path_before: Optional[str] = None
    snapshot_path_after: Optional[str] = None
    new_updated_at: Optional[str] = None
    invariant_errors: list[str] = field(default_factory=list)
    error: Optional[str] = None
    log_path: Optional[str] = None


# --- Helpers ----------------------------------------------------------------

def _company(company_key: str) -> Company:
    for c in load_companies():
        if c.key == company_key:
            return c
    raise KeyError(f"company {company_key!r} not in companies.json")


def _client(company: Company) -> WebitelClient:
    if not company.webitel_host or not company.webitel_access_token:
        raise WebitelError(
            f"company {company.key} has no webitel_host/webitel_access_token"
        )
    return WebitelClient(company.webitel_host, company.webitel_access_token)


def _resolve_schema(company_key: str, override: Optional[int]) -> tuple[int, str]:
    if override is not None:
        return int(override), ""
    name, sid = get_prod_schema(company_key)
    if not sid:
        raise KeyError(
            f"no prod schema id known for {company_key!r} "
            "(check companies.json bots.whatsapp.prod_schema_id)"
        )
    return int(sid), name or ""


# --- preview ----------------------------------------------------------------

def preview(
    company_key: str,
    *,
    schema_id: Optional[int] = None,
    recommendations: Optional[list[dict]] = None,
    target_goal: Optional[str] = None,
    min_expected_lift_pct: int = 0,
) -> ApplyPreview:
    """Plan a patch set without writing.

    `schema_id` defaults to the prod WhatsApp schema from companies.json.
    `recommendations` defaults to `audit_pending/<company_key>.json`.
    `target_goal` filters supported recs to those whose `goal` matches
    (or is `both`). Pass `prolong`, `fully_pay`, `both`, or None for no
    filter.
    `min_expected_lift_pct` drops supported recs below this threshold.

    Each pending rec is sorted into `supported` (we know how to patch it)
    or `unsupported` (with a human-readable reason). `supported` is sorted
    by `expected_lift_pct` descending so the highest-impact patches surface
    first. The fetched payload and `expected_updated_at` are returned so a
    subsequent `apply` can use them without re-fetching (and detect drift
    if the user took too long).
    """
    company = _company(company_key)
    sid, sid_name = _resolve_schema(company_key, schema_id)
    client = _client(company)

    full = client.get_schema(sid)
    payload = (full.get("payload") or {})
    pattern = cc.detect_pattern(payload)
    if pattern == cc.PATTERN_UNKNOWN:
        raise cc.UnknownPattern(
            f"schema {sid} ({sid_name or full.get('name','?')}) doesn't "
            "match any pattern the compiler knows. Phase 1 only handles "
            "WhatsApp-Infobip (Pattern 2)."
        )

    invariant_errors = cc.validate_invariants(payload)

    recs = recommendations
    if recs is None:
        recs = get_pending_corrections(company_key)

    supported: list[PlannedPatch] = []
    unsupported: list[UnsupportedRec] = []
    for rec in recs:
        rid = str(rec.get("rec_id") or rec.get("id") or "")
        applies_to = str(rec.get("applies_to") or "")
        rec_goal = str(rec.get("goal") or "neither").lower()
        try:
            rec_lift = int(rec.get("expected_lift_pct") or 0)
        except (TypeError, ValueError):
            rec_lift = 0
        rec_kind = str(rec.get("kind") or "text").lower()

        # Drop structural recs in Phase B (compiler doesn't apply them yet).
        if rec_kind == "structural":
            unsupported.append(UnsupportedRec(
                rid, applies_to,
                "kind=structural — applying structural patches is Phase C",
            ))
            continue

        # Goal filter: 'both' matches any target.
        if target_goal:
            tg = target_goal.lower()
            ok = (rec_goal == tg) or (rec_goal == "both") or (tg == "both")
            if not ok:
                unsupported.append(UnsupportedRec(
                    rid, applies_to,
                    f"goal={rec_goal} doesn't match target_goal={tg}",
                ))
                continue

        # Lift threshold.
        if rec_lift < min_expected_lift_pct:
            unsupported.append(UnsupportedRec(
                rid, applies_to,
                f"expected_lift_pct={rec_lift} < threshold "
                f"{min_expected_lift_pct}",
            ))
            continue

        try:
            target = cc.locate_target(payload, applies_to)
        except cc.InlinePathUnsupported as e:
            unsupported.append(
                UnsupportedRec(rid, applies_to, f"inline path (Phase 3): {e}")
            )
            continue
        except cc.UnknownPath as e:
            unsupported.append(
                UnsupportedRec(rid, applies_to, f"unknown path: {e}")
            )
            continue
        except cc.TargetNotFound as e:
            unsupported.append(
                UnsupportedRec(rid, applies_to, f"target not found: {e}")
            )
            continue
        supported.append(
            PlannedPatch(
                rec_id=rid,
                applies_to=applies_to,
                target=target,
                before=str(rec.get("before") or ""),
                after=str(rec.get("after") or ""),
                rationale=str(rec.get("rationale") or ""),
                goal=rec_goal,
                expected_lift_pct=max(0, min(100, rec_lift)),
                kind=rec_kind,
            )
        )

    # Highest-impact patches first.
    supported.sort(key=lambda pp: pp.expected_lift_pct, reverse=True)

    return ApplyPreview(
        company_key=company_key,
        schema_id=sid,
        schema_name=sid_name or full.get("name", ""),
        pattern=pattern,
        expected_updated_at=str(full.get("updated_at") or ""),
        full_object=full,
        payload=payload,
        supported=supported,
        unsupported=unsupported,
        invariant_errors=invariant_errors,
    )


# --- apply ------------------------------------------------------------------

def apply(
    company_key: str,
    preview_obj: ApplyPreview,
    approved_rec_ids: list[str],
    *,
    dry_run: bool = False,
    strict_before: bool = True,
) -> ApplyResult:
    """Apply the subset of `preview_obj.supported` whose rec_ids are in
    `approved_rec_ids`. Order is preserved as-given.

    If `dry_run=True`: do everything except the final PUT (snapshot,
    chained apply_patch, validate_invariants). Useful for end-to-end
    verification on a fresh fetch without touching Webitel.
    """
    result = ApplyResult(ok=False, company_key=company_key,
                         schema_id=preview_obj.schema_id)

    company = _company(company_key)
    client = _client(company)

    # Re-fetch to defeat any drift in the preview's snapshot. The
    # expected_updated_at we'll compare on push is from `preview_obj`.
    full = client.get_schema(preview_obj.schema_id)
    if str(full.get("updated_at")) != str(preview_obj.expected_updated_at):
        result.error = (
            f"schema {preview_obj.schema_id} was updated since preview "
            f"(preview saw {preview_obj.expected_updated_at}, "
            f"now {full.get('updated_at')}). Re-run preview."
        )
        return result

    snap_before = wio.make_snapshot(
        company_key, preview_obj.schema_id, full,
        label="apply-before",
    )
    result.snapshot_path_before = str(snap_before)

    payload = full.get("payload") or {}

    # Build patch list, in approved-id order, skipping ids that aren't in
    # the supported preview.
    by_id = {p.rec_id: p for p in preview_obj.supported}
    plan: list[PlannedPatch] = []
    for rid in approved_rec_ids:
        if rid in by_id:
            plan.append(by_id[rid])
    if not plan:
        result.error = "no approved rec_ids matched supported preview items"
        return result

    # Apply chained.
    cur_payload = payload
    try:
        for pp in plan:
            patch = cc.Patch(
                target=pp.target,
                before=pp.before,
                after=pp.after,
                rec_id=pp.rec_id,
                applies_to=pp.applies_to,
            )
            cur_payload = cc.apply_patch(
                cur_payload, patch, strict_before=strict_before,
            )
    except cc.CompilerError as e:
        result.error = f"patch failed: {e}"
        return result

    # Validate.
    errors = cc.validate_invariants(cur_payload)
    result.invariant_errors = errors
    if errors:
        result.error = f"invariants failed after patch: {len(errors)} errors"
        return result

    if dry_run:
        result.ok = True
        result.applied_rec_ids = [pp.rec_id for pp in plan]
        result.log_path = _write_apply_log(
            company_key, preview_obj.schema_id, plan,
            snapshot_before=str(snap_before),
            snapshot_after=None,
            new_updated_at=None,
            dry_run=True,
        )
        return result

    # Real push.
    try:
        resp = wio.push_payload(
            client, preview_obj.schema_id, cur_payload,
            expected_updated_at=preview_obj.expected_updated_at,
            base_object=full,
        )
    except WebitelConflict as e:
        result.error = str(e)
        return result
    except WebitelError as e:
        result.error = f"PUT failed: {e}"
        return result

    new_updated_at = str((resp or {}).get("updated_at") or "")
    result.new_updated_at = new_updated_at

    snap_after = wio.make_snapshot(
        company_key, preview_obj.schema_id, resp or full,
        label="apply-after",
    )
    result.snapshot_path_after = str(snap_after)

    result.ok = True
    result.applied_rec_ids = [pp.rec_id for pp in plan]
    result.log_path = _write_apply_log(
        company_key, preview_obj.schema_id, plan,
        snapshot_before=str(snap_before),
        snapshot_after=str(snap_after),
        new_updated_at=new_updated_at,
        dry_run=False,
    )
    return result


# --- Champion / candidate management ---------------------------------------

@dataclass
class CandidateInfo:
    company_key: str
    champion_id: int
    champion_name: str
    candidate_id: int
    candidate_name: str
    snapshot_path: Optional[str] = None


def _default_candidate_name(champion_name: str) -> str:
    """Default rename rule: replace 'prod' with 'candidate' if present,
    otherwise append '-candidate'. Example: 'whatsapp-infobip-credito365-prod'
    → 'whatsapp-infobip-credito365-candidate'."""
    if "prod" in champion_name:
        return champion_name.replace("prod", "candidate")
    return f"{champion_name}-candidate"


def make_candidate(
    company_key: str,
    *,
    new_name: Optional[str] = None,
    overwrite: bool = False,
) -> CandidateInfo:
    """Clone the prod (champion) WhatsApp schema into a fresh candidate
    schema in Webitel, and persist its id+name into companies.json under
    `bots.whatsapp.candidate_schema_*`.

    Refuses if a candidate already exists for this company unless
    `overwrite=True` (in which case the OLD candidate id stays in Webitel,
    just gets unlinked from companies.json — operator can clean up via UI).

    The traffic split (which phone-digits go to candidate) stays in
    Webitel-side routing config; that's an operator one-time setup.
    """
    company = _company(company_key)
    client = _client(company)

    champ_name, champ_id = get_prod_schema(company_key)
    if not champ_id:
        raise KeyError(
            f"{company_key} has no prod schema id; cannot clone."
        )

    existing_name, existing_id = get_candidate_schema(company_key)
    if existing_id and not overwrite:
        raise ValueError(
            f"{company_key} already has a candidate schema "
            f"(id={existing_id}, name={existing_name!r}). "
            "Pass overwrite=True to mint a new one (the old one stays in "
            "Webitel and must be cleaned up via UI)."
        )

    target_name = new_name or _default_candidate_name(champ_name or "")
    if not target_name:
        target_name = f"{company_key}-candidate"

    created = wio.clone_schema(
        client,
        int(champ_id),
        target_name,
        company_key=company_key,
        snapshot_label="clone-source",
    )
    new_id = int(created.get("id"))
    new_name_final = str(created.get("name") or target_name)

    set_candidate_schema(company_key, new_id, new_name_final)

    # Find the snapshot we just made (the most recent snapshot for the
    # champion id labeled clone-source).
    snap_dir = wio.snapshots_root() / company_key
    snap_path: Optional[Path] = None
    if snap_dir.exists():
        candidates = sorted(
            snap_dir.glob(f"{int(champ_id)}_*_clone-source.json"),
            reverse=True,
        )
        if candidates:
            snap_path = candidates[0]

    return CandidateInfo(
        company_key=company_key,
        champion_id=int(champ_id),
        champion_name=str(champ_name or ""),
        candidate_id=new_id,
        candidate_name=new_name_final,
        snapshot_path=str(snap_path) if snap_path else None,
    )


@dataclass
class PromoteResult:
    ok: bool
    company_key: str
    champion_id: int
    candidate_id: int
    snapshot_champion_before: Optional[str] = None
    snapshot_champion_after: Optional[str] = None
    new_updated_at: Optional[str] = None
    error: Optional[str] = None


def promote_candidate(company_key: str) -> PromoteResult:
    """Push the candidate's payload onto the champion's id.

    Effect: in Webitel, the schema id that prod-traffic uses (champion_id)
    now contains what the candidate had. The candidate id is left untouched
    and immediately becomes a fresh "starting point" for next week's cycle
    (same content as champion).

    Why not swap ids? Because Webitel-side routing config (the 80/20 phone
    digit split) is keyed by id; swapping ids would break it. Keeping ids
    stable means promotion is just `push candidate.payload → champion.id`.

    Snapshots both before and after.
    """
    result = PromoteResult(
        ok=False, company_key=company_key,
        champion_id=0, candidate_id=0,
    )

    company = _company(company_key)
    client = _client(company)

    champ_name, champ_id = get_prod_schema(company_key)
    cand_name, cand_id = get_candidate_schema(company_key)
    if not champ_id or not cand_id:
        result.error = (
            f"missing schema ids: champion={champ_id!r} candidate={cand_id!r}"
        )
        return result
    if int(champ_id) == int(cand_id):
        result.error = (
            f"champion_id == candidate_id == {champ_id}; that's a misconfig"
        )
        return result

    result.champion_id = int(champ_id)
    result.candidate_id = int(cand_id)

    # Fetch both. Champion goes to snapshot; candidate's payload is what
    # we'll push.
    try:
        champ_full = client.get_schema(int(champ_id))
        cand_full = client.get_schema(int(cand_id))
    except WebitelError as e:
        result.error = f"GET failed: {e}"
        return result

    snap_before = wio.make_snapshot(
        company_key, int(champ_id), champ_full,
        label="promote-before",
    )
    result.snapshot_champion_before = str(snap_before)

    cand_payload = cand_full.get("payload") or {}

    # Sanity: candidate should also pass invariants.
    inv = cc.validate_invariants(cand_payload)
    if inv:
        result.error = (
            f"candidate payload fails {len(inv)} invariants; refusing to "
            f"promote. First error: {inv[0]}"
        )
        return result

    try:
        resp = wio.push_payload(
            client, int(champ_id), cand_payload,
            expected_updated_at=str(champ_full.get("updated_at") or ""),
            base_object=champ_full,
        )
    except WebitelConflict as e:
        result.error = str(e)
        return result
    except WebitelError as e:
        result.error = f"PUT failed: {e}"
        return result

    snap_after = wio.make_snapshot(
        company_key, int(champ_id), resp or champ_full,
        label="promote-after",
    )
    result.snapshot_champion_after = str(snap_after)
    result.new_updated_at = str((resp or {}).get("updated_at") or "")
    result.ok = True
    return result


@dataclass
class RollbackResult:
    ok: bool
    company_key: str
    schema_id: int
    snapshot_path: str
    new_updated_at: Optional[str] = None
    error: Optional[str] = None


def rollback_to_snapshot(
    company_key: str,
    snapshot_path: str,
    *,
    schema_id: Optional[int] = None,
) -> RollbackResult:
    """Restore the schema's `payload` to what was captured in the snapshot
    file. The schema id is taken from the snapshot itself unless overridden.
    Snapshots a fresh "before-rollback" copy so rollbacks are themselves
    reversible.
    """
    path = Path(snapshot_path)
    if not path.exists():
        return RollbackResult(
            ok=False, company_key=company_key, schema_id=schema_id or 0,
            snapshot_path=snapshot_path,
            error=f"snapshot not found: {snapshot_path}",
        )
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return RollbackResult(
            ok=False, company_key=company_key, schema_id=schema_id or 0,
            snapshot_path=snapshot_path,
            error=f"could not parse snapshot: {e}",
        )

    target_id = int(schema_id or snap.get("id") or 0)
    if not target_id:
        return RollbackResult(
            ok=False, company_key=company_key, schema_id=0,
            snapshot_path=snapshot_path,
            error="snapshot has no `id` field; pass schema_id explicitly",
        )

    company = _company(company_key)
    client = _client(company)

    # Snapshot current state first — so even rollback can be rolled back.
    try:
        live = client.get_schema(target_id)
    except WebitelError as e:
        return RollbackResult(
            ok=False, company_key=company_key, schema_id=target_id,
            snapshot_path=snapshot_path,
            error=f"GET failed: {e}",
        )
    wio.make_snapshot(
        company_key, target_id, live, label="rollback-before",
    )

    # Push the snapshot's payload back, using live's updated_at for
    # conflict guard.
    snap_payload = snap.get("payload") or {}
    try:
        resp = wio.push_payload(
            client, target_id, snap_payload,
            expected_updated_at=str(live.get("updated_at") or ""),
            base_object=live,
        )
    except WebitelConflict as e:
        return RollbackResult(
            ok=False, company_key=company_key, schema_id=target_id,
            snapshot_path=snapshot_path,
            error=str(e),
        )
    except WebitelError as e:
        return RollbackResult(
            ok=False, company_key=company_key, schema_id=target_id,
            snapshot_path=snapshot_path,
            error=f"PUT failed: {e}",
        )
    wio.make_snapshot(
        company_key, target_id, resp or live, label="rollback-after",
    )
    return RollbackResult(
        ok=True, company_key=company_key, schema_id=target_id,
        snapshot_path=snapshot_path,
        new_updated_at=str((resp or {}).get("updated_at") or ""),
    )


def remove_from_pending(company_key: str, applied_rec_ids: list[str]) -> int:
    """Drop the given rec_ids from `audit_pending/<company_key>.json`.
    Returns the count actually removed."""
    if not applied_rec_ids:
        return 0
    items = get_pending_corrections(company_key)
    keep = [it for it in items if str(it.get("rec_id")) not in applied_rec_ids]
    removed = len(items) - len(keep)
    if removed:
        _save_pending(company_key, keep)
    return removed


# --- Apply log --------------------------------------------------------------

def _apply_log_dir(company_key: str) -> Path:
    return _history_dir(company_key) / "_webitel_apply"


def _write_apply_log(
    company_key: str,
    schema_id: int,
    plan: list[PlannedPatch],
    *,
    snapshot_before: Optional[str],
    snapshot_after: Optional[str],
    new_updated_at: Optional[str],
    dry_run: bool,
) -> str:
    folder = _apply_log_dir(company_key)
    folder.mkdir(parents=True, exist_ok=True)
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )
    record = {
        "ts_ms": ts_ms,
        "company_key": company_key,
        "schema_id": int(schema_id),
        "dry_run": bool(dry_run),
        "patches": [
            {
                "rec_id": pp.rec_id,
                "applies_to": pp.applies_to,
                "page_name": pp.target.page_name,
                "node_id": pp.target.node_id,
                "json_path": pp.target.json_path,
                "before_len": len(pp.before),
                "after_len": len(pp.after),
            }
            for pp in plan
        ],
        "snapshot_before": snapshot_before,
        "snapshot_after": snapshot_after,
        "new_updated_at": new_updated_at,
    }
    suffix = "_dry-run" if dry_run else ""
    path = folder / f"{ts}{suffix}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(path)


# --- CLI --------------------------------------------------------------------

def _print_preview(p: ApplyPreview) -> None:
    print(f"company:     {p.company_key}")
    print(f"schema:      {p.schema_id} ({p.schema_name})")
    print(f"pattern:     {p.pattern}")
    print(f"updated_at:  {p.expected_updated_at}")
    print(f"invariants:  {len(p.invariant_errors)} pre-existing errors")
    for e in p.invariant_errors[:3]:
        print(f"             - {e}")
    print()
    print(f"supported  ({len(p.supported)}):")
    for pp in p.supported:
        print(
            f"  [{pp.rec_id}] goal={pp.goal} lift={pp.expected_lift_pct}% "
            f"kind={pp.kind}\n"
            f"    {pp.applies_to}\n"
            f"    page={pp.target.page_name} node={pp.target.node_id} "
            f"path={pp.target.json_path}\n"
            f"    before={pp.before[:80]!r}\n"
            f"    after ={pp.after[:80]!r}"
        )
    print(f"unsupported ({len(p.unsupported)}):")
    for u in p.unsupported:
        print(f"  [{u.rec_id}] {u.applies_to}: {u.reason}")


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="calibration_apply")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_preview = sub.add_parser("preview")
    p_preview.add_argument("company_key")
    p_preview.add_argument("--schema-id", type=int, default=None)
    p_preview.add_argument(
        "--goal", choices=("prolong", "fully_pay", "both"), default=None,
        help="Filter recs to those targeting this business goal "
             "(plus goal=both, which always matches).",
    )
    p_preview.add_argument(
        "--min-lift", type=int, default=0, metavar="PCT",
        help="Drop recs whose expected_lift_pct is below this threshold.",
    )

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("company_key")
    p_apply.add_argument("rec_ids", nargs="+")
    p_apply.add_argument("--schema-id", type=int, default=None)
    p_apply.add_argument(
        "--goal", choices=("prolong", "fully_pay", "both"), default=None,
        help="Same filter as in preview — a rec_id won't apply unless it "
             "passes this goal filter.",
    )
    p_apply.add_argument("--min-lift", type=int, default=0, metavar="PCT")
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.add_argument(
        "--no-strict-before", action="store_true",
        help="apply even if `before` doesn't match the live value",
    )

    p_clone = sub.add_parser(
        "clone-candidate",
        help="Clone the prod WhatsApp schema into a fresh candidate "
             "and link it in companies.json",
    )
    p_clone.add_argument("company_key")
    p_clone.add_argument("--name", default=None,
                         help="Override the candidate schema name")
    p_clone.add_argument("--overwrite", action="store_true",
                         help="Replace existing candidate link "
                              "(old Webitel schema is left in place)")

    p_promote = sub.add_parser(
        "promote-candidate",
        help="Push candidate's payload onto champion's id",
    )
    p_promote.add_argument("company_key")

    p_review = sub.add_parser(
        "weekly-review",
        help="Compute champion vs candidate cohort metrics over the last "
             "N days and print the promotion decision (no write)",
    )
    p_review.add_argument("company_key")
    p_review.add_argument("--days", type=int, default=7,
                          help="Period length in days (default: 7)")
    p_review.add_argument(
        "--goal", choices=("prolong", "fully_pay", "both"),
        default="fully_pay",
    )
    p_review.add_argument("--min-lift-pct", type=float, default=2.0,
                          help="Min absolute rate lift, percent (default: 2.0)")
    p_review.add_argument("--min-n", type=int, default=50,
                          help="Min per-cohort sample with payment data")
    p_review.add_argument("--chat-limit", type=int, default=5000)

    p_auto = sub.add_parser(
        "auto-promote",
        help="Run weekly-review and promote candidate if it wins. "
             "Use --dry-run to skip the actual promote.",
    )
    p_auto.add_argument("company_key")
    p_auto.add_argument("--days", type=int, default=7)
    p_auto.add_argument(
        "--goal", choices=("prolong", "fully_pay", "both"),
        default="fully_pay",
    )
    p_auto.add_argument("--min-lift-pct", type=float, default=2.0)
    p_auto.add_argument("--min-n", type=int, default=50)
    p_auto.add_argument("--chat-limit", type=int, default=5000)
    p_auto.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "preview":
        pv = preview(
            args.company_key,
            schema_id=args.schema_id,
            target_goal=args.goal,
            min_expected_lift_pct=args.min_lift,
        )
        _print_preview(pv)
        return 0

    if args.cmd == "apply":
        pv = preview(
            args.company_key,
            schema_id=args.schema_id,
            target_goal=args.goal,
            min_expected_lift_pct=args.min_lift,
        )
        _print_preview(pv)
        print()
        res = apply(
            args.company_key, pv, args.rec_ids,
            dry_run=args.dry_run,
            strict_before=not args.no_strict_before,
        )
        print(f"ok:          {res.ok}")
        print(f"applied:     {res.applied_rec_ids}")
        print(f"new_updated: {res.new_updated_at}")
        print(f"snapshot_b:  {res.snapshot_path_before}")
        print(f"snapshot_a:  {res.snapshot_path_after}")
        print(f"log:         {res.log_path}")
        if res.error:
            print(f"error:       {res.error}")
        return 0 if res.ok else 2

    if args.cmd == "clone-candidate":
        info = make_candidate(
            args.company_key,
            new_name=args.name,
            overwrite=args.overwrite,
        )
        print(f"company:        {info.company_key}")
        print(f"champion:       id={info.champion_id} name={info.champion_name!r}")
        print(f"candidate:      id={info.candidate_id} name={info.candidate_name!r}")
        print(f"source snapshot: {info.snapshot_path}")
        print()
        print("Next: in Webitel UI, set up the 80/20 traffic split")
        print("between champion and candidate (by phone-digit).")
        return 0

    if args.cmd == "promote-candidate":
        res = promote_candidate(args.company_key)
        print(f"company:         {res.company_key}")
        print(f"champion id:     {res.champion_id}")
        print(f"candidate id:    {res.candidate_id}")
        print(f"snapshot before: {res.snapshot_champion_before}")
        print(f"snapshot after:  {res.snapshot_champion_after}")
        print(f"new updated_at:  {res.new_updated_at}")
        print(f"ok:              {res.ok}")
        if res.error:
            print(f"error:           {res.error}")
        return 0 if res.ok else 2

    if args.cmd in ("weekly-review", "auto-promote"):
        # Lazy import to keep `python -m app.calibration_apply preview ...`
        # working even if chat_audit_data deps aren't installed in dev.
        from . import weekly_review as wr

        until_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        since_ms = until_ms - int(args.days) * 86_400_000
        min_lift = float(args.min_lift_pct) / 100.0

        if args.cmd == "weekly-review":
            metrics = wr.compute_weekly_metrics(
                args.company_key, since_ms, until_ms,
                chat_limit=int(args.chat_limit),
            )
            decision = wr.should_promote(
                metrics,
                target_goal=args.goal,
                min_lift=min_lift,
                min_n=int(args.min_n),
            )
            print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
            return 0

        # auto-promote
        res = wr.auto_promote(
            args.company_key, since_ms, until_ms,
            target_goal=args.goal,
            min_lift=min_lift,
            min_n=int(args.min_n),
            chat_limit=int(args.chat_limit),
            dry_run=bool(args.dry_run),
        )
        out = {
            "decision": res.decision.to_dict(),
            "promoted": res.promoted,
            "promote_error": res.promote_error,
            "promote_log": res.promote_log,
            "log_path": res.log_path,
            "dry_run": bool(args.dry_run),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        if res.decision.promote and not args.dry_run:
            return 0 if res.promoted else 2
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
