"""Unified HTML formatter for Telegram alerts.

All alert messages produced by the hub go through `render_alert_html`,
giving them a consistent visual structure:

    {severity icon} {title}
    🏢 {CODE — Name}  · {category tag}
    🌐 {webitel host (short)}

    {body paragraph}

    📊 {metric label}: {value}
    📊 {metric label}: {value}
    ...

    • {bullet}
    • {bullet}
    ...

    {context K/V lines, italicized}

    💡 {action hint}
    <code>{action command}</code>

Send with `parse_mode="HTML"`. Tags supported by Telegram: `<b>`, `<i>`,
`<u>`, `<s>`, `<code>`, `<pre>`, `<a>`. Anything else needs escaping.
"""
from __future__ import annotations

import html
from typing import Iterable, Optional


# Severity → leading icon. Use sparingly (one per message).
SEVERITY_ICONS = {
    "info":     "ℹ️",
    "ok":       "✅",
    "data":     "📊",
    "warning":  "⚠️",
    "error":    "🔴",
    "critical": "🚨",
    "paused":   "🚨",
}


def esc(s) -> str:
    """HTML-escape a value for inclusion in Telegram HTML messages.
    Always non-failing; non-string inputs are stringified first."""
    return html.escape(str(s if s is not None else ""), quote=False)


def _short_host(host: str) -> str:
    if not host:
        return ""
    h = host.rstrip("/")
    for prefix in ("https://", "http://"):
        if h.startswith(prefix):
            h = h[len(prefix):]
            break
    return h


def render_alert_html(
    *,
    severity: str = "info",
    title: str,
    company_code: str = "",
    company_name: str = "",
    webitel_host: str = "",
    category: str = "",
    metrics: Iterable[tuple[str, str]] = (),
    body: str = "",
    bullets: Iterable[str] = (),
    context_kv: Iterable[tuple[str, str]] = (),
    action_hint: str = "",
    action_command: str = "",
    footer: str = "",
) -> str:
    """Produce an HTML-formatted Telegram message.

    Args:
        severity: visual severity bucket — sets the leading icon.
        title: short bold headline (1 line).
        company_code: short company key like "CO".
        company_name: full company display name.
        webitel_host: optional Webitel host URL (rendered shortened).
        category: optional hash-tagged category like "Agents", "Bot".
        metrics: list of (label, value) pairs rendered as `📊 label: <b>value</b>`.
        body: free-text paragraph (escaped).
        bullets: list of bullet items (escaped).
        context_kv: list of (label, value) shown in italics, no icons.
        action_hint: one-line hint above the action command.
        action_command: a CLI command rendered in <code> for easy copy.
        footer: optional last-line note.

    Returns:
        Ready-to-send HTML body.
    """
    icon = SEVERITY_ICONS.get(severity, SEVERITY_ICONS["info"])
    parts: list[str] = []

    head = f"{icon} <b>{esc(title)}</b>"
    parts.append(head)

    org_bits: list[str] = []
    if company_code or company_name:
        code = esc(company_code) if company_code else ""
        name = esc(company_name) if company_name else ""
        if code and name:
            org_bits.append(f"🏢 <b>{code}</b> — {name}")
        else:
            org_bits.append(f"🏢 {code or name}")
    if category:
        org_bits.append(f"#{esc(category)}")
    if org_bits:
        parts.append(" · ".join(org_bits))
    if webitel_host:
        parts.append(f"🌐 <code>{esc(_short_host(webitel_host))}</code>")

    if body:
        parts.append("")
        parts.append(esc(body))

    metric_list = list(metrics)
    if metric_list:
        parts.append("")
        for label, value in metric_list:
            parts.append(f"📊 {esc(label)}: <b>{esc(value)}</b>")

    bullet_list = list(bullets)
    if bullet_list:
        parts.append("")
        for b in bullet_list:
            parts.append(f"• {esc(b)}")

    ctx_list = list(context_kv)
    if ctx_list:
        parts.append("")
        for label, value in ctx_list:
            parts.append(f"<i>{esc(label)}:</i> <code>{esc(value)}</code>")

    if action_hint or action_command:
        parts.append("")
        if action_hint:
            parts.append(f"💡 <i>{esc(action_hint)}</i>")
        if action_command:
            parts.append(f"<code>{esc(action_command)}</code>")

    if footer:
        parts.append("")
        parts.append(f"<i>{esc(footer)}</i>")

    return "\n".join(parts)
