"""Action trees per company — hierarchical decision tree describing how to
fill the variables we POST back to CRM as a communication result.

The root variable is asked first. Each value can specify a `next_variable`
that should be asked next, branching the path. A `None` next means we've
reached a leaf for that branch (still TBD or "ничего больше не нужно").

Goal: traversing the tree to a leaf populates all of the project's
result-body fields (see `crm_results.RESULT_BODY_SCHEMAS`).

Two kinds of variables:

  * "asking": has `values` — user picks one. Each `value` can have its own
    `next_variable`, branching the path.

  * "filling": has `value_source` — value is auto-derived (a CRM internal
    type slug from `crm_field_types`, or the literal `user_input`).
    Optionally a filling variable can declare `format_options` — a list of
    strings the user can cycle through with a double-click on the row;
    the active choice persists in `data/action_tree_overrides.json`.

Schema of an entry:
    {
      "company_key": "<KEY>",
      "title": "...",
      "root": "<variable name>",
      "variables": {
        "<variable name>": { ... asking | filling ... },
      },
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .paths import data_dir


CO_CREDITO365_TREE = {
    "company_key": "CO_",
    "title": "Дерево действий — CO Credito365",
    # Несколько корневых ветвей рисуются друг под другом.
    "roots": ["contact_type", "direction", "comment"],
    "variables": {
        "contact_type": {
            "label": "Тип контакта (contact_type)",
            "values": [
                {
                    "value": "contact_type_client",
                    "label": "Клиент",
                    "next_variable": "contact_result_client",
                },
                {
                    "value": "third_party_contact",
                    "label": "Третье лицо",
                    "next_variable": "contact_result_third_party",
                },
            ],
        },
        "contact_result_client": {
            "label": "Результат контакта (contact_result) — клиент",
            "values": [
                {
                    "value": "contact_result_promise_of_payment",
                    "label": "Обещание оплаты",
                    "next_variable": "promise_type",
                },
                {
                    "value": "contact_result_refusal_to_pay",
                    "label": "Отказ платить",
                    "next_variable": None,
                },
                {
                    "value": "contact_result_already_payed",
                    "label": "Уже оплачено",
                    "next_variable": None,
                },
                {
                    "value": "contact_result_ptp_follow_up",
                    "label": "PTP follow-up",
                    "next_variable": None,
                },
                {
                    "value": "customer_with_current_agreement",
                    "label": "Клиент с действующим соглашением",
                    "next_variable": None,
                },
                {
                    "value": "contact_result_paid_after_wa",
                    "label": "Оплатил после WhatsApp",
                    "next_variable": None,
                },
                {
                    "value": "anomaly_case",
                    "label": "Аномальный случай",
                    "next_variable": None,
                },
            ],
        },
        "contact_result_third_party": {
            "label": "Результат контакта (contact_result) — третье лицо",
            "values": [
                {
                    "value": "contact_result_provided_client_contact_info",
                    "label": "Передал контакты клиента",
                    "next_variable": None,
                },
                {
                    "value": "contact_result_refusal_to_transfer_information",
                    "label": "Отказался передавать информацию",
                    "next_variable": None,
                },
                {
                    "value": "anomaly_case",
                    "label": "Аномальный случай",
                    "next_variable": None,
                },
            ],
        },
        "promise_type": {
            "label": "Тип обещания (promise_type)",
            "values": [
                {
                    "value": "promise_type_full_payment",
                    "label": "Полная оплата",
                    "next_variable": "promise_amount_full",
                },
                {
                    "value": "promise_type_partial_payment",
                    "label": "Частичная оплата",
                    "next_variable": "promise_amount_partial",
                },
                {
                    "value": "promise_type_discount",
                    "label": "Со скидкой",
                    "next_variable": "promise_amount_discount",
                },
                {
                    "value": "promise_type_extension",
                    "label": "Пролонгация",
                    "next_variable": "promise_amount_extension",
                },
            ],
        },
        # Сумма promise_amount берётся из конкретной переменной типа CRM.
        # Исходник может быть переопределён вручную позже — поле value_source
        # содержит наш внутренний slug из crm_field_types.
        "promise_amount_full": {
            "label": "Сумма обещания (promise_amount) — полная оплата",
            "value_source": "",  # TBD — выбрать из всех известных типов
            "next_variable": "promise_date",
        },
        "promise_amount_partial": {
            "label": "Сумма обещания (promise_amount) — частичная оплата",
            "value_source": "partial.amount",
            "next_variable": "promise_date",
        },
        "promise_amount_discount": {
            "label": "Сумма обещания (promise_amount) — скидка",
            "value_source": "",  # TBD
            "next_variable": "promise_date",
        },
        "promise_amount_extension": {
            "label": "Сумма обещания (promise_amount) — пролонгация",
            "value_source": "",  # TBD
            "next_variable": "promise_date",
        },
        "promise_date": {
            "label": "Дата обещания (promise_date)",
            "value_source": "user_input",
            "format_options": ["DD.MM.YYYY", "DD.MM.YYYY HH:mm"],
            "next_variable": None,
        },
        # ------- direction (своя ветка, не зависит от contact_type) -------
        "direction": {
            "label": "Direction — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "next_variable": "direction_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "next_variable": "direction_value_voice",
                },
            ],
        },
        "direction_value_wa": {
            "label": "Значение direction для WhatsApp Infobip",
            "value_source": "configured_text",
            "next_variable": None,
        },
        "direction_value_voice": {
            "label": "Значение direction для Voice Bot",
            "value_source": "configured_text",
            "next_variable": None,
        },
        # ------- comment (тоже своя ветка) -------
        "comment": {
            "label": "Comment — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "next_variable": "comment_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "next_variable": "comment_value_voice",
                },
            ],
        },
        "comment_value_wa": {
            "label": "Значение comment для WhatsApp Infobip",
            "value_source": "configured_text",
            "next_variable": None,
        },
        "comment_value_voice": {
            "label": "Значение comment для Voice Bot",
            "value_source": "configured_text",
            "next_variable": None,
        },
    },
}


ACTION_TREES: dict[str, dict] = {
    "CO_": CO_CREDITO365_TREE,
    # CO2_, AR_, PE_ — будут описаны отдельно по мере получения веток.
}


def get_tree(company_key: str) -> Optional[dict]:
    return ACTION_TREES.get(company_key)


# ---------- format-choice overrides (e.g. promise_date format) ----------

def overrides_path() -> Path:
    return data_dir() / "action_tree_overrides.json"


def load_all_overrides() -> dict:
    p = overrides_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_all_overrides(data: dict) -> None:
    p = overrides_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def get_format_choice(
    company_key: str, variable: str, default: str
) -> str:
    co = (load_all_overrides().get(company_key) or {})
    return co.get(f"{variable}.format") or default


def set_format_choice(company_key: str, variable: str, value: str) -> None:
    data = load_all_overrides()
    cm = data.setdefault(company_key, {})
    cm[f"{variable}.format"] = value
    if not cm:
        data.pop(company_key, None)
    save_all_overrides(data)


def get_value_source(
    company_key: str, variable: str, default: Optional[str]
) -> Optional[str]:
    """Override-aware lookup. Distinguishes between an unset override
    (return default) and an explicit empty string saved by the user
    (return '' meaning «не задано»)."""
    co = load_all_overrides().get(company_key) or {}
    key = f"{variable}.value_source"
    if key in co:
        return co[key]
    return default


def set_value_source(
    company_key: str, variable: str, value: Optional[str]
) -> None:
    data = load_all_overrides()
    cm = data.setdefault(company_key, {})
    if value is None:
        cm.pop(f"{variable}.value_source", None)
    else:
        cm[f"{variable}.value_source"] = value
    if not cm:
        data.pop(company_key, None)
    save_all_overrides(data)


def get_configured_text(company_key: str, variable: str) -> str:
    """Free-text value the user typed for a `configured_text` filling
    variable. Empty string means «не задано»."""
    co = load_all_overrides().get(company_key) or {}
    return co.get(f"{variable}.value") or ""


def set_configured_text(company_key: str, variable: str, value: str) -> None:
    data = load_all_overrides()
    cm = data.setdefault(company_key, {})
    if value:
        cm[f"{variable}.value"] = value
    else:
        cm.pop(f"{variable}.value", None)
    if not cm:
        data.pop(company_key, None)
    save_all_overrides(data)
