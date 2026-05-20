"""Capacity tab inside Bot → Agents.

Shows per-Collection-group caseload (G1/G2/G3) pulled live from the
company's CRM DB. Read-only — never mutates anything. Per-agent
capacity targets (250 / 300 / 500) come from `app.capacity`.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..capacity import CapacityUnavailable, compute_capacity
from ..data import Company
from ..i18n import t
from .colors import ERR_FG, META_FG, OK_FG, TEXT_FG


class CapacityPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company

        ttk.Label(
            self,
            text=t("capacity_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=14, pady=(0, 6))
        self._refresh_btn = ttk.Button(
            toolbar, text=t("btn_refresh"), command=self._on_refresh,
        )
        self._refresh_btn.pack(side="left")
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(10, 0))

        cols = ("agents", "loans", "max", "target", "needed")
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="tree headings",
            selectmode="browse", height=12,
        )
        self.tree.heading("#0",     text=t("capacity_col_group"))
        self.tree.heading("agents", text=t("capacity_col_agents"))
        self.tree.heading("loans",  text=t("capacity_col_loans"))
        self.tree.heading("max",    text=t("capacity_col_max"))
        self.tree.heading("target", text=t("capacity_col_target"))
        self.tree.heading("needed", text=t("capacity_col_needed"))
        self.tree.column("#0",     width=260, anchor="w", stretch=False)
        self.tree.column("agents", width=110, anchor="center", stretch=False)
        self.tree.column("loans",  width=170, anchor="center", stretch=False)
        self.tree.column("max",    width=160, anchor="center", stretch=False)
        self.tree.column("target", width=140, anchor="center", stretch=False)
        self.tree.column("needed", width=140, anchor="center", stretch=False)
        self.tree.tag_configure("over",  foreground=ERR_FG)
        self.tree.tag_configure("ok",    foreground=OK_FG)
        self.tree.tag_configure("muted", foreground=META_FG)
        self.tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")

        # Auto-fetch once on open so the operator sees current numbers
        # without an extra click.
        self._on_refresh()

    # ------------------------------------------------------------------
    # Refresh / worker
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self._refresh_btn.configure(state="disabled")
        self._status.configure(text=t("capacity_loading"), foreground=META_FG)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            stats = compute_capacity(self._company)
        except CapacityUnavailable as e:
            self._after(False, str(e), [])
            return
        except Exception as e:  # noqa: BLE001 — surface anything unexpected
            self._after(False, f"{type(e).__name__}: {e}", [])
            return
        self._after(True, "", stats)

    def _after(self, ok: bool, msg: str, stats: list) -> None:
        def back() -> None:
            self._refresh_btn.configure(state="normal")
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            if not ok:
                self._status.configure(
                    text=msg, foreground=ERR_FG,
                )
                return
            total_loans = sum(g.loans for g in stats)
            total_agents = sum(g.agents for g in stats)
            total_needed = sum(g.needed for g in stats if g.needed)
            for g in stats:
                target_txt = (
                    f"{g.target_per_agent} / агент"
                    if g.target_per_agent else "—"
                )
                if g.needed is None:
                    needed_txt = "—"
                else:
                    needed_txt = str(g.needed)
                # Colour-code: red if max-per-agent already over capacity
                # target; muted for G3+ (no target); ok otherwise.
                if g.target_per_agent is None:
                    tag = "muted"
                elif g.max_per_agent > g.target_per_agent:
                    tag = "over"
                else:
                    tag = "ok"
                max_txt = str(g.max_per_agent)
                if g.target_per_agent and g.max_per_agent > g.target_per_agent:
                    max_txt = f"{g.max_per_agent}  (> {g.target_per_agent})"
                dpd_lbl = (
                    f"DPD {g.dpd_from}..{g.dpd_to if g.dpd_to is not None else '+'}"
                )
                parent_iid = self.tree.insert(
                    "", "end",
                    text=f"{g.name} · {dpd_lbl}",
                    values=(
                        g.agents,
                        g.loans,
                        max_txt,
                        target_txt,
                        needed_txt,
                    ),
                    tags=(tag,),
                    open=True,
                )
                for o in g.outsource:
                    self.tree.insert(
                        parent_iid, "end",
                        text=f"    └ {o.display_name}",
                        values=(
                            "—",
                            f"{o.loans}  ({o.pct:.1f}%)",
                            "—",
                            "—",
                            "—",
                        ),
                        tags=("muted",),
                    )
            self._status.configure(
                text=t("capacity_summary").format(
                    agents=total_agents,
                    loans=total_loans,
                    needed=total_needed,
                ),
                foreground=TEXT_FG,
            )
        try:
            self.after(0, back)
        except tk.TclError:
            pass
