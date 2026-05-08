"""Telegram delivery for AI chat audits.

Two helpers:

  * `format_audit_for_telegram(company, result, period_days, model_kind, elapsed_s)`
    — render the audit result as a list of HTML messages, each <=4000 chars,
    split at section/item boundaries.

  * `send_audit_to_telegram(company, result, ...)` — push those chunks into
    the company's forum topic via the same bot/topic mapping the alerts use
    (`alerts.ensure_company_topic`).

Scheduling lives in `app/scheduler.py` — `ai_audit` is a regular alert
template configured per company in `bot_alerts[<KEY>][whatsapp]`.
"""
from __future__ import annotations

import html
from typing import Optional

from .alerts import (
    TelegramError,
    ensure_company_topic,
    load_alerts_config,
    send_telegram_message,
)
from .data import Company, load_companies


TELEGRAM_MSG_LIMIT = 4000  # leave headroom under 4096 hard limit


_SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
_KIND_ICON = {
    "prompt": "📝", "function": "🛠", "enum": "🏷",
    "flow": "🔀", "data": "📊",
}
_MODEL_LABEL = {"sonnet": "Sonnet 4.6", "opus": "Opus 4.7"}


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _section_header(company: Company, result: dict, header_meta: dict) -> str:
    summary = result.get("summary") or {}
    total = int(summary.get("total_chats") or header_meta.get("records_sent") or 0)
    good = int(summary.get("good_count") or 0)
    bad = int(summary.get("bad_count") or 0)
    code = company.key.rstrip("_")
    period_days = header_meta.get("period_days", "?")
    model_kind = header_meta.get("model_kind", "sonnet")
    model_label = _MODEL_LABEL.get(model_kind, model_kind)
    elapsed = header_meta.get("elapsed_s")
    usage = (result.get("_meta") or {}).get("usage") or {}
    cache_read = usage.get("cache_read_input_tokens") or 0
    in_t = usage.get("input_tokens") or 0
    out_t = usage.get("output_tokens") or 0
    runtime = (
        f" · runtime {elapsed:.1f}s" if isinstance(elapsed, (int, float)) else ""
    )
    return (
        f"🤖 <b>AI Audit · {_esc(company.name)} ({_esc(code)})</b>\n"
        f"📅 Period: last {_esc(period_days)} days · "
        f"{total} chats analyzed\n"
        f"🧠 Model: {_esc(model_label)}{runtime}\n"
        f"🔢 Tokens: in {in_t:,} (cache {cache_read:,}) · out {out_t:,}\n"
        f"\n"
        f"📊 <b>Summary</b>\n"
        f"Total: <b>{total}</b> · ✅ Good: <b>{good}</b> · "
        f"❌ Bad: <b>{bad}</b>"
    )


def _section_summary_lists(result: dict) -> str:
    s = result.get("summary") or {}
    parts = []
    common = list(s.get("common_failures") or [])[:8]
    if common:
        lines = "\n".join(f"• {_esc(line)}" for line in common)
        parts.append(f"⚠️ <b>Common failures</b>\n{lines}")
    signals = list(s.get("top_signals") or [])[:8]
    if signals:
        lines = "\n".join(f"• {_esc(line)}" for line in signals)
        parts.append(f"🎯 <b>Top signals</b>\n{lines}")
    return "\n\n".join(parts)


def _section_findings(result: dict) -> str:
    findings = list(result.get("findings") or [])
    if not findings:
        return ""
    parts = [f"🔍 <b>Findings ({len(findings)})</b>"]
    for i, f in enumerate(findings, start=1):
        sev = (f.get("severity") or "low").lower()
        sev_icon = _SEVERITY_ICON.get(sev, "🟡")
        kind = (f.get("kind") or "").lower()
        kind_icon = _KIND_ICON.get(kind, "•")
        impact = f.get("estimated_impact_pct")
        impact_str = (
            f" · impact ≈ {int(impact)}%"
            if isinstance(impact, (int, float))
            else ""
        )
        head = (
            f"{sev_icon} <b>{i}. [{sev.upper()} · {kind_icon} {_esc(kind)}]</b>"
            f"{impact_str}"
        )
        body = _esc(f.get("pattern") or "—")
        ev = list(f.get("evidence_chat_ids") or [])
        ev_str = ""
        if ev:
            shown = ev[:6]
            tail = " …" if len(ev) > 6 else ""
            ev_str = f"\n<i>Evidence:</i> <code>{_esc(', '.join(shown))}</code>{tail}"
        parts.append(f"{head}\n{body}{ev_str}")
    return "\n\n".join(parts)


def _section_recommendations(result: dict) -> str:
    recs = list(result.get("recommendations") or [])
    if not recs:
        return ""
    parts = [f"✅ <b>Recommendations ({len(recs)})</b>"]
    for i, r in enumerate(recs, start=1):
        head = (
            f"<b>{i}.</b> → <code>{_esc(r.get('applies_to', ''))}</code>"
        )
        rationale = r.get("rationale")
        rat_block = (
            f"\n<i>Why:</i> {_esc(rationale)}" if rationale else ""
        )
        before = (r.get("before") or "").strip()
        after = (r.get("after") or "").strip()
        diff_block = ""
        if before or after:
            # NOTE: keep at most single \n inside the <pre> block. The chunker
            # below splits at \n\n boundaries, and an unmatched <pre> across a
            # split boundary makes Telegram reject the message with HTTP 400
            # "Can't find end tag corresponding to start tag pre".
            diff_block = "\n<pre>"
            if before:
                diff_block += f"--- Before ---\n{_esc(before)}"
            if after:
                if before:
                    diff_block += "\n"
                diff_block += f"+++ After +++\n{_esc(after)}"
            diff_block += "</pre>"
        linked = r.get("linked_findings") or []
        link_block = (
            f"\n<i>Linked findings:</i> <code>{_esc(', '.join(linked))}</code>"
            if linked else ""
        )
        parts.append(f"{head}{rat_block}{diff_block}{link_block}")
    return "\n\n".join(parts)


def format_audit_for_telegram(
    company: Company,
    result: dict,
    period_days: int,
    model_kind: str,
    elapsed_s: Optional[float] = None,
) -> list[str]:
    """Return a list of HTML-formatted Telegram messages, each <= 4000 chars.
    Splits at section / item boundaries to keep readability."""
    header_meta = {
        "period_days": period_days,
        "model_kind": model_kind,
        "elapsed_s": elapsed_s,
        "records_sent": (result.get("_meta") or {}).get("records_sent"),
    }
    blocks: list[str] = []
    head = _section_header(company, result, header_meta)
    summary_lists = _section_summary_lists(result)
    if summary_lists:
        head = head + "\n\n" + summary_lists
    blocks.append(head)
    fnd = _section_findings(result)
    if fnd:
        blocks.append(fnd)
    rec = _section_recommendations(result)
    if rec:
        blocks.append(rec)

    out: list[str] = []
    for blk in blocks:
        if len(blk) <= TELEGRAM_MSG_LIMIT:
            out.append(blk)
            continue
        # Split on \n\n boundaries (item-level) to keep readability.
        pieces = blk.split("\n\n")
        cur = ""
        for piece in pieces:
            candidate = (cur + "\n\n" + piece) if cur else piece
            if len(candidate) > TELEGRAM_MSG_LIMIT and cur:
                out.append(cur)
                cur = piece
            else:
                cur = candidate
        if cur:
            out.append(cur)
    # Hard fallback for any leftover oversized chunk.
    final: list[str] = []
    for blk in out:
        if len(blk) <= TELEGRAM_MSG_LIMIT:
            final.append(blk)
        else:
            for i in range(0, len(blk), TELEGRAM_MSG_LIMIT):
                final.append(blk[i:i + TELEGRAM_MSG_LIMIT])
    return final


def send_audit_to_telegram(
    company: Company,
    result: dict,
    period_days: int,
    model_kind: str,
    elapsed_s: Optional[float] = None,
) -> Optional[str]:
    """Send the audit result to the company's TG topic. Returns None on
    success, or an error string."""
    cfg = load_alerts_config()
    tg = cfg.get("telegram") or {}
    token = tg.get("bot_token") or ""
    chat_id = tg.get("chat_id") or ""
    if not token or not chat_id:
        return "Telegram bot_token / chat_id not configured"
    company_index = {
        ck: i for i, ck in enumerate(sorted({c.key for c in load_companies()}))
    }
    topic_id = ensure_company_topic(
        cfg, company, index_hint=company_index.get(company.key, 0),
    )
    chunks = format_audit_for_telegram(
        company, result, period_days, model_kind, elapsed_s,
    )
    err: Optional[str] = None
    for chunk in chunks:
        try:
            send_telegram_message(
                token, chat_id, chunk,
                parse_mode="HTML",
                message_thread_id=topic_id,
            )
        except TelegramError as exc:
            err = str(exc)
            break
    return err


# ---------------------------------------------------------------------------
# Cycle summary (Phase G1) — daily auto-calibration result
# ---------------------------------------------------------------------------

def format_cycle_summary(company: Company, cycle_result, audit_id: str) -> str:
    """Render a one-message HTML summary of a calibration_cycle run.
    `cycle_result` is a `calibration_cycle.CycleResult` instance."""
    code = company.key.rstrip("_")
    mode = getattr(cycle_result, "approval_mode", "auto") or "auto"
    queued_count = int(getattr(cycle_result, "queued_count", 0) or 0)

    paused = bool(getattr(cycle_result, "cycle_paused", False))
    drift = bool(getattr(cycle_result, "schema_drift_detected", False))
    if paused and drift:
        head_icon, head_label = "🚨", "PAUSED — schema_drift"
    elif paused:
        head_icon, head_label = "🚨", "PAUSED — large_change_guard"
    elif cycle_result.apply_ok:
        head_icon, head_label = "✅", "applied"
    elif queued_count > 0:
        head_icon, head_label = "📝", f"queued for approval"
    elif cycle_result.skipped:
        head_icon, head_label = "🟡", "skipped"
    else:
        head_icon, head_label = "❌", "failed"

    dry = " · <b>dry-run</b>" if cycle_result.dry_run else ""
    mode_tag = f" · mode=<b>{_esc(mode)}</b>" if mode != "auto" else ""
    lines: list[str] = [
        f"🔧 <b>Calibration cycle · {_esc(company.name)} ({_esc(code)})</b>"
        f"{mode_tag}{dry}",
        f"{head_icon} <b>{head_label}</b> · audit_id=<code>{_esc(audit_id or '?')}</code>",
    ]
    if cycle_result.candidate_schema_id:
        lines.append(
            f"🎯 candidate_id=<code>{cycle_result.candidate_schema_id}</code>"
        )
    if cycle_result.skipped and cycle_result.reason:
        lines.append(f"<i>Reason:</i> {_esc(cycle_result.reason)}")
    if paused:
        lines.append(
            f"<i>Auto-paused:</i> {_esc(cycle_result.apply_error or '')}"
        )
        lines.append(
            f"<b>Resume after review:</b> <code>python -m app.calibration_cycle "
            f"unpause {_esc(company.key)}</code>"
        )
    elif not cycle_result.apply_ok and not queued_count and cycle_result.apply_error:
        lines.append(f"<i>Error:</i> {_esc(cycle_result.apply_error)}")

    lines.append(
        f"🧮 supported={cycle_result.supported_count} · "
        f"unsupported={cycle_result.unsupported_count} · "
        f"approved={len(cycle_result.approved_rec_ids)} · "
        f"applied={len(cycle_result.applied_rec_ids)} · "
        f"queued={queued_count} · "
        f"pending+={cycle_result.pending_added}"
    )
    if cycle_result.applied_rec_ids:
        lines.append("<b>Applied:</b>")
        for rid in cycle_result.applied_rec_ids[:10]:
            lines.append(f"  • <code>{_esc(rid)}</code>")

    large_warns = list(getattr(cycle_result, "large_change_warnings", []) or [])
    if large_warns and not paused:
        # Auto mode would have paused; this branch is gated mode where the
        # warnings travel with the queue but the cycle continues.
        lines.append("⚠️ <b>Large changes detected (>threshold):</b>")
        for w in large_warns[:10]:
            lines.append(
                f"  • <code>{_esc(w.get('rec_id'))}</code> "
                f"({int(round(float(w.get('change_pct', 0)) * 100))}%) — "
                f"<code>{_esc(w.get('applies_to'))}</code>"
            )
        lines.append(
            "<i>Read carefully before approving — these patches rewrote "
            "more than the configured threshold.</i>"
        )

    queued_items = list(getattr(cycle_result, "queued_items", []) or [])
    if queued_items:
        lines.append("<b>Queued for approval:</b>")
        for it in queued_items[:10]:
            qid = it.get("queue_id", "")
            lift = it.get("expected_lift_pct", 0)
            goal = it.get("goal", "")
            applies_to = it.get("applies_to", "")
            warn_marker = " ⚠️" if it.get("large_change_warning") else ""
            lines.append(
                f"  • <code>{_esc(qid)}</code>{warn_marker} "
                f"goal={_esc(goal)} +{lift}% — "
                f"<code>{_esc(applies_to)}</code>"
            )
        all_qids = " ".join(it.get("queue_id", "") for it in queued_items)
        lines.append("")
        lines.append(
            f"<b>Approve all:</b>\n"
            f"<code>python -m app.calibration_cycle approve "
            f"{_esc(company.key)} {_esc(all_qids)}</code>"
        )
        lines.append(
            f"<b>Reject:</b>\n"
            f"<code>python -m app.calibration_cycle reject "
            f"{_esc(company.key)} &lt;queue_id&gt;</code>"
        )

    if cycle_result.snapshot_before:
        lines.append(
            f"<i>snapshot_before:</i> <code>{_esc(cycle_result.snapshot_before)}</code>"
        )
    if cycle_result.snapshot_after:
        lines.append(
            f"<i>snapshot_after:</i> <code>{_esc(cycle_result.snapshot_after)}</code>"
        )
    if cycle_result.log_path:
        lines.append(f"<i>log:</i> <code>{_esc(cycle_result.log_path)}</code>")
    return "\n".join(lines)


def send_cycle_summary_to_telegram(
    company: Company, cycle_result, audit_id: str,
) -> Optional[str]:
    """Push the calibration cycle summary to the company's TG topic.
    Returns None on success, or an error string."""
    cfg = load_alerts_config()
    tg = cfg.get("telegram") or {}
    token = tg.get("bot_token") or ""
    chat_id = tg.get("chat_id") or ""
    if not token or not chat_id:
        return "Telegram bot_token / chat_id not configured"
    company_index = {
        ck: i for i, ck in enumerate(sorted({c.key for c in load_companies()}))
    }
    topic_id = ensure_company_topic(
        cfg, company, index_hint=company_index.get(company.key, 0),
    )
    text = format_cycle_summary(company, cycle_result, audit_id)
    try:
        send_telegram_message(
            token, chat_id, text,
            parse_mode="HTML",
            message_thread_id=topic_id,
        )
    except TelegramError as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------------------
# Weekly review summary (Phase G1) — Monday digest
# ---------------------------------------------------------------------------

def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "—"


def format_weekly_review_summary(
    company: Company, decision, days: int,
) -> str:
    """Render a one-message HTML summary from `weekly_review.PromoteDecision`."""
    code = company.key.rstrip("_")
    m = decision.metrics
    champ = m.champion
    cand = m.candidate
    icon = "✅" if decision.promote else "🟡"
    lines = [
        f"📊 <b>Weekly review · {_esc(company.name)} ({_esc(code)})</b>",
        f"📅 last {days}d · goal=<b>{_esc(decision.target_goal)}</b> · "
        f"candidate_digits={_esc(m.candidate_digits)}",
        "",
        f"🏆 <b>Champion</b>: n={champ.n} (pay-data={champ.with_payment_data}) · "
        f"close={_fmt_pct(champ.close_rate)} · "
        f"prolong={_fmt_pct(champ.prolong_rate)} · "
        f"bot_only={_fmt_pct(champ.bot_only_rate)}",
        f"🥊 <b>Candidate</b>: n={cand.n} (pay-data={cand.with_payment_data}) · "
        f"close={_fmt_pct(cand.close_rate)} · "
        f"prolong={_fmt_pct(cand.prolong_rate)} · "
        f"bot_only={_fmt_pct(cand.bot_only_rate)}",
        "",
        f"{icon} <b>Decision: {'PROMOTE' if decision.promote else 'KEEP'}</b>",
        f"<i>{_esc(decision.reason)}</i>",
    ]
    if decision.promote:
        lines.append("")
        lines.append(
            f"To commit: <code>python -m app.calibration_apply "
            f"auto-promote {company.key} --goal {decision.target_goal}</code>"
        )
    return "\n".join(lines)


def send_weekly_review_to_telegram(
    company: Company, decision, days: int,
) -> Optional[str]:
    cfg = load_alerts_config()
    tg = cfg.get("telegram") or {}
    token = tg.get("bot_token") or ""
    chat_id = tg.get("chat_id") or ""
    if not token or not chat_id:
        return "Telegram bot_token / chat_id not configured"
    company_index = {
        ck: i for i, ck in enumerate(sorted({c.key for c in load_companies()}))
    }
    topic_id = ensure_company_topic(
        cfg, company, index_hint=company_index.get(company.key, 0),
    )
    text = format_weekly_review_summary(company, decision, days)
    try:
        send_telegram_message(
            token, chat_id, text,
            parse_mode="HTML",
            message_thread_id=topic_id,
        )
    except TelegramError as exc:
        return str(exc)
    return None
