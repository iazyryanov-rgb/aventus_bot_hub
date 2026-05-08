"""Snapshot + diff for WhatsApp-sender health.

Pulls the live state from Infobip via `wa_bot_config.get_infobip_senders`
and compares it to the per-company snapshot persisted to disk. The diff
is what powers the `wa_senders_health` alert template — only meaningful
deltas (quality drops, status flips, limit downgrades, sender appearing
or disappearing) survive into the alert body.

Layout
------
- `data/wa_senders_state/<COMPANY_KEY>.json` — last seen senders (full
  list, slim shape — no logo blobs). First run = file missing → diff
  treats every sender as a "new presence" with severity=info, which we
  suppress in the alert builder by saving baseline first run silently.

- `Change` dataclass — one delta per (sender, field).

- `diff(prev, cur)` — list[Change]. Stable order:
  critical → high → medium → info.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .paths import data_dir


# --- Domain enums (ranked) -------------------------------------------------

QUALITY_RANK = {
    # Higher rank = better.
    "UNKNOWN": 0,
    "LOW":     1,
    "MEDIUM":  2,
    "HIGH":    3,
}

# Higher rank = larger throughput.
LIMIT_RANK = {
    "LIMIT_NA":  0,
    "LIMIT_250": 1,
    "LIMIT_2K":  2,
    "LIMIT_10K": 3,
    "LIMIT_100K":4,
    "UNLIMITED": 5,
}

# Higher rank = worse for our purposes. CONNECTED is normal-OK = 0.
STATUS_RANK = {
    "CONNECTED":    0,
    "MIGRATED":     0,
    "UNKNOWN":      0,
    "PENDING":      1,
    "UNVERIFIED":   1,
    "DISCONNECTED": 1,
    "FLAGGED":      2,
    "RATE_LIMITED": 3,
    "RESTRICTED":   3,
    "BANNED":       4,
    "DELETED":      4,
}

# Statuses that mean "the sender cannot send right now" — used by the
# panel for color coding regardless of which step on the rank axis.
STATUS_BAD = frozenset({
    "BANNED", "DELETED", "RESTRICTED", "RATE_LIMITED",
})
STATUS_WARN = frozenset({
    "FLAGGED", "DISCONNECTED", "PENDING", "UNVERIFIED",
})

# Severity tokens — match `render_alert_html`'s expected vocabulary.
SEV_CRITICAL = "error"
SEV_HIGH     = "warning"
SEV_MEDIUM   = "warning"
SEV_INFO     = "info"

SEVERITY_RANK = {SEV_CRITICAL: 3, SEV_HIGH: 2, SEV_MEDIUM: 1, SEV_INFO: 0}


# --- Persistence -----------------------------------------------------------

def _state_dir() -> Path:
    p = data_dir() / "wa_senders_state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_path(company_key: str) -> Path:
    return _state_dir() / f"{company_key}.json"


def load_snapshot(company_key: str) -> list[dict]:
    p = _state_path(company_key)
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(d, dict):  # legacy wrapper accepted
        d = d.get("senders") or []
    return list(d) if isinstance(d, list) else []


def save_snapshot(company_key: str, senders: list[dict]) -> None:
    p = _state_path(company_key)
    try:
        p.write_text(
            json.dumps(senders, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def has_snapshot(company_key: str) -> bool:
    return _state_path(company_key).exists()


# --- Diff -------------------------------------------------------------------

@dataclass
class Change:
    sender: str
    display_name: str
    field: str   # "presence" | "quality" | "status" | "limit" | "registration"
    before: str
    after: str
    severity: str
    note: str = ""  # short human description used in alert bullets

    def sort_key(self) -> tuple:
        return (-SEVERITY_RANK.get(self.severity, 0), self.sender, self.field)


def _quality_delta_severity(before: str, after: str) -> str:
    # Down = bad. Up = good (info).
    a = QUALITY_RANK.get(before, -1)
    b = QUALITY_RANK.get(after, -1)
    if a < 0 or b < 0:
        return SEV_INFO
    if b < a:
        # HIGH→LOW = critical, single-step = high.
        return SEV_CRITICAL if (a - b) >= 2 else SEV_HIGH
    return SEV_INFO  # recovery / unchanged direction


def _status_delta_severity(before: str, after: str) -> str:
    if after in STATUS_BAD:
        return SEV_CRITICAL
    if after in STATUS_WARN:
        return SEV_MEDIUM
    # CONNECTED / MIGRATED / UNKNOWN
    if before in STATUS_BAD or before in STATUS_WARN:
        return SEV_INFO  # recovery
    return SEV_INFO


def _limit_delta_severity(before: str, after: str) -> str:
    a = LIMIT_RANK.get(before, -1)
    b = LIMIT_RANK.get(after, -1)
    if a < 0 or b < 0:
        return SEV_INFO
    if b < a:
        return SEV_CRITICAL if (a - b) >= 2 else SEV_HIGH
    return SEV_INFO  # tier upgrade


def diff(prev: Iterable[dict], cur: Iterable[dict]) -> list[Change]:
    """Compare two senders snapshots, return ordered list of deltas.
    Pure function — no I/O. Caller decides whether to alert / persist
    / suppress on first run."""
    prev_by = {str(p.get("sender") or ""): p for p in prev if p.get("sender")}
    cur_by  = {str(c.get("sender") or ""): c for c in cur if c.get("sender")}
    changes: list[Change] = []

    # Sender disappeared from the account entirely.
    for sid in sorted(set(prev_by) - set(cur_by)):
        p = prev_by[sid]
        changes.append(Change(
            sender=sid,
            display_name=str(p.get("displayName") or ""),
            field="presence",
            before="present",
            after="missing",
            severity=SEV_HIGH,
            note=f"sender removed from Infobip account",
        ))

    # New sender registered.
    for sid in sorted(set(cur_by) - set(prev_by)):
        c = cur_by[sid]
        changes.append(Change(
            sender=sid,
            display_name=str(c.get("displayName") or ""),
            field="presence",
            before="missing",
            after="present",
            severity=SEV_INFO,
            note=(
                "new sender attached: "
                f"{humanize_status(str(c.get('connectionStatus') or ''))}, "
                f"quality={humanize_quality(str(c.get('qualityRating') or ''))}, "
                f"limit={humanize_limit(str(c.get('limit') or ''))}"
            ),
        ))

    # Field-level deltas for senders present in both snapshots.
    for sid in sorted(set(prev_by) & set(cur_by)):
        p = prev_by[sid]
        c = cur_by[sid]
        display = str(c.get("displayName") or p.get("displayName") or "")

        before = str(p.get("qualityRating") or "")
        after  = str(c.get("qualityRating") or "")
        if before != after:
            changes.append(Change(
                sender=sid, display_name=display, field="quality",
                before=before, after=after,
                severity=_quality_delta_severity(before, after),
                note=(
                    f"quality {humanize_quality(before) or '?'} → "
                    f"{humanize_quality(after) or '?'}"
                ),
            ))

        before = str(p.get("connectionStatus") or "")
        after  = str(c.get("connectionStatus") or "")
        if before != after:
            changes.append(Change(
                sender=sid, display_name=display, field="status",
                before=before, after=after,
                severity=_status_delta_severity(before, after),
                note=(
                    f"status {humanize_status(before) or '?'} → "
                    f"{humanize_status(after) or '?'}"
                ),
            ))

        before = str(p.get("limit") or "")
        after  = str(c.get("limit") or "")
        if before != after:
            changes.append(Change(
                sender=sid, display_name=display, field="limit",
                before=before, after=after,
                severity=_limit_delta_severity(before, after),
                note=(
                    f"messaging limit {humanize_limit(before) or '?'} → "
                    f"{humanize_limit(after) or '?'}"
                ),
            ))

        before = str(p.get("registrationStatus") or "")
        after  = str(c.get("registrationStatus") or "")
        if before != after:
            # Registration is medium severity — registration churn is
            # rare and worth surfacing, but not as bad as a status flip.
            changes.append(Change(
                sender=sid, display_name=display, field="registration",
                before=before, after=after,
                severity=SEV_MEDIUM if after != "FINISHED" else SEV_INFO,
                note=f"registration {before or '?'} → {after or '?'}",
            ))

    changes.sort(key=lambda c: c.sort_key())
    return changes


def worst_severity(changes: Iterable[Change]) -> str:
    """Return the most severe severity in the change list, or SEV_INFO
    if the iterable is empty."""
    rank = -1
    out = SEV_INFO
    for ch in changes:
        r = SEVERITY_RANK.get(ch.severity, 0)
        if r > rank:
            rank = r
            out = ch.severity
    return out


# --- Pretty formatting -----------------------------------------------------

def humanize_limit(limit: str) -> str:
    """Convert Infobip's enum to a human label. Used by both UI and
    alerts so the operator sees the same wording everywhere."""
    return {
        "LIMIT_NA":   "n/a",
        "LIMIT_250":  "250 / 24h",
        "LIMIT_2K":   "2 000 / 24h",
        "LIMIT_10K":  "10 000 / 24h",
        "LIMIT_100K": "100 000 / 24h",
        "UNLIMITED":  "∞",
    }.get(limit, limit or "—")


def humanize_status(status: str) -> str:
    return {
        "CONNECTED":    "Connected",
        "BANNED":       "Banned",
        "DELETED":      "Deleted",
        "RESTRICTED":   "Restricted",
        "RATE_LIMITED": "Rate-limited",
        "FLAGGED":      "Flagged",
        "PENDING":      "Pending",
        "UNVERIFIED":   "Unverified",
        "DISCONNECTED": "Disconnected",
        "MIGRATED":     "Migrated",
        "UNKNOWN":      "Unknown",
    }.get(status, status or "—")


def humanize_quality(q: str) -> str:
    return {
        "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low", "UNKNOWN": "Unknown",
    }.get(q, q or "—")


def format_phone(sender: str) -> str:
    """Pretty-print a digits-only sender as "+CC AAA AAA AAAA"-ish.
    Best-effort: we don't know the country code length, so we keep the
    string compact rather than guessing splits. Examples:
      "573114947740" -> "+57 311 494 7740"
      "5491176635889" -> "+54 9 11 7663 5889"  (fallback to 4-grouping)
    """
    digits = "".join(ch for ch in (sender or "") if ch.isdigit())
    if not digits:
        return sender or ""
    # Group last 4, then 3, then country code.
    if len(digits) >= 11:
        body = digits[-10:]
        cc = digits[:-10]
        groups = [body[i:i+3] for i in range(0, len(body) - 4, 3)]
        groups.append(body[-4:])
        return f"+{cc} " + " ".join(groups)
    return "+" + digits
