"""WA-bot configuration per company.

Source of truth для логики и промптов WhatsApp-Infobip-бота. Bot Hub
читает/правит этот конфиг, потом отдельный «apply»-шаг (придёт позже)
будет переписывать соответствующие узлы Webitel-схемы при выкатке нового
билда.

Config persisted to `data/wa_bot_config/<COMPANY_KEY>.json`.
"""
from __future__ import annotations

import json
from typing import Optional

from .data import load_raw, save_raw
from .paths import data_dir


GATEWAY_NAME = "WhatsApp-Infobip"


# ---------- per-company seeds ----------

CO_CRM_LOOKUP_VARS: list[dict] = [
    {"local": "collector_id",          "remote": "collector_id"},
    {"local": "link",                  "remote": "link"},
    {"local": "client_id",             "remote": "client_id"},
    {"local": "dpd",                   "remote": "dpd"},
    {"local": "amount",                "remote": "outstanding_amount"},
    {"local": "ptp_date",              "remote": "ptp_date"},
    {"local": "ptp_status",            "remote": "ptp_status"},
    {"local": "ptp_amount",            "remote": "ptp_amount"},
    {"local": "loan_id",               "remote": "loan_id"},
    {"local": "discount_valid_to",     "remote": "discount_valid_until"},
    {"local": "discounted_payment",    "remote": "discounted_payment_amount"},
    {"local": "discount_type",         "remote": "discount_type"},
    {"local": "extension_min_payment", "remote": "extension_amount"},
    {"local": "loan_type",             "remote": "loan_type"},
    {"local": "client_full_name",      "remote": "client_name"},
    {"local": "last_wa_template",      "remote": "last_wa_template"},
    {"local": "short_link",            "remote": "short_link"},
    {"local": "status",                "remote": "status"},
]


CO_RESULT_BODY_FIELDS: list[dict] = [
    {"key": "loan_id",        "value": "${loan_id}"},
    {"key": "collector_id",   "value": "${collector_id}"},
    {"key": "call_type",      "value": "${crm_call_type}"},
    {"key": "contact_type",   "value": "${contact_type}"},
    {"key": "direction",      "value": "direction_incoming"},
    {"key": "contact_result", "value": "${contact_result}"},
    {"key": "comment",        "value": "${chat_log}"},
    {"key": "phone_number",   "value": "${destination}"},
    {"key": "promise_type",   "value": "${promise_type}"},
    {"key": "promise_date",   "value": "${promise_date}"},
    {"key": "promise_amount", "value": "${promise_amount}"},
]


# Прод-промпт CO_ (вытащено из ноды set 54239123f8c944b3 в схеме).
CO_MAIN_PROMPT = """General response requirements

Always return only one plain text response.

Role and context

You speak exclusively Spanish.
You act as an employee of the Crédito 365 debt collection operator (not as a virtual assistant).
If there was already a message from an operator in the conversation, do not greet the client again.

Objective

The main objective is to obtain a promise to pay.
You must act in a persistent and intrusive manner, without rudeness or insults.
If you are not sure the promise to pay will be fulfilled, try to obtain the date and the amount of the promise.
If the interlocutor uses the words "Today or tomorrow", then we directly understand this as the payment date.
If the interlocutor says they will pay the full closing amount, it means we have received information about the payment amount. The result of the communication received in the event will be a full payment promise.
If the interlocutor says they will pay to extend the term, it means we have received information about the payment amount. The result of the communication received in the function will be a renewal promise.

Target dialogue outcomes

Full payment promise – The client provides the payment date and amount.
Renewal promise (extension): the client promises to pay the amount for the renewal.

Promise to Pay Rules

If the client understands the date and amount of their promise to pay and wants to close the loan, this is a full payment promise.
The available promise to pay timeframe is determined by the dates available for the promise to pay ${cur_dt} and ${tomorrow_dt}
If the client understands the date and amount of the promise to pay and wants to extend the loan payment term, this is an extension promise
"""


CO_SECONDARY_PROMPT = """Style rules:
- Always respond in Spanish (natural professional tone)
- Keep responses concise, natural, ready to send
- No markdown, no formatting, no links
- Do not invent data
- If critical info is missing -> offer transfer to human agent

If client insists on human -> call connect_to_agent
If conversation ends -> call return_final_status
"""


CO_GPT_FUNCTIONS: list[dict] = [
    {
        "name": "return_final_status",
        "description": (
            "When the client has said goodbye, the issue is resolved, or "
            "you need to register the outcome of this turn, return the "
            "conversation result and classification."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_response": {
                    "type": "string",
                    "description": "Short plain-text line suitable to send to the client in this turn (or empty if not applicable).",
                },
                "isFinal": {
                    "type": "boolean",
                    "description": "True if the client's interaction has ended for this conversation.",
                },
                "contact_type": {
                    "type": "string",
                    "enum": ["contact_type_client", "third_party_contact"],
                    "description": "Whether the conversation was with the client or with a third party.",
                },
                "contact_result": {
                    "type": "string",
                    "enum": [
                        "contact_result_promise_of_payment",
                        "contact_result_refusal_to_pay",
                        "contact_result_already_payed",
                        "contact_result_ptp_follow_up",
                        "customer_with_current_agreement",
                        "contact_result_paid_after_wa",
                        "contact_result_provided_client_contact_info",
                        "contact_result_refusal_to_transfer_information",
                        "other",
                    ],
                },
                "promise_type": {
                    "type": "string",
                    "enum": [
                        "promise_type_full_payment",
                        "promise_type_partial_payment",
                        "promise_type_discount",
                        "promise_type_extension",
                        "no_promise",
                    ],
                },
                "promise_date": {"type": "string", "description": "DD.MM.YYYY"},
                "promise_amount": {"type": "string"},
            },
            "required": ["contact_type", "contact_result"],
        },
    },
    {
        "name": "connect_to_agent",
        "description": (
            "Call when the client insists on speaking with a human, or you "
            "cannot handle the request safely (legal threats, complaints, "
            "unclear identity)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short reason for handover.",
                }
            },
            "required": [],
        },
    },
]


# Builder defaults — настройки для генерации тела запроса в OpenAI
# Responses API. Совпадает со схемой webitel-бота.
DEFAULT_BUILDER = {
    "endpoint": "/v1/responses",
    "model": "gpt-4.1-mini",
    "conversation_var": "${conv_id}",
    "client_content_template": (
        "PROMISE_DATE_TODAY=${cur_dt}\n"
        "PROMISE_DATE_TOMORROW=${tomorrow_dt}\n"
        "\n"
        "Client data:\n"
        "  dpd - ${dpd}\n"
        "  amount - $ ${amount} ${currency_index}\n"
        "  ptp_date - ${ptp_date}\n"
        "  ptp_status - ${ptp_status}\n"
        "  ptp_amount - ${ptp_amount}\n"
        "  loan_id - ${loan_id}\n"
        "  extension_min_payment - ${extension_min_payment}\n"
        "  discount_valid_to - ${discount_valid_to}\n"
        "  discount_payment - ${discount_payment}\n"
        "  discount_type - ${discount_type}\n"
        "  short_link - ${short_link}\n"
        "  loan_term - ${loan_term}\n"
        "  loan_type - ${loan_type}\n"
        "  client_full_name - ${client_full_name}\n"
        "  status - ${status}"
    ),
    "user_message_var": "${client_question}",
    "tool_choice": "auto",
    "tool_choice_function": "",
    "temperature": 0.5,
    "top_p": 1.0,
    "max_output_tokens": 600,
    "store": True,
    "parallel_tool_calls": False,
    "strict_tools": False,
}


SEEDS: dict[str, dict] = {
    "CO_": {
        "gateway_name": GATEWAY_NAME,
        "crm_lookup_url": "https://api.credito365.co/api/partner/webitel/client-info?phone={user}",
        "crm_lookup_vars": CO_CRM_LOOKUP_VARS,
        "result_post_url": "https://api.credito365.co/api/partner/webitel/robot_phone_result_v2",
        "result_post_fields": CO_RESULT_BODY_FIELDS,
        "gpt": {
            "model": "gpt-4.1-mini",
            "main_prompt": CO_MAIN_PROMPT,
            "secondary_prompt": CO_SECONDARY_PROMPT,
            "functions": CO_GPT_FUNCTIONS,
            "builder": dict(DEFAULT_BUILDER),
        },
    },
}


def _apply_enum_meta(params: dict, enum_meta: dict) -> None:
    """In-place: filter enum values by enabled flag and append per-value
    descriptions to each property's `description` field."""
    props = (params or {}).get("properties") or {}
    if not isinstance(props, dict):
        return
    for prop_name, prop_def in props.items():
        if not isinstance(prop_def, dict):
            continue
        values = prop_def.get("enum")
        if not isinstance(values, list) or not values:
            continue
        meta = enum_meta.get(prop_name) or {}
        if not isinstance(meta, dict):
            continue
        kept = [
            v for v in values
            if (meta.get(v) or {}).get("enabled", True)
        ]
        # If the user disabled everything, keep the original list to avoid
        # an invalid empty enum.
        if kept:
            prop_def["enum"] = kept
        else:
            kept = list(values)

        lines = []
        for v in kept:
            d = (meta.get(v) or {}).get("description")
            if d:
                lines.append(f"- {v}: {d}")
        if lines:
            base = (prop_def.get("description") or "").rstrip()
            sep = "\n\n" if base else ""
            prop_def["description"] = base + sep + "\n".join(lines)


def build_request_body(cfg: dict) -> dict:
    """Build a complete OpenAI Responses API request body from the saved
    company config. Following https://platform.openai.com/docs/api-reference/responses/create.

    Body shape:
      - model
      - input[]: developer-role message (main_prompt + client_content + secondary_prompt)
                 + user-role message (placeholder for live client_question)
      - tools[]: flat function specs (Responses API style)
      - tool_choice
      - conversation (optional — hooks into stateful Conversations API)
      - temperature, top_p, max_output_tokens, store, parallel_tool_calls
    """
    gpt = cfg.get("gpt") or {}
    b = {**DEFAULT_BUILDER, **(gpt.get("builder") or {})}

    main = (gpt.get("main_prompt") or "").rstrip()
    secondary = (gpt.get("secondary_prompt") or "").rstrip()
    client_content = (b.get("client_content_template") or "").rstrip()
    parts = [p for p in (main, client_content, secondary) if p]
    developer_text = "\n\n".join(parts)

    body: dict = {
        "model": b.get("model") or "gpt-4.1-mini",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": developer_text,
            },
            {
                "type": "message",
                "role": "user",
                "content": b.get("user_message_var") or "${client_question}",
            },
        ],
    }

    conv = (b.get("conversation_var") or "").strip()
    if conv:
        body["conversation"] = conv

    fns_all = gpt.get("functions") or []
    fns = [f for f in fns_all if f.get("enabled", True)]
    if fns:
        tools = []
        for fn in fns:
            params = json.loads(json.dumps(
                fn.get("parameters") or {"type": "object", "properties": {}}
            ))
            _apply_enum_meta(params, fn.get("enum_descriptions") or {})
            tool: dict = {
                "type": "function",
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "parameters": params,
            }
            if b.get("strict_tools"):
                tool["strict"] = True
            tools.append(tool)
        body["tools"] = tools

        choice_kind = (b.get("tool_choice") or "auto").lower()
        if choice_kind == "function":
            fname = (b.get("tool_choice_function") or "").strip()
            if fname:
                body["tool_choice"] = {"type": "function", "name": fname}
        elif choice_kind in ("auto", "required", "none"):
            body["tool_choice"] = choice_kind

    if b.get("parallel_tool_calls") is not None and fns:
        body["parallel_tool_calls"] = bool(b.get("parallel_tool_calls"))

    try:
        body["temperature"] = float(b.get("temperature"))
    except (TypeError, ValueError):
        pass
    try:
        body["top_p"] = float(b.get("top_p"))
    except (TypeError, ValueError):
        pass
    try:
        mot = int(b.get("max_output_tokens"))
        if mot > 0:
            body["max_output_tokens"] = mot
    except (TypeError, ValueError):
        pass
    if b.get("store") is not None:
        body["store"] = bool(b.get("store"))

    return body


# ---------- persistence ----------

def config_path(company_key: str):
    return data_dir() / "wa_bot_config" / f"{company_key}.json"


def load_config(company_key: str) -> dict:
    p = config_path(company_key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    # Fallback to seed.
    seed = SEEDS.get(company_key)
    if seed:
        return json.loads(json.dumps(seed))  # deep copy
    return {
        "gateway_name": GATEWAY_NAME,
        "crm_lookup_url": "",
        "crm_lookup_vars": [],
        "result_post_url": "",
        "result_post_fields": [],
        "gpt": {
            "model": "",
            "main_prompt": "",
            "secondary_prompt": "",
            "functions": [],
        },
    }


def save_config(company_key: str, cfg: dict) -> None:
    p = config_path(company_key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def get_prod_schema(company_key: str) -> tuple[Optional[str], Optional[int]]:
    """Returns (schema_name, schema_id) deployed to prod for the WhatsApp
    bot kind, taken from companies.json."""
    info = load_raw().get(company_key, {})
    bots = info.get("bots") or {}
    wa = bots.get("whatsapp") or {}
    name = wa.get("prod_schema_name") or info.get("schema_name")
    sid = wa.get("prod_schema_id") or info.get("schema_id")
    try:
        sid = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        sid = None
    return (str(name) if name else None, sid)


def get_candidate_schema(company_key: str) -> tuple[Optional[str], Optional[int]]:
    """Returns (schema_name, schema_id) of the candidate (challenger) WA
    schema for this company, or (None, None) if not set up yet.

    Lives under `bots.whatsapp.candidate_schema_id` /
    `bots.whatsapp.candidate_schema_name` in companies.json — symmetric to
    the prod counterpart."""
    info = load_raw().get(company_key, {})
    bots = info.get("bots") or {}
    wa = bots.get("whatsapp") or {}
    name = wa.get("candidate_schema_name")
    sid = wa.get("candidate_schema_id")
    try:
        sid = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        sid = None
    return (str(name) if name else None, sid)


def set_candidate_schema(
    company_key: str, schema_id: int, schema_name: str
) -> None:
    """Persist the candidate schema id+name into companies.json. Creates
    the bots/whatsapp/ subtree if missing."""
    raw = load_raw()
    info = raw.setdefault(company_key, {})
    bots = info.setdefault("bots", {})
    wa = bots.setdefault("whatsapp", {})
    wa["candidate_schema_id"] = int(schema_id)
    wa["candidate_schema_name"] = str(schema_name)
    save_raw(raw)


def clear_candidate_schema(company_key: str) -> None:
    """Drop candidate fields from companies.json (after promotion or abort)."""
    raw = load_raw()
    info = raw.get(company_key) or {}
    wa = ((info.get("bots") or {}).get("whatsapp") or {})
    changed = False
    for k in ("candidate_schema_id", "candidate_schema_name"):
        if k in wa:
            wa.pop(k, None)
            changed = True
    if changed:
        save_raw(raw)
