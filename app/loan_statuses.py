"""Loan-status registry per company.

Each company that ships a known status table gets its own dict here. The
user assigns a sector ("collection" / "cc" / "") to each status from the
UI and the choice persists in `data/loan_status_overrides.json`.
"""
from __future__ import annotations

import json
from typing import Optional

from .paths import data_dir


CO_LOAN_STATUSES: dict[str, str] = {
    "0": "STATUS_REQUEST",
    "1": "STATUS_CONFIRMED",
    "2": "STATUS_ACTIVE",
    "3": "STATUS_RETURNED",
    "4": "STATUS_DENIED",
    "5": "STATUS_TERMINATED",
    "10": "STATUS_PROCESSING",
    "15": "STATUS_PROCESSING_FAIL",
    "20": "STATUS_EXTENDED",
    "21": "STATUS_OVERDUE",
    "22": "STATUS_CUSTOMER_CONFIRMATION",
    "23": "STATUS_AWAITING_COLLECTOR",
    "24": "STATUS_COLLECTOR_IN_PROGRESS",
    "25": "STATUS_GONE",
    "26": "STATUS_AWAITING_CUSTOMER_CONFIRMATION",
    "27": "STATUS_SOLD",
    "28": "STATUS_PRESALE",
    "29": "STATUS_COMMUNICATION_HOLD",
    "100": "STATUS_NEW",
}


LOAN_STATUSES_BY_COMPANY: dict[str, dict[str, str]] = {
    "CO_": CO_LOAN_STATUSES,
    "CO2_": dict(CO_LOAN_STATUSES),
}


# Sector slug → human label. Empty slug means «не выбрано».
SECTORS: list[tuple[str, str]] = [
    ("", "—"),
    ("collection", "Collection"),
    ("cc", "КЦ"),
]


def get_statuses(company_key: str) -> Optional[dict[str, str]]:
    return LOAN_STATUSES_BY_COMPANY.get(company_key)


# ---------- per-status sector overrides ----------

def overrides_path():
    return data_dir() / "loan_status_overrides.json"


def load_all_overrides() -> dict[str, dict[str, str]]:
    p = overrides_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: dict(v) for k, v in data.items() if isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        return {}


def save_all_overrides(data: dict[str, dict[str, str]]) -> None:
    p = overrides_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def get_sector(company_key: str, status_code: str) -> str:
    return (load_all_overrides().get(company_key) or {}).get(status_code, "")


def set_sector(company_key: str, status_code: str, sector: str) -> None:
    data = load_all_overrides()
    cm = data.setdefault(company_key, {})
    if sector:
        cm[status_code] = sector
    else:
        cm.pop(status_code, None)
    if not cm:
        data.pop(company_key, None)
    save_all_overrides(data)
