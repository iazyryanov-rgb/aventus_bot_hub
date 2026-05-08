"""Hub-side consumer for bot-emitted Telegram alerts (Phase I).

The bot's Alert page (after Phase J) sends Telegram messages of the form

    {ICON} <b>{title}</b>
    🏢 <b>{company}</b> · #{process}
    📍 Stage: ...
    ...

    <pre>
    {
      "v": 1,
      "kind": "broken_validation",
      "company_key": "CO_",
      "schema_id": 126,
      "schema_role": "candidate",
      ...
    }
    </pre>

This module long-polls Telegram's `getUpdates`, finds messages whose
text contains the `<pre>{json}</pre>` tail, parses, persists, and
dispatches reactions. The polling thread is daemon — it lives as long
as the hub process; minimised-to-tray hub keeps it running.

Persistence:
  data/bot_alert_inbox/<company_key>/<ts>_<id>.json — one file per
    parsed alert (raw + parsed payload + receive ts).

State (`<offset>` in TG semantics — cursor for `getUpdates`):
  data/bot_alert_inbox/_state.json — `{"offset": <int>}`. So restarts
    don't re-process old messages.

Reactions (initial):
  - `crm_fail` × N within 30min  → auto-pause the company's calibration cycle.
  - any `kind` not in known set  → log only.

Polling does NOT block startup; if Telegram is briefly unreachable,
errors are swallowed and we retry after a back-off.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .alerts import load_alerts_config
from .paths import data_dir


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _inbox_root() -> Path:
    return data_dir() / "bot_alert_inbox"


def _state_path() -> Path:
    return _inbox_root() / "_state.json"


def load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _save_alert(co_key: str, payload: dict, raw_text: str, tg_meta: dict) -> Path:
    folder = _inbox_root() / co_key
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rec_id = tg_meta.get("update_id") or tg_meta.get("message_id") or "noid"
    path = folder / f"{ts}_{rec_id}.json"
    record = {
        "received_at_ms": int(time.time() * 1000),
        "tg_meta": tg_meta,
        "payload": payload,
        "raw_text": raw_text,
    }
    try:
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return path


def list_alerts(co_key: str, limit: int = 100) -> list[dict]:
    folder = _inbox_root() / co_key
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.json"), reverse=True)[:limit]
    out: list[dict] = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            d["_path"] = str(f)
            out.append(d)
        except (OSError, json.JSONDecodeError):
            continue
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# `<pre>{...}</pre>` block in the message text. The JSON inside spans
# multiple lines; we grab everything up to the first `</pre>`.
_PRE_RE = re.compile(r"<pre>([\s\S]+?)</pre>")


def parse_alert_text(text: str) -> Optional[dict]:
    """Extract and JSON-parse the `<pre>{json}</pre>` tail from a TG
    message. Returns None if no parseable block is found. Tolerant: any
    JSON parse error or schema mismatch returns None rather than raising."""
    if not text or "<pre>" not in text:
        return None
    m = _PRE_RE.search(text)
    if not m:
        return None
    blob = m.group(1).strip()
    try:
        d = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    if d.get("v") != 1:
        return None
    if not d.get("kind"):
        return None
    return d


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

_REACTION_LOG: dict[tuple[str, str], deque] = {}  # (co_key, kind) -> deque[ts_ms]
_REACTION_LOCK = threading.Lock()

CRM_FAIL_STREAK_THRESHOLD = 5     # alerts
CRM_FAIL_STREAK_WINDOW_MS = 30 * 60 * 1000  # 30 minutes


def _react(payload: dict) -> Optional[str]:
    """Decide if this alert triggers an automated action. Returns a
    short reason string for logging, or None if no action."""
    kind = str(payload.get("kind") or "")
    co_key = str(payload.get("company_key") or "")
    if not kind or not co_key:
        return None

    now = int(time.time() * 1000)
    key = (co_key, kind)
    with _REACTION_LOCK:
        dq = _REACTION_LOG.setdefault(key, deque())
        dq.append(now)
        # Trim to window
        cutoff = now - CRM_FAIL_STREAK_WINDOW_MS
        while dq and dq[0] < cutoff:
            dq.popleft()
        streak = len(dq)

    if kind == "crm_fail" and streak >= CRM_FAIL_STREAK_THRESHOLD:
        # Auto-pause the company's calibration cycle.
        try:
            from . import calibration_cycle as cc
            cc._pause_cycle(
                co_key,
                f"crm_fail streak: {streak} bot-side alerts in "
                f"{CRM_FAIL_STREAK_WINDOW_MS // 60000}min — "
                "investigate CRM endpoint before resuming.",
            )
            return f"auto-paused cycle (crm_fail × {streak})"
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Telegram getUpdates polling
# ---------------------------------------------------------------------------

GET_UPDATES_TIMEOUT_S = 30   # long-poll inside the TG API
HTTP_TIMEOUT_S = 35           # client-side urllib timeout
RETRY_BACKOFF_S = 10          # sleep between failures


class BotAlertConsumer:
    """Long-polling consumer. One per process — instantiate from
    `AlertScheduler.start()`."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- Public API ---------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="bot-alert-consumer", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --- Loop ---------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                # Catch-all so the daemon never dies on a transient.
                try:
                    self._stop.wait(RETRY_BACKOFF_S)
                except Exception:
                    pass

    def _tick(self) -> None:
        cfg = load_alerts_config()
        tg = cfg.get("telegram") or {}
        token = (tg.get("bot_token") or "").strip()
        chat_id_filter = str(tg.get("chat_id") or "").strip()
        if not token:
            self._stop.wait(RETRY_BACKOFF_S)
            return

        state = load_state()
        offset = int(state.get("offset") or 0)
        url = (
            f"https://api.telegram.org/bot{token}/getUpdates"
            f"?timeout={GET_UPDATES_TIMEOUT_S}"
            f"&allowed_updates=%5B%22message%22%2C%22channel_post%22%5D"
        )
        if offset > 0:
            url += f"&offset={offset}"

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError:
            self._stop.wait(RETRY_BACKOFF_S)
            return
        except json.JSONDecodeError:
            self._stop.wait(RETRY_BACKOFF_S)
            return

        if not data.get("ok"):
            self._stop.wait(RETRY_BACKOFF_S)
            return

        max_id = offset
        for update in data.get("result") or []:
            uid = int(update.get("update_id") or 0)
            if uid + 1 > max_id:
                max_id = uid + 1
            self._handle_update(update, chat_id_filter)

        if max_id != offset:
            state["offset"] = max_id
            save_state(state)

    # --- Per-message dispatch ----------------------------------------

    def _handle_update(self, update: dict, chat_id_filter: str) -> None:
        msg = update.get("message") or update.get("channel_post")
        if not isinstance(msg, dict):
            return
        chat = msg.get("chat") or {}
        if chat_id_filter and str(chat.get("id")) != chat_id_filter:
            return

        text = msg.get("text") or msg.get("caption") or ""
        payload = parse_alert_text(text)
        if not payload:
            # Not a structured alert — ignore silently.
            return

        co_key = str(payload.get("company_key") or "_unknown")
        tg_meta = {
            "update_id": int(update.get("update_id") or 0),
            "message_id": int(msg.get("message_id") or 0),
            "date": int(msg.get("date") or 0),
            "chat_id": chat.get("id"),
            "message_thread_id": msg.get("message_thread_id"),
        }
        _save_alert(co_key, payload, text, tg_meta)

        try:
            _react(payload)
        except Exception:
            pass


# Singleton helper (for clean import sites).
_consumer_singleton: Optional[BotAlertConsumer] = None
_singleton_lock = threading.Lock()


def get_consumer() -> BotAlertConsumer:
    global _consumer_singleton
    with _singleton_lock:
        if _consumer_singleton is None:
            _consumer_singleton = BotAlertConsumer()
        return _consumer_singleton
