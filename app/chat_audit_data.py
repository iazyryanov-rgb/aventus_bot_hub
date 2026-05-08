"""Data collection for the AI chat audit.

For a given period [since_ms, until_ms] this module:
  1. Pulls dialogs from Webitel (`/chat/dialogs` paginated).
  2. For each dialog (parallel) — pulls full transcript + members.
  3. Looks up the chat's loan in CRM by phone (per-company SQL).
  4. Joins the loan to a +14d payment outcome window in CRM.
  5. Strips client name and any phone-shaped digit runs from the transcript.
  6. Returns a list of compact records ready to feed into Claude.

Only CO_ has a per-loan payment query implemented today; the audit still
runs for other companies but the `payment` field is `None`.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .data import Company
from .db import connect_for_company
from .wa_bot_config import get_infobip_gateway_name
from .webitel import ChatDialog, ChatMessage, ChatPeer, WebitelClient, WebitelError


PAGE_SIZE = 200
MAX_PAGES = 20
PAYMENT_LOOKAHEAD_DAYS = 14


@dataclass
class ChatRecord:
    chat_id: str
    started_iso: str
    ended_iso: str
    duration_min: int
    handler: str  # "bot_only" | "agent_handled" | "unknown"
    crm: dict      # loan_id, loan_type, dpd, ptp_status, currency, etc. (no PII)
    payment: Optional[dict]  # {paid_within_Nd, total_paid, classification} or None
    transcript: list[dict]   # [{t: "00:00", from: "bot|client|agent", text: "..."}]
    turn_count: int
    phone_last_digit: str = ""  # last digit of caller phone — used for
    # champion/candidate cohort split in weekly review. Single character,
    # not PII on its own.


# ---------------------------------------------------------------------------
# Webitel pulls
# ---------------------------------------------------------------------------

def _paginate_dialogs(
    client: WebitelClient, since_ms: int, until_ms: int,
    *, gateway_name: Optional[str] = None,
) -> list[dict]:
    """Page through `/chat/dialogs`, optionally narrowed to a single
    gateway by `via.name`. The audit/calibration pipeline uses this to
    keep the AI's eyes ON OUR GATEWAY ONLY — KC-bot chats from other
    WA gateways in the same Webitel domain must not pollute the audit
    input.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = client._get(
            f"/chat/dialogs?size={PAGE_SIZE}&page={page}"
            f"&date.since={since_ms}&date.until={until_ms}"
        )
        items = data.get("data") or []
        new = [
            it for it in items
            if it.get("id") and it["id"] not in seen
        ]
        if not new:
            break
        for it in new:
            seen.add(it["id"])
        if gateway_name:
            new = [
                it for it in new
                if str((it.get("via") or {}).get("name") or "") == gateway_name
            ]
        out.extend(new)
        if len(items) < PAGE_SIZE or data.get("next") is False:
            break
    return out


def _classify_handler(members: list[ChatPeer]) -> str:
    """Webitel marks Anthropic-side users (agents) as `type=user`. Bot-only
    chats only have non-user peers."""
    if not members:
        return "unknown"
    for m in members:
        if (m.type or "").lower() == "user":
            return "agent_handled"
    return "bot_only"


def _format_transcript(
    msgs: list[ChatMessage],
    peers: dict[str, ChatPeer],
    dialog_id: str,
    started_ms: int,
) -> list[dict]:
    out: list[dict] = []
    for m in msgs:
        if not m.text:
            continue
        peer = peers.get(m.sender_id)
        # Heuristic same as dashboard: dialog.id == bot/agent peer id.
        if peer and (peer.type or "").lower() == "user":
            who = "agent"
        elif str(m.sender_id) == str(dialog_id):
            who = "bot"
        else:
            who = "client"
        delta = max(0, (m.date_ms - started_ms) // 1000)
        ts = f"{delta // 60:02d}:{delta % 60:02d}"
        out.append({"t": ts, "from": who, "text": m.text})
    return out


# ---------------------------------------------------------------------------
# CRM joins
# ---------------------------------------------------------------------------

def _co_lookup_loan_by_phone(company: Company, phone_digits: str) -> Optional[dict]:
    """Latest loan by phone (Credito365 / TuParcero share schema)."""
    db = "prod_credito365_api" if company.key == "CO_" else "prod_tuparcero_api"
    try:
        conn = connect_for_company(company)
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT l.id, l.userId, l.status, l.daysLate, l.term_days, "
                f"       l.is_renewal, l.amount "
                f"FROM `{db}`.user u "
                f"JOIN `{db}`.loan l ON l.userId = u.id "
                f"WHERE u.main_phone_number = %s "
                f"ORDER BY l.id DESC LIMIT 1",
                (phone_digits,),
            )
            row = cur.fetchone()
            if not row:
                return None
            loan_id, user_id, status, dpd, term, is_renewal, amount = row
            return {
                "loan_id": int(loan_id),
                "user_id": int(user_id) if user_id is not None else None,
                "loan_status": int(status) if status is not None else None,
                "dpd": int(dpd) if dpd is not None else None,
                "term_days": int(term) if term is not None else None,
                "loan_type": "REP" if (is_renewal or 0) else "NEW",
                "amount": float(amount or 0),
            }
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _co_payments_for_loans(
    company: Company,
    loan_ids: list[int],
    since_dt: datetime,
    until_dt: datetime,
) -> dict[int, dict]:
    """For each loan_id, return payment outcome in the [since_dt, until_dt]
    window: {paid: bool, total: float, classification: 'close'|'prolong'|'partial'|'none'}.
    Mirrors the classification logic in `crm_payments._co_credito365_payments`.
    """
    if not loan_ids:
        return {}
    db = "prod_credito365_api" if company.key == "CO_" else "prod_tuparcero_api"
    out: dict[int, dict] = {lid: {
        "paid": False, "total": 0.0, "classification": "none",
    } for lid in loan_ids}
    try:
        conn = connect_for_company(company)
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            ph = ",".join(["%s"] * len(loan_ids))
            cur.execute(
                f"SELECT id, loan_id, amount, finished_at, extension_term "
                f"FROM `{db}`.payment_transaction "
                f"WHERE loan_id IN ({ph}) "
                f"  AND finished_at >= %s AND finished_at <= %s "
                f"  AND direction='incoming' AND status=4",
                tuple(loan_ids) + (since_dt, until_dt),
            )
            payments = cur.fetchall()
            cur.execute(
                f"SELECT id, status FROM `{db}`.loan WHERE id IN ({ph})",
                tuple(loan_ids),
            )
            statuses = {int(lid): int(st) for lid, st in cur.fetchall()}
            cur.execute(
                f"SELECT loan_id, MAX(id) FROM `{db}`.payment_transaction "
                f"WHERE loan_id IN ({ph}) AND status=4 AND direction='incoming' "
                f"GROUP BY loan_id",
                tuple(loan_ids),
            )
            last_pmt = {int(lid): int(mx) for lid, mx in cur.fetchall()}
    except Exception:
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass

    by_loan: dict[int, list[tuple]] = {}
    for pid, lid, amount, finished, ext in payments:
        if not finished or lid is None:
            continue
        by_loan.setdefault(int(lid), []).append((int(pid), float(amount or 0), int(ext or 0)))

    for lid, pmts in by_loan.items():
        total = sum(a for _p, a, _e in pmts)
        rec = out.setdefault(lid, {"paid": False, "total": 0.0, "classification": "none"})
        rec["paid"] = bool(pmts)
        rec["total"] = total
        # Classification rules (mirror crm_payments).
        any_prolong = any(e > 0 for _p, _a, e in pmts)
        loan_status = statuses.get(lid)
        if any_prolong:
            rec["classification"] = "prolong"
        elif loan_status == 3 and last_pmt.get(lid) in {pid for pid, _a, _e in pmts}:
            rec["classification"] = "close"
        else:
            rec["classification"] = "partial"
    return out


def _crm_lookup_supported(company: Company) -> bool:
    return company.key in ("CO_", "CO2_")


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


def redact(text: str, names: list[str]) -> str:
    if not text:
        return text
    out = text
    for n in names:
        n = (n or "").strip()
        if len(n) < 3:
            continue
        out = re.sub(re.escape(n), "<CLIENT>", out, flags=re.IGNORECASE)
    out = _PHONE_RE.sub("<PHONE>", out)
    return out


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def collect_period(
    company: Company,
    since_ms: int,
    until_ms: int,
    limit: int = 100,
) -> tuple[list[ChatRecord], dict]:
    """Return (records, meta). Meta contains counts and a no-PII summary."""
    client = WebitelClient(company.webitel_host, company.webitel_access_token)
    # Audit must see ONLY chats handled by our WhatsApp gateway. KC-bot
    # chats (KC site, KC Meta-direct) live in the same Webitel domain
    # but aren't ours to optimise. Webitel stamps the gateway label on
    # every dialog as `via.name` — we look it up live by hitting
    # `/api/chat/bots` and picking the `infobip_whatsapp` provider.
    gateway_name = get_infobip_gateway_name(company.key)
    raw_dialogs = _paginate_dialogs(
        client, since_ms, until_ms, gateway_name=gateway_name,
    )
    if not raw_dialogs:
        return [], {"total_dialogs": 0, "skipped": 0, "phone_lookups": 0}

    # Sample down to `limit` — we cap the audit to keep token cost predictable.
    if len(raw_dialogs) > limit:
        raw_dialogs = raw_dialogs[:limit]

    def _fetch_dialog(d_raw: dict) -> Optional[ChatRecord]:
        d_id = d_raw.get("id") or ""
        if not d_id:
            return None
        try:
            msgs, peers = client.get_dialog_messages(d_id, limit=300)
        except WebitelError:
            return None
        try:
            members = client.list_dialog_members(d_id)
        except WebitelError:
            members = []

        try:
            started_ms = int(d_raw.get("started") or 0)
            last_ms = int(d_raw.get("date") or 0)
        except (TypeError, ValueError):
            started_ms = last_ms = 0
        started_iso = (
            datetime.fromtimestamp(started_ms / 1000, tz=timezone.utc).isoformat()
            if started_ms else ""
        )
        ended_iso = (
            datetime.fromtimestamp(last_ms / 1000, tz=timezone.utc).isoformat()
            if last_ms else ""
        )
        duration_min = max(0, (last_ms - started_ms) // 60000) if started_ms and last_ms else 0
        handler = _classify_handler(members)
        client_name = ""
        for p in members:
            if (p.type or "").lower() != "user":
                client_name = p.name or ""
                break
        client_name = client_name or str((d_raw.get("from") or {}).get("name") or "")
        # Phone for CRM lookup.
        peer_id = str((d_raw.get("from") or {}).get("id") or "")
        phone_digits = "".join(ch for ch in peer_id if ch.isdigit())

        crm: dict = {"loan_id": None, "loan_type": None, "dpd": None}
        if _crm_lookup_supported(company) and phone_digits:
            loan = _co_lookup_loan_by_phone(company, phone_digits)
            if loan:
                crm.update(loan)

        transcript = _format_transcript(msgs, peers, d_id, started_ms)
        for t in transcript:
            t["text"] = redact(t["text"], [client_name])
        return ChatRecord(
            chat_id=d_id,
            started_iso=started_iso,
            ended_iso=ended_iso,
            duration_min=duration_min,
            handler=handler,
            crm=crm,
            payment=None,
            transcript=transcript,
            turn_count=len(transcript),
            phone_last_digit=phone_digits[-1] if phone_digits else "",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch_dialog, raw_dialogs))
    records = [r for r in results if r is not None]

    # Payment join (CO/CO2 only, where SQL is implemented).
    if _crm_lookup_supported(company):
        loan_ids = sorted({
            r.crm.get("loan_id") for r in records
            if r.crm.get("loan_id") is not None
        })
        if loan_ids:
            since_dt = datetime.fromtimestamp(since_ms / 1000)
            until_dt = (
                datetime.fromtimestamp(until_ms / 1000)
                + timedelta(days=PAYMENT_LOOKAHEAD_DAYS)
            )
            payments = _co_payments_for_loans(
                company, loan_ids, since_dt, until_dt,
            )
            for r in records:
                lid = r.crm.get("loan_id")
                if lid in payments:
                    r.payment = payments[lid]

    meta = {
        "total_dialogs": len(raw_dialogs),
        "kept": len(records),
        "with_loan": sum(1 for r in records if r.crm.get("loan_id")),
        "with_payment": sum(1 for r in records if r.payment and r.payment.get("paid")),
        "bot_only": sum(1 for r in records if r.handler == "bot_only"),
        "agent_handled": sum(1 for r in records if r.handler == "agent_handled"),
    }
    return records, meta


def to_compact_dict(r: ChatRecord) -> dict:
    """Strip empty fields, keep payload tight for the model."""
    crm = {k: v for k, v in (r.crm or {}).items() if v not in (None, "")}
    out = {
        "chat_id": r.chat_id,
        "started": r.started_iso,
        "duration_min": r.duration_min,
        "handler": r.handler,
        "turn_count": r.turn_count,
        "crm": crm,
        "transcript": r.transcript,
    }
    if r.payment:
        out["payment"] = r.payment
    return out
