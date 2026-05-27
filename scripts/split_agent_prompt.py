"""Разовая утилита: подложить anchor-маркеры (`# === BLOCK: <id> ===`) в
system prompt ElevenLabs-агента, чтобы хаб мог разрезать его на 8
тематических блоков при следующем Pull.

Алгоритм:
  1. GET /v1/convai/agents/<id>           — забираем текущий promtпт.
  2. Если в нём УЖЕ есть anchor'ы (`split_blocks` вернул recognized=True)
     — выходим, не трогая. Идемпотентно.
  3. Иначе режем по top-level `# Heading` секциям через
     `voice_bot_config.split_by_headings` (карта заголовков адаптирована
     под CO_/PE_/AR_ collection-промты).
  4. Склеиваем через `join_blocks`, добавляя anchor'ы между блоками.
  5. PATCH /v1/convai/agents/<id> с новым system_prompt (если `--push`).

Запуск:
  $env:ELEVENLABS_API_KEY = "sk_..."
  py -3 scripts/split_agent_prompt.py agent_1301ks8901mmfctvp33h756xyn1x
  # либо
  py -3 scripts/split_agent_prompt.py agent_... --push

Без `--push` — dry-run: только показывает диагностику, ничего в
ElevenLabs не пишет.

Ключ берётся из (в порядке убывания приоритета):
  - аргумент `--api-key`
  - переменная окружения `ELEVENLABS_API_KEY`
  - `data/api_keys.json` в каталоге запуска (worktree/data или dist/data)

При отсутствии ключа — выход с ошибкой 2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Запуск из корня worktree; докинуть путь, чтобы импорт `app.*` работал.
_repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo))

from app.elevenlabs import (  # noqa: E402  (imports after sys.path tweak)
    ElevenLabsError,
    extract_prompt,
    get_agent,
    update_agent_prompt,
)
from app.voice_bot_config import (  # noqa: E402
    BLOCK_ORDER,
    join_blocks,
    split_blocks,
    split_by_headings,
)


def _resolve_api_key(cli_key: str | None) -> str:
    if cli_key:
        return cli_key.strip()
    env = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if env:
        return env
    # Пытаемся прочесть из data/api_keys.json — сначала worktree, потом dist
    candidates = [
        _repo / "data" / "api_keys.json",
        _repo.parent.parent.parent / "dist" / "data" / "api_keys.json",
    ]
    for p in candidates:
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                key = str(data.get("elevenlabs") or "").strip()
                if key:
                    return key
        except (OSError, json.JSONDecodeError):
            continue
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Split an ElevenLabs voice agent's system prompt into 8 "
            "thematic blocks by inserting `# === BLOCK: <id> ===` anchors."
        ),
    )
    ap.add_argument("agent_id", help="ElevenLabs agent_id (e.g. agent_...)")
    ap.add_argument(
        "--push", action="store_true",
        help="Actually PATCH the agent. Without this flag the script "
        "only prints a dry-run report.",
    )
    ap.add_argument(
        "--api-key", default=None,
        help="ElevenLabs API key. Overrides ELEVENLABS_API_KEY env var "
        "and data/api_keys.json lookup.",
    )
    ap.add_argument(
        "--dump-anchored", default=None,
        help="Optional path to dump the anchored prompt as plain text "
        "before/instead of pushing.",
    )
    args = ap.parse_args()

    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        sys.stderr.write(
            "ElevenLabs API key not found. Set ELEVENLABS_API_KEY env var, "
            "pass --api-key, or place data/api_keys.json next to the "
            "worktree/dist.\n",
        )
        return 2

    try:
        agent = get_agent(args.agent_id, api_key=api_key)
    except ElevenLabsError as exc:
        sys.stderr.write(f"GET agent failed: {exc}\n")
        return 3

    prompt, first_msg = extract_prompt(agent)
    name = agent.get("name") or "—"
    print(f"agent_id     = {args.agent_id}")
    print(f"agent_name   = {name}")
    print(f"prompt_len   = {len(prompt)} chars")
    print(f"first_msg    = {len(first_msg)} chars")
    print()

    if not prompt.strip():
        print("Prompt is empty — nothing to split. Exiting.")
        return 0

    # Идемпотентность: если anchor'ы уже стоят — не трогаем.
    _existing, recognized = split_blocks(prompt)
    if recognized and any(_existing.values()):
        print(
            "Prompt already contains `# === BLOCK: <id> ===` anchors — "
            "nothing to do. Exiting.",
        )
        return 0

    blocks, unknown = split_by_headings(prompt)
    print("Split by top-level `# Heading` sections:")
    for bid in BLOCK_ORDER:
        print(f"  {bid:25s}  {len(blocks[bid]):5d} chars")
    if unknown:
        print()
        print(
            f"Skipped {len(unknown)} heading candidates not in the whitelist "
            "(remain inside the previous section as continuation). "
            "Common cases: PASO/ETAPA subsections, multi-line `#` comments, "
            "body lines that happened to be capitalized. No action required."
        )

    anchored = join_blocks(blocks)
    print()
    print(f"anchored_len = {len(anchored)} chars (was {len(prompt)})")

    if args.dump_anchored:
        out_path = Path(args.dump_anchored)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(anchored, encoding="utf-8")
        print(f"Dumped anchored prompt to {out_path}")

    # Round-trip safety: split_blocks(anchored) → recognized=True.
    _recovered, ok = split_blocks(anchored)
    if not ok:
        sys.stderr.write(
            "Internal error: anchored prompt failed round-trip via "
            "split_blocks. Aborting push.\n",
        )
        return 4

    if not args.push:
        print()
        print(
            "Dry-run only (no --push). Re-run with `--push` to PATCH the "
            "agent in ElevenLabs.",
        )
        return 0

    try:
        update_agent_prompt(
            args.agent_id, system_prompt=anchored, api_key=api_key,
        )
    except ElevenLabsError as exc:
        sys.stderr.write(f"PATCH agent failed: {exc}\n")
        return 5
    print()
    print("OK: pushed anchored prompt to ElevenLabs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
