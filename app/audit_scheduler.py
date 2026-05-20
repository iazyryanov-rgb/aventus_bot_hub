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
