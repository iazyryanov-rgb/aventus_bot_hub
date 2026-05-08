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
                        "enum": ["text", "structural"],
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
    "too small for a finding, mark it severity=low."
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
        _lang_block(lang),
    ]
    return "\n\n".join(parts)


def build_user_prompt(records: list[ChatRecord], data_meta: dict) -> str:
    header = {
        "audit_request": "loan_outcome_audit",
        "data_meta": data_meta,
        "instructions": (
            "Below is a JSONL stream of chats from the period. Analyze "
            "outcomes by `payment.classification` (REP→prolong is the win; "
            "NEW→close is the win; both can land in 'partial'). Compare the "
            "language and flow of chats with `paid=true` vs `paid=false`. "
            "Return findings + recommendations per the schema."
        ),
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    for r in records:
        lines.append(json.dumps(to_compact_dict(r), ensure_ascii=False))
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
    user_text = build_user_prompt(records, data_meta)

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
