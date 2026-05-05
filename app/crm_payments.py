"""Per-company payments-per-day queries against the CRM DB.

Each project's CRM has its own schema, so each company key gets its own
function. The dashboard calls `fetch_payments_per_day(company, days)` and
expects back a dict {YYYY-MM-DD: stats_dict} or None on missing config /
errors. Stats dict shape:
    {
      "count": int,           # total payments
      "sum": float,           # total amount
      "close_count": int,     # payments that closed a loan
      "close_sum": float,
      "prolong_count": int,   # payments that prolonged a loan
      "prolong_sum": float,
      "partial_count": int,   # everything else (active loan, partial repay)
      "partial_sum": float,
    }

Adding a new company:
  1. Write a `_<key>_payments(port, days, tz_name) -> dict[str, dict]` for the
     project's schema.
  2. Register it in `PAYMENTS_QUERIES`.
  3. Set `crm_db_port` for that company in companies.json.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Iterable, Optional

from .crm_lookup import _open_for
from .data import Company, load_raw

QueryFn = Callable[[int, list[date], str], dict[str, dict]]


def _connect(port: int):
    """Legacy MySQL connect by port (kept for backward compat with
    _co_credito365_payments). New code should call `_open_for(company)`."""
    import pymysql

    from .db import load_db_config

    cfg = load_db_config()
    return pymysql.connect(
        host=cfg.get("host", "localhost"),
        port=int(port),
        user=cfg.get("user", "viewer"),
        password=cfg.get("password", "") or "",
        connect_timeout=int(cfg.get("connect_timeout", 5) or 5),
    )


def _chunks(lst: list, size: int) -> Iterable[list]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _empty_bucket() -> dict:
    return {
        "count": 0,
        "sum": 0.0,
        "close_count": 0,
        "close_sum": 0.0,
        "prolong_count": 0,
        "prolong_sum": 0.0,
        "partial_count": 0,
        "partial_sum": 0.0,
    }


# ---------- per-company implementations ----------

def _co_credito365_payments(
    port: int, days: list[date], tz_name: str
) -> dict[str, dict]:
    """CO Credito365: prod_credito365_api.

    A payment_transaction row is classified as:
      * Prolongation — `extension_term > 0`.
      * Closure — last payment for a loan AND `loan.status = 3` (returned).
      * Partial — anything else.
    Successful + incoming filter: `status = 4 AND direction = 'incoming'`.
    """
    if not days:
        return {}
    start = datetime.combine(days[0], datetime.min.time())
    end = datetime.combine(days[-1], datetime.max.time())

    conn = _connect(port)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, loan_id, amount, finished_at, extension_term "
                "FROM `prod_credito365_api`.payment_transaction "
                "WHERE finished_at >= %s AND finished_at <= %s "
                "  AND direction='incoming' AND status=4",
                (start, end),
            )
            payments = cur.fetchall()
            if not payments:
                return {}

            loan_ids = sorted({int(p[1]) for p in payments if p[1] is not None})

            loans_status: dict[int, int] = {}
            last_pmt: dict[int, int] = {}
            for chunk in _chunks(loan_ids, 1000):
                ph = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"SELECT id, status FROM `prod_credito365_api`.loan "
                    f"WHERE id IN ({ph})",
                    tuple(chunk),
                )
                for lid, st in cur.fetchall():
                    loans_status[int(lid)] = int(st)
                cur.execute(
                    f"SELECT loan_id, MAX(id) "
                    f"FROM `prod_credito365_api`.payment_transaction "
                    f"WHERE loan_id IN ({ph}) AND status=4 AND direction='incoming' "
                    f"GROUP BY loan_id",
                    tuple(chunk),
                )
                for lid, mx in cur.fetchall():
                    last_pmt[int(lid)] = int(mx)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out: dict[str, dict] = {}
    for pid, lid, amount, finished, ext in payments:
        if not finished:
            continue
        d_str = finished.strftime("%Y-%m-%d")
        bucket = out.setdefault(d_str, _empty_bucket())
        amt = float(amount or 0)
        bucket["count"] += 1
        bucket["sum"] += amt
        if ext and int(ext) > 0:
            bucket["prolong_count"] += 1
            bucket["prolong_sum"] += amt
        elif (
            lid is not None
            and loans_status.get(int(lid)) == 3
            and last_pmt.get(int(lid)) == int(pid)
        ):
            bucket["close_count"] += 1
            bucket["close_sum"] += amt
        else:
            bucket["partial_count"] += 1
            bucket["partial_sum"] += amt
    return out


# ---------- dispatch ----------

PAYMENTS_QUERIES: dict[str, QueryFn] = {
    "CO_": _co_credito365_payments,
}


def fetch_payments_per_day(
    company: Company, days: list[date]
) -> Optional[dict[str, dict]]:
    fn = PAYMENTS_QUERIES.get(company.key)
    if not fn:
        return None
    info = load_raw().get(company.key, {})
    port_str = str(info.get("crm_db_port") or "").strip()
    if not port_str:
        return None
    try:
        port = int(port_str)
    except ValueError:
        return None
    try:
        return fn(port, days, company.timezone)
    except Exception:
        return None
