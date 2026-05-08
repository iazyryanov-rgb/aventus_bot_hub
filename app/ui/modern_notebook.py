"""Custom flat tab widget — drop-in for the slice of ``ttk.Notebook`` we use.

`ttk.Notebook` under the `clam` base theme paints tabs with a 3D bevel
(light/dark facets baked into the `Notebook.tab` element), which is what
made our tabs look "pressed in" no matter the color settings. Borrowing
the flat tab from the `default` theme only helped a little — the tab
strip still looked boxy and unmodern.

`ModernNotebook` ditches `ttk.Notebook` and renders tabs as plain Tk
widgets so we get full control: a flat strip of text-buttons, a 2px
accent underline beneath the selected tab, a subtle hover background,
and a 1px separator line below the tab strip.

Public API mirrors the parts of ``ttk.Notebook`` we actually use:
  * ``add(widget, text="...")`` — child widgets must be created with the
    notebook itself as their master (same as `ttk.Notebook`).
  * ``select(index)`` — switch to the given tab.

Each page is geometry-managed inside the notebook's body via
``pack(in_=...)``, so children stay logical descendants of the notebook
(destroying the notebook tears them down) without needing reparenting.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .theme import (
    ACCENT,
    BORDER,
    SUBTLE_HOVER,
    TEXT,
    TEXT_MUTED,
    WIN_BG,
)


class ModernNotebook(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)

        self._bar = tk.Frame(self, bg=WIN_BG, highlightthickness=0, bd=0)
        self._bar.pack(fill="x", side="top")

        self._sep = tk.Frame(self, bg=BORDER, height=1, highlightthickness=0, bd=0)
        self._sep.pack(fill="x", side="top")

        self._body = ttk.Frame(self)
        self._body.pack(fill="both", expand=True, pady=(6, 0))

        ui_family = tkfont.nametofont("TkDefaultFont").cget("family")
        self._font = (ui_family, 9)

        self._tabs: list[dict] = []
        self._current: int = -1

    # ----- Public API ----------------------------------------------------

    def add(self, widget: tk.Widget, text: str = "") -> None:
        idx = len(self._tabs)

        btn = tk.Frame(self._bar, bg=WIN_BG, highlightthickness=0, bd=0, cursor="hand2")
        lbl = tk.Label(
            btn,
            text=text,
            bg=WIN_BG,
            fg=TEXT_MUTED,
            font=self._font,
            padx=12,
            pady=6,
        )
        lbl.pack(side="top", fill="x")
        # The accent indicator is a 2px-tall strip at the bottom of the tab.
        # When the tab is selected we recolor it to ACCENT; otherwise it
        # blends into the bar (WIN_BG) so the strip's height stays constant
        # and tabs don't jiggle on selection change.
        indicator = tk.Frame(btn, bg=WIN_BG, height=2, highlightthickness=0, bd=0)
        indicator.pack(side="bottom", fill="x")
        btn.pack(side="left")

        for w in (btn, lbl, indicator):
            w.bind("<Enter>", lambda _e, i=idx: self._on_enter(i))
            w.bind("<Leave>", lambda _e, i=idx: self._on_leave(i))
            w.bind("<Button-1>", lambda _e, i=idx: self.select(i))

        self._tabs.append({"btn": btn, "lbl": lbl, "indicator": indicator, "page": widget})

        if idx == 0:
            self.select(0)

    def select(self, idx: int) -> None:
        if idx == self._current or not (0 <= idx < len(self._tabs)):
            return
        if self._current >= 0:
            self._tabs[self._current]["page"].pack_forget()
            self._paint(self._current, selected=False, hover=False)
        page = self._tabs[idx]["page"]
        page.pack(in_=self._body, fill="both", expand=True)
        self._paint(idx, selected=True)
        self._current = idx

    # ----- Internals -----------------------------------------------------

    def _paint(self, idx: int, *, selected: bool, hover: bool = False) -> None:
        tab = self._tabs[idx]
        if selected:
            bg, fg, ind = WIN_BG, ACCENT, ACCENT
        elif hover:
            bg, fg, ind = SUBTLE_HOVER, TEXT, SUBTLE_HOVER
        else:
            bg, fg, ind = WIN_BG, TEXT_MUTED, WIN_BG
        tab["btn"].configure(bg=bg)
        tab["lbl"].configure(bg=bg, fg=fg)
        tab["indicator"].configure(bg=ind)

    def _on_enter(self, idx: int) -> None:
        if idx != self._current:
            self._paint(idx, selected=False, hover=True)

    def _on_leave(self, idx: int) -> None:
        if idx != self._current:
            self._paint(idx, selected=False, hover=False)
