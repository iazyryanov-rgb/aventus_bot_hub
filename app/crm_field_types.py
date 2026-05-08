"""Internal semantic types for fields returned by each company's CRM
phone-lookup endpoint.

The keys are exactly the JSON keys we get back from `crm_host`. The values
are short namespaced slugs (`namespace.role`) that describe what the field
*means* in our domain, regardless of the project's naming. This is used in
the «Данные из CRM» tab to annotate the response.

There are two layers:
  1. The static `FIELD_TYPES_BY_COMPANY` defaults below — versioned in code.
  2. User overrides in `data/crm_field_types_overrides.json` — per-company
     dict edited from the UI; loaded each call. Overrides win.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import data_dir

# CO Credito365 — based on the live response shape (30 top-level keys).
CO_CREDITO365_FIELD_TYPES: dict[str, str] = {
    "amount":                  "loan.amount",
    "approved_amount":         "loan.approved_amount",
    "approved_term":           "loan.approved_term_days",
    "client_id":               "client.id",
    "client_name":             "client.full_name",
    "collector_id":            "collector.id",
    "discount_type":           "discount.type",
    "discount_valid_until":    "discount.valid_until",
    "discounted_payment_amount": "discount.payment_amount",
    "due_date":                "loan.due_date",
    "extension_amount":        "extension.amount",
    "flg_discount":            "discount.is_active",
    "flg_extension":           "extension.is_available",
    "guaranty":                "loan.guarantee_amount",
    "in_blacklist":            "client.in_blacklist",
    "is_blocked":              "client.is_blocked",
    "last_number_of_contract": "contract.last_number",
    "last_wa_template":        "comm.last_whatsapp_template",
    "link":                    "admin.loan_url",
    "loan_dpd":                "loan.days_past_due",
    "loan_id":                 "loan.id",
    "loan_type":               "loan.type",
    "outstanding_amount":      "loan.outstanding_amount",
    "payment_due_date":        "loan.payment_due_date",
    "pco_approved_amount":     "loan.pco_approved_amount",
    "short_link":              "admin.short_url",
    "status":                  "loan.status",
    "thread_id":               "comm.thread_id",
    "total_repayment_amount":  "loan.total_repayment_amount",
    "warmm_token":             "comm.wamm_token",
}


# CO2 TuParcero — тот же Aventus-движок что и CO. Реальный ответ live ещё
# не получили (auth токен в Postman заглушка), но схема почти наверняка
# идентичная. Мирорим CO; что разойдётся — поправим, когда увидим живой
# ответ.
CO2_TUPARCERO_FIELD_TYPES: dict[str, str] = dict(CO_CREDITO365_FIELD_TYPES)


# AR Lendi — на основе живого ответа от api.lendi.ar (45+ ключей).
# Уверенные маппинги; неуверенные оставлены пустыми и подцепятся вручную.
AR_LENDI_FIELD_TYPES: dict[str, str] = {
    "amount":                     "loan.amount",
    "client_id":                  "client.id",
    "client_full_name":           "client.full_name",
    "collector_id":               "collector.id",
    "discount_payment":           "discount.payment_amount",
    "discount_type":              "discount.type",
    "discount_valid_to":          "discount.valid_until",
    "dpd":                        "loan.days_past_due",
    "due_date":                   "loan.due_date",
    "extension_max_term":         "extension.max_term_days",
    "in_blacklist":               "client.in_blacklist",
    "is_blocked":                 "client.is_blocked",
    "link":                       "admin.user_url",
    "loan_id":                    "loan.id",
    "loan_link":                  "admin.loan_url",
    "loan_term":                  "loan.term_days",
    "loan_type":                  "loan.type",
    "max_approved_principal":     "loan.max_approved_principal",
    "max_approved_term":          "loan.max_approved_term_days",
    "short_link":                 "admin.short_url",
    "status":                     "loan.status",
    "user_id":                    "client.id",
    "user_link":                  "admin.user_url",
    "date_of_last_ptp":           "ptp.last_date",
    "last_ptp_amount":            "ptp.last_amount",
    "last_promise_type":          "ptp.last_type",
    "agent_id":                   "agent.id",
    "agent_id_ptp":               "agent.id_ptp",
    "application_id":             "application.id",
    "application_date":           "application.created_at",
    "application_due_date":       "application.due_date",
    "application_link":           "admin.application_url",
    "interest_amount":            "loan.interest_amount",
    "settlement_amount":          "loan.settlement_amount",
    "sequence_number":            "loan.sequence_number",
    "last_action_call_date":      "comm.last_call_date",
    "last_contact_call_type":     "comm.last_call_type",
    "last_contact_call_result":   "comm.last_call_result",
    "last_message":               "comm.last_message",
    # Не уверен — оставляем пусто, разберём вручную:
    #   bank_details_entered, extension_min_payment, extension_min_payment_text,
    #   promocode_amount, active_promocode, loan_debt, loan_debt_text
}


# PE Prestamo365 — на основе живого ответа от api.prestamo365.pe (вложенный
# `data.variables.*`). Лукап в get_field_type сначала пробует полный путь,
# потом «листовой» ключ — поэтому достаточно описать листовые имена.
# `status` на верхнем уровне не маппим: у PE это статус API ("ok"), а не
# статус займа. Чтобы не путаться, переменная `status` под `data.variables`
# тоже не попадёт сюда — у CO/AR `status=loan.status`, лукап на верхний
# уровень работает только для CO/AR (своя таблица).
PE_PRESTAMO365_FIELD_TYPES: dict[str, str] = {
    "agent_id":                   "agent.id",
    "agent_id_ptp":                "agent.id_ptp",
    "application_id":             "application.id",
    "application_link":           "admin.application_url",
    "commission_amount":          "loan.commission_amount",
    "date_of_last_ptp":           "ptp.last_date",
    "discount_payment":           "discount.payment_amount",
    "discount_type":              "discount.type",
    "discount_valid_to":          "discount.valid_until",
    "dpd":                        "loan.days_past_due",
    "extension_payment":          "extension.amount",
    "extension_payment_text":     "extension.amount_text",
    "interest_amount":            "loan.interest_amount",
    "last_infobip_template":      "comm.last_whatsapp_template",
    "last_ptp_amount":            "ptp.last_amount",
    "loan_id":                    "loan.id",
    "loan_link":                  "admin.loan_url",
    "loan_type":                  "loan.type",
    "max_approved_principal":     "loan.max_approved_principal",
    "max_approved_term":          "loan.max_approved_term_days",
    "registration_step":          "client.registration_step",
    "sequence_number":            "loan.sequence_number",
    "settlement_amount":          "loan.settlement_amount",
    "short_link":                 "admin.short_url",
    "thread_id":                  "comm.thread_id",
    "user_id":                    "client.id",
    "user_link":                  "admin.user_url",
    "user_name":                  "client.full_name",
    "wammchat_token":             "comm.wamm_token",
    # CIP (Código de Identificación de Pago) — перуанский платёжный код,
    # которым клиент платит через банки. Specific для PE.
    "CIP":              "cip.code",
    "CIP_amount":       "cip.amount",
    "CIP_created_at":   "cip.created_at",
    "CIP_valid_till":   "cip.valid_until",
    # Не уверен — оставляем пусто:
    #   loan_debt, loan_debt_text
}


FIELD_TYPES_BY_COMPANY: dict[str, dict[str, str]] = {
    "AR_":  AR_LENDI_FIELD_TYPES,
    "CO_":  CO_CREDITO365_FIELD_TYPES,
    "CO2_": CO2_TUPARCERO_FIELD_TYPES,
    "PE_":  PE_PRESTAMO365_FIELD_TYPES,
}


# Synthetic / non-CRM types: appear in the «выбор типа» dropdown even
# though no CRM-returned field is auto-mapped to them. Use cases — values
# the agent enters by hand (e.g. `partial.amount` for partial-payment promise).
EXTRA_KNOWN_TYPES: set[str] = {
    "partial.amount",
}


_INDEX_RE = re.compile(r"\[\d+\]")


def overrides_path() -> Path:
    return data_dir() / "crm_field_types_overrides.json"


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


def upsert_override(company_key: str, field_name: str, internal_type: str) -> None:
    """Set / clear a single field type override and persist to disk.
    Empty `internal_type` removes the override (returns to static default
    or no-mapping)."""
    data = load_all_overrides()
    cm = data.setdefault(company_key, {})
    if internal_type:
        cm[field_name] = internal_type
    else:
        cm.pop(field_name, None)
    if not cm:
        data.pop(company_key, None)
    save_all_overrides(data)


def merge_overrides(company_key: str, mapping: dict[str, str]) -> None:
    """Apply a batch of (field_name -> internal_type) overrides at once.
    Empty values clear the override for that field."""
    data = load_all_overrides()
    cm = data.setdefault(company_key, {})
    for field_name, internal_type in mapping.items():
        if internal_type:
            cm[field_name] = internal_type
        else:
            cm.pop(field_name, None)
    if not cm:
        data.pop(company_key, None)
    save_all_overrides(data)


def _lookup(table: dict[str, str], path: str) -> str:
    if path in table:
        return table[path]
    if "." in path:
        leaf = path.rsplit(".", 1)[-1]
        if leaf in table:
            return table[leaf]
    return ""


def get_field_type(company_key: str, field_path: str) -> str:
    """Return internal semantic slug for a CRM field, or '' if not mapped.

    Order: user overrides (data/crm_field_types_overrides.json) → static
    defaults (FIELD_TYPES_BY_COMPANY). Both tables tried with full path
    first, then leaf name fallback (handles nested responses like PE)."""
    if not field_path:
        return ""
    path = _INDEX_RE.sub("", field_path)
    overrides = load_all_overrides().get(company_key) or {}
    hit = _lookup(overrides, path)
    if hit:
        return hit
    static = FIELD_TYPES_BY_COMPANY.get(company_key) or {}
    return _lookup(static, path)


def lookup_value_by_type(company_key: str, payload, slug: str):
    """Walk the CRM payload (any nesting) and return the first value whose
    field path maps to the given internal `slug` (e.g. "loan.id"). Returns
    None if not found."""
    if not slug:
        return None

    def walk(obj, prefix: str = ""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, (dict, list)):
                    r = walk(v, key)
                    if r is not None:
                        return r
                elif get_field_type(company_key, key) == slug:
                    return v
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                r = walk(v, f"{prefix}[{i}]")
                if r is not None:
                    return r
        return None

    return walk(payload)


def all_known_types() -> list[str]:
    """All currently-defined internal type slugs (static + overrides +
    extras), sorted alphabetically. Used to populate the editor combobox."""
    types: set[str] = set(EXTRA_KNOWN_TYPES)
    for table in FIELD_TYPES_BY_COMPANY.values():
        types.update(table.values())
    for table in load_all_overrides().values():
        types.update(table.values())
    return sorted(t for t in types if t)
