"""Per-company testers list (universal across bot kinds).

Lives on `CompanyPanel`. Reads/writes `data/testers/<COMPANY_KEY>.json` via
`app.testers`. CRUD on the testers list, plus a checkbox-equivalent button
to mark one tester as the company default.
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..data import Company
from ..i18n import t
from ..testers import (
    ENVIRONMENTS,
    delete_tester,
    load_testers,
    make_tester_id,
    set_default_tester,
    upsert_tester,
)
from .colors import META_FG


class TestersPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company

        ttk.Label(
            self,
            text=t("testers_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))
        ttk.Label(
            self,
            text=t("testers_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Button(toolbar, text=t("btn_add"), command=self._add).pack(side="left")
        self._edit_btn = ttk.Button(
            toolbar, text=t("btn_edit"), command=self._edit, state="disabled"
        )
        self._edit_btn.pack(side="left", padx=(8, 0))
        self._del_btn = ttk.Button(
            toolbar, text=t("btn_delete"), command=self._delete, state="disabled"
        )
        self._del_btn.pack(side="left", padx=(8, 0))
        self._default_btn = ttk.Button(
            toolbar,
            text=t("testers_make_default"),
            command=self._make_default,
            state="disabled",
        )
        self._default_btn.pack(side="left", padx=(8, 0))

        cols = (
            "name", "phone", "destination", "environment",
            "owner", "default", "notes",
        )
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="browse",
        )
        self.tree.heading("name", text=t("col_name"))
        self.tree.heading("phone", text=t("testers_col_phone"))
        self.tree.heading("destination", text=t("testers_col_destination"))
        self.tree.heading("environment", text=t("testers_col_env"))
        self.tree.heading("owner", text=t("testers_col_owner"))
        self.tree.heading("default", text=t("testers_col_default"))
        self.tree.heading("notes", text=t("testers_col_notes"))
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("phone", width=140, anchor="w", stretch=False)
        self.tree.column("destination", width=140, anchor="w", stretch=False)
        self.tree.column("environment", width=90, anchor="w", stretch=False)
        self.tree.column("owner", width=180, anchor="w")
        self.tree.column("default", width=80, anchor="center", stretch=False)
        self.tree.column("notes", width=300, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_buttons())
        self.tree.bind("<Double-Button-1>", lambda _e: self._edit())

        self._row_to_tester: dict[str, dict] = {}
        self._reload()

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        data = load_testers(self._company.key)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_tester.clear()
        default_id = data.get("default_tester_id") or ""
        for tester in data.get("testers") or []:
            tid = tester.get("id", "")
            iid = self.tree.insert(
                "", "end",
                values=(
                    tester.get("display_name", ""),
                    tester.get("phone_e164", ""),
                    tester.get("destination", ""),
                    tester.get("environment", ""),
                    tester.get("test_owner_key", ""),
                    t("testers_default_marker") if tid and tid == default_id else "",
                    tester.get("notes", ""),
                ),
            )
            self._row_to_tester[iid] = tester
        self._update_buttons()

    def _selected(self) -> Optional[dict]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._row_to_tester.get(sel[0])

    def _update_buttons(self) -> None:
        st = "normal" if self._selected() else "disabled"
        self._edit_btn.configure(state=st)
        self._del_btn.configure(state=st)
        self._default_btn.configure(state=st)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add(self) -> None:
        TesterEditDialog(self, self._company, None, on_saved=self._on_saved)

    def _edit(self) -> None:
        tester = self._selected()
        if not tester:
            return
        TesterEditDialog(self, self._company, tester, on_saved=self._on_saved)

    def _delete(self) -> None:
        tester = self._selected()
        if not tester:
            return
        name = tester.get("display_name") or tester.get("id", "")
        if not messagebox.askyesno(
            t("testers_confirm_delete"),
            f"{t('testers_confirm_delete')}\n\n{name}",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            delete_tester(self._company.key, tester.get("id", ""))
        except OSError as exc:
            messagebox.showerror(
                "Error", str(exc), parent=self.winfo_toplevel(),
            )
            return
        self._reload()

    def _make_default(self) -> None:
        tester = self._selected()
        if not tester:
            return
        try:
            set_default_tester(self._company.key, tester.get("id", ""))
        except OSError as exc:
            messagebox.showerror(
                "Error", str(exc), parent=self.winfo_toplevel(),
            )
            return
        self._reload()

    def _on_saved(self, _tester: dict) -> None:
        self._reload()


class TesterEditDialog(tk.Toplevel):
    """Modal-ish edit dialog. Single column form, autoderives `destination`
    from `phone_e164` when destination is empty on save."""

    def __init__(
        self,
        master: tk.Misc,
        company: Company,
        tester: Optional[dict],
        on_saved=None,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._tester = dict(tester) if tester else {}
        self._on_saved = on_saved

        self.title(
            t("testers_dialog_edit") if tester else t("testers_dialog_add")
        )
        try:
            self.transient(master.winfo_toplevel())
        except tk.TclError:
            pass
        self.resizable(False, False)

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        row = 0
        self._name_var = self._add_entry(frm, row, t("testers_field_name"), self._tester.get("display_name", ""))
        row += 1
        self._phone_var = self._add_entry(frm, row, t("testers_field_phone"), self._tester.get("phone_e164", ""))
        row += 1
        self._dest_var = self._add_entry(frm, row, t("testers_field_destination"), self._tester.get("destination", ""))
        row += 1

        ttk.Label(frm, text=t("testers_field_env") + ":").grid(
            row=row, column=0, sticky="w", pady=2,
        )
        self._env_var = tk.StringVar(value=self._tester.get("environment") or "prod")
        ttk.Combobox(
            frm,
            textvariable=self._env_var,
            values=ENVIRONMENTS,
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        self._owner_var = self._add_entry(frm, row, t("testers_field_owner"), self._tester.get("test_owner_key", ""))
        row += 1

        ttk.Label(frm, text=t("testers_field_notes") + ":").grid(
            row=row, column=0, sticky="nw", pady=2,
        )
        self._notes_text = tk.Text(frm, width=44, height=4, wrap="word")
        self._notes_text.grid(row=row, column=1, sticky="ew", pady=2)
        self._notes_text.insert("1.0", self._tester.get("notes", "") or "")
        row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text=t("btn_save"), command=self._save).pack(
            side="left", padx=(0, 6),
        )
        ttk.Button(btns, text=t("btn_cancel"), command=self.destroy).pack(
            side="left",
        )

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())

    @staticmethod
    def _add_entry(parent: ttk.Frame, row: int, label: str, value: str) -> tk.StringVar:
        ttk.Label(parent, text=label + ":").grid(
            row=row, column=0, sticky="w", pady=2,
        )
        var = tk.StringVar(value=value or "")
        ttk.Entry(parent, textvariable=var, width=44).grid(
            row=row, column=1, sticky="ew", pady=2,
        )
        return var

    def _save(self) -> None:
        name = self._name_var.get().strip()
        phone = self._phone_var.get().strip()
        dest = self._dest_var.get().strip()
        if not name or (not phone and not dest):
            messagebox.showwarning(
                self.title() or "—",
                t("testers_required_fields"),
                parent=self,
            )
            return
        if not dest and phone:
            dest = re.sub(r"\D", "", phone)
        notes = self._notes_text.get("1.0", "end").rstrip()
        record = {
            **self._tester,
            "display_name": name,
            "phone_e164": phone,
            "destination": dest,
            "environment": self._env_var.get().strip() or "prod",
            "test_owner_key": self._owner_var.get().strip(),
            "company": self._company.name,
            "notes": notes,
        }
        if not record.get("id"):
            record["id"] = make_tester_id(name, dest)
        try:
            upsert_tester(self._company.key, record)
        except OSError as exc:
            messagebox.showerror(self.title() or "—", str(exc), parent=self)
            return
        if self._on_saved:
            self._on_saved(record)
        self.destroy()
