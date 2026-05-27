"""History of voice-bot prompt snapshots per (company, sector).

Two kinds of snapshots are tracked separately:

* ``elevenlabs`` — saved on every successful Pull from ElevenLabs in the
  Prompts panel. Captures **what was in prod** at that moment, so the
  operator can later restore it if local edits break something.

* ``analysis``  — saved on every successful Apply in the Call Analysis
  panel. Captures **the state right after AI suggestions were applied
  locally**, before any further hand-edits. The operator can roll back
  to either the pre-AI state (via the previous ``elevenlabs`` snapshot)
  or to a known-good post-AI state.

Storage:
    data/voice_bot_config/<COMPANY>/<sector>/versions/
        elevenlabs__<unix_ts>.json
        analysis__<unix_ts>.json
        ...

Each file holds a self-contained payload:

    {
      "kind":          "elevenlabs" | "analysis",
      "ts":            <int unix seconds>,
      "company_key":   "AR_",
      "sector":        "collection",
      "main_prompt_blocks": { <block_id>: <str>, ... },
      "first_message": "...",
      "meta":          { ... arbitrary }
    }

Pruning: keep the last ``MAX_PER_KIND`` (10) snapshots per kind. The
oldest extras are deleted on save.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .paths import data_dir
from .sectors import DEFAULT_SECTOR, SECTORS


KIND_ELEVENLABS = "elevenlabs"
KIND_ANALYSIS = "analysis"
KINDS: tuple[str, ...] = (KIND_ELEVENLABS, KIND_ANALYSIS)

MAX_PER_KIND = 10


def _versions_dir(company_key: str, sector: str) -> Path:
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    return (
        data_dir() / "voice_bot_config" / company_key / sector / "versions"
    )


def version_path(
    company_key: str, sector: str, kind: str, ts: int,
) -> Path:
    return _versions_dir(company_key, sector) / f"{kind}__{int(ts)}.json"


@dataclass
class PromptVersion:
    company_key: str
    sector: str
    kind: str
    ts: int
    main_prompt_blocks: dict
    first_message: str
    meta: dict
    path: Path

    @property
    def label(self) -> str:
        """Short human label e.g. 'elevenlabs · 2026-05-27 21:14'."""
        return f"{self.kind} · " + time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(self.ts),
        )


def save_version(
    company_key: str, sector: str, kind: str,
    blocks: dict, first_message: str,
    meta: Optional[dict] = None,
    *,
    skip_if_unchanged: bool = True,
) -> Optional[PromptVersion]:
    """Persist a snapshot. If ``skip_if_unchanged`` (default), and the
    last snapshot of the same kind has identical blocks + first_message,
    no new file is created — avoids exploding history with duplicates
    when the operator hits Pull twice in a row.

    Returns the new ``PromptVersion`` on save, ``None`` when skipped or
    on I/O error.
    """
    if kind not in KINDS:
        return None
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR

    ts = int(time.time())

    if skip_if_unchanged:
        recent = list_versions(company_key, sector, kind=kind)
        if recent:
            last = recent[0]  # newest
            if (
                last.main_prompt_blocks == (blocks or {})
                and (last.first_message or "") == (first_message or "")
            ):
                return None

    payload = {
        "kind": kind,
        "ts": ts,
        "company_key": company_key,
        "sector": sector,
        "main_prompt_blocks": dict(blocks or {}),
        "first_message": str(first_message or ""),
        "meta": dict(meta or {}),
    }
    p = version_path(company_key, sector, kind, ts)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return None

    _prune(company_key, sector, kind)

    return PromptVersion(
        company_key=company_key, sector=sector, kind=kind, ts=ts,
        main_prompt_blocks=payload["main_prompt_blocks"],
        first_message=payload["first_message"],
        meta=payload["meta"], path=p,
    )


def _prune(company_key: str, sector: str, kind: str) -> None:
    versions = list_versions(company_key, sector, kind=kind)
    if len(versions) <= MAX_PER_KIND:
        return
    for v in versions[MAX_PER_KIND:]:
        try:
            v.path.unlink()
        except OSError:
            pass


def list_versions(
    company_key: str, sector: str, *, kind: Optional[str] = None,
) -> list[PromptVersion]:
    """Newest-first list of saved snapshots. ``kind`` filter is optional."""
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    d = _versions_dir(company_key, sector)
    if not d.exists():
        return []
    out: list[PromptVersion] = []
    for p in d.glob("*.json"):
        name = p.stem
        if "__" not in name:
            continue
        k, _, ts_str = name.partition("__")
        if kind and k != kind:
            continue
        if k not in KINDS:
            continue
        try:
            ts = int(ts_str)
        except ValueError:
            continue
        v = _load_path(p)
        if v is not None:
            out.append(v)
    out.sort(key=lambda v: v.ts, reverse=True)
    return out


def _load_path(p: Path) -> Optional[PromptVersion]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return PromptVersion(
        company_key=str(data.get("company_key") or ""),
        sector=str(data.get("sector") or DEFAULT_SECTOR),
        kind=str(data.get("kind") or ""),
        ts=int(data.get("ts") or 0),
        main_prompt_blocks=dict(data.get("main_prompt_blocks") or {}),
        first_message=str(data.get("first_message") or ""),
        meta=dict(data.get("meta") or {}),
        path=p,
    )


def load_version(
    company_key: str, sector: str, kind: str, ts: int,
) -> Optional[PromptVersion]:
    return _load_path(version_path(company_key, sector, kind, ts))


def latest_version(
    company_key: str, sector: str, kind: str,
) -> Optional[PromptVersion]:
    versions = list_versions(company_key, sector, kind=kind)
    return versions[0] if versions else None


def delete_version(version: PromptVersion) -> bool:
    try:
        version.path.unlink()
        return True
    except OSError:
        return False
