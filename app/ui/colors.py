"""Shared UI palette — aligned with the Windows 11 Fluent theme in
`app.ui.theme`. Existing module-level constants kept (and re-pointed) so
that all the `tk.Frame(bg=CARD_BG, ...)` / `tk.Label(fg=META_FG, ...)`
call-sites stay valid without any churn."""

from .theme import (
    ACCENT as _ACCENT,
    BORDER as _BORDER,
    ERR as _ERR,
    OK as _OK,
    SURFACE_ALT as _SURFACE_ALT,
    TEXT as _TEXT,
    TEXT_DISABLED as _TEXT_DISABLED,
    TEXT_MUTED as _TEXT_MUTED,
)


# Surfaces -----------------------------------------------------------------
CARD_BG = _SURFACE_ALT     # was "#f9fafb" — now Win11 white card
CARD_BORDER = _BORDER      # was "#e5e7eb"

# Text ---------------------------------------------------------------------
TEXT_FG = _TEXT            # was "#111827"
META_FG = _TEXT_MUTED      # was "#6b7280"
TBD_FG = _TEXT_DISABLED    # was "#9ca3af"

# Status -------------------------------------------------------------------
OK_FG = _OK                # was "#16a34a"
ERR_FG = _ERR              # was "#dc2626"
LINK_FG = _ACCENT          # was "#1d4ed8"
