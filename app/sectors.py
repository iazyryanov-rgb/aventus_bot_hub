"""Sector taxonomy used to split a company's bots into CC vs Collection.

Each company in the hub now owns two sectors. Each sector independently
configures its own voice bot, WhatsApp bot, and agents. Sector keys are
used as part of every per-bot config file path:

    data/voice_bot_config/<COMPANY>/<sector>.json
    data/wa_bot_config/<COMPANY>/<sector>.json
    data/voice_bot_tools/<COMPANY>/<sector>/<tool>.json

Defaults: when migrating from a pre-sector layout, existing data files
move under the ``collection`` sector (the historical scope of all
production bots today). CC sectors start empty.
"""
from __future__ import annotations


SECTOR_CC = "cc"
SECTOR_COLLECTION = "collection"
SECTORS: tuple[str, ...] = (SECTOR_CC, SECTOR_COLLECTION)
DEFAULT_SECTOR = SECTOR_COLLECTION


def sector_label_key(sector: str) -> str:
    """i18n key for a sector's user-visible label."""
    return f"sector_{sector}"
