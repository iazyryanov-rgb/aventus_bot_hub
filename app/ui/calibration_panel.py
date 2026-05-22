"""Calibration tab: operator's control room for the auto-calibration loop.

Sections:
  * Status     — champion / candidate / router schema ids; cycle-paused
                 banner with Resume button when applicable.
  * Cycle config — enabled / approval_mode / target_goal / max_changes /
                   min_lift_pct / large_change_threshold / dry_run.
  * Approval queue — Treeview of items awaiting approval; per-row diff
                     popup; Apply / Reject / Refresh buttons.
  * Apply history  — Treeview of recent _webitel_apply log files;
                     Rollback selected (restores `snapshot_before`).

All side effects are routed through `app.calibration_cycle` and
`app.calibration_apply` — this file only renders + dispatches.
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from .. import calibration_apply as ca
from .. import calibration_cycle as cc
from ..audit_storage import _history_dir as audit_history_dir
from ..bot_alert_consumer import list_alerts as list_bot_alerts
from ..data import Company
from ..i18n import t
from ..router_schema import get_router_schema
from ..wa_bot_config import get_candidate_schema, get_prod_schema
from .colors import META_FG, OK_FG, ERR_FG, TEXT_FG


APPROVAL_MODES = ("auto", "gated", "off")
TARGET_GOALS = ("fully_pay", "prolong", "both")


class CalibrationPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company

        self._build_header()
        self._build_status_section()
        self._build_config_section()
        self._build_queue_section()
        self._build_history_section()
        self._build_bot_inbox_section()

        self.refresh()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        ttk.Label(
            self, text=t("calib_header"),
            font=("Segoe UI", 9, "bold"), foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = self._company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {self._company.name} ({self._company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 6))
    def _build_status_section(self) -> None:
        sec = ttk.LabelFrame(self, text=t("calib_section_status"), padding=10)
        sec.pack(fill="x", padx=12, pady=(8, 4))
        sec.columnconfigure(1, weight=1)

        self._lbl_champion = self._row(sec, 0, t("calib_field_champion"))
        self._lbl_candidate = self._row(sec, 1, t("calib_field_candidate"))
        self._lbl_router = self._row(sec, 2, t("calib_field_router"))

        # Promotion toolbar — destructive on champion, kept compact.
        promo_frame = ttk.Frame(sec)
        promo_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._promote_btn = ttk.Button(
            promo_frame,
            text="Promote candidate → champion",
            command=self._on_promote,
        )
        self._promote_btn.pack(side="left")
        ttk.Label(
            promo_frame,
            text=("Pushes the candidate schema's payload onto the "
                  "champion id. Keeps id stable so the router/gate setup "
                  "stays valid."),
            foreground=META_FG, wraplength=600, justify="left",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(10, 0))

        # Paused banner — shown only when paused.
        self._paused_frame = ttk.Frame(sec)
        self._paused_label = ttk.Label(
            self._paused_frame, text="", foreground=ERR_FG,
            wraplength=720, justify="left",
            font=("Segoe UI", 9, "bold"),
        )
        self._paused_label.pack(side="left", padx=(0, 10))
        self._resume_btn = ttk.Button(
            self._paused_frame, text=t("calib_resume"),
            command=self._on_resume,
        )
        self._resume_btn.pack(side="left")

    def _row(self, parent: ttk.LabelFrame, r: int, label: str) -> ttk.Label:
        ttk.Label(parent, text=label + ":", foreground=META_FG).grid(
            row=r, column=0, sticky="w", padx=(0, 8), pady=2,
        )
        val = ttk.Label(parent, text="—", foreground=TEXT_FG)
        val.grid(row=r, column=1, sticky="w", pady=2)
        return val

    def _build_config_section(self) -> None:
        sec = ttk.LabelFrame(self, text=t("calib_section_config"), padding=10)
        sec.pack(fill="x", padx=12, pady=(4, 4))

        self._cfg_enabled = tk.BooleanVar()
        self._cfg_dry_run = tk.BooleanVar()
        self._cfg_mode = tk.StringVar(value="auto")
        self._cfg_goal = tk.StringVar(value="fully_pay")
        self._cfg_max_changes = tk.IntVar(value=3)
        self._cfg_min_lift = tk.IntVar(value=5)
        self._cfg_large_thresh = tk.IntVar(value=30)

        row = ttk.Frame(sec)
        row.pack(fill="x", pady=(0, 4))
        ttk.Checkbutton(
            row, text=t("calib_cfg_enabled"), variable=self._cfg_enabled,
        ).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(
            row, text=t("calib_cfg_dry_run"), variable=self._cfg_dry_run,
        ).pack(side="left", padx=(0, 12))

        row2 = ttk.Frame(sec)
        row2.pack(fill="x", pady=(0, 4))
        ttk.Label(row2, text=t("calib_cfg_mode") + ":").pack(side="left")
        ttk.Combobox(
            row2, textvariable=self._cfg_mode,
            values=APPROVAL_MODES, state="readonly", width=10,
        ).pack(side="left", padx=(4, 16))
        ttk.Label(row2, text=t("calib_cfg_target_goal") + ":").pack(side="left")
        ttk.Combobox(
            row2, textvariable=self._cfg_goal,
            values=TARGET_GOALS, state="readonly", width=12,
        ).pack(side="left", padx=(4, 16))

        row3 = ttk.Frame(sec)
        row3.pack(fill="x", pady=(0, 4))
        ttk.Label(row3, text=t("calib_cfg_max_changes") + ":").pack(side="left")
        ttk.Spinbox(
            row3, from_=1, to=20, textvariable=self._cfg_max_changes, width=6,
        ).pack(side="left", padx=(4, 16))
        ttk.Label(row3, text=t("calib_cfg_min_lift") + ":").pack(side="left")
        ttk.Spinbox(
            row3, from_=0, to=100, textvariable=self._cfg_min_lift, width=6,
        ).pack(side="left", padx=(4, 16))
        ttk.Label(row3, text=t("calib_cfg_large_thresh") + ":").pack(side="left")
        ttk.Spinbox(
            row3, from_=10, to=100, textvariable=self._cfg_large_thresh, width=6,
        ).pack(side="left", padx=(4, 16))
        ttk.Button(
            row3, text=t("calib_cfg_save"), command=self._on_save_config,
        ).pack(side="right")

    def _build_queue_section(self) -> None:
        sec = ttk.LabelFrame(self, text=t("calib_section_queue"), padding=10)
        sec.pack(fill="both", expand=True, padx=12, pady=(4, 4))

        toolbar = ttk.Frame(sec)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(
            toolbar, text="Apply pending now",
            command=self._on_process_pending,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text=t("calib_queue_refresh"), command=self._reload_queue,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text=t("calib_queue_show_diff"), command=self._show_queue_diff,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text=t("calib_queue_approve"), command=self._on_approve,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text=t("calib_queue_reject"), command=self._on_reject,
        ).pack(side="left", padx=(0, 6))
        self._queue_status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._queue_status.pack(side="right")

        cols = ("queue_id", "rec_id", "applies_to", "goal", "lift", "warn", "audit_id")
        self._queue_tree = ttk.Treeview(
            sec, columns=cols, show="headings", height=8, selectmode="extended",
        )
        for col, label, w in (
            ("queue_id", "queue_id", 120),
            ("rec_id", "rec_id", 100),
            ("applies_to", "applies_to", 320),
            ("goal", "goal", 90),
            ("lift", "lift %", 60),
            ("warn", "⚠", 30),
            ("audit_id", "audit_id", 130),
        ):
            self._queue_tree.heading(col, text=label)
            self._queue_tree.column(col, width=w, anchor="w")
        self._queue_tree.pack(fill="both", expand=True)
        self._queue_tree.bind("<Double-1>", lambda _e: self._show_queue_diff())

    def _build_history_section(self) -> None:
        sec = ttk.LabelFrame(self, text=t("calib_section_history"), padding=10)
        sec.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        toolbar = ttk.Frame(sec)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(
            toolbar, text=t("calib_queue_refresh"), command=self._reload_history,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text=t("calib_history_open_log"), command=self._open_log,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text=t("calib_history_rollback"), command=self._on_rollback,
        ).pack(side="left", padx=(0, 6))
        self._history_status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._history_status.pack(side="right")

        cols = ("ts", "schema_id", "patches", "new_updated", "log_file")
        self._history_tree = ttk.Treeview(
            sec, columns=cols, show="headings", height=8, selectmode="browse",
        )
        for col, label, w in (
            ("ts", "ts (UTC)", 150),
            ("schema_id", "schema", 70),
            ("patches", "patches", 70),
            ("new_updated", "new_updated_at", 130),
            ("log_file", "log file", 480),
        ):
            self._history_tree.heading(col, text=label)
            self._history_tree.column(col, width=w, anchor="w")
        self._history_tree.pack(fill="both", expand=True)

    def _build_bot_inbox_section(self) -> None:
        sec = ttk.LabelFrame(self, text="Bot alerts inbox", padding=10)
        sec.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        toolbar = ttk.Frame(sec)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(
            toolbar, text=t("calib_queue_refresh"), command=self._reload_inbox,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            toolbar, text="Open record", command=self._open_inbox_record,
        ).pack(side="left", padx=(0, 6))
        self._inbox_status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._inbox_status.pack(side="right")

        cols = ("ts", "kind", "schema_id", "schema_role", "stage", "destination", "chat_id")
        self._inbox_tree = ttk.Treeview(
            sec, columns=cols, show="headings", height=8, selectmode="browse",
        )
        for col, label, w in (
            ("ts", "ts (UTC)", 150),
            ("kind", "kind", 160),
            ("schema_id", "schema", 70),
            ("schema_role", "role", 90),
            ("stage", "stage", 160),
            ("destination", "destination", 130),
            ("chat_id", "chat_id", 200),
        ):
            self._inbox_tree.heading(col, text=label)
            self._inbox_tree.column(col, width=w, anchor="w")
        self._inbox_tree.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._reload_status()
        self._reload_config()
        self._reload_queue()
        self._reload_history()
        self._reload_inbox()

    def _reload_status(self) -> None:
        co = self._company
        cn, cid = get_prod_schema(co.key)
        candn, candid = get_candidate_schema(co.key)
        rn, rid = get_router_schema(co.key)
        self._lbl_champion.configure(
            text=f"id={cid} · {cn or '—'}" if cid else "—"
        )
        self._lbl_candidate.configure(
            text=f"id={candid} · {candn or '—'}" if candid else "—"
        )
        self._lbl_router.configure(
            text=f"id={rid} · {rn or '—'}" if rid else "—"
        )
        cfg = cc.load_cycle_config(co.key)
        if cfg.get("paused_reason"):
            self._paused_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            self._paused_label.configure(
                text=f"{t('calib_field_paused')}: {cfg.get('paused_reason')}",
            )
        else:
            self._paused_frame.grid_forget()

    def _reload_config(self) -> None:
        cfg = cc.load_cycle_config(self._company.key)
        self._cfg_enabled.set(bool(cfg.get("enabled")))
        self._cfg_dry_run.set(bool(cfg.get("dry_run")))
        self._cfg_mode.set(str(cfg.get("approval_mode") or "auto"))
        self._cfg_goal.set(str(cfg.get("target_goal") or "fully_pay"))
        try:
            self._cfg_max_changes.set(int(cfg.get("max_changes_per_run") or 3))
            self._cfg_min_lift.set(int(cfg.get("min_lift_pct") or 5))
            self._cfg_large_thresh.set(int(cfg.get("large_change_threshold_pct") or 30))
        except (TypeError, ValueError):
            pass

    def _reload_queue(self) -> None:
        self._queue_tree.delete(*self._queue_tree.get_children())
        items = cc.load_approval_queue(self._company.key)
        if not items:
            self._queue_status.configure(text=t("calib_queue_empty"))
            return
        for it in items:
            warn = "⚠" if it.get("large_change_warning") else ""
            self._queue_tree.insert(
                "", "end",
                iid=it.get("queue_id", ""),
                values=(
                    it.get("queue_id", ""),
                    it.get("rec_id", ""),
                    it.get("applies_to", ""),
                    it.get("goal", ""),
                    f"+{int(it.get('expected_lift_pct') or 0)}",
                    warn,
                    it.get("audit_id", ""),
                ),
            )
        self._queue_status.configure(text=f"{len(items)} item(s)")

    def _reload_history(self) -> None:
        self._history_tree.delete(*self._history_tree.get_children())
        folder = audit_history_dir(self._company.key) / "_webitel_apply"
        if not folder.exists():
            self._history_status.configure(text=t("calib_history_empty"))
            return
        files = sorted(folder.glob("*.json"), reverse=True)[:50]
        if not files:
            self._history_status.configure(text=t("calib_history_empty"))
            return
        for f in files:
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            ts = datetime.fromtimestamp(
                int(rec.get("ts_ms") or 0) / 1000
            ).strftime("%Y-%m-%d %H:%M:%S") if rec.get("ts_ms") else f.stem
            self._history_tree.insert(
                "", "end", iid=str(f),
                values=(
                    ts,
                    rec.get("schema_id", ""),
                    len(rec.get("patches") or []),
                    rec.get("new_updated_at") or "",
                    str(f),
                ),
            )
        self._history_status.configure(text=f"{len(files)} file(s)")

    def _reload_inbox(self) -> None:
        self._inbox_tree.delete(*self._inbox_tree.get_children())
        items = list_bot_alerts(self._company.key, limit=100)
        if not items:
            self._inbox_status.configure(text="empty (consumer running, awaiting bot alerts)")
            return
        for rec in items:
            payload = rec.get("payload") or {}
            received_ts = int(rec.get("received_at_ms") or 0)
            ts = datetime.fromtimestamp(received_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if received_ts else "?"
            self._inbox_tree.insert(
                "", "end",
                iid=str(rec.get("_path", "")),
                values=(
                    ts,
                    payload.get("kind", ""),
                    payload.get("schema_id", ""),
                    payload.get("schema_role", ""),
                    payload.get("stage", ""),
                    payload.get("destination", ""),
                    (payload.get("chat_id") or "")[:30],
                ),
            )
        self._inbox_status.configure(text=f"{len(items)} record(s)")

    def _open_inbox_record(self) -> None:
        sel = self._inbox_tree.selection()
        if not sel:
            messagebox.showinfo(
                "Bot alert", t("calib_select_first"),
                parent=self.winfo_toplevel(),
            )
            return
        path = Path(sel[0])
        if path.exists():
            import os
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_save_config(self) -> None:
        cfg = cc.load_cycle_config(self._company.key)
        cfg["enabled"] = bool(self._cfg_enabled.get())
        cfg["dry_run"] = bool(self._cfg_dry_run.get())
        cfg["approval_mode"] = self._cfg_mode.get()
        cfg["target_goal"] = self._cfg_goal.get()
        try:
            cfg["max_changes_per_run"] = max(1, int(self._cfg_max_changes.get()))
            cfg["min_lift_pct"] = max(0, int(self._cfg_min_lift.get()))
            cfg["large_change_threshold_pct"] = max(10, int(self._cfg_large_thresh.get()))
        except (TypeError, ValueError):
            messagebox.showerror(
                t("calib_cfg_save"), "Invalid numeric input",
                parent=self.winfo_toplevel(),
            )
            return
        # If user toggled enabled=true while paused — clear paused state.
        if cfg["enabled"]:
            cfg.pop("paused_reason", None)
            cfg.pop("paused_at_ms", None)
        try:
            cc.save_cycle_config(self._company.key, cfg)
        except OSError as e:
            messagebox.showerror(
                t("calib_cfg_save"), f"Could not save: {e}",
                parent=self.winfo_toplevel(),
            )
            return
        self._reload_status()

    def _on_resume(self) -> None:
        cfg = cc.load_cycle_config(self._company.key)
        cfg["enabled"] = True
        cfg.pop("paused_reason", None)
        cfg.pop("paused_at_ms", None)
        try:
            cc.save_cycle_config(self._company.key, cfg)
        except OSError as e:
            messagebox.showerror(
                t("calib_resume"), f"Could not save: {e}",
                parent=self.winfo_toplevel(),
            )
            return
        self.refresh()

    def _selected_queue_ids(self) -> list[str]:
        return list(self._queue_tree.selection())

    def _show_queue_diff(self) -> None:
        sel = self._selected_queue_ids()
        if not sel:
            messagebox.showinfo(
                t("calib_queue_show_diff"), t("calib_select_first"),
                parent=self.winfo_toplevel(),
            )
            return
        items = cc.load_approval_queue(self._company.key)
        by_qid = {it.get("queue_id"): it for it in items}
        item = by_qid.get(sel[0])
        if not item:
            return
        self._open_diff_dialog(item)

    def _open_diff_dialog(self, item: dict) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(t("calib_diff_title"))
        try:
            dlg.transient(self.winfo_toplevel())
        except tk.TclError:
            pass
        dlg.geometry("900x600")
        head = ttk.Frame(dlg, padding=10)
        head.pack(fill="x")
        ttk.Label(
            head,
            text=f"queue_id={item.get('queue_id')} · rec_id={item.get('rec_id')}\n"
                 f"applies_to: {item.get('applies_to')}\n"
                 f"goal={item.get('goal')} · lift=+{item.get('expected_lift_pct')}% · "
                 f"kind={item.get('kind')} · large_warning={item.get('large_change_warning')}",
            font=("Segoe UI", 9), foreground=META_FG, justify="left",
        ).pack(anchor="w")
        if item.get("rationale"):
            ttk.Label(
                head, text=f"Why: {item.get('rationale')}",
                wraplength=860, justify="left",
            ).pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        ttk.Label(body, text="— BEFORE —", foreground=ERR_FG,
                  font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="+ AFTER +", foreground=OK_FG,
                  font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w")

        before_box = tk.Text(body, wrap="word", font=("Consolas", 9))
        before_box.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        before_box.insert("1.0", item.get("before") or "")
        before_box.configure(state="disabled")
        after_box = tk.Text(body, wrap="word", font=("Consolas", 9))
        after_box.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        after_box.insert("1.0", item.get("after") or "")
        after_box.configure(state="disabled")

        ttk.Button(dlg, text="OK", command=dlg.destroy).pack(pady=(0, 10))

    def _on_promote(self) -> None:
        # Confirm — this overwrites the champion (prod) schema.
        if not messagebox.askyesno(
            "Promote candidate → champion",
            "Это перезапишет champion-схему (prod) содержимым candidate. "
            "Snapshots сохранятся, можно откатить через History → Rollback. "
            "Продолжить?",
            parent=self.winfo_toplevel(),
        ):
            return
        self._set_busy(True)

        def work() -> None:
            try:
                res = ca.promote_candidate(self._company.key)
            except Exception as e:  # noqa: BLE001
                self._after_promote_done(False, f"{type(e).__name__}: {e}")
                return
            if res.ok:
                msg = (
                    f"OK — champion id={res.champion_id} updated.\n"
                    f"snapshot_before: {res.snapshot_champion_before}\n"
                    f"snapshot_after:  {res.snapshot_champion_after}\n"
                    f"new_updated_at:  {res.new_updated_at}"
                )
            else:
                msg = res.error or "unknown error"
            self._after_promote_done(res.ok, msg)

        threading.Thread(target=work, daemon=True).start()

    def _after_promote_done(self, ok: bool, msg: str) -> None:
        def back() -> None:
            self._set_busy(False)
            (messagebox.showinfo if ok else messagebox.showerror)(
                "Promote candidate → champion", msg,
                parent=self.winfo_toplevel(),
            )
            self.refresh()
        try:
            self.after(0, back)
        except tk.TclError:
            pass

    def _on_process_pending(self) -> None:
        # Long-running: hits Webitel preview + (auto mode) push. Run on a
        # background thread, modal-feedback when done.
        self._set_busy(True)

        def work() -> None:
            try:
                res = cc.process_pending_now(self._company.key)
            except Exception as e:  # noqa: BLE001
                self._after_process_done(False, f"{type(e).__name__}: {e}")
                return
            if res.skipped:
                self._after_process_done(True, f"skipped: {res.reason}")
            elif res.cycle_paused:
                self._after_process_done(False, f"PAUSED: {res.apply_error}")
            elif res.queued_count:
                self._after_process_done(
                    True,
                    f"queued {res.queued_count} item(s) for approval — "
                    f"see the list below.",
                )
            elif res.apply_ok:
                self._after_process_done(
                    True, f"applied {len(res.applied_rec_ids)} item(s)",
                )
            else:
                self._after_process_done(
                    False, res.apply_error or "unknown error",
                )

        threading.Thread(target=work, daemon=True).start()

    def _after_process_done(self, ok: bool, msg: str) -> None:
        def back() -> None:
            self._set_busy(False)
            (messagebox.showinfo if ok else messagebox.showerror)(
                "Apply pending now", msg,
                parent=self.winfo_toplevel(),
            )
            self.refresh()
        try:
            self.after(0, back)
        except tk.TclError:
            pass

    def _on_approve(self) -> None:
        sel = self._selected_queue_ids()
        if not sel:
            messagebox.showinfo(
                t("calib_queue_approve"), t("calib_select_first"),
                parent=self.winfo_toplevel(),
            )
            return
        self._do_approve(sel, strict_before=True)

    def _do_approve(self, sel: list[str], *, strict_before: bool) -> None:
        self._set_busy(True)

        def work() -> None:
            try:
                decision = cc.approve_pending(
                    self._company.key, sel,
                    strict_before=strict_before,
                )
            except Exception as e:  # noqa: BLE001
                self._after_apply_done(False, f"{type(e).__name__}: {e}", sel)
                return
            self._after_apply_done(
                decision.apply_ok, decision.apply_error or "ok",
                sel, force_offered=strict_before,
            )

        threading.Thread(target=work, daemon=True).start()

    def _after_apply_done(
        self, ok: bool, msg: str,
        sel: Optional[list[str]] = None,
        *, force_offered: bool = True,
    ) -> None:
        is_stale = (
            not ok and force_offered
            and msg and "Stale recommendation" in msg
        )

        def back() -> None:
            self._set_busy(False)
            if ok:
                messagebox.showinfo(
                    t("calib_queue_approve"), msg,
                    parent=self.winfo_toplevel(),
                )
                self.refresh()
                return
            if is_stale and sel:
                # Offer force-apply: live value differs, but operator may
                # have legitimate reason to overwrite anyway.
                proceed = messagebox.askyesno(
                    t("calib_queue_approve"),
                    f"{msg}\n\n"
                    "The live candidate value differs from what the AI "
                    "recommendation expected as `before`. Apply anyway? "
                    "(This will OVERWRITE the live value with the "
                    "recommendation's `after`.)",
                    parent=self.winfo_toplevel(),
                )
                if proceed:
                    self._do_approve(sel, strict_before=False)
                else:
                    self.refresh()
                return
            messagebox.showerror(
                t("calib_queue_approve"), msg,
                parent=self.winfo_toplevel(),
            )
            self.refresh()
        try:
            self.after(0, back)
        except tk.TclError:
            pass

    def _on_reject(self) -> None:
        sel = self._selected_queue_ids()
        if not sel:
            messagebox.showinfo(
                t("calib_queue_reject"), t("calib_select_first"),
                parent=self.winfo_toplevel(),
            )
            return
        cc.reject_pending(self._company.key, sel)
        self._reload_queue()

    def _open_log(self) -> None:
        sel = self._history_tree.selection()
        if not sel:
            return
        path = Path(sel[0])
        if path.exists():
            import os
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass

    def _on_rollback(self) -> None:
        sel = self._history_tree.selection()
        if not sel:
            messagebox.showinfo(
                t("calib_history_rollback"), t("calib_select_first"),
                parent=self.winfo_toplevel(),
            )
            return
        path = Path(sel[0])
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        snap_before = rec.get("snapshot_before")
        if not snap_before:
            messagebox.showerror(
                t("calib_history_rollback"),
                "This log has no `snapshot_before`.",
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            t("calib_history_rollback"), t("calib_confirm_rollback"),
            parent=self.winfo_toplevel(),
        ):
            return

        self._set_busy(True)

        def work() -> None:
            try:
                res = ca.rollback_to_snapshot(
                    self._company.key, str(snap_before),
                    schema_id=int(rec.get("schema_id") or 0) or None,
                )
            except Exception as e:  # noqa: BLE001
                self._after_apply_done(False, f"{type(e).__name__}: {e}")
                return
            self._after_apply_done(res.ok, res.error or "rollback ok")

        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        try:
            cursor = "watch" if busy else ""
            self.configure(cursor=cursor)
        except tk.TclError:
            pass
