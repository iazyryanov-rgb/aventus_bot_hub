"""Background scheduler for alert templates that auto-fire on a schedule.

Supported templates (auto-fire):
  * `queue_checklist`   — alerts on missing G*/Main/APTP/BPTP Collection queues.
  * `agents_on_break`   — alerts when pause-count > online-count in any
                          Collection × {Main, APTP, BPTP} queue.

Both share the same trigger machinery:
  * `schedule` (periodicity preset) → minimum interval between fires.
  * `working_hours_only` → require Mon–Fri 09:00–18:00 in company timezone.
  * `trigger_mode` ("event" or "time"):
        - "event" — fire whenever the condition is true and the throttle
          interval has elapsed since last fire.
        - "time"  — additionally gate by `start_time` (HH:MM, company tz):
          don't fire before today's start_time.
  * If the template's builder returns None (condition not satisfied), we
    update `last_run_at_ms` anyway to keep the throttle ticking but skip
    the Telegram send.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .alert_format import render_alert_html
from .alerts import (
    TelegramError,
    load_alerts_config,
    save_alerts_config,
    ensure_company_topic,
    send_telegram_message,
)
from .data import Company, load_companies
from .webitel import Queue, WebitelClient, WebitelError

SCHEDULE_INTERVALS: dict[str, timedelta] = {
    "Каждые 5 минут": timedelta(minutes=5),
    "Каждые 15 минут": timedelta(minutes=15),
    "Каждые 30 минут": timedelta(minutes=30),
    "Каждый час": timedelta(hours=1),
    "Каждые 3 часа": timedelta(hours=3),
    "Раз в сутки": timedelta(hours=24),
}

TICK_SECONDS = 30

AGENT_QUEUE_TYPES = (0, 1, 4, 5, 10)
COLLECTION_GROUPS = ("G1", "G2", "G3")
COLLECTION_SUBS = ("Main", "APTP", "BPTP")

def _has_token(name: str, token: str) -> bool:
    pattern = r"(?:^|[^A-Za-z0-9])" + re.escape(token) + r"(?:$|[^A-Za-z0-9])"
    return re.search(pattern, name, re.IGNORECASE) is not None


def _is_working_hours(tz_name: str) -> bool:
    try:
        now = datetime.now(ZoneInfo(tz_name or "UTC"))
    except Exception:
        return False
    if now.weekday() >= 5:
        return False
    return 9 <= now.hour < 18


def _before_daily_start(tz_name: str, start_time: str) -> bool:
    """True if 'now' in company tz hasn't reached today's HH:MM yet."""
    if not start_time:
        return False
    try:
        h, m = start_time.split(":")
        h_i, m_i = int(h), int(m)
    except (ValueError, TypeError):
        return False
    try:
        now = datetime.now(ZoneInfo(tz_name or "UTC"))
    except Exception:
        return False
    today_start = now.replace(hour=h_i, minute=m_i, second=0, microsecond=0)
    return now < today_start


UNANSWERED_THRESHOLD_MIN = 15
UNANSWERED_LOOKBACK_HOURS = 24


def _build_agents_chats_unanswered_text(company: Company) -> Optional[str]:
    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
    except Exception:
        return None
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - UNANSWERED_THRESHOLD_MIN * 60 * 1000
    since_ms = now_ms - UNANSWERED_LOOKBACK_HOURS * 3600 * 1000

    dialogs: list[dict] = []
    try:
        for page in range(1, 10):
            data = client._get(
                f"/chat/dialogs?size=500&page={page}"
                f"&date.since={since_ms}&date.until={now_ms}"
            )
            items = data.get("data") or []
            dialogs.extend(items)
            if not data.get("next") or not items:
                break
    except WebitelError:
        return None

    pending: list[tuple[dict, int]] = []
    for d in dialogs:
        msg = d.get("message") or {}
        sender = (msg.get("sender") or {}).get("id")
        if not sender:
            continue
        if str(sender) == str(d.get("id")):
            continue  # last message from bot/agent — answered
        try:
            last_ms = int(msg.get("date") or 0)
        except (TypeError, ValueError):
            last_ms = 0
        if not last_ms or last_ms > cutoff_ms:
            continue  # not aged 15 min yet
        pending.append((d, last_ms))

    if not pending:
        return None

    def _members(d_id: str) -> list:
        try:
            return client.list_dialog_members(d_id)
        except WebitelError:
            return []

    by_agent: dict[str, list[int]] = {}
    no_agent_ages: list[int] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        members_list = list(pool.map(lambda p: _members(p[0]["id"]), pending))
    for (d, last_ms), members in zip(pending, members_list):
        agent_name: Optional[str] = None
        for m in members:
            if m.type == "user" and m.name:
                agent_name = m.name
                break
        age_min = max(1, int((now_ms - last_ms) / 60000))
        if agent_name:
            by_agent.setdefault(agent_name, []).append(age_min)
        else:
            no_agent_ages.append(age_min)

    if not by_agent and not no_agent_ages:
        return None

    bullets: list[str] = []
    total_chats = 0
    for agent, ages in sorted(
        by_agent.items(), key=lambda kv: (-len(kv[1]), -max(kv[1]))
    ):
        total_chats += len(ages)
        bullets.append(f"{agent} — {len(ages)} chat(s), max {max(ages)}m")
    if no_agent_ages:
        total_chats += len(no_agent_ages)
        bullets.append(
            f"(bot/no-agent) — {len(no_agent_ages)} chat(s), max {max(no_agent_ages)}m"
        )

    return render_alert_html(
        severity="warning",
        title=f"Chats unanswered > {UNANSWERED_THRESHOLD_MIN}min",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Agents",
        metrics=[
            ("Stuck chats", str(total_chats)),
            ("Threshold", f"{UNANSWERED_THRESHOLD_MIN} min"),
        ],
        bullets=bullets,
    )


def _build_agents_on_break_text(company: Company) -> Optional[str]:
    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
        queues = client.list_queues(types=list(AGENT_QUEUE_TYPES))
    except WebitelError:
        return None

    candidates: list[Queue] = []
    for q in queues:
        if not q.enabled:
            continue
        name = q.name or ""
        if not name.lstrip().lower().startswith("collection"):
            continue
        if not any(_has_token(name, s) for s in COLLECTION_SUBS):
            continue
        candidates.append(q)
    if not candidates:
        return None

    def _fetch(q: Queue) -> tuple[Queue, Optional[int], Optional[int]]:
        try:
            statuses = client.list_queue_agent_statuses(q.id)
        except WebitelError:
            return q, None, None
        online = sum(1 for s in statuses if s == "online")
        pause = sum(1 for s in statuses if s == "pause")
        return q, online, pause

    rows: list[tuple[Queue, int, int]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for q, online, pause in pool.map(_fetch, candidates):
            if online is None or pause is None:
                continue
            rows.append((q, online, pause))

    bad = [(q, o, p) for q, o, p in rows if p > o]
    if not bad:
        return None

    bullets = [f"{q.name} — online={o}, pause={p}" for q, o, p in bad]
    return render_alert_html(
        severity="warning",
        title="Agents on break > online · Collection",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Agents",
        metrics=[("Affected queues", str(len(bad)))],
        bullets=bullets,
    )


def _build_queue_checklist_text(company: Company) -> Optional[str]:
    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
        queues: list[Queue] = client.list_queues(types=list(AGENT_QUEUE_TYPES))
    except WebitelError:
        return None
    try:
        chat_queues: list[Queue] = client.list_queues(types=[6])
    except WebitelError:
        chat_queues = []

    def _has_voice(g: str, s: str) -> bool:
        for q in queues:
            if not q.enabled:
                continue
            name = q.name or ""
            if not name.lstrip().lower().startswith("collection"):
                continue
            if _has_token(name, g) and _has_token(name, s):
                return True
        return False

    def _has_chat(g: str) -> bool:
        for q in chat_queues:
            if not q.enabled:
                continue
            name = q.name or ""
            if "collection" not in name.lower():
                continue
            if _has_token(name, g):
                return True
        return False

    missing: list[tuple[str, str]] = []
    ok = 0
    for g in COLLECTION_GROUPS:
        for s in COLLECTION_SUBS:
            if _has_voice(g, s):
                ok += 1
            else:
                missing.append((g, s))
        if _has_chat(g):
            ok += 1
        else:
            missing.append((g, "Chat"))

    if not missing:
        return None
    total = len(COLLECTION_GROUPS) * (len(COLLECTION_SUBS) + 1)
    bullets = [f"{g} — {s}" for g, s in missing]
    return render_alert_html(
        severity="warning",
        title="Queues check · Collection",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Agents",
        metrics=[
            ("Coverage", f"{ok} / {total}"),
            ("Missing", str(len(missing))),
            ("Configured", str(ok)),
        ],
        bullets=bullets,
        body="The following queues are not enabled or not present:",
    )


def _latest_dash_snapshot(company: Company) -> Optional[dict]:
    """Pick the most recently-stored snapshot from the dashboard cache for
    this company. Snapshot keys are `<period>_<sector>` — we just take the
    one with the freshest `ts_ms`."""
    try:
        from .dashboard_cache import load_cache
    except Exception:
        return None
    cache = load_cache(company.key) or {}
    snaps = cache.get("snapshots") if isinstance(cache, dict) else None
    if not isinstance(snaps, dict) or not snaps:
        return None
    best = None
    best_ts = -1
    for snap in snaps.values():
        if not isinstance(snap, dict):
            continue
        ts = int(snap.get("ts_ms") or 0)
        if ts > best_ts:
            best_ts = ts
            best = snap
    return best


def _build_dash_outbound_drop_text(company: Company) -> Optional[str]:
    snap = _latest_dash_snapshot(company)
    if not snap:
        return None
    today = (snap.get("co_today") or {}).get("total")
    co_outbound_per_day = list(snap.get("c_outbound") or [])
    if today is None or len(co_outbound_per_day) < 2:
        return None
    today_n = int(today)
    history = co_outbound_per_day[:-1] or [0]
    avg = sum(history) / len(history) if history else 0
    if avg <= 0:
        return None
    if today_n >= avg * 0.5:
        return None
    drop_pct = round((1 - today_n / avg) * 100)
    return render_alert_html(
        severity="warning",
        title="Outbound · sharp drop",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Voice",
        metrics=[
            ("Today", str(today_n)),
            (f"Avg over {len(history)}d", f"{avg:.0f}"),
            ("Drop", f"{drop_pct}%"),
        ],
    )


def _build_dash_amd_machine_high_text(company: Company) -> Optional[str]:
    snap = _latest_dash_snapshot(company)
    if not snap:
        return None
    co = snap.get("co_today") or {}
    total = int(co.get("total") or 0)
    machine = int(co.get("amd_machine") or 0)
    if total < 50:
        return None
    pct = machine * 100 / total
    if pct <= 60:
        return None
    return render_alert_html(
        severity="warning",
        title="AMD-MACHINE > 60%",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Voice",
        metrics=[
            ("MACHINE", f"{machine} / {total}"),
            ("Share", f"{pct:.0f}%"),
        ],
    )


def _build_dash_handled_low_text(company: Company) -> Optional[str]:
    snap = _latest_dash_snapshot(company)
    if not snap:
        return None
    co = snap.get("co_today") or {}
    total = int(co.get("total") or 0)
    handled = int(co.get("handled") or 0)
    if total < 50:
        return None
    pct = handled * 100 / total
    if pct >= 40:
        return None
    return render_alert_html(
        severity="warning",
        title="Handled-by-agent < 40%",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Voice",
        metrics=[
            ("Handled", f"{handled} / {total}"),
            ("Share", f"{pct:.0f}%"),
        ],
    )


def _build_dash_crm_results_low_text(company: Company) -> Optional[str]:
    snap = _latest_dash_snapshot(company)
    if not snap:
        return None
    co = snap.get("co_today") or {}
    handled = int(co.get("handled") or 0)
    crm = co.get("crm_results_today")
    if not isinstance(crm, int) or handled < 20:
        return None
    pct = crm * 100 / handled
    if pct >= 50:
        return None
    return render_alert_html(
        severity="warning",
        title="CRM-results < 50% of handled",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="CRM",
        metrics=[
            ("CRM-records", f"{crm} / {handled}"),
            ("Share", f"{pct:.0f}%"),
        ],
    )


# ---------------------------------------------------------------------------
# Phase H — health-checks for the WhatsApp pipeline
# ---------------------------------------------------------------------------

import json
from collections import Counter
from pathlib import Path

from .paths import data_dir


def _health_state_path(company_key: str) -> Path:
    """Per-company small state file for sticky alerts (H1/H4): tracks
    consecutive failures, last-fired timestamp, etc. Keeping it per-builder
    inside the same JSON so we don't multiply small files."""
    return data_dir() / "alert_health_state" / f"{company_key}.json"


def _load_health_state(company_key: str) -> dict:
    path = _health_state_path(company_key)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_health_state(company_key: str, state: dict) -> None:
    path = _health_state_path(company_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _autopause_cycle(company_key: str, reason: str) -> None:
    """Best-effort cycle auto-pause for health-check trips. Mirrors the
    `_pause_cycle` helper in calibration_cycle but tolerates that module
    not being importable in non-bot configurations."""
    try:
        from . import calibration_cycle as cc
        cfg = cc.load_cycle_config(company_key)
        cfg["enabled"] = False
        cfg["paused_at_ms"] = int(time.time() * 1000)
        cfg["paused_reason"] = reason
        cc.save_cycle_config(company_key, cfg)
    except Exception:
        pass


# H4 — Webitel API down --------------------------------------------------------

WEBITEL_API_DOWN_MIN_FAILS = 2


def _build_webitel_api_down_text(company: Company) -> Optional[str]:
    """Ping a cheap Webitel endpoint. Alert only after MIN_FAILS consecutive
    failures so transient blips don't spam — and once recovered, send a
    one-shot "back online" message."""
    state = _load_health_state(company.key)
    h4 = state.setdefault("h4_webitel_api_down", {})
    fails = int(h4.get("consecutive_fails") or 0)
    was_alerted = bool(h4.get("alerted"))

    last_error: Optional[str] = None
    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
        client._get("/chat/schemas?size=1")
        ok = True
    except WebitelError as e:
        ok = False
        last_error = str(e)
    except Exception as e:  # network-level failures
        ok = False
        last_error = f"{type(e).__name__}: {e}"

    text: Optional[str] = None
    if ok:
        if was_alerted:
            text = render_alert_html(
                severity="ok",
                title="Webitel API recovered",
                company_code=company.code,
                company_name=company.name,
                webitel_host=company.webitel_host,
                category="Webitel",
                metrics=[("Status", "back online")],
            )
        h4["consecutive_fails"] = 0
        h4["alerted"] = False
    else:
        fails += 1
        h4["consecutive_fails"] = fails
        h4["last_error"] = last_error or ""
        if fails >= WEBITEL_API_DOWN_MIN_FAILS and not was_alerted:
            text = render_alert_html(
                severity="critical",
                title="Webitel API unreachable",
                company_code=company.code,
                company_name=company.name,
                webitel_host=company.webitel_host,
                category="Webitel",
                metrics=[
                    ("Consecutive fails", str(fails)),
                ],
                context_kv=[("Last error", (last_error or "")[:200])],
                body=(
                    "Health-check cannot reach the Webitel API. "
                    "Calibration cycle and audits will not run until restored."
                ),
            )
            h4["alerted"] = True

    state["h4_webitel_api_down"] = h4
    _save_health_state(company.key, state)
    return text


# H1 — WA inbound chat volume drop ---------------------------------------------

def _pull_wa_dialog_count(client: WebitelClient, since_ms: int, until_ms: int) -> int:
    """Count WhatsApp dialogs in the period. Robust: tolerates pagination
    short-circuit, returns 0 on errors."""
    try:
        n = 0
        for page in range(1, 10):
            data = client._get(
                f"/chat/dialogs?size=500&page={page}"
                f"&date.since={since_ms}&date.until={until_ms}"
            )
            items = data.get("data") or []
            n += len(items)
            if not data.get("next") or not items or len(items) < 500:
                break
        return n
    except WebitelError:
        return -1  # signal failure (distinct from "actually 0")


def _build_wa_chat_volume_drop_text(company: Company) -> Optional[str]:
    """Compare last-1h dialog count vs rolling baseline (avg of same hour
    of day across last 7 days). Auto-pauses calibration cycle on trip.
    Skips on quiet hours (23:00–08:00 local) and on Sundays — too noisy."""
    try:
        tz = ZoneInfo(company.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    if now_local.weekday() == 6:  # Sunday — too sparse to trust baseline
        return None
    if now_local.hour < 8 or now_local.hour >= 23:
        return None

    now_ms = int(time.time() * 1000)
    one_hour_ms = 3600 * 1000
    since_ms = now_ms - one_hour_ms

    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
    except Exception:
        return None

    cur = _pull_wa_dialog_count(client, since_ms, now_ms)
    if cur < 0:
        return None  # API down; H4 covers that

    state = _load_health_state(company.key)
    h1 = state.setdefault("h1_chat_volume", {})
    bucket_key = f"hour_{now_local.hour}"
    history = list(h1.setdefault(bucket_key, []))[-7:]  # keep 7 most recent

    avg = (sum(history) / len(history)) if history else 0
    text: Optional[str] = None
    drop_pct = 0
    triggered = False
    if len(history) >= 3 and avg > 5:
        if cur <= avg * 0.3:
            drop_pct = round((1 - cur / avg) * 100) if avg else 100
            triggered = True

    if triggered:
        last_alert_ms = int(h1.get("last_alert_ms") or 0)
        if now_ms - last_alert_ms > 2 * 3600 * 1000:  # at most every 2h
            text = render_alert_html(
                severity="critical",
                title="WA inbound traffic dropped sharply",
                company_code=company.code,
                company_name=company.name,
                webitel_host=company.webitel_host,
                category="Bot",
                metrics=[
                    ("Last hour dialogs", str(cur)),
                    (f"Avg same-hour ({len(history)}d)", f"{avg:.1f}"),
                    ("Drop", f"{drop_pct}%"),
                ],
                body=(
                    "Inbound WA volume in the last hour is far below the rolling "
                    "baseline. Likely causes: gateway misrouted, router schema "
                    "broken, or Infobip channel offline. Calibration cycle was "
                    "auto-paused as a precaution."
                ),
                action_hint="After diagnosing, resume the cycle:",
                action_command=f"python -m app.calibration_cycle unpause {company.key}",
            )
            h1["last_alert_ms"] = now_ms
            _autopause_cycle(
                company.key,
                f"wa_chat_volume_drop: last_hour={cur}, avg={avg:.1f}, drop={drop_pct}%",
            )

    # Update rolling baseline at the END so the very-low current value
    # doesn't poison its own future baselines.
    if not triggered:
        history.append(int(cur))
        history = history[-7:]
        h1[bucket_key] = history

    state["h1_chat_volume"] = h1
    _save_health_state(company.key, state)
    return text


# H2 — WA bot silent -----------------------------------------------------------

WA_BOT_SILENT_TAIL_MIN = 5
WA_BOT_SILENT_THRESHOLD_PCT = 50


def _build_wa_bot_silent_text(company: Company) -> Optional[str]:
    """Of the WA dialogs from the last hour, how many had:
      - last message from CLIENT (not bot/agent)
      - aged > WA_BOT_SILENT_TAIL_MIN
      - no Webitel-side `user` member (i.e. no human took it over)
    If >threshold% — alert. Catches "schema loads but bot silent" symptom."""
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - 3600 * 1000
    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
    except Exception:
        return None
    try:
        data = client._get(
            f"/chat/dialogs?size=500&page=1"
            f"&date.since={since_ms}&date.until={now_ms}"
        )
        dialogs = list(data.get("data") or [])
    except WebitelError:
        return None
    if len(dialogs) < 10:
        return None  # too few to draw any conclusion

    cutoff_ms = now_ms - WA_BOT_SILENT_TAIL_MIN * 60 * 1000
    candidates: list[dict] = []
    for d in dialogs:
        msg = d.get("message") or {}
        sender_id = (msg.get("sender") or {}).get("id")
        if not sender_id or str(sender_id) == str(d.get("id")):
            continue  # last msg from bot/agent — bot did respond
        try:
            last_ms = int(msg.get("date") or 0)
        except (TypeError, ValueError):
            last_ms = 0
        if not last_ms or last_ms > cutoff_ms:
            continue  # too fresh
        candidates.append(d)

    silent_n = 0
    if candidates:
        with ThreadPoolExecutor(max_workers=8) as pool:
            members_list = list(
                pool.map(
                    lambda d: client.list_dialog_members(d["id"]),
                    candidates,
                )
            )
        for d, members in zip(candidates, members_list):
            has_user = any(
                (m.type or "").lower() == "user" for m in (members or [])
            )
            if not has_user:
                silent_n += 1

    silent_pct = (silent_n * 100 / len(dialogs)) if dialogs else 0
    if silent_pct < WA_BOT_SILENT_THRESHOLD_PCT:
        return None

    state = _load_health_state(company.key)
    h2 = state.setdefault("h2_bot_silent", {})
    last_alert_ms = int(h2.get("last_alert_ms") or 0)
    if now_ms - last_alert_ms < 1800 * 1000:  # at most every 30min
        return None
    h2["last_alert_ms"] = now_ms
    state["h2_bot_silent"] = h2
    _save_health_state(company.key, state)

    return render_alert_html(
        severity="critical",
        title="WA bot is silent on most chats",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Bot",
        metrics=[
            ("Last-hour dialogs", str(len(dialogs))),
            (
                f"Silent (client wrote, no agent, >{WA_BOT_SILENT_TAIL_MIN}m)",
                f"{silent_n} ({silent_pct:.0f}%)",
            ),
            ("Threshold", f"{WA_BOT_SILENT_THRESHOLD_PCT}%"),
        ],
        body=(
            "Most chats in the last hour are stuck — the bot didn't reply "
            "and no human took over. Likely the schema loads but a runtime "
            "node fails on the first hop. Open Webitel logs and check the "
            "router / champion schema."
        ),
    )


# H3 — Cohort imbalance --------------------------------------------------------

def _build_cohort_imbalance_text(company: Company) -> Optional[str]:
    """Compare actual candidate-cohort share with the configured candidate
    digits. Default: digits {0,1,2} → expected 30%; tolerance ±15pp."""
    try:
        from .audit_storage import get_ab_split
        from .wa_bot_config import load_config
        cfg = load_config(company.key) or {}
        ab = get_ab_split(cfg)
        cand_digits = {int(d) for d in (ab.get("candidate_digits") or []) if str(d).isdigit()}
    except Exception:
        cand_digits = {0, 1, 2}
    if not cand_digits:
        cand_digits = {0, 1, 2}
    expected_pct = len(cand_digits) * 10.0  # 1 digit ≈ 10%
    tolerance_pp = 15.0

    now_ms = int(time.time() * 1000)
    since_ms = now_ms - 2 * 3600 * 1000  # last 2h
    try:
        client = WebitelClient(company.webitel_host, company.webitel_access_token)
        data = client._get(
            f"/chat/dialogs?size=500&page=1"
            f"&date.since={since_ms}&date.until={now_ms}"
        )
    except WebitelError:
        return None
    dialogs = list(data.get("data") or [])
    if len(dialogs) < 30:
        return None

    digits: Counter = Counter()
    cand_n = 0
    for d in dialogs:
        peer_id = str((d.get("from") or {}).get("id") or "")
        last = "".join(ch for ch in peer_id if ch.isdigit())[-1:]
        if not last.isdigit():
            continue
        digits[int(last)] += 1
        if int(last) in cand_digits:
            cand_n += 1

    classified = sum(digits.values()) or 1
    actual_pct = cand_n * 100 / classified
    deviation = actual_pct - expected_pct
    if abs(deviation) < tolerance_pp:
        return None

    state = _load_health_state(company.key)
    h3 = state.setdefault("h3_cohort_imbalance", {})
    last_alert_ms = int(h3.get("last_alert_ms") or 0)
    if now_ms - last_alert_ms < 3600 * 1000:  # at most every 1h
        return None
    h3["last_alert_ms"] = now_ms
    state["h3_cohort_imbalance"] = h3
    _save_health_state(company.key, state)

    direction = "above" if deviation > 0 else "below"
    digit_dist = ", ".join(
        f"{d}:{digits.get(d, 0)}" for d in range(10) if digits.get(d, 0)
    )
    return render_alert_html(
        severity="warning",
        title="A/B router cohort imbalance",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="Calibration",
        metrics=[
            ("Last 2h dialogs", str(len(dialogs))),
            ("Candidate share (actual)", f"{actual_pct:.1f}%"),
            ("Candidate share (expected)", f"{expected_pct:.0f}%"),
            ("Deviation", f"{deviation:+.1f}pp ({direction} expected)"),
        ],
        bullets=[f"digit distribution: {digit_dist}"],
        body=(
            "The router schema is supposed to send a fixed share of traffic "
            "to the candidate cohort. The observed share is far off — the "
            "router js/switch may be broken, or the gate is no longer "
            "pointing at the router schema."
        ),
        context_kv=[("Candidate digits", str(sorted(cand_digits)))],
    )


# CRM call-list dispatch failures (Lendi engine: AR/PE) ------------------------

CRM_CALL_LIST_MAX_BULLETS = 5


def _build_crm_call_list_failed_text(company: Company) -> Optional[str]:
    """Poll CRM `dialer_process` for new rows in state='error' and surface
    them once per row. High-water mark stored as `last_seen_updated_ms` so
    historical errors at first run don't fire a flood."""
    try:
        from . import db as _db
    except Exception:
        return None

    try:
        conn = _db.connect_for_company(company)
    except Exception:
        return None

    try:
        try:
            cur = conn.cursor()
        except Exception:
            return None
        try:
            cur.execute(
                "SELECT dp.id, dp.campaign_id, COALESCE(dc.name, ''), "
                "       dp.last_error, "
                "       (EXTRACT(EPOCH FROM dp.updated_at) * 1000)::bigint "
                "FROM public.dialer_process dp "
                "LEFT JOIN public.dialer_campaign dc ON dc.id = dp.campaign_id "
                "WHERE dp.state = 'error' "
                "  AND dp.updated_at > NOW() - INTERVAL '24 hours' "
                "ORDER BY dp.updated_at DESC "
                "LIMIT 50"
            )
            rows = cur.fetchall() or []
        finally:
            try:
                cur.close()
            except Exception:
                pass
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    state = _load_health_state(company.key)
    cl = state.setdefault("h_crm_call_list_failed", {})
    last_seen = int(cl.get("last_seen_updated_ms") or 0)

    fresh = [r for r in rows if int(r[4] or 0) > last_seen]
    new_max = max((int(r[4] or 0) for r in rows), default=last_seen)

    if last_seen == 0:
        cl["last_seen_updated_ms"] = new_max
        state["h_crm_call_list_failed"] = cl
        _save_health_state(company.key, state)
        return None

    if not fresh:
        return None

    cl["last_seen_updated_ms"] = new_max
    state["h_crm_call_list_failed"] = cl
    _save_health_state(company.key, state)

    bullets: list[str] = []
    for r in fresh[:CRM_CALL_LIST_MAX_BULLETS]:
        proc_id = r[0]
        camp_name = (r[2] or f"campaign #{r[1]}") or "—"
        err = (r[3] or "").strip().splitlines()[0] if r[3] else "(no message)"
        if len(err) > 140:
            err = err[:137] + "…"
        bullets.append(f"<b>{camp_name}</b> · process #{proc_id}: {err}")
    extra = len(fresh) - CRM_CALL_LIST_MAX_BULLETS
    if extra > 0:
        bullets.append(f"…and {extra} more failed process(es)")

    return render_alert_html(
        severity="error",
        title="CRM call list dispatch failed",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="CRM",
        metrics=[("New failed processes", str(len(fresh)))],
        bullets=bullets,
        body=(
            "CRM `dialer_process` rows transitioned to state='error'. "
            "Outbound call lists scheduled by these campaigns were not sent "
            "to Webitel — affected dialer queues will be quiet until the "
            "underlying issue is fixed and the process is restarted."
        ),
        action_hint="Open Dialer campaigns admin and restart the failed process:",
        action_command="/admin#/dialer_campaigns",
    )


# ---------------------------------------------------------------------------

def _build_wa_senders_health_text(company: Company) -> Optional[str]:
    """Snapshot Infobip's `/whatsapp/2/senders` for this company, diff
    against the previous snapshot in `data/wa_senders_state/<co>.json`,
    and emit an alert if the delta contains anything actionable.

    Suppression rules:
      * First run (no snapshot file yet) — silently save baseline,
        return None. The next run actually compares.
      * Empty senders list (Infobip down or no Infobip bot in tenant)
        — return None. We don't want a "lost all senders" alert from
        a transient API hiccup; let the cache return-last-good logic
        in `infobip.cached_senders` handle it.
      * Diff produced only INFO-level changes (recoveries, new sender
        appeared healthy) — save snapshot, return None. The senders
        panel surfaces these visually; alerts are reserved for
        problems.
    """
    from . import wa_senders_state as state
    from .wa_bot_config import get_infobip_senders

    cur = get_infobip_senders(company.key)
    if not cur:
        # No senders pulled — likely Infobip transient or the company
        # has no Infobip bot. Don't churn the snapshot or emit alerts.
        return None

    if not state.has_snapshot(company.key):
        state.save_snapshot(company.key, cur)
        return None

    prev = state.load_snapshot(company.key)
    changes = state.diff(prev, cur)
    if not changes:
        # Senders identical — refresh the snapshot timestamp by re-saving
        # (cheap) and skip the alert.
        state.save_snapshot(company.key, cur)
        return None

    # Filter to actionable severities. INFO-only batches don't justify
    # a Telegram ping; the panel shows them.
    actionable = [c for c in changes if c.severity != state.SEV_INFO]
    state.save_snapshot(company.key, cur)
    if not actionable:
        return None

    severity = state.worst_severity(actionable)
    bullets = []

    def _humanize_value(field: str, value: str) -> str:
        if field == "quality":
            return state.humanize_quality(value)
        if field == "status":
            return state.humanize_status(value)
        if field == "limit":
            return state.humanize_limit(value)
        return value or "—"

    field_labels = {
        "quality":      "quality",
        "status":       "status",
        "limit":        "messaging limit",
        "registration": "registration",
        "presence":     "presence",
    }
    # Bullets are HTML-escaped by render_alert_html, so we keep them as
    # plain text and rely on the arrow + ': ' to separate field / before
    # / after. Telegram still bolds the bullet via the • + body shape.
    for ch in actionable[:25]:
        sender_label = state.format_phone(ch.sender)
        name = ch.display_name or sender_label
        label = field_labels.get(ch.field, ch.field)
        before_h = _humanize_value(ch.field, ch.before)
        after_h = _humanize_value(ch.field, ch.after)
        bullets.append(
            f"{name} ({sender_label}) — {label}: "
            f"{before_h} → {after_h}"
        )
    if len(actionable) > 25:
        bullets.append(f"…and {len(actionable) - 25} more change(s)")

    counts_by_field: dict[str, int] = {}
    for ch in actionable:
        counts_by_field[ch.field] = counts_by_field.get(ch.field, 0) + 1
    metrics = [("Total changes", str(len(actionable)))]
    for field, n in sorted(counts_by_field.items()):
        metrics.append((field.capitalize(), str(n)))
    metrics.append(("Senders tracked", str(len(cur))))

    return render_alert_html(
        severity=severity,
        title="WhatsApp senders · health changed",
        company_code=company.code,
        company_name=company.name,
        webitel_host=company.webitel_host,
        category="WhatsApp",
        metrics=metrics,
        bullets=bullets,
        body=(
            "Infobip reported a change in our WhatsApp sender(s) state. "
            "Statuses like BANNED / RESTRICTED / RATE_LIMITED stop "
            "outbound traffic immediately; quality / messaging-limit "
            "drops degrade reach. Compare against the senders tab in "
            "the WhatsApp bot panel for the current state."
        ),
        action_hint="Open Infobip portal · Channels & Numbers · WhatsApp · Senders:",
        action_command="https://portal.infobip.com/channels-and-numbers/channels/whatsapp/senders",
    )


# ---------------------------------------------------------------------------

TEMPLATE_BUILDERS: dict[str, Callable[[Company], Optional[str]]] = {
    "queue_checklist": _build_queue_checklist_text,
    "agents_on_break": _build_agents_on_break_text,
    "agents_chats_unanswered": _build_agents_chats_unanswered_text,
    "dash_outbound_drop": _build_dash_outbound_drop_text,
    "dash_amd_machine_high": _build_dash_amd_machine_high_text,
    "dash_handled_low": _build_dash_handled_low_text,
    "dash_crm_results_low": _build_dash_crm_results_low_text,
    "webitel_api_down": _build_webitel_api_down_text,
    "wa_chat_volume_drop": _build_wa_chat_volume_drop_text,
    "wa_bot_silent": _build_wa_bot_silent_text,
    "wa_senders_health": _build_wa_senders_health_text,
    "cohort_imbalance": _build_cohort_imbalance_text,
    "crm_call_list_failed": _build_crm_call_list_failed_text,
}


class AlertScheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # AI audits run minutes-long; never block the tick. Bound concurrency
        # because each audit hits Webitel + CRM + Anthropic.
        self._audit_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="ai-audit",
        )
        self._audit_inflight: set[str] = set()
        self._audit_inflight_lock = threading.Lock()
        # Bot-side alert consumer (Phase I) lives in its own daemon
        # thread, lazy-started here so non-bot deployments don't pay
        # the cost.
        self._bot_consumer = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="alert-scheduler", daemon=True
        )
        self._thread.start()
        # Spin up the bot-alert-consumer once.
        try:
            from .bot_alert_consumer import get_consumer
            self._bot_consumer = get_consumer()
            self._bot_consumer.start()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        try:
            self._audit_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        if self._bot_consumer is not None:
            try:
                self._bot_consumer.stop()
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(TICK_SECONDS)

    def _tick(self) -> None:
        cfg = load_alerts_config()
        bot_alerts = cfg.get("bot_alerts") or {}
        if not bot_alerts:
            return
        companies = {c.key: c for c in load_companies()}
        tg = cfg.get("telegram") or {}
        token = tg.get("bot_token", "")
        chat_id = tg.get("chat_id", "")
        now_ms = int(time.time() * 1000)
        changed = False

        company_index = {ck: i for i, ck in enumerate(sorted(companies.keys()))}
        for ckey, by_kind in bot_alerts.items():
            company = companies.get(ckey)
            if not company:
                continue
            topic_id = ensure_company_topic(
                cfg, company, index_hint=company_index.get(ckey, 0)
            )
            if topic_id is not None:
                changed = True
            for _kind, alerts in (by_kind or {}).items():
                for alert in alerts or []:
                    if not alert.get("enabled", True):
                        continue
                    template = alert.get("template", "")
                    interval = SCHEDULE_INTERVALS.get(alert.get("schedule", ""))
                    if interval is None:
                        continue
                    if alert.get("working_hours_only") and not _is_working_hours(
                        company.timezone
                    ):
                        continue
                    if alert.get("trigger_mode", "event") == "time":
                        if _before_daily_start(
                            company.timezone, alert.get("start_time", "")
                        ):
                            continue
                    last = int(alert.get("last_run_at_ms") or 0)
                    if last and now_ms - last < interval.total_seconds() * 1000:
                        continue

                    # Fork ai_audit into a worker thread — it can run for
                    # minutes and would block the tick otherwise.
                    if template == "ai_audit":
                        with self._audit_inflight_lock:
                            if ckey in self._audit_inflight:
                                continue
                            self._audit_inflight.add(ckey)
                        alert["last_run_at_ms"] = now_ms
                        changed = True
                        snapshot = dict(alert)
                        self._audit_pool.submit(
                            self._run_ai_audit, company, snapshot,
                        )
                        continue

                    # weekly_review fires once a week (configured weekday,
                    # default Monday) and pulls thousands of chats — same
                    # forking model as ai_audit. The schedule throttle still
                    # applies (Раз в сутки = at-most-daily), so the weekday
                    # filter just gates which day actually fires.
                    if template == "weekly_review":
                        weekday_target = int(alert.get("weekday") or 0)
                        try:
                            now_local = datetime.now(
                                ZoneInfo(company.timezone or "UTC")
                            )
                        except Exception:
                            now_local = datetime.utcnow()
                        if now_local.weekday() != weekday_target:
                            continue
                        wr_key = f"{ckey}/weekly_review"
                        with self._audit_inflight_lock:
                            if wr_key in self._audit_inflight:
                                continue
                            self._audit_inflight.add(wr_key)
                        alert["last_run_at_ms"] = now_ms
                        changed = True
                        snapshot = dict(alert)
                        self._audit_pool.submit(
                            self._run_weekly_review, company, snapshot,
                        )
                        continue

                    builder = TEMPLATE_BUILDERS.get(template)
                    if builder is None:
                        continue
                    text = builder(company)
                    alert["last_run_at_ms"] = now_ms
                    changed = True
                    if text is None:
                        continue
                    try:
                        send_telegram_message(
                            token, chat_id, text,
                            parse_mode="HTML",
                            message_thread_id=topic_id,
                        )
                    except TelegramError:
                        pass

        if changed:
            try:
                save_alerts_config(cfg)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # AI audit worker
    # ------------------------------------------------------------------

    def _run_ai_audit(self, company: Company, alert: dict) -> None:
        try:
            self._do_ai_audit(company, alert)
        except Exception:
            pass
        finally:
            with self._audit_inflight_lock:
                self._audit_inflight.discard(company.key)

    def _do_ai_audit(self, company: Company, alert: dict) -> None:
        # Imports here so the alert scheduler stays usable even if anthropic
        # SDK is missing (e.g. dev environment).
        from .audit_scheduler import send_audit_to_telegram
        from .chat_audit import run_audit

        period_days = int(alert.get("period_days") or 1)
        model_kind = alert.get("model_kind") or "sonnet"
        chat_limit = int(alert.get("chat_limit") or 500)
        try:
            tz = ZoneInfo(company.timezone or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        until = datetime.now(tz)
        since = until - timedelta(days=period_days)
        since_ms = int(since.timestamp() * 1000)
        until_ms = int(until.timestamp() * 1000)
        t0 = time.time()
        try:
            result = run_audit(
                company, since_ms, until_ms,
                model_kind=model_kind, chat_limit=chat_limit, lang="ENG",
            )
        except Exception as exc:
            self._record_ai_audit_status(
                company.key, alert.get("id", ""),
                last_status="failed",
                last_error=f"{type(exc).__name__}: {exc}",
            )
            return
        elapsed = time.time() - t0
        tg_err = send_audit_to_telegram(
            company, result, period_days, model_kind, elapsed,
        )
        # Run the auto-calibration cycle on the candidate schema. Any
        # error here MUST NOT propagate — the audit + Telegram delivery
        # is the operator's promised contract; cycle is best-effort.
        try:
            from .audit_scheduler import send_cycle_summary_to_telegram
            from .calibration_cycle import run_cycle
            audit_id = (result.get("_meta") or {}).get("audit_id") or ""
            cycle_res = run_cycle(
                company.key, result,
                audit_meta={
                    "audit_id": audit_id,
                    "ts_ms": (result.get("_meta") or {}).get("ts_ms") or 0,
                    "model_kind": model_kind,
                },
            )
            try:
                send_cycle_summary_to_telegram(company, cycle_res, audit_id)
            except Exception:
                pass
        except Exception:
            pass
        self._record_ai_audit_status(
            company.key, alert.get("id", ""),
            last_status="ok" if not tg_err else "tg_failed",
            last_error=tg_err or "",
        )

    # ------------------------------------------------------------------
    # Weekly review worker
    # ------------------------------------------------------------------

    def _run_weekly_review(self, company: Company, alert: dict) -> None:
        wr_key = f"{company.key}/weekly_review"
        try:
            self._do_weekly_review(company, alert)
        except Exception:
            pass
        finally:
            with self._audit_inflight_lock:
                self._audit_inflight.discard(wr_key)

    def _do_weekly_review(self, company: Company, alert: dict) -> None:
        from .audit_scheduler import send_weekly_review_to_telegram
        from .weekly_review import compute_weekly_metrics, should_promote

        days = int(alert.get("days") or 7)
        target_goal = str(alert.get("target_goal") or "fully_pay")
        try:
            min_lift = float(alert.get("min_lift_pct") or 2.0) / 100.0
        except (TypeError, ValueError):
            min_lift = 0.02
        min_n = int(alert.get("min_n") or 50)
        chat_limit = int(alert.get("chat_limit") or 5000)
        until_ms = int(time.time() * 1000)
        since_ms = until_ms - days * 86_400_000

        try:
            metrics = compute_weekly_metrics(
                company.key, since_ms, until_ms,
                chat_limit=chat_limit,
            )
        except Exception as exc:
            self._record_ai_audit_status(
                company.key, alert.get("id", ""),
                last_status="failed",
                last_error=f"{type(exc).__name__}: {exc}",
            )
            return
        decision = should_promote(
            metrics,
            target_goal=target_goal,
            min_lift=min_lift,
            min_n=min_n,
        )
        tg_err = send_weekly_review_to_telegram(company, decision, days)
        self._record_ai_audit_status(
            company.key, alert.get("id", ""),
            last_status="ok" if not tg_err else "tg_failed",
            last_error=tg_err or "",
        )

    @staticmethod
    def _record_ai_audit_status(
        company_key: str, alert_id: str, **patch,
    ) -> None:
        if not alert_id:
            return
        cfg = load_alerts_config()
        bot_alerts = cfg.get("bot_alerts") or {}
        co = bot_alerts.get(company_key) or {}
        for _kind, alerts in (co or {}).items():
            for a in alerts or []:
                if a.get("id") == alert_id:
                    a.update(patch)
                    try:
                        save_alerts_config(cfg)
                    except OSError:
                        pass
                    return
