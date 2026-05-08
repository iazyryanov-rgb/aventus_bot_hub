"""Count communication-result rows registered in the company's CRM today.

Used by the dashboard funnel to show what % of outbound attempts produced
a registered result in CRM."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .data import Company
from .db import connect_for_company as _open_for


def _today_local_start_naive(company: Company) -> datetime:
    try:
        tz = ZoneInfo(company.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    today_local = datetime.now(tz).date()
    start_local = datetime.combine(today_local, datetime.min.time(), tzinfo=tz)
    # Convert to naive UTC datetime — communication_history.created_at stores
    # datetimes without timezone, server side is UTC for Aventus stack.
    return start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _co_count(company: Company, db_name: str) -> int:
    start = _today_local_start_naive(company)
    conn = _open_for(company)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM `{db_name}`.communication_history "
                f"WHERE created_at >= %s",
                (start,),
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _co_credito365_count(company: Company) -> int:
    return _co_count(company, "prod_credito365_api")


def _co2_tuparcero_count(company: Company) -> int:
    return _co_count(company, "prod_tuparcero_api")


COUNTERS = {
    "CO_": _co_credito365_count,
    "CO2_": _co2_tuparcero_count,
}


def count_results_today(company: Company) -> Optional[int]:
    fn = COUNTERS.get(company.key)
    if not fn:
        return None
    try:
        return fn(company)
    except Exception:
        return None
