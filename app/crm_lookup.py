"""Per-company CRM helpers — pull a phone of an active loan from the project's
CRM DB and call the CRM HTTP endpoint with that phone.

DB engine and database name are taken from the company record in
`companies.json` (`crm_db_engine`, `crm_db_name`, `crm_db_port`)."""
from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable, Optional

from .data import Company, load_raw
from .db import connect_for_company as _open_for


# ---------- per-company "find active loan phone" ----------

def _mysql_active_phone(company: Company, db_name: str) -> Optional[str]:
    """Generic MySQL lookup used by CO/CO2 — both run on the same Aventus
    schema (loan.status=2 active, user.main_phone_number)."""
    conn = _open_for(company)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT u.main_phone_number "
                f"FROM `{db_name}`.loan l "
                f"JOIN `{db_name}`.user u ON l.userId = u.id "
                f"WHERE l.status = 2 "
                f"  AND u.main_phone_number IS NOT NULL "
                f"  AND u.main_phone_number != '' "
                f"ORDER BY l.id DESC LIMIT 1"
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _co_credito365_active_phone(company: Company) -> Optional[str]:
    return _mysql_active_phone(company, "prod_credito365_api")


def _co2_tuparcero_active_phone(company: Company) -> Optional[str]:
    return _mysql_active_phone(company, "prod_tuparcero_api")


def _mysql_active_phone_dpd(company: Company, db_name: str, min_dpd: int) -> Optional[str]:
    conn = _open_for(company)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT u.main_phone_number "
                f"FROM `{db_name}`.loan l "
                f"JOIN `{db_name}`.user u ON l.userId = u.id "
                f"WHERE l.returnedDate IS NULL "
                f"  AND l.daysLate >= %s "
                f"  AND u.main_phone_number IS NOT NULL "
                f"  AND u.main_phone_number != '' "
                f"ORDER BY l.daysLate DESC, l.id DESC LIMIT 1",
                (min_dpd,),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _co_credito365_active_phone_dpd90(company: Company) -> Optional[str]:
    return _mysql_active_phone_dpd(company, "prod_credito365_api", 90)


def _co2_tuparcero_active_phone_dpd90(company: Company) -> Optional[str]:
    return _mysql_active_phone_dpd(company, "prod_tuparcero_api", 90)


def _pg_active_phone(company: Company, country_prefix: str) -> Optional[str]:
    """Generic PG lookup used by AR/PE — same Aventus schema (loan.state=active,
    user.username = main phone). `country_prefix` is prepended only if the
    number doesn't already start with it (AR usernames are already full
    international, PE — local 9-digit)."""
    conn = _open_for(company)
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                'SELECT u.username '
                'FROM public.loan l JOIN public."user" u ON l.user_id = u.id '
                "WHERE l.state = 'active' "
                "  AND u.username IS NOT NULL AND u.username <> '' "
                "ORDER BY l.id DESC LIMIT 1"
            )
            row = cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row or not row[0]:
        return None
    phone = "".join(ch for ch in str(row[0]) if ch.isdigit())
    if phone and country_prefix and not phone.startswith(country_prefix):
        phone = country_prefix + phone
    return phone or None


def _pe_prestamo365_active_phone(company: Company) -> Optional[str]:
    """PE: usernames stored as 9-digit local number — prepend `51`."""
    return _pg_active_phone(company, "51")


def _ar_lendi_active_phone(company: Company) -> Optional[str]:
    """AR Lendi: usernames already in full international form (54...). No
    prefix substitution needed."""
    return _pg_active_phone(company, "")


ACTIVE_PHONE_QUERIES: dict[str, Callable[[Company], Optional[str]]] = {
    "AR_": _ar_lendi_active_phone,
    "CO_": _co_credito365_active_phone,
    "CO2_": _co2_tuparcero_active_phone,
    "PE_": _pe_prestamo365_active_phone,
}


ACTIVE_PHONE_DPD90_QUERIES: dict[str, Callable[[Company], Optional[str]]] = {
    "CO_": _co_credito365_active_phone_dpd90,
    "CO2_": _co2_tuparcero_active_phone_dpd90,
}


def _mysql_find_phone_by_criteria(
    company: Company,
    db_name: str,
    *,
    dpd: Optional[int],
    status_code: Optional[int],
    is_renewal: Optional[bool],
) -> Optional[str]:
    """Generic CO/CO2 (Aventus MySQL schema) search by loan attributes.

    Any of dpd / status_code / is_renewal may be None to skip that clause.

    Note: `loan` has no native `is_renewal` flag — the CRM HTTP API derives
    NEW/REP by checking whether the user has any prior loan. We mirror that
    via an EXISTS subquery: REP ⇔ user has at least one earlier loan record.

    Returns the latest matching user's `main_phone_number` (digits) or None.
    """
    conds = [
        "u.main_phone_number IS NOT NULL",
        "u.main_phone_number != ''",
    ]
    params: list = []
    if dpd is not None:
        conds.append("l.daysLate = %s")
        params.append(int(dpd))
    if status_code is not None:
        conds.append("l.status = %s")
        params.append(int(status_code))
    if is_renewal is True:
        conds.append(
            f"EXISTS (SELECT 1 FROM `{db_name}`.loan l2 "
            "WHERE l2.userId = l.userId AND l2.id < l.id)"
        )
    elif is_renewal is False:
        conds.append(
            f"NOT EXISTS (SELECT 1 FROM `{db_name}`.loan l2 "
            "WHERE l2.userId = l.userId AND l2.id < l.id)"
        )
    where_sql = " AND ".join(conds)

    conn = _open_for(company)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT u.main_phone_number "
                f"FROM `{db_name}`.loan l "
                f"JOIN `{db_name}`.user u ON l.userId = u.id "
                f"WHERE {where_sql} "
                f"ORDER BY l.id DESC LIMIT 1",
                tuple(params),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


CRM_DB_NAME_BY_COMPANY: dict[str, str] = {
    "CO_": "prod_credito365_api",
    "CO2_": "prod_tuparcero_api",
}


def find_client_phone_by_criteria(
    company: Company,
    *,
    dpd: Optional[int],
    loan_status: Optional[int],
    client_type: Optional[str],  # "NEW" | "REP" | None
) -> tuple[Optional[str], Optional[str]]:
    """Look up a CRM client matching the (dpd, loan_status, client_type)
    criteria — used by the testers UI to pick a realistic phone to use as
    `destination` for a tester profile.

    Returns (phone, error_message). On success `error_message` is None.
    """
    db_name = CRM_DB_NAME_BY_COMPANY.get(company.key)
    if not db_name:
        return None, (
            f"CRM search by criteria not configured for {company.key.rstrip('_')}"
        )
    info = load_raw().get(company.key, {})
    port_str = str(info.get("crm_db_port") or "").strip()
    if not port_str:
        return None, "В компании не задан CRM DB port"
    try:
        int(port_str)
    except ValueError:
        return None, f"CRM DB port должен быть числом ({port_str!r})"
    if (info.get("crm_db_engine") or "mysql").lower() != "mysql":
        return None, f"Engine {info.get('crm_db_engine')} пока не поддержан"
    is_renewal: Optional[bool] = None
    if client_type:
        ct = client_type.strip().upper()
        if ct == "NEW":
            is_renewal = False
        elif ct == "REP":
            is_renewal = True
    try:
        phone = _mysql_find_phone_by_criteria(
            company, db_name,
            dpd=dpd, status_code=loan_status, is_renewal=is_renewal,
        )
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not phone:
        return None, "Не найден клиент по заданным условиям"
    return phone, None


def fetch_active_loan_phone_dpd90(
    company: Company,
) -> tuple[Optional[str], Optional[str]]:
    fn = ACTIVE_PHONE_DPD90_QUERIES.get(company.key)
    if not fn:
        return None, (
            f"DB-запрос (90+ DPD) не настроен для {company.key.rstrip('_')}"
        )
    info = load_raw().get(company.key, {})
    port_str = str(info.get("crm_db_port") or "").strip()
    if not port_str:
        return None, "В компании не задан CRM DB port"
    try:
        int(port_str)
    except ValueError:
        return None, f"CRM DB port должен быть числом ({port_str!r})"
    if (info.get("crm_db_engine") or "mysql").lower() == "postgres" and not (
        info.get("crm_db_name") or ""
    ):
        return None, "Для Postgres нужно указать crm_db_name"
    try:
        phone = fn(company)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not phone:
        return None, "Активный займ с 90+ DPD не найден"
    return phone, None


def fetch_active_loan_phone(company: Company) -> tuple[Optional[str], Optional[str]]:
    """Return (phone, error_message). On success error_message is None."""
    fn = ACTIVE_PHONE_QUERIES.get(company.key)
    if not fn:
        return None, (
            f"DB-запрос для поиска активного займа не настроен для {company.key.rstrip('_')}"
        )
    info = load_raw().get(company.key, {})
    port_str = str(info.get("crm_db_port") or "").strip()
    if not port_str:
        return None, "В компании не задан CRM DB port"
    try:
        port = int(port_str)
    except ValueError:
        return None, f"CRM DB port должен быть числом ({port_str!r})"
    if (info.get("crm_db_engine") or "mysql").lower() == "postgres" and not (
        info.get("crm_db_name") or ""
    ):
        return None, "Для Postgres нужно указать crm_db_name"
    try:
        phone = fn(company)
    except NotImplementedError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not phone:
        return None, "Активный незакрытый займ не найден"
    return phone, None


# ---------- HTTP test ----------

def call_crm_by_phone(
    crm_host: str,
    header_name: str,
    header_value: str,
    phone: str,
    timeout: float = 15.0,
) -> tuple[int, str, Optional[str]]:
    """GET against the CRM URL with `{phone}` substituted (or appended as
    `?phone=`). Returns (status_code, body_preview, error_message_or_None)."""
    if "{phone}" in crm_host:
        url = crm_host.replace("{phone}", phone)
    else:
        sep = "&" if "?" in crm_host else "?"
        url = f"{crm_host}{sep}phone={phone}"
    headers = {
        header_name: header_value,
        # Some prod CRMs (PE) sit behind Cloudflare and reject requests
        # without a real-looking User-Agent.
        "User-Agent": "AventusBotHub/1.0",
        "Accept": "*/*",
    }
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(2000).decode("utf-8", errors="replace")
            return r.getcode() or 0, body, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read(2000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return 0, "", f"Сеть: {e.reason}"
    except Exception as e:
        return 0, "", f"{type(e).__name__}: {e}"
