"""Per-company testers list (universal across bot kinds).

Lives on `CompanyPanel`. The list is read-only: a single «Sync with
Webitel» button reconciles `data/testers/<COMPANY_KEY>.json` against
the company's Webitel router schema (its `testers` page switch on
`${user}`). The hub never writes back to Webitel from this panel.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..data import Company
from ..i18n import t
from ..testers import load_testers, sync_from_router
from ..webitel import WebitelError
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
        self._sync_btn = ttk.Button(
            toolbar,
            text=t("testers_sync_btn"),
            command=self._on_sync,
        )
        self._sync_btn.pack(side="left")
        self._sync_status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._sync_status.pack(side="left", padx=(10, 0))

        cols = ("name", "phone", "destination", "active", "notes")
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="browse",
        )
        self.tree.heading("name", text=t("col_name"))
        self.tree.heading("phone", text=t("testers_col_phone"))
        self.tree.heading("destination", text=t("testers_col_destination"))
        self.tree.heading("active", text=t("testers_col_active"))
        self.tree.heading("notes", text=t("testers_col_notes"))
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("phone", width=160, anchor="w", stretch=False)
        self.tree.column("destination", width=160, anchor="w", stretch=False)
        self.tree.column("active", width=90, anchor="center", stretch=False)
        self.tree.column("notes", width=320, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")

        self._reload()

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        data = load_testers(self._company.key)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        active_yes = t("testers_active_yes")
        active_no = t("testers_active_no")
        for tester in data.get("testers") or []:
            self.tree.insert(
                "", "end",
                values=(
                    tester.get("display_name", ""),
                    tester.get("phone_e164", ""),
                    tester.get("destination", ""),
                    active_yes if tester.get("active") else active_no,
                    tester.get("notes", ""),
                ),
            )

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def _on_sync(self) -> None:
        self._sync_btn.configure(state="disabled")
        self._sync_status.configure(
            text=t("testers_sync_running"), foreground=META_FG,
        )
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self) -> None:
        try:
            report = sync_from_router(self._company.key)
        except KeyError as exc:
            self._after_sync(False, str(exc))
            return
        except WebitelError as exc:
            self._after_sync(False, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — surface anything unexpected
            self._after_sync(False, f"{type(exc).__name__}: {exc}")
            return
        msg = t("testers_sync_done").format(
            created=len(report.get("created") or []),
            updated=len(report.get("updated") or []),
            deactivated=len(report.get("deactivated") or []),
        )
        self._after_sync(True, msg)

    def _after_sync(self, ok: bool, msg: str) -> None:
        def back() -> None:
            self._sync_btn.configure(state="normal")
            if ok:
                self._sync_status.configure(text=msg, foreground=META_FG)
                self._reload()
            else:
                self._sync_status.configure(
                    text=t("testers_sync_err").format(err=msg),
                    foreground="#b00020",
                )
                messagebox.showerror(
                    t("testers_sync_btn"),
                    msg,
                    parent=self.winfo_toplevel(),
                )
        try:
            self.after(0, back)
        except tk.TclError:
            pass
