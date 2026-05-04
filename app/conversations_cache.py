"""Per-company cache of chat dialogs / members / messages.

Lives at `data/conversations_cache/<company_key>.json`. Survives rebuilds
because `build.py` overlays source onto dist without wiping unknown subfolders.

Format:
{
  "dialogs":  { chat_id: {ChatDialog asdict} },
  "members":  { chat_id: [ChatPeer asdict, ...] },
  "messages": { chat_id: { "msgs": [ChatMessage asdict], "peers": {pid: ChatPeer asdict}, "last_msg_at_ms": int } }
}
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir

_EMPTY = {"dialogs": {}, "members": {}, "messages": {}}


def cache_dir() -> Path:
    p = data_dir() / "conversations_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path(company_key: str) -> Path:
    return cache_dir() / f"{company_key}.json"


def load_cache(company_key: str) -> dict:
    path = cache_path(company_key)
    if not path.exists():
        return {k: dict(v) if isinstance(v, dict) else list(v) for k, v in _EMPTY.items()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {k: dict(v) if isinstance(v, dict) else list(v) for k, v in _EMPTY.items()}
    for key in _EMPTY:
        data.setdefault(key, {})
    return data


def save_cache(company_key: str, cache: dict) -> None:
    path = cache_path(company_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
