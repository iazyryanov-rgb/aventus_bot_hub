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

from .alerts import (
    TelegramError,
    load_alerts_config,
    save_alerts_config,
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

    lines: list[str] = []
    for agent, ages in sorted(
        by_agent.items(), key=lambda kv: (-len(kv[1]), -max(kv[1]))
    ):
        lines.append(f"• {agent} — {len(ages)} chat(s), max {max(ages)}m")
    if no_agent_ages:
        lines.append(
            f"• (bot/no-agent) — {len(no_agent_ages)} chat(s), max {max(no_agent_ages)}m"
        )

    return (
        f"⚠️ #{company.name} | #Agents\n"
        f"🕒 Chats unanswered > {UNANSWERED_THRESHOLD_MIN}min\n"
        f"\n"
        + "\n".join(lines)
        + f"\n\n🌐 {company.webitel_host.rstrip('/')}"
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

    lines = "\n".join(f"• {q.name} — online={o}, pause={p}" for q, o, p in bad)
    return (
        f"⚠️ #{company.name} | #Agents\n"
        f"😴 Agents on break > online · Collection\n"
        f"\n"
        f"{lines}\n"
        f"\n"
        f"🌐 {company.webitel_host.rstrip('/')}"
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
    missing_lines = "\n".join(f"• {g} — {s}" for g, s in missing)
    return (
        f"⚠️ #{company.name} | #Agents\n"
        f"🧩 Queues check · Collection\n"
        f"📊 Coverage: {ok} / {total}\n"
        f"\n"
        f"❌ Missing enabled queues:\n"
        f"{missing_lines}\n"
        f"\n"
        f"✅ Already configured: {ok}\n"
        f"🌐 {company.webitel_host.rstrip('/')}"
    )


TEMPLATE_BUILDERS: dict[str, Callable[[Company], Optional[str]]] = {
    "queue_checklist": _build_queue_checklist_text,
    "agents_on_break": _build_agents_on_break_text,
    "agents_chats_unanswered": _build_agents_chats_unanswered_text,
}


class AlertScheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="alert-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

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

        for ckey, by_kind in bot_alerts.items():
            company = companies.get(ckey)
            if not company:
                continue
            for _kind, alerts in (by_kind or {}).items():
                for alert in alerts or []:
                    if not alert.get("enabled", True):
                        continue
                    builder = TEMPLATE_BUILDERS.get(alert.get("template", ""))
                    if builder is None:
                        continue
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
                    text = builder(company)
                    alert["last_run_at_ms"] = now_ms
                    changed = True
                    if text is None:
                        continue
                    try:
                        send_telegram_message(token, chat_id, text)
                    except TelegramError:
                        pass

        if changed:
            try:
                save_alerts_config(cfg)
            except OSError:
                pass
