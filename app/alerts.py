import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from .paths import data_dir

ALERT_TEMPLATES: list[tuple[str, str, str]] = [
    ("queue_checklist",          "🧩 Queues check · Collection", "Автопроверка чек-листа Collection (G1/G2/G3 × Main/APTP/BPTP). Алерт уходит только если есть пробелы."),
    ("agents_on_break",          "😴 Agents on break > online", "Считает по очередям Collection × {Main, APTP, BPTP}: сколько агентов online vs pause. Алерт, если в любой такой очереди на перерыве больше, чем онлайн."),
    ("agents_chats_unanswered",  "🕒 Agents · chats unanswered > 15min", "Перечисляет агентов, у которых есть открытые чаты, где последнее сообщение от клиента старше 15 минут."),
    ("broken_validation", "🔴 Broken Validation", "Сбой валидации диалога — критично. Поля для фикса: stage, alert_type, destination."),
    ("crm_validation",    "⚠️ CRM Validation",   "Расхождение ответа CRM с ожиданиями. Поля: vars_to_check, problem_variable, crm_error, crm_message."),
    ("company_error",     "🔴 Company Error",    "Ошибка на стороне компании. Поля: alert_type, project_index."),
    ("generic_error",     "🔴 Error",            "Любая необработанная ошибка ветки бота. Поля: alert_type, stage."),
    ("integration",       "🔴 Integration",      "Сбой внешней интеграции (CRM/AI). Поля: counter, alert_type, conversations_response."),
    ("collection_group",  "🔴 Collection Group", "Ошибка маршрутизации по группе коллекции. Поля: collection_group, dpd, link, destination."),
    ("dash_outbound_drop",   "📉 Исходящие · падение",   "Алерт, если число исходящих попыток сегодня <50% от среднего за предыдущие 7 дней (на текущий час)."),
    ("dash_amd_machine_high", "🤖 AMD-MACHINE > 60%",     "Сигнал, если доля MACHINE среди попыток сегодня превышает 60%."),
    ("dash_handled_low",      "👥 Обработано агентом < 40%", "Сигнал, если процент звонков, обработанных агентом, ниже 40% от попыток сегодня."),
    ("dash_crm_results_low",  "📒 CRM-результаты < 50% от обработанных", "Сигнал, если число записей в communication_history меньше 50% от обработанных агентом сегодня."),
    ("ai_audit",              "🤖 AI-аудит · WhatsApp",                  "Полный AI-аудит чатов через Claude (Sonnet/Opus). Запускается по расписанию, рекомендации публикуются в тему компании в Telegram. Поля для фикса: model_kind (sonnet/opus), chat_limit, period_days."),
    ("weekly_review",         "📊 Weekly review · Champion vs Candidate", "Еженедельная сводка: champion-когорта vs candidate-когорта (split по последней цифре телефона). Считает close/prolong/any-pay rates, выдаёт PROMOTE/KEEP decision. Поля: weekday (0=Mon), days (default 7), target_goal (fully_pay/prolong/both), min_lift_pct (default 2.0), min_n (default 50), chat_limit (default 5000)."),
    ("webitel_api_down",      "🚨 Webitel API недоступен",                "Health-check: пингует cheap эндпоинт Webitel; алерт после 2 подряд фейлов и о восстановлении. Без полей. Запуск раз в 5 минут."),
    ("wa_chat_volume_drop",   "📉 WA трафик упал",                        "Сравнивает количество WA-диалогов за последний час с rolling baseline (тот же час дня за последние 7 дней, weekdays). Алерт при падении >70%. Auto-pause цикла. Запуск раз в 30 минут."),
    ("wa_bot_silent",         "🚨 Бот молчит на чатах",                   "Если за последний час >50% диалогов: клиент написал последним, прошло >5min, агент не подключался — бот не отвечает. Alert raise при росте. Запуск раз в 15 минут."),
    ("wa_senders_health",     "📡 WA Senders · health (Infobip)",         "Поллит Infobip /whatsapp/2/senders по нашему гейтвею. Алерт при понижении quality (HIGH→MEDIUM/LOW) или лимита (UNLIMITED↓100K↓10K↓2K↓250) и при переходе статуса в BANNED/RESTRICTED/RATE_LIMITED/FLAGGED/DELETED. INFO-изменения (новый сендер, recovery) видны в панели «Сендеры», в TG не уходят. Первый запуск — тихо сохраняет baseline. Запуск раз в 30 минут."),
    ("cohort_imbalance",      "⚖️ A/B router cohort imbalance",           "Сравнивает фактическую долю candidate-когорты (digits 0,1,2 по умолчанию) с ожидаемыми 30%. Алерт при отклонении ≥15pp — router сломан или gate сменили. Запуск раз в час."),
    ("crm_call_list_failed",  "📞 Коллист · ошибка отправки",             "Поллит CRM-таблицу dialer_process (Lendi-движок: AR/PE): алерт по новым строкам со state='error'. В сообщение идут campaign name, process id и last_error. Throttle через high-water mark по updated_at — каждый сбой репортится один раз."),
]

ALERT_TEMPLATE_BY_SLUG = {slug: (slug, title, desc) for slug, title, desc in ALERT_TEMPLATES}

SCHEDULE_PRESETS: list[str] = [
    "Не запускать",
    "Каждые 5 минут",
    "Каждые 15 минут",
    "Каждые 30 минут",
    "Каждый час",
    "Каждые 3 часа",
    "Раз в сутки",
]

DEFAULT_CONFIG = {
    "telegram": {
        "bot_token": "8051942313:AAFyj5poYItKlp0idbCQxw2OdE6WTWMDutw",
        "chat_id": "-1002627199331",
    }
}


def alerts_config_path() -> Path:
    return data_dir() / "alerts.json"


def load_alerts_config() -> dict:
    path = alerts_config_path()
    if not path.exists():
        return {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_CONFIG.items()}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "telegram" not in data:
        data["telegram"] = dict(DEFAULT_CONFIG["telegram"])
    return data


def save_alerts_config(cfg: dict) -> None:
    path = alerts_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
        f.write("\n")


class TelegramError(Exception):
    pass


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    message_thread_id: int | None = None,
    timeout: float = 15.0,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if message_thread_id is not None:
        payload["message_thread_id"] = int(message_thread_id)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("description")
        except Exception:
            detail = e.reason
        raise TelegramError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise TelegramError(f"Сеть: {e.reason}") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise TelegramError(f"Некорректный ответ: {e}") from e
    if not resp.get("ok"):
        raise TelegramError(f"Telegram: {resp}")


# Telegram-allowed forum topic icon colors (decimal RGB).
_TOPIC_ICON_COLORS = (
    7322096, 16766590, 13338331, 9367192, 16749490, 16478047,
)


def create_forum_topic(
    bot_token: str,
    chat_id: str,
    name: str,
    icon_color: int | None = None,
    timeout: float = 15.0,
) -> int:
    """Create a forum topic in `chat_id` and return its `message_thread_id`.
    The chat must be a Forum-enabled supergroup and the bot must have the
    «Manage Topics» permission."""
    url = f"https://api.telegram.org/bot{bot_token}/createForumTopic"
    payload: dict = {"chat_id": chat_id, "name": name}
    if icon_color is not None:
        payload["icon_color"] = int(icon_color)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("description")
        except Exception:
            detail = e.reason
        raise TelegramError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise TelegramError(f"Сеть: {e.reason}") from e
    if not resp.get("ok"):
        raise TelegramError(f"Telegram: {resp}")
    tid = (resp.get("result") or {}).get("message_thread_id")
    if not tid:
        raise TelegramError(f"Telegram: no message_thread_id in {resp}")
    return int(tid)


def get_company_topic(cfg: dict, company_key: str) -> int | None:
    topics = (cfg.get("telegram") or {}).get("topics") or {}
    val = topics.get(company_key)
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def set_company_topic(cfg: dict, company_key: str, topic_id: int) -> None:
    tg = cfg.setdefault("telegram", {})
    topics = tg.setdefault("topics", {})
    topics[company_key] = int(topic_id)


def ensure_company_topic(cfg: dict, company, index_hint: int = 0) -> int | None:
    """Return the per-company topic id, creating it on Telegram if missing.
    Mutates `cfg` and saves it on creation. Returns None if Telegram refuses
    (chat is not a forum / bot lacks rights)."""
    existing = get_company_topic(cfg, company.key)
    if existing:
        return existing
    tg = cfg.get("telegram") or {}
    token = tg.get("bot_token") or ""
    chat_id = tg.get("chat_id") or ""
    if not token or not chat_id:
        return None
    code = company.key.rstrip("_")
    name = f"{code} — {company.name}"
    color = _TOPIC_ICON_COLORS[index_hint % len(_TOPIC_ICON_COLORS)]
    try:
        tid = create_forum_topic(token, chat_id, name, icon_color=color)
    except TelegramError:
        return None
    set_company_topic(cfg, company.key, tid)
    try:
        save_alerts_config(cfg)
    except OSError:
        pass
    return tid


# --- General "for all" topic (hub changelog only) ---------------------------

GENERAL_TOPIC_NAME = "🚀 Aventus Bot Hub · changelog"


def get_general_topic(cfg: dict) -> int | None:
    """The general / cross-company topic id. Reserved for **hub
    update changelogs only** — every regular alert routes to its own
    company's topic via `ensure_company_topic`."""
    val = (cfg.get("telegram") or {}).get("general_topic")
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def ensure_general_topic(cfg: dict) -> int | None:
    """Return the changelog topic id, creating it on first use. Mutates
    `cfg` and saves it. Returns None if Telegram refuses (non-forum
    chat / bot rights missing)."""
    existing = get_general_topic(cfg)
    if existing:
        return existing
    tg = cfg.get("telegram") or {}
    token = tg.get("bot_token") or ""
    chat_id = tg.get("chat_id") or ""
    if not token or not chat_id:
        return None
    try:
        # Color picked deliberately distinct from per-company topics
        # (latter cycle through 6 hues).
        tid = create_forum_topic(
            token, chat_id, GENERAL_TOPIC_NAME, icon_color=9367192,
        )
    except TelegramError:
        return None
    cfg.setdefault("telegram", {})["general_topic"] = int(tid)
    try:
        save_alerts_config(cfg)
    except OSError:
        pass
    return tid


def get_last_changelog_sha(cfg: dict) -> str:
    return str((cfg.get("telegram") or {}).get("last_changelog_sha") or "")


def set_last_changelog_sha(cfg: dict, sha: str) -> None:
    cfg.setdefault("telegram", {})["last_changelog_sha"] = str(sha)


def send_hub_changelog(cfg: dict, text: str) -> str | None:
    """Push a single HTML-formatted changelog message into the general
    topic. Returns None on success, or an error string."""
    tg = cfg.get("telegram") or {}
    token = tg.get("bot_token") or ""
    chat_id = tg.get("chat_id") or ""
    if not token or not chat_id:
        return "Telegram not configured"
    topic_id = ensure_general_topic(cfg)
    try:
        send_telegram_message(
            token, chat_id, text,
            parse_mode="HTML",
            message_thread_id=topic_id,
        )
    except TelegramError as exc:
        return str(exc)
    return None


def get_bot_alerts(company_key: str, kind: str) -> list[dict]:
    cfg = load_alerts_config()
    return list(cfg.get("bot_alerts", {}).get(company_key, {}).get(kind, []) or [])


def _set_bot_alerts(company_key: str, kind: str, alerts: list[dict]) -> None:
    cfg = load_alerts_config()
    bots = cfg.setdefault("bot_alerts", {})
    co = bots.setdefault(company_key, {})
    co[kind] = alerts
    save_alerts_config(cfg)


def upsert_bot_alert(company_key: str, kind: str, alert: dict) -> dict:
    alerts = get_bot_alerts(company_key, kind)
    aid = alert.get("id")
    if not aid:
        alert = {**alert, "id": secrets.token_hex(8)}
        alerts.append(alert)
    else:
        for i, a in enumerate(alerts):
            if a.get("id") == aid:
                alerts[i] = alert
                break
        else:
            alerts.append(alert)
    _set_bot_alerts(company_key, kind, alerts)
    return alert


def delete_bot_alert(company_key: str, kind: str, alert_id: str) -> None:
    alerts = [a for a in get_bot_alerts(company_key, kind) if a.get("id") != alert_id]
    _set_bot_alerts(company_key, kind, alerts)


DEFAULT_AGENT_ALERTS: list[dict] = [
    {
        "name": "Agents on break > online",
        "template": "agents_on_break",
        "schedule": "Каждые 15 минут",
        "trigger_mode": "event",
        "working_hours_only": True,
        "start_time": "",
        "enabled": True,
        "notes": "Авто: алерт, если в любой Collection × {Main, APTP, BPTP} очереди на перерыве больше людей, чем онлайн.",
    },
    {
        "name": "Agents chats unanswered > 15min",
        "template": "agents_chats_unanswered",
        "schedule": "Каждые 15 минут",
        "trigger_mode": "event",
        "working_hours_only": True,
        "start_time": "",
        "enabled": True,
        "notes": "Авто: чаты, в которых клиент написал последним и не получил ответа более 15 минут. В алерт идёт список агентов и сколько у каждого зависших чатов.",
    },
]


DEFAULT_AI_AUDIT_ALERTS: list[dict] = [
    {
        "name": "AI audit · WhatsApp · daily",
        "template": "ai_audit",
        "schedule": "Раз в сутки",
        "trigger_mode": "time",
        "working_hours_only": False,
        "start_time": "09:00",
        "enabled": True,
        # Audit-specific knobs (read by scheduler.py).
        "model_kind": "sonnet",
        "chat_limit": 500,
        "period_days": 1,
        "notes": (
            "Авто: ежедневный AI-аудит чатов за последние сутки на Sonnet 4.6, "
            "до 500 чатов. Результат уходит в тему компании в Telegram."
        ),
    },
]


# Phase H — health-check alerts. Every WA-enabled company gets these by
# default; they are cheap and the auto-pause hooks keep accidents
# contained. Cohort-imbalance only fires once an A/B router is present
# (otherwise the deviation is meaningless), so it's safe to enable
# everywhere — early-out lives in the builder.
DEFAULT_HEALTH_ALERTS: list[dict] = [
    {
        "name": "Webitel API health (5min ping)",
        "template": "webitel_api_down",
        "schedule": "Каждые 5 минут",
        "trigger_mode": "event",
        "working_hours_only": False,
        "start_time": "",
        "enabled": True,
        "notes": (
            "Health-check: пингует cheap-эндпоинт Webitel. Алерт после 2 "
            "подряд фейлов и о восстановлении."
        ),
    },
    {
        "name": "WA chat volume drop (1h vs baseline)",
        "template": "wa_chat_volume_drop",
        "schedule": "Каждые 30 минут",
        "trigger_mode": "event",
        "working_hours_only": False,
        "start_time": "",
        "enabled": True,
        "notes": (
            "Сравнивает WA-диалоги за последний час с rolling baseline (тот "
            "же час дня за последние 7 weekdays). Alerts на падение >70% + "
            "auto-pause цикла."
        ),
    },
    {
        "name": "WA bot silent (>50% chats stuck)",
        "template": "wa_bot_silent",
        "schedule": "Каждые 15 минут",
        "trigger_mode": "event",
        "working_hours_only": False,
        "start_time": "",
        "enabled": True,
        "notes": (
            "Если >50% диалогов за час: клиент написал последним, прошло "
            ">5min, агент не подключался — бот молчит."
        ),
    },
    {
        "name": "A/B router cohort imbalance",
        "template": "cohort_imbalance",
        "schedule": "Каждый час",
        "trigger_mode": "event",
        "working_hours_only": False,
        "start_time": "",
        "enabled": True,
        "notes": (
            "Сравнивает фактическую долю candidate-когорты с ожидаемой. "
            "Алерт при отклонении ≥15pp."
        ),
    },
]


def ensure_default_health_alerts(company_keys: list[str]) -> None:
    """Idempotently inject DEFAULT_HEALTH_ALERTS into bot_alerts[<key>]['whatsapp']
    for every company that has any whatsapp alerts already (i.e. a real
    WA bot setup, not a placeholder). Skips templates already present."""
    cfg = load_alerts_config()
    bot_alerts = cfg.setdefault("bot_alerts", {})
    changed = False
    for key in company_keys:
        co = bot_alerts.setdefault(key, {})
        wa = co.setdefault("whatsapp", [])
        existing_templates = {a.get("template") for a in wa}
        for tpl in DEFAULT_HEALTH_ALERTS:
            if tpl["template"] in existing_templates:
                continue
            wa.append({**tpl, "id": secrets.token_hex(8)})
            changed = True
    if changed:
        save_alerts_config(cfg)


def ensure_default_ai_audit_alerts(company_keys: list[str]) -> None:
    """Idempotently inject DEFAULT_AI_AUDIT_ALERTS into bot_alerts[<key>]['whatsapp']
    for every passed company. Skips if an `ai_audit` alert already exists."""
    cfg = load_alerts_config()
    bot_alerts = cfg.setdefault("bot_alerts", {})
    changed = False
    for key in company_keys:
        co = bot_alerts.setdefault(key, {})
        wa = co.setdefault("whatsapp", [])
        existing_templates = {a.get("template") for a in wa}
        for tpl in DEFAULT_AI_AUDIT_ALERTS:
            if tpl["template"] in existing_templates:
                continue
            wa.append({**tpl, "id": secrets.token_hex(8)})
            changed = True
    if changed:
        save_alerts_config(cfg)


def ensure_default_agent_alerts(company_keys: list[str]) -> None:
    """Idempotently inject DEFAULT_AGENT_ALERTS into bot_alerts[<key>]['agents']
    for every passed company. Skips alerts whose template already exists for
    the company, so user customisation isn't clobbered."""
    cfg = load_alerts_config()
    bot_alerts = cfg.setdefault("bot_alerts", {})
    changed = False
    for key in company_keys:
        co = bot_alerts.setdefault(key, {})
        agents = co.setdefault("agents", [])
        existing_templates = {a.get("template") for a in agents}
        for tpl in DEFAULT_AGENT_ALERTS:
            if tpl["template"] in existing_templates:
                continue
            agents.append({**tpl, "id": secrets.token_hex(8)})
            changed = True
    if changed:
        save_alerts_config(cfg)
