"""Anthropic Claude API wrapper for the chat-audit feature.

API key persistence: `data/api_keys.json`. Key is loaded into
`AnthropicAuditClient` on construction. Use `is_configured()` before calling
`call_audit()`.

Models:
  * `claude-sonnet-4-6` — default, good cost/quality for batched audits.
  * `claude-opus-4-7`   — deep audit; adaptive thinking only, no sampling
    parameters, no `budget_tokens`.

Both calls use:
  * adaptive thinking (`thinking={"type": "adaptive"}`)
  * `output_config.format = json_schema` for structured output
  * cache_control on the system prompt (5-minute TTL — reuse across audit
    invocations for the same company)
  * streaming via `messages.stream` to avoid SDK read-timeout on long outputs
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .paths import data_dir


MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS = "claude-opus-4-7"
MODEL_KINDS = ("sonnet", "opus")


def _api_keys_path() -> Path:
    return data_dir() / "api_keys.json"


def load_api_keys() -> dict:
    p = _api_keys_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_api_keys(data: dict) -> None:
    p = _api_keys_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_anthropic_key() -> str:
    return str(load_api_keys().get("anthropic") or "").strip()


def set_anthropic_key(key: str) -> None:
    keys = load_api_keys()
    if key:
        keys["anthropic"] = key.strip()
    else:
        keys.pop("anthropic", None)
    save_api_keys(keys)


class AnthropicError(Exception):
    pass


class AnthropicAuditClient:
    """Lightweight wrapper around `anthropic.Anthropic` tailored for our
    audit pipeline. The actual SDK is imported lazily so missing `anthropic`
    only fails when the user runs an audit, not on app startup."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._key = api_key or get_anthropic_key()
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._key)

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # noqa: WPS433
        except ImportError as exc:
            raise AnthropicError(
                "Не установлен пакет `anthropic`. "
                "Запусти: py -3 -m pip install anthropic"
            ) from exc
        if not self._key:
            raise AnthropicError("Anthropic API key не задан.")
        self._client = anthropic.Anthropic(api_key=self._key)
        return self._client

    @staticmethod
    def model_id(kind: str) -> str:
        if kind == "opus":
            return MODEL_OPUS
        return MODEL_SONNET

    def call_audit(
        self,
        kind: str,
        system_text: str,
        user_text: str,
        output_schema: dict,
        max_tokens: int = 32_000,
        timeout_s: float = 600.0,
    ) -> dict:
        """Run one audit request and return the parsed JSON output.

        Raises `AnthropicError` on transport/parse errors.
        """
        client = self._ensure_client()
        try:
            import anthropic  # noqa: WPS433
        except ImportError as exc:
            raise AnthropicError(str(exc)) from exc

        model = self.model_id(kind)
        try:
            with client.with_options(timeout=timeout_s).messages.stream(
                model=model,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "high",
                    "format": {
                        "type": "json_schema",
                        "schema": output_schema,
                    },
                },
                system=[{
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_text}],
            ) as stream:
                final = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise AnthropicError(
                f"HTTP {exc.status_code}: {getattr(exc, 'message', exc)}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AnthropicError(f"Сеть: {exc}") from exc
        except Exception as exc:
            raise AnthropicError(f"{type(exc).__name__}: {exc}") from exc

        if final.stop_reason == "refusal":
            raise AnthropicError("Модель отказалась отвечать (stop_reason=refusal).")
        text = next(
            (b.text for b in final.content if getattr(b, "type", "") == "text"),
            "",
        )
        if not text.strip():
            raise AnthropicError("Пустой ответ модели.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnthropicError(f"Не-JSON ответ модели: {exc}") from exc
        usage = getattr(final, "usage", None)
        if usage is not None:
            data.setdefault("_meta", {})["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", 0,
                ),
                "cache_read_input_tokens": getattr(
                    usage, "cache_read_input_tokens", 0,
                ),
                "model": model,
            }
        return data
