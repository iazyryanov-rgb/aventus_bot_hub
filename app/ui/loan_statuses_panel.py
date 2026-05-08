import tkinter as tk
from tkinter import ttk
from typing import Optional

from ..data import Company
from ..i18n import t
from ..loan_statuses import (
    SECTORS,
    get_sector,
    get_statuses,
    set_sector,
)
from .colors import META_FG, TBD_FG, TEXT_FG


class LoanStatusesPanel(ttk.Frame):
    """Lists known loan statuses for the company and lets the user assign
    a sector (Collection / КЦ / —) to each status. Empty assignment is
    allowed and means «не выбрано»."""

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._editor: Optional[ttk.Combobox] = None
        self._iid_to_code: dict[str, str] = {}

        ttk.Label(
            self,
            text=t("loan_statuses_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))

        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        statuses = get_statuses(company.key)
        if not statuses:
            ttk.Label(
                self,
                text=(
                    "Статусы для этой компании ещё не описаны. "
                    "Добавьте таблицу в app/loan_statuses.py."
                ),
                foreground=META_FG,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=14, pady=20)
            return

        ttk.Label(
            self,
            text=(
                "Двойной клик по строке — выбрать сектор ответственности "
                "(Collection / КЦ / —)."
            ),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        cols = ("code", "name", "sector")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("code", text=t("loan_status_code"))
        self.tree.heading("name", text=t("loan_status_name"))
        self.tree.heading("sector", text=t("loan_status_sector"))
        self.tree.column("code", width=80, anchor="w", stretch=False)
        self.tree.column("name", width=380, anchor="w")
        self.tree.column("sector", width=200, anchor="w")
        self.tree.tag_configure("unset", foreground=TBD_FG)
        self.tree.tag_configure("set", foreground=TEXT_FG)
        scl = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")

        self.tree.bind("<Double-Button-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._maybe_close_editor, add="+")

        self._statuses = statuses
        self._sector_label_by_slug = dict(SECTORS)
        self._render()

    def _render(self) -> None:
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._iid_to_code.clear()
        # Sort numerically by code (codes are stringified ints).
        items = sorted(
            self._statuses.items(), key=lambda kv: int(kv[0])
        )
        for code, name in items:
            slug = get_sector(self._company.key, code)
            label = self._sector_label_by_slug.get(slug, "—") if slug else "—"
            tag = "set" if slug else "unset"
            iid = self.tree.insert(
                "", "end", values=(code, name, label), tags=(tag,)
            )
            self._iid_to_code[iid] = code

    # ---------- editor ----------

    def _close_editor(self) -> None:
        if self._editor is not None:
            try:
                self._editor.destroy()
            except tk.TclError:
                pass
            self._editor = None

    def _maybe_close_editor(self, event: tk.Event) -> None:
        if self._editor is None:
            return
        if event.widget is self._editor:
            return
        self._close_editor()

    def _on_double_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        code = self._iid_to_code.get(iid)
        if not code:
            return
        bbox = self.tree.bbox(iid, column="sector")
        if not bbox:
            return
        x, y, w, h = bbox
        self._close_editor()
        labels = [lbl for _slug, lbl in SECTORS]
        cb = ttk.Combobox(self.tree, values=labels, state="readonly", height=8)
        current_slug = get_sector(self._company.key, code)
        current_label = self._sector_label_by_slug.get(current_slug, "—")
        cb.set(current_label)
        cb.place(x=x, y=y, width=max(180, w), height=h)
        cb.focus_set()
        cb.bind(
            "<<ComboboxSelected>>",
            lambda _e, c=code, w=cb: self._commit(c, w),
        )
        cb.bind("<Escape>", lambda _e: self._close_editor())
        cb.bind("<FocusOut>", lambda _e, c=code, w=cb: self._commit(c, w))
        self._editor = cb

    def _commit(self, code: str, cb: ttk.Combobox) -> None:
        if self._editor is None or self._editor is not cb:
            return
        chosen_label = cb.get().strip()
        slug = next(
            (s for s, lbl in SECTORS if lbl == chosen_label),
            "",
        )
        set_sector(self._company.key, code, slug)
        self._close_editor()
        self._render()
