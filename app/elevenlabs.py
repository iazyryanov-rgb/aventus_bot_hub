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

def get_elevenlabs_key() -> str:
    return str(load_api_keys().get("elevenlabs") or "").strip()


def set_elevenlabs_key(key: str) -> None:
    keys = load_api_keys()
    if key:
        keys["elevenlabs"] = key.strip()
    else:
        keys.pop("elevenlabs", None)
    save_api_keys(keys)


def is_configured() -> bool:
    return bool(get_elevenlabs_key())


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
