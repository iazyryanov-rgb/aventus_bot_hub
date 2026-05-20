"""AI chat-audit engine.

Glue between `chat_audit_data` (data collection) and `ai_client` (Anthropic
SDK call). One public entrypoint: `run_audit()`. Returns a structured dict
matching `OUTPUT_SCHEMA`, plus `_meta.usage` from the API response.

Design notes:
  * The system prompt = role + glossary + per-company context + a snapshot of
    the bot config (`build_request_body`-style JSON without the live dialog).
    All of that is stable across runs for the same company → it sits in the
    cached prefix (cache_control: ephemeral on the system block).
  * The user message = JSONL of chats + meta header. Volatile per request.
  * Output is constrained via `output_config.format = json_schema` in
    `ai_client`. Schema below is "strict" (`additionalProperties=false`).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from .ai_client import AnthropicAuditClient
from .audit_storage import save_audit_result
from .chat_audit_data import ChatRecord, collect_period, to_compact_dict
from .data import Company
from .wa_bot_config import build_request_body, load_config


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "findings", "recommendations"],
    "properties": {
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "total_chats", "good_count", "bad_count",
                "common_failures", "top_signals",
            ],
            "properties": {
                "total_chats": {"type": "integer"},
                "good_count": {"type": "integer"},
                "bad_count": {"type": "integer"},
                "common_failures": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "top_signals": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id", "severity", "pattern", "kind",
                    "evidence_chat_ids", "estimated_impact_pct",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "pattern": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "prompt", "function", "enum", "flow", "data",
                            # Phase-II finding kinds — see ROLE_AND_GLOSSARY:
                            "crm_field",         # бот не знал что-то, что есть в CRM
                            "schema_drift",      # mapping ≠ prod/candidate schema
                            "compliance",        # бот нарушает запреты (police/jail/…)
                            "dropoff",           # клиенты массово отваливаются в узле X
                            "ab_compare",        # candidate делает что-то лучше/хуже champion
                            "function_hygiene",  # функции дёргаются с мусорными аргументами
                            "stage_segment",     # REP/NEW/late требуют разного скрипта
                            "sentiment",         # бот сам триггерит конфликт
                        ],
                    },
                    "evidence_chat_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "estimated_impact_pct": {"type": "integer"},
                },
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id", "applies_to", "before", "after",
                    "rationale", "linked_findings",
                    "goal", "expected_lift_pct", "kind",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "applies_to": {"type": "string"},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "rationale": {"type": "string"},
                    "linked_findings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "goal": {
                        "type": "string",
                        "enum": ["prolong", "fully_pay", "both", "neither"],
                    },
                    "expected_lift_pct": {
                        "type": "integer",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [
                            "text", "structural",
                            "crm_field_add",      # добавить новую переменную в crm_lookup_vars
                            "schema_patch",       # править Webitel-схему (prod/candidate)
                        ],
                    },
                    "crm_field_add": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "properties": {
                            "local":       {"type": "string"},
                            "remote":      {"type": "string"},
                            "why_needed":  {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

ROLE_AND_GLOSSARY = (
    "You are a senior collections-AI consultant auditing a WhatsApp debt-"
    "collection bot. The bot speaks Spanish to Latin-American clients.\n"
    "\n"
    "Your job: find concrete, actionable improvements that increase the "
    "share of chats that end with the client actually paying. "
    "Distinguish two business goals by `crm.loan_type`:\n"
    "  - REP (`is_renewal=true`): the goal is to PROLONG the loan. Best "
    "outcome is the client paying the renewal/extension amount.\n"
    "  - NEW (`is_renewal=false`): the goal is to CLOSE the loan with full "
    "payment, with the upside of taking out a larger follow-up loan. "
    "Mention this upside framing only when the chat clearly invites it.\n"
    "\n"
    "Glossary:\n"
    "  - PTP — promise to pay; a commitment to pay by date X amount Y.\n"
    "  - dpd — days past due. Higher dpd = harder negotiation.\n"
    "  - REP — renewal/extension flow.\n"
    "  - NEW — first-cycle / fresh-loan flow.\n"
    "  - `payment.classification`: 'close' = loan was fully paid, "
    "'prolong' = renewal/extension paid, 'partial' = some money in but loan "
    "still active, 'none' = no payment in the +14 day window.\n"
    "  - `handler`: 'bot_only' = bot closed the chat itself; 'agent_handled' "
    "= a human agent participated.\n"
    "\n"
    "Goal-specific rules (these tell you which way to push the bot):\n"
    "\n"
    "  PROLONG (REP / extension):\n"
    "    - Don't scare the client with talk of full closure if they came to "
    "extend.\n"
    "    - Lean on `${extension_min_payment}` — concrete amount they need to "
    "pay TODAY to renew.\n"
    "    - Propose `${cur_dt}` or `${tomorrow_dt}` as the PTP date — short "
    "horizon, less negotiation room.\n"
    "    - The winning function-call result is "
    "`promise_type=promise_type_extension` with the renewal amount.\n"
    "\n"
    "  FULLY_PAY (NEW / first-cycle close):\n"
    "    - If `${discount_valid_to}` is set and not expired: lead with the "
    "discounted closing amount; the discount is the strongest motivator.\n"
    "    - Frame closing as opening the door to a larger next-loan; only "
    "when the client signals interest.\n"
    "    - PTP date in `${cur_dt}` or `${tomorrow_dt}`; longer horizons "
    "decay severely.\n"
    "    - The winning function-call result is "
    "`promise_type=promise_type_full_payment` (or "
    "`promise_type_discount` if a discount applies).\n"
    "\n"
    "Findings should be specific and tied to evidence (cite chat_ids). "
    "Recommendations should be in the same style as the existing config: "
    "produce concrete `before`/`after` text the operator can paste in. "
    "`applies_to` is a path inside the bot config: e.g. "
    "`gpt.main_prompt`, `gpt.secondary_prompt`, "
    "`gpt.builder.client_content_template`, "
    "`gpt.functions[return_final_status].description`, "
    "`gpt.functions[return_final_status].enum_descriptions.contact_result.contact_result_promise_of_payment`. "
    "If you propose a brand-new enum value, set `applies_to` to "
    "`gpt.functions[<fn>].parameters.properties.<prop>.enum[+]`.\n"
    "\n"
    "Tag every recommendation with three meta-fields:\n"
    "  - `goal`: which business goal this recommendation primarily helps. "
    "Use `prolong` (helps REP/extension flow), `fully_pay` (helps NEW/close "
    "flow), `both` (genuinely lifts both — be conservative, prefer one), "
    "or `neither` (style/safety/clarity fix that doesn't shift outcomes).\n"
    "  - `expected_lift_pct`: integer 0..100, your honest estimate of the "
    "percentage-point lift in the GOAL-relevant outcome rate (i.e. "
    "`payment.classification == 'prolong'` for `goal=prolong`, "
    "`payment.classification == 'close'` for `goal=fully_pay`, "
    "the corresponding union for `both`). For `neither` use 0. "
    "Don't inflate — if you're guessing, pick a small number (1..3).\n"
    "  - `kind`: `text` for any change to a prompt, function description, "
    "enum description, or other text-valued field — these we can apply "
    "automatically. `structural` for changes that add/remove flow nodes "
    "or rewire the routing — these we cannot apply yet, so prefer to "
    "express the same idea as a `text` change when possible.\n"
    "\n"
    "Be brief and high-signal. Do not invent statistics. If sample size is "
    "too small for a finding, mark it severity=low.\n"
    "\n"
    "== Phase-II finding kinds (use when the evidence justifies; otherwise "
    "stick to prompt/function/enum/flow/data) ==\n"
    "  - `crm_field` — клиент задаёт вопрос или ведёт диалог, на который "
    "бот не смог ответить, потому что у него не было данных в "
    "`crm_lookup_vars`. Пример: клиент спрашивает «у меня есть скидка», а "
    "в маппинге нет `discount_*`. В рекомендации используй "
    "`kind=crm_field_add` и обязательно заполни `crm_field_add` объект "
    "{`local`, `remote`, `why_needed`} — это новая пара переменных, "
    "которую надо добавить в `crm_lookup_vars`.\n"
    "  - `schema_drift` — расхождение между локальным маппингом и "
    "реальной Webitel-схемой (prod / candidate). Контекст в "
    "`MAPPING_DRIFT` секции. Severity=high когда поле меняет семантику "
    "(direction, call_type), severity=medium для опечаток в значениях. "
    "В рекомендации используй `kind=schema_patch`.\n"
    "  - `compliance` — бот говорит запрещённое (police / jail / "
    "коллекторские угрозы) или клиент жалуется на тон. Список запретов — "
    "в `FORBIDDEN_PHRASES`. Severity=high.\n"
    "  - `dropoff` — клиенты массово прерывают диалог в одном и том же "
    "узле action-tree (см. `tree_path` чатов). Назвать узел (по индексу "
    "пути или последней метке) и предложить чем заменить шаг.\n"
    "  - `ab_compare` — у champion и candidate чатов разный исход на "
    "одинаковых вопросах. Каждый чат маркирован `arm` "
    "(`champion`/`candidate`). Рекомендация — что из кандидата перенести "
    "в champion (или наоборот). Severity по lift'у.\n"
    "  - `function_hygiene` — функция (например `return_final_status`) "
    "вызывается с пустыми/нелогичными аргументами (`promise_amount` без "
    "`promise_date`, `contact_result=promise_of_payment` без "
    "`promise_type`). Рекомендуй ужесточение enum-описаний или required.\n"
    "  - `stage_segment` — REP-клиентам (`is_renewal=true`) бот говорит "
    "как с NEW-клиентами и наоборот, теряя конверсию. Конкретный сегмент "
    "+ конкретная правка.\n"
    "  - `sentiment` — бот сам триггерит эскалацию: формальный тон, "
    "повторяемая фраза в ответ на возражение, etc. Цитируй чат_id и фразу.\n"
)


def _company_context(company: Company) -> str:
    return (
        f"COMPANY:\n"
        f"  key: {company.key}\n"
        f"  name: {company.name}\n"
        f"  country: {company.country}\n"
        f"  timezone: {company.timezone}\n"
    )


def _bot_config_snapshot(company: Company) -> str:
    cfg = load_config(company.key)
    body = build_request_body(cfg)
    # Drop the live `input` user message — only the developer message is
    # part of the static bot config.
    inputs = body.get("input") or []
    devs = [m for m in inputs if isinstance(m, dict) and m.get("role") == "developer"]
    body_for_prompt = {
        **body,
        "input": devs,  # keep developer (system-ish) message; drop user template
    }
    return (
        "BOT CONFIG (current, what the bot is using right now):\n"
        + json.dumps(body_for_prompt, ensure_ascii=False, indent=2)
    )


_LANG_INSTRUCTIONS = {
    "RU":  "Russian",
    "ENG": "English",
    "ES":  "Spanish",
}


def _lang_block(lang: str) -> str:
    name = _LANG_INSTRUCTIONS.get(lang, "English")
    return (
        "OUTPUT LANGUAGE:\n"
        f"  Write all natural-language analysis text in {name}. "
        f"This applies to: summary.common_failures items, "
        f"summary.top_signals items, findings.pattern, and "
        f"recommendations.rationale.\n"
        "  Keep recommendations.before and recommendations.after in their "
        "ORIGINAL language (Spanish — the bot's operating language). "
        "They are literal text fragments the operator will paste back into "
        "the bot config.\n"
        "  Never translate: enum values (e.g. contact_result_*, "
        "promise_type_*), severity / kind enum tokens, applies_to paths, "
        "JSON keys, chat_ids, or any code/identifier."
    )


def build_system_prompt(company: Company, lang: str = "ENG") -> str:
    parts = [
        ROLE_AND_GLOSSARY,
        _company_context(company),
        _bot_config_snapshot(company),
        _phase2_context(company),
        _lang_block(lang),
    ]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Phase-II context — CRM vars, mapping drift, compliance, A/B config.
# ---------------------------------------------------------------------------

_FORBIDDEN_PHRASES_ES = [
    "arresto", "cárcel", "carcel", "prisión", "prision", "policía", "policia",
    "embargo", "denuncia penal", "represalia", "demanda judicial",
    # ENG fall-backs (some bots leak English):
    "arrest", "jail", "police", "lawsuit", "prison",
]


def _phase2_context(company: Company) -> str:
    """Inject mapping / drift / compliance / A/B context for Phase-II
    finding kinds."""
    parts: list[str] = []

    cfg = load_config(company.key)

    # 1) crm_lookup_vars — список переменных, которые бот уже умеет.
    vars_list = cfg.get("crm_lookup_vars") or []
    if vars_list:
        parts.append(
            "CRM LOOKUP VARS (what the bot already pulls from CRM by phone):\n"
            + json.dumps(vars_list, ensure_ascii=False, indent=2)
        )

    # 2) Mapping ↔ Webitel schema drift.
    drift = _compute_drift(company, cfg)
    if drift is not None:
        parts.append(
            "MAPPING DRIFT (mapping vs live prod/candidate schemas in Webitel):\n"
            + json.dumps(drift, ensure_ascii=False, indent=2)
        )

    # 3) Compliance — forbidden phrases.
    parts.append(
        "FORBIDDEN PHRASES (the bot must never use):\n"
        + ", ".join(_FORBIDDEN_PHRASES_ES)
    )

    # 4) A/B router config — digits routed to candidate.
    try:
        from .wa_bot_config import candidate_digits_for
        digits = candidate_digits_for(company.key)
    except Exception:
        digits = []
    if digits:
        parts.append(
            "A/B ROUTER CONFIG:\n"
            f"  Candidate digits: {sorted(digits)} (phones ending in these "
            f"go to candidate schema; rest → champion). Each chat in the "
            f"user prompt carries `arm` ∈ {{champion, candidate}} computed "
            f"from the same rule. Use this to build `ab_compare` findings."
        )

    return "\n\n".join(parts) if parts else ""


def _compute_drift(company: Company, cfg: dict) -> Optional[dict]:
    """Pull prod + candidate POST signatures from Webitel and diff against
    mapping. Returns a compact dict suitable for the prompt; None on error.
    """
    try:
        from .data import load_raw
        from .webitel import WebitelClient
        from .wa_bot_config import get_candidate_schema, get_prod_schema
    except Exception:
        return None
    info = load_raw().get(company.key, {}) or {}
    host = (info.get("webitel_host") or "").strip()
    tok = (info.get("webitel_access_token") or "").strip()
    if not host or not tok:
        return None
    _, prod_id = get_prod_schema(company.key)
    _, cand_id = get_candidate_schema(company.key)
    if not prod_id:
        return None
    client = WebitelClient(host, tok)

    def _extract(schema_obj: dict) -> dict:
        payload = schema_obj.get("payload") or {}
        for n in payload.get("nodes") or []:
            sch = n.get("schema") or {}
            url = sch.get("url") or ""
            if "robot_phone_result" in url:
                data_s = sch.get("data") or ""
                try:
                    fields = json.loads(data_s) if data_s else {}
                except json.JSONDecodeError:
                    import re as _re
                    fields = {}
                    for m in _re.finditer(r'"([^"]+)"\s*:\s*"([^"]*)"', data_s):
                        fields[m.group(1)] = m.group(2)
                return {"url": url, "fields": fields}
        return {"url": "", "fields": {}}

    try:
        prod_sig = _extract(client.get_schema(int(prod_id)))
    except Exception:
        return None
    cand_sig = None
    if cand_id:
        try:
            cand_sig = _extract(client.get_schema(int(cand_id)))
        except Exception:
            cand_sig = None

    mapping_fields = {
        f.get("key", ""): f.get("value", "")
        for f in (cfg.get("result_post_fields") or [])
    }
    mapping_url = cfg.get("result_post_url") or ""

    diffs = []
    all_keys = (
        set(mapping_fields)
        | set(prod_sig.get("fields") or {})
        | set((cand_sig or {}).get("fields") or {})
    )
    for k in sorted(all_keys):
        m = mapping_fields.get(k, "")
        p = (prod_sig.get("fields") or {}).get(k, "")
        c = (cand_sig.get("fields") or {}).get(k, "") if cand_sig else None
        ok = (m == p) and (c is None or m == c)
        if ok:
            continue
        diffs.append({
            "field": k,
            "mapping": m, "prod": p,
            "cand": c if c is not None else "(no candidate)",
        })

    url_ok = (mapping_url == prod_sig.get("url")) and (
        cand_sig is None or mapping_url == cand_sig.get("url")
    )

    return {
        "prod_schema_id": prod_id,
        "candidate_schema_id": cand_id,
        "url_ok": url_ok,
        "url_mapping": mapping_url,
        "url_prod": prod_sig.get("url"),
        "url_cand": cand_sig.get("url") if cand_sig else None,
        "field_diffs": diffs,
        "all_ok": (url_ok and not diffs),
    }


def build_user_prompt(
    records: list[ChatRecord],
    data_meta: dict,
    candidate_digits: Optional[set[str]] = None,
) -> str:
    header = {
        "audit_request": "loan_outcome_audit",
        "data_meta": data_meta,
        "instructions": (
            "Below is a JSONL stream of chats from the period. Analyze "
            "outcomes by `payment.classification` (REP→prolong is the win; "
            "NEW→close is the win; both can land in 'partial'). Compare the "
            "language and flow of chats with `paid=true` vs `paid=false`. "
            "Return findings + recommendations per the schema. Each chat "
            "carries `arm` (`champion`/`candidate`/`unknown`) — leverage it "
            "for `ab_compare` findings when outcomes differ."
        ),
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    cd = candidate_digits or set()
    for r in records:
        d = to_compact_dict(r)
        last = (r.phone_last_digit or "").strip()[-1:]
        if not last:
            d["arm"] = "unknown"
        elif last in cd:
            d["arm"] = "candidate"
        else:
            d["arm"] = "champion"
        lines.append(json.dumps(d, ensure_ascii=False))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run_audit(
    company: Company,
    since_ms: int,
    until_ms: int,
    model_kind: str = "sonnet",
    chat_limit: int = 100,
    api_key: Optional[str] = None,
    lang: str = "ENG",
    elapsed_for_save: Optional[float] = None,
) -> dict:
    """Pull data + call Claude. Returns the parsed audit dict (with `_meta`).

    `lang` controls only the natural-language analysis text in the response
    (summary, findings.pattern, recommendations.rationale). Bot-config diffs
    (`before`/`after`) stay in their source language (Spanish), and IDs /
    enums / `applies_to` paths are never translated.

    Raises `AnthropicError` on API issues; raises `RuntimeError` if no chats
    were collected for the period.
    """
    records, data_meta = collect_period(
        company, since_ms, until_ms, limit=chat_limit,
    )
    if not records:
        raise RuntimeError("За выбранный период чатов не нашлось.")

    system_text = build_system_prompt(company, lang=lang)
    try:
        from .wa_bot_config import candidate_digits_for
        cand_digits = {str(d) for d in candidate_digits_for(company.key)}
    except Exception:
        cand_digits = set()
    user_text = build_user_prompt(records, data_meta, candidate_digits=cand_digits)

    client = AnthropicAuditClient(api_key=api_key)
    result = client.call_audit(
        kind=model_kind,
        system_text=system_text,
        user_text=user_text,
        output_schema=OUTPUT_SCHEMA,
    )
    meta = result.setdefault("_meta", {})
    meta["data"] = data_meta
    meta["chat_limit"] = chat_limit
    meta["records_sent"] = len(records)
    meta["lang"] = lang
    # Persist for the calibration queue. `elapsed_for_save` is best-effort —
    # callers that have a stopwatch (UI worker, scheduler) pass it in.
    period_days_int = max(1, int((until_ms - since_ms) / 86_400_000))
    try:
        audit_id = save_audit_result(
            company.key, result,
            period_days=period_days_int,
            model_kind=model_kind,
            elapsed_s=elapsed_for_save,
            chat_limit=chat_limit,
            lang=lang,
        )
        meta["audit_id"] = audit_id
        meta["ts_ms"] = int(time.time() * 1000)
    except OSError:
        pass
    return result
