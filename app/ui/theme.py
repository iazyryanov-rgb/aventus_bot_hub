"""Windows 11 Fluent-style ttk theme.

Tk has no native Win11 renderer, so we customize the `clam` base theme with
a Mica-light palette, Segoe UI Variable typography, and per-widget styles
that approximate Fluent surfaces, accents, and tab bars.

`apply_modern_theme(root)` is idempotent — call once at app startup. Returns
the chosen UI font family so callers can use it for headings.

Limitations:
  * No real rounded corners on widgets — Tk doesn't expose them.
  * No Mica/acrylic translucency (system DWM API not exposed via Tk).
  * The Notebook accent indicator under the selected tab is approximated
    via a thin colored bottom border on the selected tab background.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


# ---------------------------------------------------------------------------
# Win11 Fluent-light palette
# ---------------------------------------------------------------------------

WIN_BG          = "#F3F3F3"   # window / Mica background
SURFACE         = "#FBFBFB"   # card surface
SURFACE_ALT     = "#FFFFFF"   # input fields, raised content
BORDER          = "#E5E5E5"   # card / panel border
BORDER_STRONG   = "#D1D1D1"   # input border, button stroke

TEXT            = "#1F1F1F"
TEXT_MUTED      = "#5C5C5C"
TEXT_DISABLED   = "#A0A0A0"
TEXT_INVERSE    = "#FFFFFF"

ACCENT          = "#0078D4"   # Windows accent blue
ACCENT_HOVER    = "#106EBE"
ACCENT_PRESSED  = "#005A9E"
ACCENT_SOFT     = "#E5F1FB"

OK              = "#107C10"
WARN            = "#9D5D00"
ERR             = "#C42B1C"

HOVER_BG        = "#EAEAEA"
SUBTLE_HOVER    = "#F5F5F5"
PRESSED_BG      = "#DEDEDE"
SELECTED_BG     = "#E0EEF9"


def _pick_font(root: tk.Misc) -> str:
    """Win11 ships Segoe UI Variable; older systems have plain Segoe UI.
    Fall back gracefully so the app still runs anywhere."""
    fams = set(tkfont.families(root))
    for candidate in (
        "Segoe UI Variable Display",
        "Segoe UI Variable",
        "Segoe UI",
    ):
        if candidate in fams:
            return candidate
    return "TkDefaultFont"


def apply_modern_theme(root: tk.Misc) -> str:
    ui = _pick_font(root)

    # Re-target every named Tk font so even widgets that don't read styles
    # (Toplevel titles, menubars) follow the new typography.
    for name in (
        "TkDefaultFont", "TkTextFont", "TkMenuFont",
        "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
        "TkIconFont", "TkTooltipFont",
    ):
        try:
            tkfont.nametofont(name).configure(family=ui, size=9)
        except tk.TclError:
            pass

    base_font  = (ui, 9)
    bold_font  = (ui, 9, "bold")
    head_font  = (ui, 10, "bold")
    h1_font    = (ui, 14, "bold")

    try:
        root.configure(bg=WIN_BG)
    except tk.TclError:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # ---- Defaults ----
    style.configure(
        ".",
        background=WIN_BG,
        foreground=TEXT,
        fieldbackground=SURFACE_ALT,
        bordercolor=BORDER,
        focuscolor=ACCENT,
        insertcolor=TEXT,
        font=base_font,
    )

    # ---- Frames ----
    style.configure("TFrame", background=WIN_BG)
    style.configure("Card.TFrame", background=SURFACE_ALT)
    style.configure("Surface.TFrame", background=SURFACE)

    # ---- Labels ----
    style.configure("TLabel", background=WIN_BG, foreground=TEXT)
    style.configure("Card.TLabel", background=SURFACE_ALT, foreground=TEXT)
    style.configure("Meta.TLabel", background=WIN_BG, foreground=TEXT_MUTED)
    style.configure("Header.TLabel", background=WIN_BG, foreground=TEXT, font=head_font)
    style.configure("Title.TLabel", background=WIN_BG, foreground=TEXT, font=h1_font)

    # ---- Buttons (Win11 "Standard" — light surface, 1px border, hover ramp) ----
    style.configure(
        "TButton",
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
        relief="solid",
        borderwidth=1,
        padding=(11, 4),
        font=base_font,
    )
    style.map(
        "TButton",
        background=[
            ("disabled", SUBTLE_HOVER),
            ("pressed", PRESSED_BG),
            ("active", HOVER_BG),
        ],
        foreground=[("disabled", TEXT_DISABLED)],
        bordercolor=[("focus", ACCENT), ("active", BORDER_STRONG)],
        lightcolor=[("active", HOVER_BG)],
        darkcolor=[("active", HOVER_BG)],
    )

    # ---- Accent button (filled blue, primary action) ----
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=TEXT_INVERSE,
        bordercolor=ACCENT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        relief="flat",
        borderwidth=0,
        padding=(11, 4),
        font=base_font,
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", "#C7C7C7"),
            ("pressed", ACCENT_PRESSED),
            ("active", ACCENT_HOVER),
        ],
        foreground=[("disabled", TEXT_INVERSE)],
        lightcolor=[("active", ACCENT_HOVER), ("pressed", ACCENT_PRESSED)],
        darkcolor=[("active", ACCENT_HOVER), ("pressed", ACCENT_PRESSED)],
    )

    # ---- Entry / Combobox / Spinbox: 1px Win11 input look ----
    style.configure(
        "TEntry",
        fieldbackground=SURFACE_ALT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        relief="solid",
        borderwidth=1,
        insertcolor=TEXT,
        padding=(6, 3),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE_ALT,
        background=SURFACE_ALT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        arrowcolor=TEXT_MUTED,
        relief="solid",
        borderwidth=1,
        padding=(6, 3),
    )
    style.map(
        "TCombobox",
        bordercolor=[("focus", ACCENT), ("active", BORDER_STRONG)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
        fieldbackground=[
            ("readonly", SURFACE_ALT),
            ("disabled", SUBTLE_HOVER),
        ],
        foreground=[("disabled", TEXT_DISABLED)],
        arrowcolor=[("active", TEXT)],
    )
    # Make popdown listbox match the field surface.
    root.option_add("*TCombobox*Listbox.background", SURFACE_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECTED_BG)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.borderWidth", 1)
    root.option_add("*TCombobox*Listbox.relief", "solid")
    root.option_add("*TCombobox*Listbox.font", base_font)

    style.configure(
        "TSpinbox",
        fieldbackground=SURFACE_ALT,
        background=SURFACE_ALT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        arrowcolor=TEXT_MUTED,
        relief="solid",
        borderwidth=1,
        padding=(6, 2),
    )
    style.map(
        "TSpinbox",
        bordercolor=[("focus", ACCENT)],
        arrowcolor=[("active", TEXT)],
    )

    # ---- Checkbutton / Radiobutton ----
    style.configure(
        "TCheckbutton",
        background=WIN_BG,
        foreground=TEXT,
        focuscolor=WIN_BG,
        padding=4,
    )
    style.map(
        "TCheckbutton",
        background=[("active", WIN_BG)],
        foreground=[("disabled", TEXT_DISABLED)],
    )
    style.configure("Card.TCheckbutton", background=SURFACE_ALT)
    style.map("Card.TCheckbutton", background=[("active", SURFACE_ALT)])

    style.configure(
        "TRadiobutton",
        background=WIN_BG,
        foreground=TEXT,
        focuscolor=WIN_BG,
        padding=4,
    )
    style.map(
        "TRadiobutton",
        background=[("active", WIN_BG)],
        foreground=[("disabled", TEXT_DISABLED)],
    )

    # ---- LabelFrame (group / card with title) ----
    style.configure(
        "TLabelframe",
        background=WIN_BG,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        relief="solid",
        borderwidth=1,
        padding=9,
    )
    style.configure(
        "TLabelframe.Label",
        background=WIN_BG,
        foreground=TEXT,
        font=(ui, 8, "bold"),
    )

    # ---- Notebook (flat Win11 segmented-pill tabs) ----
    # `clam` draws Notebook.tab with a 3D bevel (light/dark facets), which
    # is what makes the tabs look pressed-in. Borrow the flat tab element
    # from the `default` theme and rebuild the layout without bevels.
    try:
        style.element_create("Flat.Notebook.tab", "from", "default")
    except tk.TclError:
        pass  # already created on a previous theme reload
    style.layout("TNotebook", [
        ("Notebook.client", {"sticky": "nswe"}),
    ])
    style.layout("TNotebook.Tab", [
        ("Flat.Notebook.tab", {
            "sticky": "nswe",
            "children": [
                ("Notebook.padding", {
                    "side": "top",
                    "sticky": "nswe",
                    "children": [
                        ("Notebook.label", {"side": "top", "sticky": ""}),
                    ],
                }),
            ],
        }),
    ])
    style.configure(
        "TNotebook",
        background=WIN_BG,
        borderwidth=0,
        tabmargins=[4, 8, 4, 0],
    )
    style.configure(
        "TNotebook.Tab",
        background=WIN_BG,
        foreground=TEXT_MUTED,
        bordercolor=WIN_BG,
        lightcolor=WIN_BG,
        darkcolor=WIN_BG,
        borderwidth=0,
        padding=[18, 9],
        font=base_font,
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", ACCENT_SOFT),
            ("active", SUBTLE_HOVER),
            ("!selected", WIN_BG),
        ],
        foreground=[
            ("selected", ACCENT),
            ("active", TEXT),
            ("!selected", TEXT_MUTED),
        ],
        bordercolor=[("selected", ACCENT_SOFT), ("active", SUBTLE_HOVER)],
        lightcolor=[("selected", ACCENT_SOFT), ("active", SUBTLE_HOVER)],
        darkcolor=[("selected", ACCENT_SOFT), ("active", SUBTLE_HOVER)],
    )

    # ---- Treeview (Win11-clean list) ----
    style.configure(
        "Treeview",
        background=SURFACE_ALT,
        fieldbackground=SURFACE_ALT,
        foreground=TEXT,
        bordercolor=BORDER,
        relief="flat",
        rowheight=22,
        font=base_font,
    )
    style.map(
        "Treeview",
        background=[("selected", SELECTED_BG)],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE,
        foreground=TEXT_MUTED,
        bordercolor=BORDER,
        relief="flat",
        font=(ui, 8, "bold"),
        padding=(8, 4),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", HOVER_BG)],
        foreground=[("active", TEXT)],
    )
    # Default colorless column separator.
    style.layout("Treeview.Heading", [
        ("Treeheading.cell", {"sticky": "nswe"}),
        ("Treeheading.border", {"sticky": "nswe", "children": [
            ("Treeheading.padding", {"sticky": "nswe", "children": [
                ("Treeheading.image", {"side": "right", "sticky": ""}),
                ("Treeheading.text", {"sticky": "we"}),
            ]}),
        ]}),
    ])

    # ---- Scrollbars (slim Win11 style) ----
    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"{orient}.TScrollbar",
            background="#C7C7C7",
            troughcolor=WIN_BG,
            bordercolor=WIN_BG,
            lightcolor=WIN_BG,
            darkcolor=WIN_BG,
            arrowcolor=TEXT_MUTED,
            gripcount=0,
            relief="flat",
            arrowsize=14,
        )
        style.map(
            f"{orient}.TScrollbar",
            background=[("active", "#A6A6A6"), ("pressed", "#8E8E8E")],
        )

    # ---- PanedWindow / Sash ----
    style.configure("TPanedwindow", background=WIN_BG)
    try:
        style.configure("Sash", sashthickness=4, gripcount=0, background=BORDER)
    except tk.TclError:
        pass

    # ---- Separator ----
    style.configure("TSeparator", background=BORDER)

    # ---- Progressbar ----
    style.configure(
        "TProgressbar",
        background=ACCENT,
        troughcolor=SUBTLE_HOVER,
        bordercolor=BORDER,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )

    # ---- Tk-classic widget defaults via option DB (tk.Text / tk.Listbox / tk.Canvas / Toplevel / Menu) ----
    root.option_add("*Text.background", SURFACE_ALT)
    root.option_add("*Text.foreground", TEXT)
    root.option_add("*Text.insertBackground", TEXT)
    root.option_add("*Text.selectBackground", SELECTED_BG)
    root.option_add("*Text.selectForeground", TEXT)
    root.option_add("*Text.borderWidth", 1)
    root.option_add("*Text.relief", "solid")
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightBackground", BORDER_STRONG)
    root.option_add("*Text.highlightColor", ACCENT)
    root.option_add("*Text.font", base_font)

    root.option_add("*Listbox.background", SURFACE_ALT)
    root.option_add("*Listbox.foreground", TEXT)
    root.option_add("*Listbox.selectBackground", SELECTED_BG)
    root.option_add("*Listbox.selectForeground", TEXT)
    root.option_add("*Listbox.borderWidth", 1)
    root.option_add("*Listbox.relief", "solid")
    root.option_add("*Listbox.highlightThickness", 0)
    root.option_add("*Listbox.font", base_font)

    root.option_add("*Toplevel.background", WIN_BG)
    root.option_add("*Menu.background", SURFACE_ALT)
    root.option_add("*Menu.foreground", TEXT)
    root.option_add("*Menu.activeBackground", ACCENT_SOFT)
    root.option_add("*Menu.activeForeground", TEXT)
    root.option_add("*Menu.borderWidth", 1)
    root.option_add("*Menu.relief", "solid")
    root.option_add("*Menu.font", base_font)

    return ui
