"""Per-company Collection capacity calculator.

The Collection group definitions live in the CRM, table
`collection_category(id, name, dpd_from, dpd_to)`. Collectors are
attached to groups via `collector_category_assignment(collector_id,
category_id, distribution_percentage)` — that's the column shown as
"Number of collectors" in the CRM admin UI ("Purpose of collectors").

For each group we report:
  * `agents`         — collectors currently assigned to the group via
                       `collector_category_assignment` (the
                       "Number of collectors" column in the CRM admin);
  * `loans`          — open loans WITH a `collector_id` whose
                       `daysLate` falls within `[dpd_from … dpd_to]`
                       (inclusive; NULL `dpd_to` means open-ended on
                       the high side). "Закреплено сделок всего."
  * `max_per_agent`  — heaviest caseload on a single collector inside
                       that DPD window right now;
  * `outsource`      — per-agency loan share for groups DPD ≥ 31.
                       admUser.admin_type values: 0=agent (human),
                       1=bot, 2=collection agency / outsource. For G3+
                       the Collection team outsources to agencies
                       (Recovery / Puntualmente / Accion Legal /
                       Virtus / Serlefin etc.), so we break the bucket
                       down per agency with absolute count and % of
                       the group total.
  * `needed`         — `ceil(loans / target_per_agent)` with capacity
                       targets:
                          DPD ≤ 0      → 250 loans / agent
                          DPD 1-15     → 300 loans / agent
                          DPD 16-30    → 500 loans / agent
                          DPD > 30     → no target (column shows "—")

Currently supports MySQL companies (CO_/CO2_). AR_/PE_ are Postgres
and use a different schema; they raise `CapacityUnavailable`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .data import Company, load_raw
from .db import connect_for_company


# CO_ / CO2_ run on the same Aventus MySQL schema (database name
# differs). Other tenants need their own recipe.
MYSQL_DB_BY_COMPANY: dict[str, str] = {
    "CO_":  "prod_credito365_api",
    "CO2_": "prod_tuparcero_api",
}


# Threshold from which we treat the group as outsourced.
# `dpd_from >= 31` covers G3..G5 in both CO_ and CO2_ schemas.
OUTSOURCE_DPD_THRESHOLD = 31

# admUser.admin_type
ADMIN_TYPE_AGENT = 0
ADMIN_TYPE_BOT = 1
ADMIN_TYPE_AGENCY = 2


def _target_for(dpd_from: int, dpd_to: Optional[int]) -> Optional[int]:
    """Map a (dpd_from, dpd_to) window to its per-agent loan target.
    `None` ⇒ no rule (the column shows '—' in the UI)."""
    if dpd_to is None:
        return None
    if dpd_to <= 0:
        return 250
    if dpd_to <= 15:
        return 300
    if dpd_to <= 30:
        return 500
    return None


class CapacityUnavailable(Exception):
    """The company's CRM doesn't have a supported capacity recipe yet
    (e.g. AR_/PE_ Postgres tenants until we add a query)."""


@dataclass
class OutsourceShare:
    collector_id: int
    display_name: str   # human-readable agency name
    loans: int          # loans this agency holds in this DPD window
    pct: float          # share of the group's total (0..100)


@dataclass
class GroupStats:
    name: str         # 'G0' / 'G1' / ...
    dpd_from: int
    dpd_to: Optional[int]
    agents: int       # collectors assigned to this category (from CRM)
    loans: int        # open loans with daysLate in the window
    max_per_agent: int  # heaviest caseload on a single collector in the window
    target_per_agent: Optional[int]  # capacity rule (None when unknown)
    needed: Optional[int]            # math.ceil(loans / target) or None
    outsource: list[OutsourceShare]  # per-agency split (G3+ only)


def _resolve_mysql_db(company: Company) -> str:
    db = MYSQL_DB_BY_COMPANY.get(company.key)
    if not db:
        raise CapacityUnavailable(
            f"{company.key}: capacity recipe не настроен (MySQL-схема "
            "только для CO_/CO2_)"
        )
    return db


def _ensure_supported(company: Company) -> None:
    raw = load_raw().get(company.key, {}) or {}
    engine = (raw.get("crm_db_engine") or "mysql").lower()
    if engine != "mysql":
        raise CapacityUnavailable(
            f"{company.key}: CRM engine={engine!r}, capacity пока умеет "
            "только MySQL (CO_/CO2_)"
        )
    if not raw.get("crm_db_port"):
        raise CapacityUnavailable(
            f"{company.key}: crm_db_port не задан в companies.json"
        )
    _resolve_mysql_db(company)


def compute_capacity(company: Company) -> list[GroupStats]:
    """One SQL roundtrip + a handful of per-group window queries.

    The category list is small (≤10) and the per-group queries hit the
    `loan` table's `(returnedDate, daysLate, collector_id)` index, so
    the whole call takes well under a second on CO_'s 1.2M-row table.
    """
    _ensure_supported(company)
    db = _resolve_mysql_db(company)
    conn = connect_for_company(company)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, name, dpd_from, dpd_to "
                f"FROM `{db}`.collection_category"
            )
            categories = [
                {
                    "id": int(r[0]),
                    "name": str(r[1] or ""),
                    "dpd_from": int(r[2]) if r[2] is not None else 0,
                    "dpd_to": (int(r[3]) if r[3] is not None else None),
                }
                for r in cur.fetchall()
            ]

            cur.execute(
                f"SELECT category_id, COUNT(*) "
                f"FROM `{db}`.collector_category_assignment "
                f"GROUP BY category_id"
            )
            assigned_by_cat = {int(r[0]): int(r[1]) for r in cur.fetchall()}

            results: list[GroupStats] = []
            for cat in categories:
                dpd_from = cat["dpd_from"]
                dpd_to = cat["dpd_to"]
                if dpd_to is None:
                    where = (
                        "l.returnedDate IS NULL "
                        "AND l.collector_id IS NOT NULL "
                        "AND l.daysLate >= %s"
                    )
                    params: tuple = (dpd_from,)
                else:
                    where = (
                        "l.returnedDate IS NULL "
                        "AND l.collector_id IS NOT NULL "
                        "AND l.daysLate BETWEEN %s AND %s"
                    )
                    params = (dpd_from, dpd_to)

                cur.execute(
                    f"SELECT COUNT(*) FROM `{db}`.loan l WHERE {where}",
                    params,
                )
                loans_total = int((cur.fetchone() or (0,))[0])

                cur.execute(
                    f"SELECT MAX(c) FROM ("
                    f"  SELECT COUNT(*) AS c FROM `{db}`.loan l "
                    f"  WHERE {where} "
                    f"  GROUP BY l.collector_id"
                    f") sub",
                    params,
                )
                row = cur.fetchone()
                max_per_agent = int(row[0]) if row and row[0] is not None else 0

                target = _target_for(dpd_from, dpd_to)
                needed = (
                    math.ceil(loans_total / target)
                    if target and loans_total
                    else (0 if target else None)
                )

                outsource: list[OutsourceShare] = []
                if dpd_from >= OUTSOURCE_DPD_THRESHOLD:
                    cur.execute(
                        f"SELECT u.id, u.username, u.name, u.surname, "
                        f"       COUNT(*) AS n "
                        f"FROM `{db}`.loan l "
                        f"JOIN `{db}`.admUser u ON u.id = l.collector_id "
                        f"WHERE {where} AND u.admin_type = %s "
                        f"GROUP BY u.id, u.username, u.name, u.surname "
                        f"ORDER BY n DESC",
                        params + (ADMIN_TYPE_AGENCY,),
                    )
                    for r in cur.fetchall():
                        cid = int(r[0])
                        username = str(r[1] or "")
                        first = str(r[2] or "").strip()
                        last = str(r[3] or "").strip()
                        if first and last and first.lower() != last.lower():
                            display = f"{first} {last}"
                        else:
                            display = first or last or username or f"#{cid}"
                        n = int(r[4] or 0)
                        pct = (n / loans_total * 100.0) if loans_total else 0.0
                        outsource.append(OutsourceShare(
                            collector_id=cid,
                            display_name=display,
                            loans=n,
                            pct=pct,
                        ))

                results.append(GroupStats(
                    name=cat["name"],
                    dpd_from=dpd_from,
                    dpd_to=dpd_to,
                    agents=assigned_by_cat.get(cat["id"], 0),
                    loans=loans_total,
                    max_per_agent=max_per_agent,
                    target_per_agent=target,
                    needed=needed,
                    outsource=outsource,
                ))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Sort by dpd_from then by name so groups appear in DPD order, with
    # a stable tiebreaker for overlapping ranges (CO2_ has G3/G4/G5 all
    # at dpd_from=31).
    results.sort(key=lambda g: (g.dpd_from, g.name))
    return results
