"""WA-bot configuration per company per sector.

Source of truth для логики и промптов WhatsApp-Infobip-бота. Bot Hub
читает/правит этот конфиг, потом отдельный «apply»-шаг (придёт позже)
будет переписывать соответствующие узлы Webitel-схемы при выкатке нового
билда.

Config persisted to `data/wa_bot_config/<COMPANY_KEY>/<sector>.json`
(``<sector>`` = ``cc`` or ``collection``). Legacy
``data/wa_bot_config/<COMPANY_KEY>.json`` is migrated to the
``collection`` sector on first read.
"""
from __future__ import annotations

import json
from typing import Optional

from .data import load_raw, save_raw
from .paths import data_dir
from .sectors import DEFAULT_SECTOR, SECTORS


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
    {"local": "discount_payment",      "remote": "discounted_payment_amount"},
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
    {"key": "direction",      "value": "wa_bot_inbound"},
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

Segment-aware strategy (after the discount rule)

- loan_type == "NEW" without an active discount: drive FULL CLOSURE. Open the conversation by directly asking for the full payment ($ ${amount} ${currency_index}) today (${cur_dt}) or tomorrow (${tomorrow_dt}). Do not offer extension or partial payment up front; only fall back to alternatives if the client refuses full closure. Register promise_type=promise_type_full_payment when the client agrees.
- loan_type == "REP": drive PROLONG/EXTENSION. Open by directly asking for the extension payment ($ ${extension_min_payment} ${currency_index}) today (${cur_dt}) or tomorrow (${tomorrow_dt}) to extend the loan term. Do not offer full closure or partial payment up front; only fall back if the client asks. Register promise_type=promise_type_extension when the client agrees.
- loan_type empty/unknown: ask neutrally about the client's intent without committing to a specific outcome until you have a signal.

Cross-cutting rule: never present a menu of options at the start. Push the segment-appropriate outcome first; only offer alternatives if the client explicitly asks or refuses the primary option.
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


SEEDS: dict[str, dict[str, dict]] = {
    "CO_": {
        "collection": {
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
        "cc": {},
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

def config_path(company_key: str, sector: str = DEFAULT_SECTOR):
    return data_dir() / "wa_bot_config" / company_key / f"{sector}.json"


def _legacy_config_path(company_key: str):
    """Pre-sector path. Kept for one-shot migration."""
    return data_dir() / "wa_bot_config" / f"{company_key}.json"


def _migrate_legacy(company_key: str) -> None:
    legacy = _legacy_config_path(company_key)
    if not legacy.exists() or legacy.is_dir():
        return
    target = config_path(company_key, DEFAULT_SECTOR)
    if target.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(target)
    except OSError:
        pass


def _empty_cfg() -> dict:
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


def load_config(company_key: str, sector: str = DEFAULT_SECTOR) -> dict:
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    _migrate_legacy(company_key)
    p = config_path(company_key, sector)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    # Fallback to seed (per-sector seed).
    seed = (SEEDS.get(company_key) or {}).get(sector) or {}
    if seed:
        return json.loads(json.dumps(seed))  # deep copy
    return _empty_cfg()


def save_config(
    company_key: str, cfg: dict, sector: str = DEFAULT_SECTOR,
) -> None:
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    p = config_path(company_key, sector)
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


INFOBIP_PROVIDER = "infobip_whatsapp"


def get_infobip_chat_bot(company_key: str):
    """Return our Webitel chat-bot profile for the company's Infobip
    WhatsApp gateway, or None when no such bot is registered. The
    profile carries the per-tenant Infobip credentials in `metadata`
    (`api_key`, `url`) — single source of truth lives in Webitel, not
    in `companies.json`.

    Returns a `webitel.ChatBot` instance.
    """
    info = load_raw().get(company_key, {}) or {}
    host = str(info.get("webitel_host") or "").strip()
    token = str(info.get("webitel_access_token") or "").strip()
    if not host or not token:
        return None
    # Lazy import — `webitel` pulls urllib + several dataclasses that
    # the calibration tooling and CLI code don't always need.
    from .webitel import WebitelClient, WebitelError
    try:
        bots = WebitelClient(host, token).list_chat_bots()
    except WebitelError:
        return None
    for b in bots:
        if b.provider == INFOBIP_PROVIDER and b.enabled:
            return b
    return None


def get_owned_whatsapp_numbers(company_key: str) -> list[str]:
    """Return the list of WhatsApp numbers attached to this company's
    Infobip account (E.164 strings — Infobip preserves the formatting,
    typically '+573151586256').

    Discovery flow:
      1. Pull the chat-bot profile from Webitel (`/api/chat/bots`) and
         pick the one whose `provider == 'infobip_whatsapp'`. Its
         `metadata` carries `api_key` + `url` (= Infobip personalised
         base URL like `https://n8vpk5.api-us.infobip.com`).
      2. Hit Infobip's `/numbers/1/numbers` (cached 30 min in
         `app.infobip`) and keep entries whose `capabilities[]`
         contains `WHATSAPP`.
      3. On any failure (Webitel unreachable, no Infobip bot in this
         tenant, Infobip 4xx) → fall back to the legacy single-number
         field `bots.whatsapp.bot_phone_number` if present.

    The hub uses this list to scope the AI chat audit input to OUR
    gateway — calibration must NOT see KC-bot chats from other
    gateways that also live in the same Webitel domain.
    """
    bot = get_infobip_chat_bot(company_key)
    if bot is not None:
        api_key = str(bot.metadata.get("api_key") or "").strip()
        base_url = str(bot.metadata.get("url") or "").strip()
        if api_key and base_url:
            from . import infobip
            nums = infobip.cached_owned_whatsapp_numbers(
                company_key, api_key, base_url=base_url,
            )
            if nums:
                return nums
    # Legacy fallback — single number kept in companies.json under
    # `bots.whatsapp.bot_phone_number` from the pre-discovery era.
    info = load_raw().get(company_key, {}) or {}
    wa = ((info.get("bots") or {}).get("whatsapp") or {})
    legacy = str(wa.get("bot_phone_number") or "").strip()
    return [legacy] if legacy else []


def get_infobip_senders(company_key: str) -> list[dict]:
    """Live (cached 30 min) list of WhatsApp senders for the company's
    Infobip subaccount, with quality / status / limit / registration
    fields per Infobip's `/whatsapp/2/senders`. Returns [] when the
    company doesn't have an Infobip chat-bot in Webitel.

    Used by the senders panel (UI) and the alert builder.
    """
    bot = get_infobip_chat_bot(company_key)
    if bot is None:
        return []
    api_key = str(bot.metadata.get("api_key") or "").strip()
    base_url = str(bot.metadata.get("url") or "").strip()
    if not api_key or not base_url:
        return []
    from . import infobip
    return infobip.cached_senders(
        company_key, api_key, base_url=base_url,
    )


def refresh_infobip_senders(company_key: str) -> list[dict]:
    """Drop the cache for this company and re-pull. Hooked to the
    'Refresh' button in the senders panel."""
    from . import infobip
    infobip.invalidate_cache(company_key)
    return get_infobip_senders(company_key)


def get_infobip_gateway_name(company_key: str) -> str:
    """Live name of the Infobip chat-bot in Webitel, used by the audit
    pipeline as the `via.name` filter. Falls back to the historical
    constant `WhatsApp-Infobip` when discovery fails so audits still
    work with their previous behaviour."""
    bot = get_infobip_chat_bot(company_key)
    if bot is not None and bot.name:
        return bot.name
    return GATEWAY_NAME


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
