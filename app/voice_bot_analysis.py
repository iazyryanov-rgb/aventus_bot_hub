"""ИИ-анализ ElevenLabs voice-bot звонков и предложения по правкам
промта/save_call_result tool.

Пайплайн `run_analysis`:
  1. `list_conversations(agent_id=...)` пагинируется до `max_calls`
     или пока `start_time_unix_secs` ≥ `since_ts`.
  2. Для каждого conversation_id — `get_conversation()`, получаем
     полный transcript + analysis (transcript_summary, call_successful).
  3. Каждый звонок сжимается в `_summarize_call` — turn-level текст,
     dynamic_variables (значения SIP-headers при которых был звонок),
     payload save_call_result tool call (если был), результат tool
     (HTTP-код + ответ CRM).
  4. Собираем system + user prompt и отправляем в Claude через
     `AnthropicAuditClient.call_audit(...)`. Output — JSON со списком
     suggestions, каждая targets либо `main_prompt_blocks[<block_id>]`,
     либо property в `save_call_result.json`.
  5. `apply_suggestion(...)` применяет конкретную suggestion локально
     (на диск под `data/voice_bot_config/...` или `data/voice_bot_tools/...`).
     Push в ElevenLabs/CRM делается отдельно из «Промтов»/«Результатов».
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .ai_client import AnthropicAuditClient, AnthropicError
from .action_trees import get_tree
from .elevenlabs import (
    ElevenLabsError,
    extract_save_call_result_from_transcript,
    get_conversation,
    get_elevenlabs_key,
    list_conversations,
)
from .paths import data_dir
from .sectors import DEFAULT_SECTOR, SECTORS
from .voice_bot_config import (
    BLOCK_ORDER,
    BLOCK_TITLES,
    enum_sets_from_tree,
    load_config,
    save_config,
)


# ---------------------------------------------------------------------------
# Tool snapshot persistence  (mirrors VoiceBotResultsPanel logic, kept here
# to avoid importing the UI module from the analysis backend).
# ---------------------------------------------------------------------------

def tool_snapshot_path(company_key: str, sector: str = DEFAULT_SECTOR) -> Path:
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    return (
        data_dir() / "voice_bot_tools" / company_key / sector
        / "save_call_result.json"
    )


def load_tool_snapshot(
    company_key: str, sector: str = DEFAULT_SECTOR,
) -> Optional[dict]:
    p = tool_snapshot_path(company_key, sector)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def save_tool_snapshot(
    company_key: str, sector: str, tool: dict,
) -> None:
    p = tool_snapshot_path(company_key, sector)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(tool, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fetch calls from ElevenLabs
# ---------------------------------------------------------------------------

# Защита от уйти-в-космос: верхняя планка по сумме transcript-символов.
# Если за период набралось сильно больше — режем до самых свежих, чтобы не
# создать $20+ batch ради хвоста.
DEFAULT_MAX_CALLS = 50
HARD_MAX_TRANSCRIPT_CHARS = 400_000


def fetch_calls_window(
    agent_id: str,
    *,
    since_ts: int,
    until_ts: Optional[int] = None,
    max_calls: int = DEFAULT_MAX_CALLS,
    api_key: Optional[str] = None,
    progress_cb=None,
) -> list[dict]:
    """Тянем conversations этого агента в окне ``[since_ts, until_ts]``.

    Берём сначала легковесный list_conversations (страницы по 100), потом
    для каждой подходящей по времени конверсации делаем `get_conversation`
    чтобы достать transcript + analysis.

    Возвращает список полных dict'ов в порядке от свежих к старым.
    ``progress_cb(stage: str, done: int, total: int)`` — опциональный
    колбэк прогресса (`stage='list'`, `'detail'`).
    """
    if not agent_id:
        return []
    if until_ts is None:
        until_ts = int(time.time()) + 86400  # на всякий случай, чтоб не отрезало последние

    candidates: list[dict] = []
    cursor = ""
    while True:
        try:
            page = list_conversations(
                agent_id=agent_id,
                page_size=100,
                cursor=cursor,
                api_key=api_key,
            )
        except ElevenLabsError:
            break
        items = page.get("conversations") or []
        if not isinstance(items, list):
            break
        for it in items:
            ts = int(it.get("start_time_unix_secs") or 0)
            if ts == 0:
                continue
            if ts < since_ts:
                # дальше будут только старее → можно завершать пагинацию
                items = []  # сигнал "прекращаем дальнейший запрос"
                break
            if ts > until_ts:
                continue
            candidates.append(it)
            if progress_cb:
                progress_cb("list", len(candidates), max_calls)
            if len(candidates) >= max_calls:
                break
        if len(candidates) >= max_calls:
            break
        if not items:
            break
        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor") or ""
        if not cursor:
            break

    # candidates уже отсортированы desc (как ElevenLabs возвращает); если
    # внутри одной страницы порядок не гарантирован — пересортируем.
    candidates.sort(key=lambda c: int(c.get("start_time_unix_secs") or 0), reverse=True)
    candidates = candidates[:max_calls]

    # Hydrate full transcripts.
    out: list[dict] = []
    total = len(candidates)
    for i, c in enumerate(candidates):
        cid = c.get("conversation_id")
        if not cid:
            continue
        try:
            full = get_conversation(cid, api_key=api_key)
        except ElevenLabsError:
            full = c  # хоть что-то
        # carry list-level fields onto detail (status, summary, etc.)
        merged = {**c, **full}
        out.append(merged)
        if progress_cb:
            progress_cb("detail", i + 1, total)
    return out


# ---------------------------------------------------------------------------
# Per-call summary for LLM
# ---------------------------------------------------------------------------

def _turn_text(turn: dict) -> str:
    """Extract a single transcript turn as `'agent: ...'` / `'user: ...'`."""
    role = turn.get("role") or turn.get("speaker") or "agent"
    msg = (
        turn.get("message")
        or turn.get("text")
        or turn.get("content")
        or ""
    )
    if isinstance(msg, list):
        # ElevenLabs sometimes returns list of content parts
        parts: list[str] = []
        for p in msg:
            if isinstance(p, dict):
                parts.append(str(p.get("text") or ""))
            else:
                parts.append(str(p))
        msg = "".join(parts)
    return f"{role}: {str(msg).strip()}"


def summarize_call(conv: dict) -> dict:
    """Compact representation of a single ElevenLabs conversation tailored
    for LLM consumption. Drops audio/binary fields, normalises transcript
    to ``role: text`` strings, surfaces tool-call payloads."""
    cid = conv.get("conversation_id") or conv.get("id") or ""
    start = int(conv.get("start_time_unix_secs") or 0)
    duration = int(conv.get("call_duration_secs") or 0)
    status = conv.get("status") or ""
    success = conv.get("call_successful")
    analysis = conv.get("analysis") or {}
    transcript_summary = (
        conv.get("transcript_summary")
        or analysis.get("transcript_summary")
        or ""
    )
    termination = conv.get("termination_reason") or ""
    dyn_vars = (conv.get("conversation_initiation_client_data") or {}) \
        .get("dynamic_variables") or {}
    if not isinstance(dyn_vars, dict):
        dyn_vars = {}

    turns_raw = conv.get("transcript") or []
    turn_strings: list[str] = []
    for t in turns_raw if isinstance(turns_raw, list) else []:
        if not isinstance(t, dict):
            continue
        turn_strings.append(_turn_text(t))

    tool_call = extract_save_call_result_from_transcript(conv)

    return {
        "conversation_id": cid,
        "start_ts": start,
        "duration_secs": duration,
        "status": status,
        "call_successful": success,  # 'success' | 'failure' | 'unknown'
        "termination_reason": termination,
        "transcript_summary": transcript_summary,
        "dynamic_variables": dyn_vars,
        "transcript": turn_strings,
        "save_call_result": tool_call,
    }


def _trim_calls_for_budget(
    summaries: list[dict],
    *,
    char_budget: int = HARD_MAX_TRANSCRIPT_CHARS,
) -> list[dict]:
    """Если сумма символов транскриптов превышает бюджет — режем самые
    длинные turn-перечисления у самых старых звонков, чтобы запрос
    оставался в пределах токенов модели."""
    total = sum(sum(len(t) for t in c["transcript"]) for c in summaries)
    if total <= char_budget:
        return summaries
    # iterate oldest→newest, обрезаем transcript длинных
    for c in sorted(summaries, key=lambda x: x["start_ts"]):
        cur = sum(len(t) for t in c["transcript"])
        if cur > 4000:
            # сжимаем до 4k символов: keep first 1.5k + ... + last 2.5k
            joined = "\n".join(c["transcript"])
            head = joined[:1500]
            tail = joined[-2500:]
            c["transcript"] = [
                head,
                "[… truncated for LLM context budget …]",
                tail,
            ]
        total = sum(sum(len(t) for t in c["transcript"]) for c in summaries)
        if total <= char_budget:
            break
    return summaries


# ---------------------------------------------------------------------------
# LLM input
# ---------------------------------------------------------------------------

ANALYSIS_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "1–3 sentence overview of what's working and what's not "
                "in the analyzed calls."
            ),
        },
        "calls_analyzed": {"type": "integer"},
        "common_failures": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Up to 5 short bullets — recurring problems across calls "
                "(e.g. 'agent skips Step 5 consequence/benefit', "
                "'tool call_result enum missing promise_extension')."
            ),
        },
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id", "target", "severity", "title", "rationale",
                    "evidence", "before", "after",
                ],
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Stable short id, e.g. 's-001'.",
                    },
                    "target": {
                        "type": "string",
                        "enum": ["prompt_block", "tool_property"],
                    },
                    "block_id": {
                        "type": "string",
                        "description": (
                            "When target=prompt_block — one of: "
                            + ", ".join(BLOCK_ORDER)
                        ),
                    },
                    "tool_property": {
                        "type": "string",
                        "description": (
                            "When target=tool_property — id/name of the "
                            "property inside save_call_result tool's "
                            "request_body_schema.properties."
                        ),
                    },
                    "tool_field": {
                        "type": "string",
                        "enum": [
                            "description", "enum", "dynamic_variable",
                            "constant_value", "type", "required",
                        ],
                        "description": (
                            "When target=tool_property — which field of "
                            "the property to change."
                        ),
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "title": {
                        "type": "string",
                        "description": "Short imperative summary (≤ 80 chars).",
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "Why this change helps. Reference concrete "
                            "behaviours observed in the transcripts."
                        ),
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Quote 1–3 short transcript snippets that "
                            "demonstrate the problem."
                        ),
                    },
                    "before": {
                        "type": "string",
                        "description": (
                            "Current text/value being replaced. For "
                            "prompt_block this is the relevant excerpt of "
                            "the current block content (may be empty if "
                            "adding new rule). For tool_property — the "
                            "current field value."
                        ),
                    },
                    "after": {
                        "type": "string",
                        "description": (
                            "Proposed new text/value. For prompt_block "
                            "with diff_kind='replace_excerpt' this is the "
                            "drop-in replacement of `before`. For "
                            "diff_kind='append'/'prepend' this is the "
                            "block of text to add."
                        ),
                    },
                    "diff_kind": {
                        "type": "string",
                        "enum": [
                            "replace_excerpt", "append", "prepend",
                            "replace_full", "set_value",
                        ],
                        "description": (
                            "How to apply `after` to the target. "
                            "prompt_block: replace_excerpt/append/prepend/"
                            "replace_full. tool_property: set_value."
                        ),
                    },
                },
            },
        },
    },
    "required": ["summary", "calls_analyzed", "common_failures", "suggestions"],
}


def _block_overview(blocks: dict[str, str]) -> str:
    """Render the 8 prompt blocks as labelled sections for LLM input."""
    parts: list[str] = []
    for bid in BLOCK_ORDER:
        title = BLOCK_TITLES.get(bid, bid)
        body = (blocks.get(bid) or "").strip()
        parts.append(f"### BLOCK `{bid}` ({title})\n{body or '(empty)'}")
    return "\n\n".join(parts)


def _tool_overview(tool: Optional[dict]) -> str:
    """Render the save_call_result tool snapshot — what properties exist
    and which dynamic_variables they bind."""
    if not isinstance(tool, dict):
        return "(no local save_call_result.json snapshot found)"
    api = tool.get("api_schema") or {}
    rbs = api.get("request_body_schema") or {}
    props = rbs.get("properties") or []
    lines: list[str] = []
    lines.append(f"Tool name: {tool.get('name') or '—'}")
    lines.append(f"URL: {api.get('url') or '—'}")
    lines.append(f"Method: {api.get('method') or '—'}")
    lines.append(f"Properties ({len(props) if isinstance(props, list) else len(props or {})}):")
    if isinstance(props, list):
        iterable = enumerate(props)
    elif isinstance(props, dict):
        iterable = props.items()
    else:
        iterable = []
    for key, p in iterable:
        if not isinstance(p, dict):
            continue
        pid = p.get("id") or p.get("name") or str(key)
        ptype = p.get("type") or "?"
        desc = (p.get("description") or "").strip()
        if len(desc) > 200:
            desc = desc[:200] + "…"
        dv = p.get("dynamic_variable") or ""
        const = p.get("constant_value")
        enum_vals = p.get("enum")
        enum_str = ""
        if isinstance(enum_vals, list) and enum_vals:
            preview = ", ".join(str(x) for x in enum_vals[:8])
            tail = "…" if len(enum_vals) > 8 else ""
            enum_str = f"  enum=[{preview}{tail}] (n={len(enum_vals)})"
        binding = ""
        if dv:
            binding = f"  dyn={dv}"
        elif const not in (None, ""):
            binding = f"  const={const!r}"
        req = " required" if p.get("required") else ""
        lines.append(
            f"  • {pid} ({ptype}){req}{binding}{enum_str}\n"
            f"    desc: {desc or '(empty)'}",
        )
    return "\n".join(lines)


def _action_tree_overview(tree: Optional[dict]) -> str:
    if not tree:
        return "(no action_tree for this company)"
    enum_sets = enum_sets_from_tree(tree)
    if not enum_sets:
        return "(action_tree has no produces→values mappings)"
    lines = ["Allowed enum values per CRM field (source of truth):"]
    for produces, values in enum_sets.items():
        lines.append(f"  • {produces}: {', '.join(values)}")
    return "\n".join(lines)


def build_system_text(
    company_key: str, sector: str,
    blocks: dict[str, str],
    tool: Optional[dict],
    action_tree: Optional[dict],
) -> str:
    return f"""You are auditing an ElevenLabs Conversational AI **voice collection bot** that calls customers with overdue loans. Your task: analyse a batch of recorded conversations and propose concrete edits to the bot's system prompt and to its `save_call_result` webhook-tool schema.

# Bot context
Company: `{company_key}`  Sector: `{sector}`
The bot's system prompt is split into 8 thematic blocks (the hub edits each in its own tab):

{_block_overview(blocks)}

# CRM webhook-tool schema (`save_call_result`)
The bot calls this tool at the end of every call. Each `property` here maps a value the LLM produces or a SIP `dynamic_variable` to a field on the CRM webhook payload. Wrong/missing enums, missing properties or sloppy descriptions ⇒ the CRM rejects the call result.

{_tool_overview(tool)}

# Action tree (CRM contract — source of truth for enums)
{_action_tree_overview(action_tree)}

# What to look for in the transcripts
- Steps of the Call Flow that the agent skipped or executed in the wrong order.
- Missing mandatory consequence/benefit before payment confirmation (Step 5).
- Vague commitments ("la próxima semana", "más tarde") accepted as valid PTPs.
- Wrong language register (tú instead of usted, English leaking).
- Wrong handling of third-party / disputed loan / already-paid / silence scenarios.
- Cases where the bot fabricated information that should have come from a `{{sip_*}}` placeholder.
- `save_call_result` tool calls with: wrong enum values (compare with action_tree above), missing required fields, unexpected status codes from CRM, or `result` values that don't match what actually happened in the call.
- Cases where the agent identified itself as AI without being asked, or refused to acknowledge when directly asked.

# Output rules
- Return JSON matching the provided schema strictly.
- For each suggestion, set `target` = `prompt_block` and `block_id` ∈ {{{", ".join(BLOCK_ORDER)}}}, OR `target` = `tool_property` with `tool_property` = property id and `tool_field` = which property field to change.
- For `prompt_block` use `diff_kind`:
  - `replace_excerpt` — `before` is an exact substring of the current block, `after` replaces it;
  - `append` — `after` will be appended at the end of the block (`before` may be empty);
  - `prepend` — `after` will be prepended to the start of the block;
  - `replace_full` — `after` is the full new content of the block (use sparingly).
- For `tool_property` use `diff_kind` = `set_value`.
- Provide 0–10 suggestions. Skip if there's nothing meaningful to change.
- `evidence` MUST quote actual transcript fragments (not paraphrases) so the operator can verify the finding.
- Keep `title` ≤ 80 chars in Russian or English.
- Do NOT propose stylistic-only edits; every suggestion must be backed by call-data evidence.
"""


def build_user_text(calls: list[dict]) -> str:
    """Compact user prompt — calls_analyzed metric + per-call payloads."""
    parts: list[str] = []
    parts.append(
        f"Analyse the following {len(calls)} ElevenLabs conversations "
        "and return suggestions per the schema."
    )
    for i, c in enumerate(calls, start=1):
        cid = c["conversation_id"]
        ts_h = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["start_ts"]))
        meta = (
            f"#{i}  id={cid}  start={ts_h}  dur={c['duration_secs']}s  "
            f"status={c['status']}  success={c['call_successful']}  "
            f"term={c['termination_reason']!r}"
        )
        dyn = c.get("dynamic_variables") or {}
        dyn_str = ", ".join(f"{k}={v!r}" for k, v in dyn.items()) or "(none)"
        tcr = c.get("save_call_result")
        if tcr:
            tcr_str = (
                f"  call_result_tool: name={tcr.get('name')} "
                f"params={json.dumps(tcr.get('params'), ensure_ascii=False)[:500]} "
                f"status={tcr.get('status_code')}"
            )
        else:
            tcr_str = "  call_result_tool: (not called)"
        ts = c.get("transcript") or []
        ts_text = "\n".join(ts)
        summary = c.get("transcript_summary") or ""
        if summary:
            summary_block = f"  summary: {summary}\n"
        else:
            summary_block = ""
        parts.append(
            f"\n=== CALL {i} ===\n"
            f"{meta}\n"
            f"  dynamic_variables: {dyn_str}\n"
            f"{summary_block}"
            f"{tcr_str}\n"
            f"  transcript:\n{ts_text}"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_analysis(
    company_key: str,
    sector: str,
    *,
    since_ts: int,
    until_ts: int,
    max_calls: int = DEFAULT_MAX_CALLS,
    model_kind: str = "sonnet",
    progress_cb=None,
) -> dict:
    """Главный оркестратор.

    Возвращает dict вида ``{"ok": bool, "result": <schema>, "error":
    str|None, "calls_fetched": int, ...}``. Никаких исключений наружу —
    UI просто читает `ok` и при `False` показывает `error`.
    """
    cfg = load_config(company_key, sector)
    agent_id = str(cfg.get("elevenlabs_agent_id") or "").strip()
    if not agent_id:
        return {
            "ok": False,
            "error": "agent_id не задан для этого сектора компании.",
            "calls_fetched": 0,
        }
    api_key = get_elevenlabs_key(company_key)
    if not api_key:
        return {
            "ok": False,
            "error": "ElevenLabs API key не настроен.",
            "calls_fetched": 0,
        }
    if progress_cb:
        progress_cb("fetch_start", 0, max_calls)

    convos = fetch_calls_window(
        agent_id,
        since_ts=since_ts,
        until_ts=until_ts,
        max_calls=max_calls,
        api_key=api_key,
        progress_cb=progress_cb,
    )
    if not convos:
        return {
            "ok": False,
            "error": "За выбранный период звонков не нашлось.",
            "calls_fetched": 0,
        }

    summaries = [summarize_call(c) for c in convos]
    summaries = _trim_calls_for_budget(summaries)

    blocks = cfg.get("main_prompt_blocks") or {}
    tool = load_tool_snapshot(company_key, sector)
    tree = get_tree(company_key)
    system_text = build_system_text(company_key, sector, blocks, tool, tree)
    user_text = build_user_text(summaries)

    if progress_cb:
        progress_cb("llm_call", len(summaries), len(summaries))

    client = AnthropicAuditClient()
    if not client.is_configured():
        return {
            "ok": False,
            "error": "Anthropic API key не настроен (data/api_keys.json → anthropic).",
            "calls_fetched": len(summaries),
        }
    try:
        result = client.call_audit(
            kind=model_kind,
            system_text=system_text,
            user_text=user_text,
            output_schema=ANALYSIS_OUTPUT_SCHEMA,
            max_tokens=32_000,
            timeout_s=600.0,
        )
    except AnthropicError as exc:
        return {
            "ok": False,
            "error": f"Anthropic: {exc}",
            "calls_fetched": len(summaries),
        }
    payload = {
        "ok": True,
        "result": result,
        "calls_fetched": len(summaries),
        "calls_range": {"since": since_ts, "until": until_ts},
        "model": model_kind,
        "params": {
            "since_ts": since_ts,
            "until_ts": until_ts,
            "max_calls": max_calls,
            "model_kind": model_kind,
        },
    }
    # Event-trigger: разослать алерты «новые предложения». Тихо, без
    # исключений — анализ уже отработал успешно, любая ошибка с TG не
    # должна мешать оператору увидеть результат в UI.
    try:
        from .voice_bot_alerts import dispatch_analysis_alerts
        dispatch_analysis_alerts(company_key, sector, payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[voice_bot_analysis] dispatch_analysis_alerts failed: {exc}")
    return payload


# ---------------------------------------------------------------------------
# Apply suggestion
# ---------------------------------------------------------------------------

def _apply_prompt_block(
    cfg: dict, suggestion: dict,
) -> tuple[bool, str]:
    bid = suggestion.get("block_id") or ""
    if bid not in BLOCK_ORDER:
        return False, f"unknown block_id={bid!r}"
    blocks = cfg.setdefault("main_prompt_blocks", {})
    current = str(blocks.get(bid) or "")
    after = str(suggestion.get("after") or "")
    diff_kind = suggestion.get("diff_kind") or "replace_excerpt"
    before = str(suggestion.get("before") or "")
    if diff_kind == "replace_full":
        blocks[bid] = after
        return True, "replace_full"
    if diff_kind == "append":
        glue = "\n\n" if (current.strip() and after.strip()) else ""
        blocks[bid] = (current + glue + after).rstrip() if after else current
        return True, "append"
    if diff_kind == "prepend":
        glue = "\n\n" if (current.strip() and after.strip()) else ""
        blocks[bid] = (after + glue + current).rstrip() if after else current
        return True, "prepend"
    # replace_excerpt (default)
    if not before.strip():
        # treat as append when no before-anchor supplied
        glue = "\n\n" if (current.strip() and after.strip()) else ""
        blocks[bid] = (current + glue + after).rstrip() if after else current
        return True, "append (no before)"
    if before not in current:
        # try a softened match — ignore trailing whitespace differences
        loose = before.strip()
        if loose and loose in current:
            blocks[bid] = current.replace(loose, after.strip(), 1)
            return True, "replace_excerpt (loose)"
        return False, "before-excerpt not found in current block"
    blocks[bid] = current.replace(before, after, 1)
    return True, "replace_excerpt"


def _find_property(props, pid: str):
    """Поддерживаем оба формата request_body_schema.properties:
    список dict'ов (export-shape) и dict (PATCH-shape)."""
    if isinstance(props, list):
        for i, p in enumerate(props):
            if isinstance(p, dict) and (p.get("id") == pid or p.get("name") == pid):
                return i, p
        return None, None
    if isinstance(props, dict):
        if pid in props and isinstance(props[pid], dict):
            return pid, props[pid]
    return None, None


def _apply_tool_property(
    tool: dict, suggestion: dict,
) -> tuple[bool, str]:
    pid = (suggestion.get("tool_property") or "").strip()
    if not pid:
        return False, "tool_property is empty"
    field = (suggestion.get("tool_field") or "").strip()
    if not field:
        return False, "tool_field is empty"
    after_raw = suggestion.get("after")
    api = tool.setdefault("api_schema", {})
    rbs = api.setdefault("request_body_schema", {})
    props = rbs.setdefault("properties", [])
    idx, prop = _find_property(props, pid)
    if prop is None:
        return False, f"property id={pid!r} not found in tool snapshot"
    if field == "enum":
        # `after` may come as JSON-encoded list or comma-separated string
        new_enum: list[str] = []
        if isinstance(after_raw, list):
            new_enum = [str(x) for x in after_raw]
        elif isinstance(after_raw, str):
            t = after_raw.strip()
            if t.startswith("["):
                try:
                    parsed = json.loads(t)
                    if isinstance(parsed, list):
                        new_enum = [str(x) for x in parsed]
                except json.JSONDecodeError:
                    pass
            if not new_enum:
                new_enum = [s.strip() for s in t.split(",") if s.strip()]
        prop["enum"] = new_enum
        return True, "enum set"
    if field == "required":
        v = str(after_raw).strip().lower()
        prop["required"] = v in ("true", "1", "yes")
        return True, "required set"
    prop[field] = after_raw if after_raw is not None else ""
    return True, f"{field} set"


def apply_suggestion(
    company_key: str, sector: str, suggestion: dict,
) -> tuple[bool, str]:
    """Применить одно suggestion локально на диск.

    Возвращает ``(ok, message)``. Side effects:
      * для `target=prompt_block` — `save_config(company_key, cfg, sector)`;
      * для `target=tool_property` — `save_tool_snapshot(company_key, sector, tool)`.
    Push в ElevenLabs / CRM не делает.
    """
    target = (suggestion.get("target") or "").strip()
    if target == "prompt_block":
        cfg = load_config(company_key, sector)
        ok, msg = _apply_prompt_block(cfg, suggestion)
        if ok:
            save_config(company_key, cfg, sector)
        return ok, msg
    if target == "tool_property":
        tool = load_tool_snapshot(company_key, sector)
        if tool is None:
            return False, "no save_call_result.json snapshot — open Results tab and Pull first"
        ok, msg = _apply_tool_property(tool, suggestion)
        if ok:
            save_tool_snapshot(company_key, sector, tool)
        return ok, msg
    return False, f"unknown target={target!r}"


# ---------------------------------------------------------------------------
# Persistence of analysis results (so the panel can survive a reopen)
# ---------------------------------------------------------------------------

def analysis_state_path(
    company_key: str, sector: str = DEFAULT_SECTOR,
) -> Path:
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    return (
        data_dir() / "voice_bot_analysis" / company_key / f"{sector}.json"
    )


def load_analysis_state(
    company_key: str, sector: str = DEFAULT_SECTOR,
) -> Optional[dict]:
    p = analysis_state_path(company_key, sector)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def save_analysis_state(
    company_key: str, sector: str, state: dict,
) -> None:
    p = analysis_state_path(company_key, sector)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
