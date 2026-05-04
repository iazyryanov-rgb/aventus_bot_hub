import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from .paths import data_dir

ALERT_TEMPLATES: list[tuple[str, str, str]] = [
    ("queue_checklist",   "🧩 Queues check · Collection", "Автопроверка чек-листа Collection (G1/G2/G3 × Main/APTP/BPTP). Алерт уходит только если есть пробелы."),
    ("agents_on_break",   "😴 Agents on break > online", "Считает по очередям Collection × {Main, APTP, BPTP}: сколько агентов online vs pause. Алерт, если в любой такой очереди на перерыве больше, чем онлайн."),
    ("broken_validation", "🔴 Broken Validation", "Сбой валидации диалога — критично. Поля для фикса: stage, alert_type, destination."),
    ("crm_validation",    "⚠️ CRM Validation",   "Расхождение ответа CRM с ожиданиями. Поля: vars_to_check, problem_variable, crm_error, crm_message."),
    ("company_error",     "🔴 Company Error",    "Ошибка на стороне компании. Поля: alert_type, project_index."),
    ("generic_error",     "🔴 Error",            "Любая необработанная ошибка ветки бота. Поля: alert_type, stage."),
    ("integration",       "🔴 Integration",      "Сбой внешней интеграции (CRM/AI). Поля: counter, alert_type, conversations_response."),
    ("collection_group",  "🔴 Collection Group", "Ошибка маршрутизации по группе коллекции. Поля: collection_group, dpd, link, destination."),
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
    timeout: float = 15.0,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
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
]


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
