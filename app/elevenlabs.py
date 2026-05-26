"""ElevenLabs Conversational AI client.

Тонкая обёртка над публичным REST API. Используется UI-панелью Voice Bot,
чтобы по кнопке «Pull» вытянуть текущий system prompt + first_message из
prod-агента в ElevenLabs, по кнопке «Push» — залить отредактированный
обратно. Никаких голосовых вызовов отсюда не делается — это чисто конфиг
агента.

Хранение ключа: `data/api_keys.json` под ключом `elevenlabs` (тот же
файл, где живёт Anthropic key — единый локальный store).

Эндпоинты (через `xi-api-key` header):
  - GET    /v1/convai/agents
  - GET    /v1/convai/agents/{agent_id}
  - PATCH  /v1/convai/agents/{agent_id}

Форма обновления промта (partial PATCH):
    {
      "conversation_config": {
        "agent": {
          "prompt": {"prompt": "<system prompt>"},
          "first_message": "<first message>"
        }
      }
    }

При создании испаноязычного агента (создание из хаба не нужно, но это
известное ограничение API): `conversation_config.tts.model_id` обязан
быть `eleven_turbo_v2_5` или `eleven_flash_v2_5` — иначе POST /create
вернёт 400 «Non-english Agents must use turbo or flash v2_5».
"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .ai_client import load_api_keys, save_api_keys


API_BASE = "https://api.elevenlabs.io"


class ElevenLabsError(Exception):
    pass


# ---------- key persistence ----------
#
# Storage shape in `data/api_keys.json`:
#   {
#     "elevenlabs": "sk_global_fallback",         # global / shared key
#     "elevenlabs_by_company": {                  # optional per-company overrides
#       "PE_": "sk_prestamo365_workspace_key",
#       "CO_": "sk_credito365_workspace_key"
#     }
#   }
#
# Resolution order for `get_elevenlabs_key(company_key)`:
#   1. per-company override if `company_key` is given AND a non-empty key is
#      registered for it in `elevenlabs_by_company`;
#   2. global `elevenlabs` key otherwise.

def get_elevenlabs_key(company_key: Optional[str] = None) -> str:
    keys = load_api_keys()
    if company_key:
        per = (keys.get("elevenlabs_by_company") or {}).get(company_key) or ""
        if str(per).strip():
            return str(per).strip()
    return str(keys.get("elevenlabs") or "").strip()


def set_elevenlabs_key(
    key: str, *, company_key: Optional[str] = None,
) -> None:
    """Store an ElevenLabs key. Without `company_key` updates the global
    fallback. With `company_key` updates the per-company override
    (creating the `elevenlabs_by_company` sub-dict on demand). Empty
    `key` deletes the corresponding entry."""
    keys = load_api_keys()
    if company_key:
        per_map = keys.get("elevenlabs_by_company")
        if not isinstance(per_map, dict):
            per_map = {}
        if key:
            per_map[company_key] = key.strip()
        else:
            per_map.pop(company_key, None)
        if per_map:
            keys["elevenlabs_by_company"] = per_map
        else:
            keys.pop("elevenlabs_by_company", None)
    else:
        if key:
            keys["elevenlabs"] = key.strip()
        else:
            keys.pop("elevenlabs", None)
    save_api_keys(keys)


def is_configured(company_key: Optional[str] = None) -> bool:
    return bool(get_elevenlabs_key(company_key))


# ---------- low-level HTTP ----------

def _request(
    method: str,
    path: str,
    *,
    api_key: Optional[str] = None,
    body: Optional[dict] = None,
    timeout: float = 30.0,
) -> dict:
    key = (api_key or get_elevenlabs_key()).strip()
    if not key:
        raise ElevenLabsError("ElevenLabs API key not configured")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise ElevenLabsError(f"HTTP {e.code} {method} {path}: {msg[:400]}") from e
    except urllib.error.URLError as e:
        raise ElevenLabsError(f"{method} {path}: {e}") from e


# ---------- public API ----------

def list_agents(
    *, api_key: Optional[str] = None, page_size: int = 100, search: str = "",
) -> list[dict]:
    """All agents the API key can see. Empty list if the key is bound to a
    sub-workspace that has none.

    Each entry has `agent_id` and `name`; full config requires
    :func:`get_agent`.
    """
    qs = urllib.parse.urlencode({"page_size": page_size, "search": search})
    resp = _request("GET", f"/v1/convai/agents?{qs}", api_key=api_key)
    return list(resp.get("agents") or [])


def get_agent(agent_id: str, *, api_key: Optional[str] = None) -> dict:
    """Full agent config — everything PATCH would accept back, plus
    read-only fields (`agent_id`, `version_id`, `access_info`, ...).
    """
    if not agent_id:
        raise ElevenLabsError("agent_id is required")
    return _request("GET", f"/v1/convai/agents/{agent_id}", api_key=api_key)


def extract_prompt(agent: dict) -> tuple[str, str]:
    """Pull (system_prompt, first_message) out of a `get_agent` response."""
    cc = (agent or {}).get("conversation_config") or {}
    ag = cc.get("agent") or {}
    prompt = ((ag.get("prompt") or {}).get("prompt")) or ""
    first_message = ag.get("first_message") or ""
    return str(prompt), str(first_message)


def update_agent_prompt(
    agent_id: str,
    *,
    system_prompt: Optional[str] = None,
    first_message: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Partial update: only the fields you pass are sent. Returns the
    updated agent dict (full GET shape — ElevenLabs returns the whole
    config on PATCH).
    """
    if not agent_id:
        raise ElevenLabsError("agent_id is required")
    agent_block: dict = {}
    if system_prompt is not None:
        agent_block["prompt"] = {"prompt": system_prompt}
    if first_message is not None:
        agent_block["first_message"] = first_message
    if not agent_block:
        raise ElevenLabsError("nothing to update (both fields are None)")
    body = {"conversation_config": {"agent": agent_block}}
    return _request("PATCH", f"/v1/convai/agents/{agent_id}", api_key=api_key, body=body)


# ---------- Tools (webhook tools attached to an agent) ----------

def get_tool(tool_id: str, *, api_key: Optional[str] = None) -> dict:
    """Full tool config — same shape that PATCH expects back."""
    if not tool_id:
        raise ElevenLabsError("tool_id is required")
    return _request("GET", f"/v1/convai/tools/{tool_id}", api_key=api_key)


def _normalize_tool_for_patch(spec: dict) -> dict:
    """Convert ElevenLabs tool *export* shape into PATCH-acceptable shape.

    Reverse-engineered against `GET /v1/convai/tools/<id>` of a live tool
    (`tool_config` slice of the response equals what PATCH expects back).

    Cumulative transformations:

      1. ``dynamic_variables.dynamic_variable_placeholders.<name>``:
         export ``{"type":"string_literal","value":<v>}`` → PATCH ``<v>``.

      2. ``api_schema.request_headers``:
         export list ``[{"type":"value","name":<n>,"value":<v>}]``
         → PATCH dict ``{<n>: <v>}``.

      3. ``api_schema.path_params_schema``:
         export ``[]`` (list) → PATCH ``{}`` (empty dict).

      4. ``api_schema.query_params_schema``:
         export ``[]`` (list, empty) → PATCH ``None``.

      5. ``api_schema.request_body_schema``:
         - drop ``id`` and ``value_type`` keys (export-only labels);
         - ``required`` becomes a list of property IDs aggregated from
           per-property ``required: true`` flags;
         - ``properties`` becomes a dict keyed by property ``id``, with
           ``id`` / ``value_type`` / ``required`` stripped from each
           property value.

      6. Top-level ``response_mocks`` is NOT a ``tool_config`` field —
         it lives next to ``tool_config`` in GET responses. Drop it from
         the PATCH payload.

    Returns a deep copy; the input dict is untouched.
    """
    out = copy.deepcopy(spec)
    out.pop("response_mocks", None)

    dvars = out.get("dynamic_variables")
    if isinstance(dvars, dict):
        placeholders = dvars.get("dynamic_variable_placeholders")
        if isinstance(placeholders, dict):
            for k, v in list(placeholders.items()):
                if isinstance(v, dict) and "value" in v:
                    placeholders[k] = v.get("value")

    api = out.get("api_schema")
    if isinstance(api, dict):
        headers = api.get("request_headers")
        if isinstance(headers, list):
            new_headers: dict = {}
            for h in headers:
                if isinstance(h, dict) and h.get("name"):
                    new_headers[h["name"]] = h.get("value", "")
            api["request_headers"] = new_headers

        if isinstance(api.get("path_params_schema"), list):
            api["path_params_schema"] = {}
        if isinstance(api.get("query_params_schema"), list):
            api["query_params_schema"] = (
                None if not api["query_params_schema"] else api["query_params_schema"]
            )
        if "response_body_schema" not in api:
            api["response_body_schema"] = None

        rbs = api.get("request_body_schema")
        if isinstance(rbs, dict):
            required_ids: list[str] = []
            props = rbs.get("properties")
            if isinstance(props, list):
                new_props: dict = {}
                for p in props:
                    if not isinstance(p, dict):
                        continue
                    pid = p.get("id")
                    if not pid:
                        continue
                    if p.get("required"):
                        required_ids.append(pid)
                    new_props[pid] = {
                        kk: vv for kk, vv in p.items()
                        if kk not in ("id", "value_type", "required")
                    }
                rbs["properties"] = new_props
            elif isinstance(props, dict):
                for pid, p in list(props.items()):
                    if not isinstance(p, dict):
                        continue
                    if p.pop("required", False):
                        required_ids.append(pid)
                    p.pop("value_type", None)
                    p.pop("id", None)
            rbs.pop("id", None)
            rbs.pop("value_type", None)
            rbs["required"] = required_ids

    return out


# ---------- Conversations (transcripts) ----------

def list_conversations(
    *,
    agent_id: str = "",
    page_size: int = 30,
    cursor: str = "",
    api_key: Optional[str] = None,
) -> dict:
    """Page through conversations the API key can see. Returns the raw
    ElevenLabs response: `{"conversations": [...], "next_cursor": "...",
    "has_more": bool}`. Each conversation entry has `conversation_id`,
    `agent_id`, `agent_name`, `start_time_unix_secs`, `call_duration_secs`,
    `status`, `call_successful`, `transcript_summary`, `termination_reason`,
    `message_count`, etc.
    """
    qs_parts = [f"page_size={int(page_size)}"]
    if agent_id:
        qs_parts.append(f"agent_id={urllib.parse.quote(agent_id)}")
    if cursor:
        qs_parts.append(f"cursor={urllib.parse.quote(cursor)}")
    qs = "&".join(qs_parts)
    return _request("GET", f"/v1/convai/conversations?{qs}", api_key=api_key)


def get_conversation(
    conversation_id: str, *, api_key: Optional[str] = None,
) -> dict:
    """Full conversation detail: transcript (turns with tool_calls/results),
    metadata, analysis (call_successful, transcript_summary,
    data_collection_results), has_audio."""
    if not conversation_id:
        raise ElevenLabsError("conversation_id is required")
    return _request(
        "GET", f"/v1/convai/conversations/{conversation_id}", api_key=api_key,
    )


def get_conversation_audio(
    conversation_id: str, *, api_key: Optional[str] = None,
) -> bytes:
    """Raw audio bytes (mp3 by default) of the whole conversation.
    Heavy — only fetch on demand."""
    if not conversation_id:
        raise ElevenLabsError("conversation_id is required")
    key = (api_key or get_elevenlabs_key()).strip()
    if not key:
        raise ElevenLabsError("ElevenLabs API key not configured")
    req = urllib.request.Request(
        API_BASE + f"/v1/convai/conversations/{conversation_id}/audio",
        headers={"xi-api-key": key, "Accept": "audio/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise ElevenLabsError(
            f"HTTP {e.code} GET /v1/convai/conversations/{conversation_id}/audio: {msg[:400]}"
        ) from e
    except urllib.error.URLError as e:
        raise ElevenLabsError(
            f"GET /v1/convai/conversations/{conversation_id}/audio: {e}"
        ) from e


def extract_save_call_result_from_transcript(
    conversation: dict,
) -> Optional[dict]:
    """Walk the conversation transcript looking for a `save_call_result`
    tool call. Returns `{"params": <body sent to CRM>, "status_code":
    <HTTP code>, "response": <CRM response body>}` if found, else None.
    """
    transcript = (conversation or {}).get("transcript") or []
    if not isinstance(transcript, list):
        return None
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        tool_calls = turn.get("tool_calls") or []
        tool_results = turn.get("tool_results") or []
        for i, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                continue
            name = (
                call.get("tool_name")
                or call.get("name")
                or (call.get("params_as_json") or {}).get("__tool_name__", "")
            )
            if not isinstance(name, str):
                continue
            if "save_call_result" not in name.lower():
                continue
            params = (
                call.get("params_as_json")
                or call.get("parameters")
                or call.get("arguments")
                or {}
            )
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except (ValueError, TypeError):
                    params = {"_raw": params}
            res: dict = {}
            if i < len(tool_results) and isinstance(tool_results[i], dict):
                tr = tool_results[i]
                res = {
                    "status_code": (
                        tr.get("response_status_code")
                        or tr.get("status_code")
                        or tr.get("status")
                    ),
                    "response": (
                        tr.get("result_value")
                        or tr.get("response")
                        or tr.get("body")
                    ),
                }
            return {
                "name": name,
                "params": params,
                **res,
            }
    return None


def update_tool(
    tool_id: str, body: dict, *, api_key: Optional[str] = None,
) -> dict:
    """Replace the tool spec on ElevenLabs side. `body` must be the full
    tool JSON (same shape as the ElevenLabs export the hub stores under
    `data/voice_bot_tools/<COMPANY>/<name>.json`). PATCH expects the
    spec wrapped in `tool_config`, and a couple of export-only fields
    (`dynamic_variable_placeholders` as `{type, value}`) need flattening
    — we accept the export shape and normalize here. Requires editor
    role on the tool; viewer-only keys will receive HTTP 403."""
    if not tool_id:
        raise ElevenLabsError("tool_id is required")
    if not isinstance(body, dict):
        raise ElevenLabsError("body must be a dict")
    if "tool_config" in body:
        inner = body["tool_config"]
        payload = {"tool_config": _normalize_tool_for_patch(inner)}
    else:
        payload = {"tool_config": _normalize_tool_for_patch(body)}
    return _request(
        "PATCH", f"/v1/convai/tools/{tool_id}", api_key=api_key, body=payload,
    )


def list_phone_numbers(*, api_key: Optional[str] = None) -> list[dict]:
    """All phone numbers зарегистрированные в workspace + к какому agent
    привязан каждый. GET /v1/convai/phone-numbers возвращает список;
    каждый item — ``{phone_number_id, phone_number, label, provider,
    supports_inbound, supports_outbound, assigned_agent: {agent_id,
    agent_name}}``. Возвращаем список как есть; UI фильтрует по agent_id."""
    resp = _request("GET", "/v1/convai/phone-numbers", api_key=api_key)
    if isinstance(resp, list):
        return resp
    return list(resp.get("phone_numbers") or [])


def list_tools(*, api_key: Optional[str] = None) -> list[dict]:
    """All webhook tools the API key can see in this workspace.

    GET /v1/convai/tools. Каждый элемент — `{id, tool_config: {name,
    description, type, ...}, access_info: ..., ...}`. Возвращаем как есть;
    UI читает id/имя через :func:`extract_tool_meta`.
    """
    resp = _request("GET", "/v1/convai/tools", api_key=api_key)
    return list(resp.get("tools") or [])


def extract_tool_meta(tool: dict) -> tuple[str, str]:
    """Возвращает ``(tool_id, name)`` из элемента ``list_tools`` или ответа
    ``get_tool``."""
    if not isinstance(tool, dict):
        return "", ""
    tid = tool.get("id") or tool.get("tool_id") or ""
    cfg = tool.get("tool_config") or {}
    name = cfg.get("name") or tool.get("name") or ""
    return str(tid), str(name)
