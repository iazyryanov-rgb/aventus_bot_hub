"""WhatsApp bot conversion funnel — champion vs candidate (Phase 2).

Считает воронку конверсии WA-бота для прод-канала рассылки в Infobip
(`sms.smsProvider='infobip-wa-mass'`), разбивая по двум руки A/B-теста:

  * champion  — пользователи, чей телефон НЕ попадает в
                `candidate_digits` (см. `router_schema._candidate_digits_for`)
  * candidate — те, чей телефон оканчивается на цифру из candidate-digits

Сплит совпадает с тем, как Webitel-router (schema id из
`bots.whatsapp.router_schema_id`) делит входящие чаты: JS-нода в
router-схеме читает последнюю цифру `${from.id}` и выбирает champion
или candidate. Поскольку логика детерминированная и зависит только от
телефона, мы её повторяем на стороне хаба — не нужно дёргать Webitel
chats и сшивать по timestamp.

Если у компании нет A/B (нет `candidate_schema_id` или router-схемы)
— возвращаем числа целиком в `champion`, `candidate.sent==0`.

Метрики на день (одни и те же для champion/candidate):
  * sent        — отправлено (sms.smsProvider='infobip-wa-mass',
                  status != 'error')
  * engaged     — уникальных userId с записью в communication_history
                  в течение 3 дней после отправки
  * extended    — уникальных userId с продлением (extension table) в
                  течение 7 дней после отправки
  * results     — строки communication_history после отправки
  * promises    — связанные обещания из collection_result_promise_to_pay
  * promise_full / promise_extension — разбивка по типу обещания
                  (по `tree_path_labels.itemLabel`:
                   {full_payment, promise_type_full_payment} → full,
                   {extension,    promise_type_extension}    → extension)
  * fulfilled_full / fulfilled_extension — выполненные обещания:
      - full:       SUM(income.income) по loan_id, income_date <=
                    promise.planned_at + 1 day, >= promised_amount
      - extension:  extension row для loanId с extensionDate <=
                    promise.planned_at + 1 day

Кэш 5 мин (per company_key + days). Live-refresh кнопкой в UI.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from . import db
from .data import Company


WA_MASS_PROVIDER = "infobip-wa-mass"
DEFAULT_DAYS = 14
CACHE_TTL_SEC = 300

# Per-company CRM database name. Источник правды — companies.json:crm_db_name
# (та же запись, что использует ``db.connect_for_company``). Карта ниже
# оставлена как fallback, если в companies.json ключ ещё не заполнен.
_MYSQL_DB_NAME = {
    "CO_":  "prod_credito365_api",
    "CO2_": "prod_tuparcero_api",
}


# Per-company action-tree filter for «бот-результат».
# `communication_history.tree_path_labels` — JSON-список нод; чтобы строка
# считалась как зарегистрированный ботом результат, хотя бы один из
# элементов должен совпадать со словарём ниже (matched по всем заданным
# ключам). Action tree различается между компаниями — для CO/CO2 бот
# помечает свои строки `direction=wa_bot_inbound`, у других тенантов
# может быть иначе, добавлять сюда по мере подключения.
_RESULT_FILTERS: dict[str, list[dict[str, str]]] = {
    "CO_":  [{"groupLabel": "direction", "itemLabel": "wa_bot_inbound"}],
    "CO2_": [{"groupLabel": "direction", "itemLabel": "wa_bot_inbound"}],
}


# Per-engine «как определить, что у клиента была WA-Infobip отправка». Для
# CO MySQL это `sms.smsProvider='infobip-wa-mass'`, для PE Postgres —
# `public.notification.transmitter='info_bip'` (подтверждено по
# admin.prestamo365.pe). Структура одинаковая, чтобы добавлять новые
# движки без переписывания SQL-функций.
_INFOBIP_RULES: dict[str, dict] = {
    "mysql": {
        "table": "sms",
        "transmitter_column": "smsProvider",
        "transmitter_value": WA_MASS_PROVIDER,
        "timestamp_column": "sendDate",
        "user_id_column": "userId",
        "status_column": "status",
        "status_error_value": "error",
        "user_table": "user",
        "user_phone_column": "main_phone_number",
    },
    "postgres": {
        # PE_ rule per CRM admin screenshot (2026-05-26): notification таблица
        # хранит все исходящие включая Infobip WhatsApp; столбец
        # `transmitter_id` — FK на справочник (label `info_bip` — это значение
        # в reference-таблице, не литерал в notification). Имя справочника
        # резолвится в рантайме через ``_resolve_pg_transmitter_id``.
        "table": "public.notification",
        "transmitter_column": "transmitter_id",
        "transmitter_label": "info_bip",  # значение в справочнике
        "timestamp_column": "created_at",
        "user_id_column": "user_id",
        # У PE notifications сам phone лежит прямо в `destination`, поэтому
        # JOIN на user не нужен для ARM-split.
        "destination_column": "destination",
    },
}


# ---------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------

@dataclass
class ArmMetrics:
    sent: int = 0
    engaged: int = 0
    extended: int = 0
    results: int = 0
    promises: int = 0
    promise_full: int = 0
    promise_extension: int = 0
    fulfilled_full: int = 0
    fulfilled_extension: int = 0

    def add(self, other: "ArmMetrics") -> None:
        self.sent += other.sent
        self.engaged += other.engaged
        self.extended += other.extended
        self.results += other.results
        self.promises += other.promises
        self.promise_full += other.promise_full
        self.promise_extension += other.promise_extension
        self.fulfilled_full += other.fulfilled_full
        self.fulfilled_extension += other.fulfilled_extension


@dataclass
class DayMetrics:
    date: date
    champion: ArmMetrics = field(default_factory=ArmMetrics)
    candidate: ArmMetrics = field(default_factory=ArmMetrics)


@dataclass
class FunnelReport:
    days: list[DayMetrics]
    total_champion: ArmMetrics = field(default_factory=ArmMetrics)
    total_candidate: ArmMetrics = field(default_factory=ArmMetrics)
    candidate_digits: tuple[int, ...] = ()
    champion_schema: Optional[tuple[int, str]] = None  # (id, name)
    candidate_schema: Optional[tuple[int, str]] = None
    error: Optional[str] = None
    fetched_at: Optional[datetime] = None


_CACHE: dict[tuple, tuple[float, FunnelReport]] = {}
_LOCK = threading.Lock()


def _cache_get(company_key: str, days: int) -> Optional[FunnelReport]:
    with _LOCK:
        v = _CACHE.get((company_key, days))
        if v and (time.time() - v[0]) < CACHE_TTL_SEC:
            return v[1]
    return None


def _cache_set(company_key: str, days: int, report: FunnelReport) -> None:
    with _LOCK:
        _CACHE[(company_key, days)] = (time.time(), report)


def invalidate(company_key: Optional[str] = None) -> None:
    """Drop the cache so the next compute_funnel call re-queries CRM."""
    with _LOCK:
        if company_key is None:
            _CACHE.clear()
        else:
            for k in list(_CACHE.keys()):
                if k[0] == company_key:
                    _CACHE.pop(k, None)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _db_name(company: Company) -> Optional[str]:
    """Resolve CRM DB name for funnel queries.

    Источник правды — companies.json:crm_db_name (тот же, что использует
    ``db.connect_for_company``). Если запись там пуста — fallback в
    локальный hardcoded `_MYSQL_DB_NAME` (исторически только CO_/CO2_).
    """
    from .data import load_raw
    info = load_raw().get(company.key) or {}
    name = str(info.get("crm_db_name") or "").strip()
    if name:
        return name
    return _MYSQL_DB_NAME.get(company.key) or None


def _db_engine(company: Company) -> str:
    """Возвращает 'mysql' | 'postgres' для компании. Дефолт — mysql,
    как и в ``db.connect_for_company``."""
    from .data import load_raw
    info = load_raw().get(company.key) or {}
    return (info.get("crm_db_engine") or "mysql").lower()


def _q(db_name: str, table: str) -> str:
    return f"`{db_name}`.`{table}`"


_PROMISE_TYPE_FULL = {"promise_type_full_payment", "full_payment"}
_PROMISE_TYPE_EXTENSION = {"promise_type_extension", "extension"}


def _parse_labels(labels_json):
    """Return list[dict] from comm_history.tree_path_labels JSON column."""
    if labels_json is None:
        return []
    if isinstance(labels_json, (bytes, bytearray)):
        labels_json = labels_json.decode("utf-8", errors="replace")
    if isinstance(labels_json, str):
        try:
            v = json.loads(labels_json)
        except json.JSONDecodeError:
            return []
    else:
        v = labels_json
    return v if isinstance(v, list) else []


def _classify_promise_type(labels_json) -> str:
    """'full' / 'extension' / 'other' по полю `tree_path_labels`."""
    for lab in _parse_labels(labels_json):
        if not isinstance(lab, dict):
            continue
        group = (lab.get("groupLabel") or "").strip().lower()
        if group and group != "promise_types":
            continue
        item = (lab.get("itemLabel") or "").strip().lower()
        if item in _PROMISE_TYPE_FULL:
            return "full"
        if item in _PROMISE_TYPE_EXTENSION:
            return "extension"
    return "other"


def _is_bot_result(labels_json, filters: list[dict[str, str]]) -> bool:
    """True если в tree_path_labels есть нода, совпадающая со всеми
    `(groupLabel, itemLabel)` парами хотя бы одного фильтра из списка.

    Для CO_/CO2_ фильтр — `{groupLabel='direction', itemLabel='wa_bot_inbound'}`.
    Любое совпадение → строку считаем «зарегистрированной ботом»."""
    if not filters:
        return False
    labels = _parse_labels(labels_json)
    for lab in labels:
        if not isinstance(lab, dict):
            continue
        for f in filters:
            if all(
                (lab.get(k) or "").strip().lower() == (v or "").strip().lower()
                for k, v in f.items()
            ):
                return True
    return False


def _ab_arm(phone: Optional[str], candidate_digits: set[str]) -> str:
    """'champion' / 'candidate' / 'unknown' по последней цифре телефона.

    Совпадает с router-схемой ([app/router_schema.py:_js_split_body](app/router_schema.py))
    — берёт `phone[-1]`, проверяет на принадлежность candidate_digits."""
    if not phone:
        return "unknown"
    last = phone.strip()[-1:]
    if not last.isdigit():
        return "unknown"
    return "candidate" if last in candidate_digits else "champion"


def _fetch_chats_by_phone(
    company: Company, days: int,
) -> dict[str, list[datetime]]:
    """Pull Webitel chats via Grafana Postgres for the lookback window and
    index them by `from_phone`. Returns {phone: [chat_started_dt, ...]}.

    Used to compute `engaged`: для конкретного юзера, получившего mass-WA
    нотификацию в день D, считаем его «engaged», если у нас есть хотя бы
    один Webitel-чат от его номера в окне [D, D+3 days].

    Если grafana не настроена (нет credentials в companies.json) или у
    компании нет WhatsApp-номеров — возвращаем пустой словарь, и engaged
    деградирует в 0. Метрики из CRM (results, extended, promises и т.д.)
    при этом считаются как обычно.
    """
    try:
        from . import grafana_pg
        from .wa_bot_config import get_owned_whatsapp_numbers
    except Exception:
        return {}
    if not grafana_pg.is_configured(company.key):
        return {}
    nums = get_owned_whatsapp_numbers(company.key)
    if not nums:
        return {}

    # Окно: от начала периода SMS до сегодня+3д (чат может прийти позже).
    today = date.today()
    since_dt = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    until_dt = datetime.combine(today + timedelta(days=3), datetime.max.time())
    since_ms = int(since_dt.timestamp() * 1000)
    until_ms = int(until_dt.timestamp() * 1000)

    try:
        chats = grafana_pg.list_chat_conversations(
            since_ms, until_ms,
            company_key=company.key,
            channel="whatsapp",
            whatsapp_numbers=nums,
            limit=10000,
        )
    except Exception:
        return {}

    by_phone: dict[str, list[datetime]] = {}
    for c in chats:
        phone = (c.get("from_phone") or "").strip()
        ts = c.get("created_at_ms") or 0
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            continue
        if not phone or ts_f <= 0:
            continue
        dt = datetime.fromtimestamp(ts_f / 1000.0)
        by_phone.setdefault(phone, []).append(dt)
    return by_phone


def _resolve_ab_config(company: Company) -> tuple[
    tuple[int, ...],
    Optional[tuple[int, str]],
    Optional[tuple[int, str]],
]:
    """Возвращает (candidate_digits, champion_schema, candidate_schema)."""
    try:
        from .router_schema import _candidate_digits_for, DEFAULT_CANDIDATE_DIGITS
        digits = tuple(_candidate_digits_for(company.key))
    except Exception:
        digits = (0, 1, 2)

    from .wa_bot_config import get_candidate_schema, get_prod_schema
    cname, cid = get_prod_schema(company.key)
    champ = (cid, cname or "") if cid else None
    ccname, ccid = get_candidate_schema(company.key)
    cand = (ccid, ccname or "") if ccid else None
    return digits, champ, cand


# ---------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------

def compute_funnel(
    company: Company,
    days: int = DEFAULT_DAYS,
    *,
    force: bool = False,
) -> FunnelReport:
    if not force:
        cached = _cache_get(company.key, days)
        if cached is not None:
            return cached

    db_name = _db_name(company)
    engine = _db_engine(company)
    digits, champ, cand = _resolve_ab_config(company)
    filters = _RESULT_FILTERS.get(company.key) or []
    chats_by_phone = _fetch_chats_by_phone(company, days)
    if not db_name:
        rep = FunnelReport(
            days=[],
            candidate_digits=digits,
            champion_schema=champ,
            candidate_schema=cand,
            error=(
                f"CRM DB name для {company.key} не настроен — заполни "
                f"`crm_db_name` в `data/companies.json`."
            ),
            fetched_at=datetime.now(),
        )
        _cache_set(company.key, days, rep)
        return rep

    if engine not in ("mysql", "postgres"):
        rep = FunnelReport(
            days=[],
            candidate_digits=digits,
            champion_schema=champ,
            candidate_schema=cand,
            error=(
                f"{company.key}: CRM engine `{engine}` не поддерживается "
                f"(пока только mysql / postgres). См. `app/wa_bot_overview.py`."
            ),
            fetched_at=datetime.now(),
        )
        _cache_set(company.key, days, rep)
        return rep

    today = date.today()
    start_dt = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())

    try:
        conn = db.connect_for_company(company)
    except Exception as exc:  # noqa: BLE001
        return FunnelReport(
            days=[],
            candidate_digits=digits,
            champion_schema=champ,
            candidate_schema=cand,
            error=f"DB connect: {exc}",
            fetched_at=datetime.now(),
        )

    try:
        if engine == "postgres":
            rep = _query_funnel_postgres(
                conn, start_dt, days,
                set(str(d) for d in digits),
                chats_by_phone,
            )
        else:
            rep = _query_funnel(
                conn, db_name, start_dt, days,
                set(str(d) for d in digits), filters,
                chats_by_phone,
            )
        rep.candidate_digits = digits
        rep.champion_schema = champ
        rep.candidate_schema = cand
    except Exception as exc:  # noqa: BLE001
        rep = FunnelReport(
            days=[],
            candidate_digits=digits,
            champion_schema=champ,
            candidate_schema=cand,
            error=f"query: {type(exc).__name__}: {exc}",
            fetched_at=datetime.now(),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    _cache_set(company.key, days, rep)
    return rep


def _query_funnel(
    conn,
    db_name: str,
    start_dt: datetime,
    days: int,
    candidate_digits_set: set[str],
    result_filters: list[dict[str, str]],
    chats_by_phone: dict[str, list[datetime]],
) -> FunnelReport:
    """Core SQL pipeline. Buckets per day × arm."""
    cur = conn.cursor()
    sms_t = _q(db_name, "sms")
    user_t = _q(db_name, "user")
    ch_t = _q(db_name, "communication_history")
    ptp_t = _q(db_name, "collection_result_promise_to_pay")
    ext_t = _q(db_name, "extension")
    loan_t = _q(db_name, "loan")
    income_t = _q(db_name, "income")

    # --- 1. Все отправки в окне -------------------------------------
    cur.execute(
        f"SELECT s.id, s.userId, s.sendDate, s.status, u.main_phone_number "
        f"FROM {sms_t} s "
        f"JOIN {user_t} u ON u.id = s.userId "
        f"WHERE s.smsProvider=%s AND s.sendDate >= %s "
        f"ORDER BY s.sendDate ASC",
        (WA_MASS_PROVIDER, start_dt),
    )
    sends: list[tuple] = list(cur.fetchall())
    # row: (sms_id, user_id, sendDate, status, phone)

    by_day: dict[date, DayMetrics] = {}
    user_arm: dict[int, str] = {}
    user_first_send: dict[int, datetime] = {}
    user_day: dict[int, date] = {}
    user_phone: dict[int, str] = {}

    for sms_id, user_id, send_date, status, phone in sends:
        d = send_date.date() if hasattr(send_date, "date") else send_date
        bucket = by_day.setdefault(d, DayMetrics(date=d))
        arm = _ab_arm(phone, candidate_digits_set)
        if (status or "").lower() != "error" and arm in ("champion", "candidate"):
            getattr(bucket, arm).sent += 1
        if (status or "").lower() == "error":
            continue
        if arm == "unknown":
            continue
        user_arm[user_id] = arm
        if user_id not in user_first_send or send_date < user_first_send[user_id]:
            user_first_send[user_id] = send_date
            user_day[user_id] = d
            user_phone[user_id] = (phone or "").strip()

    if not user_first_send:
        return _finalize(by_day, days)

    user_ids = list(user_first_send.keys())

    # --- 2. communication_history по userId после отправки ----------
    ch_by_user: dict[int, list[tuple]] = {}
    for chunk in _chunks(user_ids, 1000):
        ph = ",".join(["%s"] * len(chunk))
        cur.execute(
            f"SELECT ch.id, ch.user_id, ch.loan_id, ch.created_at, "
            f"       ch.tree_path_labels, ch.promise_amount, ch.promise_date "
            f"FROM {ch_t} ch "
            f"WHERE ch.user_id IN ({ph}) AND ch.created_at >= %s",
            (*chunk, start_dt),
        )
        for row in cur.fetchall():
            ch_id, uid, loan_id, created_at, labels, promise_amount, promise_date = row
            send_dt = user_first_send.get(uid)
            if send_dt is None:
                continue
            if created_at < send_dt:
                continue
            if created_at > send_dt + timedelta(days=3):
                continue
            # «Результат» = строка, помеченная как бот-инбаунд (action_tree
            # фильтр из `_RESULT_FILTERS`). Прочие строки (ручная работа
            # операторов после нотификации) в воронку не идут.
            if result_filters and not _is_bot_result(labels, result_filters):
                continue
            ch_by_user.setdefault(uid, []).append(
                (ch_id, loan_id, created_at, labels, promise_amount, promise_date)
            )

    # --- 3. extension по userId (через loan.userId) ----------------
    ext_by_user: dict[int, list[tuple]] = {}
    for chunk in _chunks(user_ids, 1000):
        ph = ",".join(["%s"] * len(chunk))
        cur.execute(
            f"SELECT l.userId, ext.loanId, ext.extensionDate, ext.price, ext.dateTo "
            f"FROM {ext_t} ext "
            f"JOIN {loan_t} l ON l.id = ext.loanId "
            f"WHERE l.userId IN ({ph}) AND ext.extensionDate >= %s",
            (*chunk, start_dt),
        )
        for uid, loan_id, ext_date, price, dateTo in cur.fetchall():
            send_dt = user_first_send.get(uid)
            if send_dt is None:
                continue
            if ext_date < send_dt or ext_date > send_dt + timedelta(days=7):
                continue
            ext_by_user.setdefault(uid, []).append(
                (loan_id, ext_date, price, dateTo)
            )

    # --- 4. Промисы ------------------------------------------------
    ch_ids: list[int] = [
        row[0] for rows in ch_by_user.values() for row in rows
    ]
    promises_by_ch: dict[int, list[tuple]] = {}
    if ch_ids:
        for chunk in _chunks(ch_ids, 1000):
            ph = ",".join(["%s"] * len(chunk))
            cur.execute(
                f"SELECT ptp.id, ptp.loan_id, ptp.planned_at, "
                f"       ptp.promised_amount, ptp.status, "
                f"       ptp.communication_history_id "
                f"FROM {ptp_t} ptp "
                f"WHERE ptp.communication_history_id IN ({ph})",
                tuple(chunk),
            )
            for row in cur.fetchall():
                ptp_id, loan_id, planned_at, amount, ptp_status, ch_id = row
                promises_by_ch.setdefault(ch_id, []).append(
                    (ptp_id, loan_id, planned_at, amount, ptp_status)
                )

    # --- 5. income (для проверки выполнения «полная оплата») -------
    promise_loan_ids = sorted({
        p[1] for ps in promises_by_ch.values() for p in ps if p[1] is not None
    })
    incomes_by_loan: dict[int, list[tuple]] = {}
    if promise_loan_ids:
        for chunk in _chunks(promise_loan_ids, 1000):
            ph = ",".join(["%s"] * len(chunk))
            cur.execute(
                f"SELECT loan_id, income_date, income, is_extend "
                f"FROM {income_t} "
                f"WHERE loan_id IN ({ph}) AND income_date >= %s",
                (*chunk, start_dt),
            )
            for loan_id, income_date, income_amount, is_extend in cur.fetchall():
                incomes_by_loan.setdefault(loan_id, []).append(
                    (income_date, float(income_amount or 0), int(is_extend or 0))
                )

    # ---------------------------------------------------------------
    # Aggregate per day × arm
    # ---------------------------------------------------------------
    for uid in user_ids:
        d = user_day[uid]
        arm = user_arm[uid]
        send_dt = user_first_send[uid]
        bucket = by_day.setdefault(d, DayMetrics(date=d))
        target: ArmMetrics = getattr(bucket, arm)

        # `engaged` — у пользователя есть Webitel-чат от его номера в окне
        # [sendDate, sendDate + 3 day]. Уникальный per (user, day) — один
        # юзер ↔ максимум 1 engaged-пойнт.
        phone = user_phone.get(uid) or ""
        if phone:
            chat_window_end = send_dt + timedelta(days=3)
            for chat_dt in chats_by_phone.get(phone) or []:
                if send_dt <= chat_dt <= chat_window_end:
                    target.engaged += 1
                    break

        ch_rows = ch_by_user.get(uid) or []
        if ch_rows:
            target.results += len(ch_rows)

        if ext_by_user.get(uid):
            target.extended += 1

        for ch_id, loan_id, created_at, labels, *_ in ch_rows:
            ptype = _classify_promise_type(labels)
            promises = promises_by_ch.get(ch_id) or []
            for ptp_id, p_loan_id, planned_at, amount, p_status in promises:
                target.promises += 1
                if ptype == "full":
                    target.promise_full += 1
                    if _full_fulfilled(p_loan_id, planned_at, amount, incomes_by_loan):
                        target.fulfilled_full += 1
                elif ptype == "extension":
                    target.promise_extension += 1
                    if _extension_fulfilled(p_loan_id, planned_at, ext_by_user, uid):
                        target.fulfilled_extension += 1

    return _finalize(by_day, days)


def _resolve_pg_transmitter_id(conn, label: str) -> int:
    """Найти целочисленный ``transmitter_id`` в PE reference-таблице по
    строковой метке (например ``info_bip``).

    PE-схема хранит трансмиттеры в отдельной таблице (имя в каталоге не
    зафиксировано); admin-UI отображает строковую метку через JOIN. Чтобы
    не гадать имя схемы/таблицы/колонки, бежим по information_schema:

    1. Находим все таблицы с именем ``transmitter`` (любой схемы), сортируем
       handbook → public → прочие.
    2. В каждой пробуем text-колонки в порядке вероятности (name, code,
       slug, label, key) — first match wins.
    3. Возвращаем id; если ничего не нашлось, кидаем ValueError с описанием.

    Postgres'овский catch: при первом же SQL-сбое транзакция уходит в
    aborted state — после каждой неудачной попытки делаем ``rollback()``.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name = 'transmitter'
            ORDER BY
                CASE table_schema
                    WHEN 'handbook' THEN 0
                    WHEN 'public'   THEN 1
                    ELSE 2
                END
            """
        )
        tables = list(cur.fetchall())
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    if not tables:
        raise ValueError(
            f"Не нашёл reference-таблицу `transmitter` ни в одной схеме "
            f"(нужно для resolving label '{label}' → transmitter_id). "
            "Сообщи имя справочника в _INFOBIP_RULES."
        )

    label_columns_priority = ("name", "code", "slug", "label", "key")

    for schema, table in tables:
        # Discover text columns in this candidate.
        try:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                  AND data_type IN ('character varying', 'text', 'citext')
                """,
                (schema, table),
            )
            text_cols = {r[0] for r in cur.fetchall()}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            continue

        for col in label_columns_priority:
            if col not in text_cols:
                continue
            try:
                cur.execute(
                    f'SELECT id FROM "{schema}"."{table}" '
                    f'WHERE "{col}" = %s LIMIT 1',
                    (label,),
                )
                row = cur.fetchone()
                if row:
                    return int(row[0])
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

    raise ValueError(
        f"Метка трансмиттера '{label}' не найдена ни в одной из "
        f"reference-таблиц: {tables}. Проверь имя метки в admin или "
        "укажи схему/колонку явно в _INFOBIP_RULES."
    )


def _query_funnel_postgres(
    conn,
    start_dt: datetime,
    days: int,
    candidate_digits_set: set[str],
    chats_by_phone: dict[str, list[datetime]],
) -> FunnelReport:
    """Postgres-flavoured funnel: на сейчас считаем только sent + engaged.

    Источник правды для отправок — `public.notification` с
    `transmitter='info_bip'` (правило подтверждено по admin.prestamo365.pe
    2026-05-26). Engagement-сигнал — Webitel `chats_by_phone` (cross-tenant,
    не зависит от CRM).

    Остальные ветки (results / promises / extensions / fulfilled) — TBD,
    пока пишут 0. Под них нужны правила:
      * как помечается «зарегистрированный ботом результат» в PE
        (`public.communication` + какое поле? action_tree id?);
      * связь communication → promise_to_pay (через какой FK?);
      * как помечается extension у loan'а (есть ли `loan.is_extended` /
        отдельная таблица extension в Postgres);
      * как matched `income.received_at ≤ promise_to_pay.promise_date + 1д`
        для full-payment fulfilled (`public.income` + `public.promise_to_pay`).

    SQL ниже использует только колонки, подтверждённые по UI screenshot:
    `id, user_id, created_at, delivery, destination, transmitter`.
    """
    rule = _INFOBIP_RULES["postgres"]
    transmitter_id = _resolve_pg_transmitter_id(conn, rule["transmitter_label"])
    cur = conn.cursor()

    cur.execute(
        f"SELECT id, {rule['user_id_column']}, {rule['timestamp_column']}, "
        f"       {rule['destination_column']} "
        f"FROM {rule['table']} "
        f"WHERE {rule['transmitter_column']} = %s "
        f"  AND {rule['timestamp_column']} >= %s "
        f"ORDER BY {rule['timestamp_column']} ASC",
        (transmitter_id, start_dt),
    )
    sends: list[tuple] = list(cur.fetchall())

    by_day: dict[date, DayMetrics] = {}
    user_first_send: dict[int, datetime] = {}
    user_phone: dict[int, str] = {}
    user_arm: dict[int, str] = {}

    for _send_id, user_id, send_date, destination in sends:
        if user_id is None:
            continue
        d = send_date.date() if hasattr(send_date, "date") else send_date
        bucket = by_day.setdefault(d, DayMetrics(date=d))
        arm = _ab_arm(destination, candidate_digits_set)
        if arm in ("champion", "candidate"):
            getattr(bucket, arm).sent += 1
        if arm == "unknown":
            continue
        user_arm[user_id] = arm
        if user_id not in user_first_send or send_date < user_first_send[user_id]:
            user_first_send[user_id] = send_date
            user_phone[user_id] = (destination or "").strip()

    # Engagement: Webitel chat в окне [send, send+3д] от phone клиента.
    # Mirror CO логики, у которой engagement не CRM-зависимый.
    for uid, phone in user_phone.items():
        arm = user_arm.get(uid)
        if arm not in ("champion", "candidate"):
            continue
        send_dt = user_first_send.get(uid)
        if not send_dt:
            continue
        d = send_dt.date() if hasattr(send_dt, "date") else send_dt
        bucket = by_day.setdefault(d, DayMetrics(date=d))
        for chat_dt in chats_by_phone.get(phone) or []:
            if send_dt <= chat_dt <= send_dt + timedelta(days=3):
                getattr(bucket, arm).engaged += 1
                break  # макс 1 engaged point per user

    return _finalize(by_day, days)


def _full_fulfilled(loan_id, planned_at, promised_amount, incomes_by_loan) -> bool:
    if loan_id is None or planned_at is None or promised_amount is None:
        return False
    deadline = planned_at + timedelta(days=1)
    total = 0.0
    for income_date, amount, _is_extend in incomes_by_loan.get(loan_id) or []:
        if income_date <= deadline:
            total += amount
    return total >= float(promised_amount)


def _extension_fulfilled(loan_id, planned_at, ext_by_user, uid) -> bool:
    if loan_id is None or planned_at is None:
        return False
    deadline = planned_at + timedelta(days=1)
    for ext_loan_id, ext_date, *_ in ext_by_user.get(uid) or []:
        if ext_loan_id == loan_id and ext_date <= deadline:
            return True
    return False


def _finalize(by_day: dict[date, DayMetrics], days: int) -> FunnelReport:
    today = date.today()
    rows: list[DayMetrics] = []
    for i in range(days):
        d = today - timedelta(days=i)
        rows.append(by_day.get(d) or DayMetrics(date=d))
    rows.sort(key=lambda r: r.date, reverse=True)

    total_c = ArmMetrics()
    total_k = ArmMetrics()
    for r in rows:
        total_c.add(r.champion)
        total_k.add(r.candidate)

    return FunnelReport(
        days=rows,
        total_champion=total_c,
        total_candidate=total_k,
        fetched_at=datetime.now(),
    )


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
