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


# Реальные типы ботов в приложении. Значения в ботовых ветках дерева
# (direction / phone / comment) ссылаются на эти ключи через поле
# `bot_kind`. При появлении нового типа бота — добавь сюда и в
# соответствующие values веток.
BOT_KINDS: dict[str, str] = {
    "whatsapp": "WhatsApp Infobip bot",
    "voice": "Voice Bot",
}


CO_CREDITO365_TREE = {
    "company_key": "CO_",
    "title": "Дерево действий — CO Credito365",
    # Несколько корневых ветвей рисуются друг под другом.
    "roots": [
        "contact_type", "loan_id", "collector_id", "call_type",
        "direction", "phone", "comment",
    ],
    "variables": {
        "contact_type": {
            "label": "Тип контакта (contact_type)",
            "produces": "contact_type",
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
            "produces": "contact_result",
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
            "produces": "contact_result",
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
            "produces": "promise_type",
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
            "produces": "promise_amount",
            "value_source": "",  # TBD — выбрать из всех известных типов
            "next_variable": "promise_date",
        },
        "promise_amount_partial": {
            "label": "Сумма обещания (promise_amount) — частичная оплата",
            "produces": "promise_amount",
            "value_source": "partial.amount",
            "next_variable": "promise_date",
        },
        "promise_amount_discount": {
            "label": "Сумма обещания (promise_amount) — скидка",
            "produces": "promise_amount",
            "value_source": "",  # TBD
            "next_variable": "promise_date",
        },
        "promise_amount_extension": {
            "label": "Сумма обещания (promise_amount) — пролонгация",
            "produces": "promise_amount",
            "value_source": "",  # TBD
            "next_variable": "promise_date",
        },
        "promise_date": {
            "label": "Дата обещания (promise_date)",
            "produces": "promise_date",
            "value_source": "user_input",
            "format_options": ["DD.MM.YYYY", "DD.MM.YYYY HH:mm"],
            "next_variable": None,
        },
        # ------- loan_id (своя ветка, общее значение для обоих ботов) -------
        "loan_id": {
            "label": "Loan ID — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "bot_kind": "whatsapp",
                    "next_variable": "loan_id_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "bot_kind": "voice",
                    "next_variable": "loan_id_value_voice",
                },
            ],
        },
        "loan_id_value_wa": {
            "label": "Значение loan_id для WhatsApp Infobip",
            "produces": "loan_id",
            "value_source": "loan.id",
            "next_variable": None,
        },
        "loan_id_value_voice": {
            "label": "Значение loan_id для Voice Bot",
            "produces": "loan_id",
            "value_source": "loan.id",
            "next_variable": None,
        },
        # ------- collector_id (берётся из company.crm_bot_id) -------
        "collector_id": {
            "label": "Collector ID — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "bot_kind": "whatsapp",
                    "next_variable": "collector_id_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "bot_kind": "voice",
                    "next_variable": "collector_id_value_voice",
                },
            ],
        },
        "collector_id_value_wa": {
            "label": "Значение collector_id для WhatsApp Infobip",
            "produces": "collector_id",
            "value_source": "company.crm_bot_id",
            "next_variable": None,
        },
        "collector_id_value_voice": {
            "label": "Значение collector_id для Voice Bot",
            "produces": "collector_id",
            "value_source": "company.crm_bot_id",
            "next_variable": None,
        },
        # ------- call_type (свободный текст по типу бота) -------
        "call_type": {
            "label": "Call Type — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "bot_kind": "whatsapp",
                    "next_variable": "call_type_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "bot_kind": "voice",
                    "next_variable": "call_type_value_voice",
                },
            ],
        },
        "call_type_value_wa": {
            "label": "Значение call_type для WhatsApp Infobip",
            "produces": "call_type",
            "value_source": "configured_text",
            "next_variable": None,
        },
        "call_type_value_voice": {
            "label": "Значение call_type для Voice Bot",
            "produces": "call_type",
            "value_source": "configured_text",
            "next_variable": None,
        },
        # ------- direction (своя ветка, не зависит от contact_type) -------
        # У значений ботовых веток (direction / phone / comment) есть поле
        # `bot_kind` — явная связь с реальным типом бота, заведённым в
        # приложении (см. BOT_KINDS ниже). Сейчас поддерживаются только
        # "whatsapp" (WhatsApp Infobip bot) и "voice" (Voice Bot).
        "direction": {
            "label": "Direction — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "bot_kind": "whatsapp",
                    "next_variable": "direction_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "bot_kind": "voice",
                    "next_variable": "direction_value_voice",
                },
            ],
        },
        "direction_value_wa": {
            "label": "Значение direction для WhatsApp Infobip",
            "produces": "direction",
            "value_source": "configured_text",
            "next_variable": None,
        },
        "direction_value_voice": {
            "label": "Значение direction для Voice Bot",
            "produces": "direction",
            "value_source": "configured_text",
            "next_variable": None,
        },
        # ------- phone (своя ветка, не зависит от contact_type) -------
        "phone": {
            "label": "Phone — по типу бота",
            "values": [
                {
                    "value": "wa_infobip",
                    "label": "WhatsApp Infobip",
                    "bot_kind": "whatsapp",
                    "next_variable": "phone_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "bot_kind": "voice",
                    "next_variable": "phone_value_voice",
                },
            ],
        },
        "phone_value_wa": {
            "label": "Значение phone_number для WhatsApp Infobip",
            "produces": "phone_number",
            "value_source": "configured_text",
            "next_variable": None,
        },
        "phone_value_voice": {
            "label": "Значение phone_number для Voice Bot",
            "produces": "phone_number",
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
                    "bot_kind": "whatsapp",
                    "next_variable": "comment_value_wa",
                },
                {
                    "value": "voice_bot",
                    "label": "Voice Bot",
                    "bot_kind": "voice",
                    "next_variable": "comment_value_voice",
                },
            ],
        },
        "comment_value_wa": {
            "label": "Значение comment для WhatsApp Infobip",
            "produces": "comment",
            "value_source": "configured_text",
            "next_variable": None,
        },
        "comment_value_voice": {
            "label": "Значение comment для Voice Bot",
            "produces": "comment",
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


# ---------- per-bot-kind readiness ----------

def _walk_with_bot_kind(
    tree_def: dict,
) -> dict[str, set[Optional[str]]]:
    """Return {variable_name: {bot_kind, ...}}. bot_kind is None for variables
    visited from a non-bot branch (i.e. shared between all bot kinds), or one
    of the keys in BOT_KINDS for variables reached through a bot-kind-specific
    value branch."""
    variables = tree_def.get("variables") or {}
    out: dict[str, set[Optional[str]]] = {}

    def walk(var_name: str, kind: Optional[str], visited: set[str]) -> None:
        if var_name in visited:
            return
        var_def = variables.get(var_name)
        if not var_def:
            return
        out.setdefault(var_name, set()).add(kind)
        visited = visited | {var_name}
        for val in var_def.get("values") or []:
            child_kind = val.get("bot_kind", kind)
            nxt = val.get("next_variable")
            if nxt:
                walk(nxt, child_kind, visited)
        nxt = var_def.get("next_variable")
        if nxt:
            walk(nxt, kind, visited)

    roots = list(tree_def.get("roots") or [])
    if not roots:
        single = tree_def.get("root")
        if single:
            roots = [single]
    for root_var in roots:
        walk(root_var, None, set())
    return out


def _is_var_filled(company_key: str, var_name: str, var_def: dict) -> bool:
    """True if the variable has a usable value definition, considering
    overrides. Asking variables (with `values`) are filled when at least one
    value is defined."""
    if "values" in var_def:
        return bool(var_def.get("values"))
    if "value_source" not in var_def:
        return False
    static = var_def.get("value_source")
    src = get_value_source(company_key, var_name, static)
    if not src:
        return False
    if src == "configured_text":
        return bool(get_configured_text(company_key, var_name))
    return True


def enumerate_main_paths(
    tree_def: dict, root_var: str = "contact_type",
) -> list[list[tuple[str, Optional[dict]]]]:
    """Walk the asking subtree starting at `root_var` and return every
    leaf path. Each path is a list of (variable_name, chosen_value_dict).
    For filling variables encountered along the way, chosen_value_dict is
    None (they pass through but contribute via `produces` at body-build
    time)."""
    variables = tree_def.get("variables") or {}
    out: list[list[tuple[str, Optional[dict]]]] = []

    def walk(var_name: Optional[str], path: list[tuple[str, Optional[dict]]]) -> None:
        if not var_name:
            out.append(list(path))
            return
        var_def = variables.get(var_name)
        if not var_def:
            out.append(list(path))
            return
        if "values" in var_def:
            for v in var_def.get("values") or []:
                walk(v.get("next_variable"), path + [(var_name, v)])
        else:
            walk(var_def.get("next_variable"), path + [(var_name, None)])

    walk(root_var, [])
    return out


def dot_lookup(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def resolve_value_source(
    company_key: str,
    var_name: str,
    var_def: dict,
    crm_payload: Optional[dict],
    company_info: Optional[dict] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve the effective value for a filling variable. Returns
    (value_string, error_message). value_string=None with error=None means
    the variable is intentionally empty (e.g. user_input not yet known)."""
    static = var_def.get("value_source")
    src = get_value_source(company_key, var_name, static)
    if not src:
        return None, "источник не задан"
    if src == "configured_text":
        v = get_configured_text(company_key, var_name)
        if not v:
            return None, "configured_text пуст"
        return v, None
    if src == "user_input":
        return None, None
    if src.startswith("company."):
        if company_info is None:
            return None, f"company-info недоступна для '{src}'"
        key = src.split(".", 1)[1]
        v = company_info.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            return None, f"company.{key} не задан"
        return str(v), None
    # Otherwise: `src` is an internal-type slug (e.g. "loan.id"). Look it up
    # via the company's CRM-field-type mapping (handles flat and nested
    # responses uniformly).
    if crm_payload is None:
        return None, f"CRM payload не получен для '{src}'"
    from .crm_field_types import lookup_value_by_type
    v = lookup_value_by_type(company_key, crm_payload, src)
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, f"в CRM-ответе нет поля типа '{src}'"
    return str(v), None


def compute_readiness(
    company_key: str,
    tree_def: dict,
    field_names: list[str],
) -> dict[str, dict[str, str]]:
    """For each body field, compute per-bot-kind status.

    Returns: {field_name: {bot_kind: status}} where status ∈
        - "ok"        — all producing variables for that bot kind are filled
        - "missing"   — some producing variable for that bot kind is empty
        - "no_tree"   — the tree has no variable producing this field
    """
    visits = _walk_with_bot_kind(tree_def)
    variables = tree_def.get("variables") or {}
    # field -> [(var_name, kinds_visited_under), ...]
    producers: dict[str, list[tuple[str, set[Optional[str]]]]] = {}
    for var_name, var_def in variables.items():
        prod = var_def.get("produces")
        if not prod:
            continue
        kinds = visits.get(var_name) or set()
        producers.setdefault(prod, []).append((var_name, kinds))

    result: dict[str, dict[str, str]] = {}
    for field in field_names:
        prods = producers.get(field) or []
        per_kind: dict[str, str] = {}
        for kind in BOT_KINDS:
            relevant = [
                (vn, var_kinds)
                for vn, var_kinds in prods
                if (None in var_kinds) or (kind in var_kinds)
            ]
            if not relevant:
                per_kind[kind] = "no_tree"
                continue
            all_ok = all(
                _is_var_filled(company_key, vn, variables[vn])
                for vn, _ in relevant
            )
            per_kind[kind] = "ok" if all_ok else "missing"
        result[field] = per_kind
    return result


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
