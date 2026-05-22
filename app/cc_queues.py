"""CC-sector queue checklist + name-matching helpers.

Single source of truth for the operator's expected CC queue catalog.
Used by:

* ``app/ui/queues_panel.py`` — the in-app «Чек-лист CC» Treeview
* ``app/scheduler.py`` — the ``queue_checklist_cc`` alert builder

Both surface the same coverage check (is each expected queue enabled
in Webitel?) and reuse the same matching rules (case-insensitive,
Cyrillic СС ↔ Latin CC, whitespace squash).
"""
from __future__ import annotations


# Each entry: (category, channel, expected queue name as it should
# appear in Webitel for the company). Names match the CO1 catalog
# after the team's May-2026 rename; if a tenant uses a different
# naming convention, factor a per-company override here later.
CC_CHECKLIST: tuple[tuple[str, str, str], ...] = (
    # Unsigned (CC_Uns)
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned Agents_40%_repeat Today"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned Agents _100%_new today"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned Agent _100%_new yesterday"),
    ("Unsigned",         "Predictive (Agent)", "СС_Unsigned_Today_Sun&HollyD_Agent_100%"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned_Agents_Night"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned appliactions_call_backs"),
    ("Unsigned",         "VoiceBot",           "CC_Unsigned 60%_VoiceBot_repeat today"),
    ("Unsigned",         "VoiceBot",           "CC_Unsigned 60%_VoiceBot_repeat yesterday"),
    ("Unsigned",         "VoiceBot",           "CC_unsigned_IVR_small"),
    ("Unsigned",         "VoiceBot",           "CC_Unsigned_telesales_VoiceBot"),
    ("Unsigned",         "Inbound",            "CC_Inbound_Unsigned"),
    # Unfinished (CC_Unf)
    ("Unfinished",       "Predictive (Agent)", "CC_Unfinished_Agents_Night"),
    ("Unfinished",       "Predictive (Agent)", "CC_Unsigned Agents_40%_repeat yesterday"),
    ("Unfinished",       "Predictive (Agent)", "СС_Unfinished_Today_Agent_50%"),
    ("Unfinished",       "Predictive (Agent)", "СС_Unfinished_Today_Sun&HollyD_Agent_100%"),
    ("Unfinished",       "Predictive (Agent)", "СС_Unfinished_Yesterday_Agent_20%"),
    ("Unfinished",       "Predictive (Agent)", "CC_Unfinished_after_VB"),
    ("Unfinished",       "Predictive (Agent)", "CC_ Today_Documents_agents>1/2h"),
    ("Unfinished",       "VoiceBot",           "CC_Documents_VoiceBot<1/2h"),
    ("Unfinished",       "VoiceBot",           "СС_Unfinished_Today_Bot_50%"),
    ("Unfinished",       "VoiceBot",           "СС_Unfinished_Yesterday_Bot_ 80%"),
    ("Unfinished",       "VoiceBot",           "CC_Unfinished_ 10-15days_100%_Voicebot"),
    ("Unfinished",       "Inbound",            "CC_Verification_calls_after_BOT"),
    ("Unfinished",       "Inbound",            "CC_Unfinished_Inb_VB"),
    # Auto-creation
    ("Auto-creation",    "Predictive (Agent)", "CC_Autocreation_Unsigned_Reapeat_50%_agent"),
    ("Auto-creation",    "VoiceBot",           "CC_Autocreation_Unsigned_Reapeat_50%Bot"),
    # Phone confirmation
    ("Phone confirmation", "VoiceBot",         "CC_Phone_confirmation"),
    # Inbound (hotline)
    ("Inbound (hotline)", "Inbound",           "CC_HotLine"),
    # Telesales
    ("Telesales",        "Inbound",            "CC Inbound Sleep and Sold"),
    # Other
    ("Other",            "Predictive (Agent)", "CC_Callbacks"),
    ("Other",            "Predictive (Agent)", "СС_Duplicates"),
)


def normalize_queue_name(name: str) -> str:
    """Case-insensitive comparison key for matching expected CC queue
    names against live Webitel names. Equalizes Cyrillic ``с`` (U+0441)
    and Latin ``c`` (so СС vs CC don't fork the check), squashes
    whitespace runs, and lowercases.
    """
    n = (name or "").strip().lower()
    n = n.replace("с", "c")
    n = " ".join(n.split())
    return n


def is_cc_queue_name(name: str) -> bool:
    """Heuristic: does this queue name look like a CC sector queue?
    Used by alert builders (agents_on_break_cc, dash_*_cc) to filter
    queue lists down to the CC subset without an explicit sector tag
    on the queue itself."""
    n = normalize_queue_name(name)
    return n.startswith("cc_") or n.startswith("cc ") or n == "cc"
