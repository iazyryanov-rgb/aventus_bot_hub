"""Per-company POST-body schemas for registering communication results in CRM.

This module *describes* what each project expects in the body of
POST `crm_results_host`. It does NOT yet build/send the request — value
mapping (loan_id, contact_result, promise_*, etc.) will be wired later.

Auth comes from the same fields used for the GET-by-phone request:
    headers = { <crm_token_header>: <crm_access_token> }
The "from" user is `crm_bot_id` from companies.json (where the project's
schema needs the bot's CRM user id).

Body example (Postman-style) for CO Credito365 / CO2 TuParcero:
    {
      "loan_id": "704452",
      "collector_id": "138",
      "call_type": "action_type_whatsapp",
      "contact_type": "contact_type_client",
      "direction": "direction_incoming",
      "contact_result": "contact_result_promise_of_payment",
      "comment": "test",
      "phone_number": "573016614888",
      "promise_type": "promise_type_full_payment",
      "promise_date": "25.04.2026",
      "promise_amount": "100"
    }

Adding another company:
    1. Build a `<KEY>_BODY_FIELDS` list following the schema-field shape.
    2. Register it in `RESULT_BODY_SCHEMAS`.
"""
from __future__ import annotations

from typing import Optional


# ---------- field schema ----------
# Each field is a dict with:
#   name        — JSON key in the request body
#   type        — semantic hint ("string" / "integer" / "date" / ...)
#   example     — sample value (kept verbatim from production sample)
#   note        — optional human note (where the value should come from)


CO_CREDITO365_BODY_FIELDS: list[dict] = [
    {"name": "loan_id",        "type": "string", "example": "704452",
     "note": "loan.id у клиента, по которому записываем результат"},
    {"name": "collector_id",   "type": "string", "example": "138",
     "note": "id агента-коллектора в CRM (или crm_bot_id для бота)"},
    {"name": "call_type",      "type": "string", "example": "action_type_whatsapp",
     "note": "канал: action_type_whatsapp / action_type_call / ..."},
    {"name": "contact_type",   "type": "string", "example": "contact_type_client",
     "note": "contact_type_client / contact_type_third_party"},
    {"name": "direction",      "type": "string", "example": "direction_incoming",
     "note": "direction_incoming / direction_outgoing"},
    {"name": "contact_result", "type": "string", "example": "contact_result_promise_of_payment",
     "note": "результат: promise_of_payment / refusal / no_contact / ..."},
    {"name": "comment",        "type": "string", "example": "test",
     "note": "произвольный комментарий по диалогу"},
    {"name": "phone_number",   "type": "string", "example": "573016614888",
     "note": "номер телефона клиента, с международным префиксом"},
    {"name": "promise_type",   "type": "string", "example": "promise_type_full_payment",
     "note": "promise_type_full_payment / partial / extension"},
    {"name": "promise_date",   "type": "string", "example": "25.04.2026",
     "note": "дата обещания платежа DD.MM.YYYY"},
    {"name": "promise_amount", "type": "string", "example": "100",
     "note": "сумма обещанного платежа"},
]


# CO2 TuParcero использует тот же Aventus-движок и идентичную схему.
CO2_TUPARCERO_BODY_FIELDS: list[dict] = list(CO_CREDITO365_BODY_FIELDS)


# AR Lendi: формат отличается от CO — есть user_id и webitel_call_id, нет
# direction, comment мапится на history_uuid из Webitel-диалога. Названия в
# `note` — именно те placeholder-имена, которыми бот в Webitel помечает
# контекстные переменные (видны в payload запроса как ${name}).
AR_LENDI_BODY_FIELDS: list[dict] = [
    {"name": "loan_id",         "type": "string", "example": "${loan_id}",
     "note": "${loan_id} — id займа клиента"},
    {"name": "user_id",         "type": "string", "example": "${user_id}",
     "note": "${user_id} — id клиента в Lendi CRM"},
    {"name": "collector_id",    "type": "string", "example": "${collector_id}",
     "note": "${collector_id} — id агента-коллектора (или crm_bot_id для бота)"},
    {"name": "call_type",       "type": "string", "example": "${call_type}",
     "note": "${call_type} — тип канала коммуникации"},
    {"name": "phone_number",    "type": "string", "example": "${destination}",
     "note": "${destination} — номер клиента (whatsapp peer / dialed number)"},
    {"name": "contact_type",    "type": "string", "example": "${contact_type}",
     "note": "${contact_type} — кто на связи (клиент / третье лицо)"},
    {"name": "contact_result",  "type": "string", "example": "${result}",
     "note": "${result} — итог разговора"},
    {"name": "promise_type",    "type": "string", "example": "${promise_type}",
     "note": "${promise_type} — тип обещания платежа"},
    {"name": "promise_date",    "type": "string", "example": "${ptp_date}",
     "note": "${ptp_date} — дата обещания платежа DD.MM.YYYY"},
    {"name": "promise_amount",  "type": "string", "example": "${ptp_amount}",
     "note": "${ptp_amount} — сумма обещанного платежа"},
    {"name": "comment",         "type": "string", "example": "${history_uuid}",
     "note": "${history_uuid} — ссылка на историю диалога (uuid из Webitel-flow)"},
    {"name": "webitel_call_id", "type": "string", "example": "${uuid}",
     "note": "${uuid} — id звонка/диалога в Webitel"},
]


# PE Prestamo365 использует то же тело, что и AR Lendi (one-to-one).
PE_PRESTAMO365_BODY_FIELDS: list[dict] = list(AR_LENDI_BODY_FIELDS)


RESULT_BODY_SCHEMAS: dict[str, list[dict]] = {
    "AR_": AR_LENDI_BODY_FIELDS,
    "CO_": CO_CREDITO365_BODY_FIELDS,
    "CO2_": CO2_TUPARCERO_BODY_FIELDS,
    "PE_": PE_PRESTAMO365_BODY_FIELDS,
}


def get_body_schema(company_key: str) -> Optional[list[dict]]:
    """Return the body field list for a company (None if not yet defined)."""
    return RESULT_BODY_SCHEMAS.get(company_key)


def list_field_names(company_key: str) -> list[str]:
    """Just the keys that go into JSON, for quick checks / UI."""
    schema = get_body_schema(company_key)
    return [f["name"] for f in schema] if schema else []
