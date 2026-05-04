import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .paths import data_dir

DEFAULT_COUNTRY_TZ = {
    "Argentina": "America/Argentina/Buenos_Aires",
    "Colombia": "America/Bogota",
    "Peru": "America/Lima",
}


def default_timezone_for_country(country: str) -> str:
    return DEFAULT_COUNTRY_TZ.get(country, "UTC")


@dataclass
class Company:
    key: str
    code: str
    name: str
    country: str
    schema_name: str
    webitel_host: str
    webitel_access_token: str
    timezone: str


def load_raw() -> dict:
    with open(data_dir() / "companies.json", encoding="utf-8") as f:
        return json.load(f)


def save_raw(raw: dict) -> None:
    path = data_dir() / "companies.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=4)
        f.write("\n")


def load_companies() -> list[Company]:
    raw = load_raw()
    out: list[Company] = []
    for key, info in raw.items():
        out.append(
            Company(
                key=key,
                code=key.rstrip("_"),
                name=info.get("name", ""),
                country=info.get("country", ""),
                schema_name=info.get("schema_name", ""),
                webitel_host=info.get("webitel_host", ""),
                webitel_access_token=info.get("webitel_access_token", ""),
                timezone=info.get("timezone")
                or default_timezone_for_country(info.get("country", "")),
            )
        )
    out.sort(key=lambda c: c.code)
    return out


def latest_build_date(company_key: str) -> Optional[date]:
    folder = data_dir() / "catalogs" / company_key
    if not folder.exists():
        return None
    latest: Optional[date] = None
    for entry in folder.iterdir():
        if not entry.is_dir():
            continue
        try:
            d = datetime.strptime(entry.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if latest is None or d > latest:
            latest = d
    return latest


def load_bot(company_key: str, kind: str) -> dict:
    raw = load_raw()
    return dict(raw.get(company_key, {}).get("bots", {}).get(kind, {}))


def save_bot(company_key: str, kind: str, info: dict) -> None:
    raw = load_raw()
    co = raw.setdefault(company_key, {})
    bots = co.setdefault("bots", {})
    bots[kind] = info
    save_raw(raw)


REQUIRED_COMPANY_FIELDS = (
    "name",
    "country",
    "webitel_host",
    "webitel_access_token",
    "crm_host",
    "crm_access_token",
)


def is_company_complete(company_key: str) -> bool:
    raw = load_raw()
    info = raw.get(company_key, {})
    for field in REQUIRED_COMPANY_FIELDS:
        value = info.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
    return True


REQUIRED_BOT_FIELDS: dict[str, tuple[str, ...]] = {
    "voice": (),
    "whatsapp": ("prod_schema_id",),
    "agents": (),
}


def is_bot_complete(company_key: str, kind: str) -> bool:
    info = load_bot(company_key, kind)
    for field in REQUIRED_BOT_FIELDS.get(kind, ()):
        value = info.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
    return True


def now_in_timezone(tz_name: str) -> str:
    if not tz_name:
        return ""
    try:
        return datetime.now(ZoneInfo(tz_name)).strftime("%H:%M:%S")
    except Exception:
        return ""
