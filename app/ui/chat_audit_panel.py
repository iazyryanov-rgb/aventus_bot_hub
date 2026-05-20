"""WhatsApp bot tab: AI chat-audit.

Workflow:
  * pick period (24h / 7 days / 30 days)
  * pick model (Sonnet 4.6 / Opus 4.7)
  * pick chat limit (50 / 100 / 200)
  * Run → background thread runs `chat_audit.run_audit`
  * results render as cards in a scrollable view
  * Settings ⚙ button opens a tiny modal to set the Anthropic API key
"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import messagebox, ttk
from typing import Optional
from zoneinfo import ZoneInfo

from ..ai_client import (
    AnthropicAuditClient,
    AnthropicError,
    get_anthropic_key,
    set_anthropic_key,
)
from ..audit_queue import (
    AuditJob,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    get_queue,
    latest_active_job,
    latest_terminal_job,
    load_job,
)
from ..audit_scheduler import send_audit_to_telegram
from ..audit_storage import (
    add_to_pending,
    get_pending_corrections,
    load_audit,
)
from ..chat_audit import run_audit
from ..data import Company
from ..i18n import current_language, t
from .colors import META_FG, OK_FG, ERR_FG, TEXT_FG, CARD_BG, CARD_BORDER


# When a job is in flight we poll the on-disk job file every N ms to
# pick up status changes. Cheap (small JSON file) and decoupled from
# the worker thread.
JOB_POLL_INTERVAL_MS = 1500


PERIODS = (
    ("audit_period_24h",  1),
    ("audit_period_7d",   7),
    ("audit_period_30d", 30),
)

MODELS = (
    ("audit_model_sonnet", "sonnet"),
    ("audit_model_opus",   "opus"),
)

CHAT_LIMITS = (50, 100, 200, 500)


class ChatAuditPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        # `_active_job_id` is set when this panel is watching a job
        # (either started here or reattached after re-creation).
        # Polling stops when the job hits a terminal status.
        self._active_job_id: Optional[str] = None
        self._poll_after_id: Optional[str] = None

        # Header
        ttk.Label(
            self,
            text=t("audit_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 6))
        ttk.Label(
            self,
            text=t("audit_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Controls
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Label(controls, text=t("audit_period_label") + ":").pack(side="left")
        self._period_var = tk.StringVar(value=t(PERIODS[1][0]))
        period_box = ttk.Combobox(
            controls,
            textvariable=self._period_var,
            values=[t(k) for k, _ in PERIODS],
            state="readonly",
            width=20,
        )
        period_box.pack(side="left", padx=(4, 14))

        ttk.Label(controls, text=t("audit_model_label") + ":").pack(side="left")
        self._model_var = tk.StringVar(value=t(MODELS[0][0]))
        ttk.Combobox(
            controls,
            textvariable=self._model_var,
            values=[t(k) for k, _ in MODELS],
            state="readonly",
            width=22,
        ).pack(side="left", padx=(4, 14))

        ttk.Label(controls, text=t("audit_limit_label") + ":").pack(side="left")
        self._limit_var = tk.IntVar(value=CHAT_LIMITS[1])
        ttk.Combobox(
            controls,
            textvariable=self._limit_var,
            values=list(CHAT_LIMITS),
            state="readonly",
            width=6,
        ).pack(side="left", padx=(4, 14))

        self._run_btn = ttk.Button(
            controls, text=t("audit_run"), command=self._run,
        )
        self._run_btn.pack(side="left")

        self._send_tg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text=t("audit_send_to_tg"),
            variable=self._send_tg_var,
        ).pack(side="left", padx=(14, 0))

        ttk.Button(
            controls, text=t("audit_set_key"), command=self._open_key_dialog,
        ).pack(side="right")

        ttk.Label(
            self,
            text=t("audit_alerts_hint"),
            foreground=META_FG, wraplength=900, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 4))

        self._status = ttk.Label(self, text="", foreground=META_FG)
        self._status.pack(anchor="w", padx=14, pady=(2, 6))
        self._update_status_idle()

        # --- Selection / calibration toolbar ---
        cal_bar = ttk.Frame(self)
        cal_bar.pack(fill="x", padx=14, pady=(0, 6))
        self._sel_status = ttk.Label(cal_bar, text="", foreground=META_FG)
        self._sel_status.pack(side="left")
        self._take_btn = ttk.Button(
            cal_bar, text=t("audit_take_to_corrections"),
            command=self._take_to_corrections, state="disabled",
        )
        self._take_btn.pack(side="left", padx=(10, 0))
        # NB: the legacy "Запустить калибровку" button + CalibrationDialog
        # were removed. The real calibration flow is the WhatsApp →
        # «Калибровка» tab (queue / approve / apply / rollback).
        # Per-recommendation checkbox state — keyed by rec id from current
        # audit; reset on every new run.
        self._rec_select_vars: dict[str, tk.BooleanVar] = {}
        # Last audit's recommendations + meta (used by _take_to_corrections).
        self._last_recs: list[dict] = []
        self._last_audit_meta: dict = {}
        self._refresh_calibration_buttons()

        # Results (scrollable)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._canvas = tk.Canvas(body, bg="#ffffff", highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        scroll.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=scroll.set)
        self._results_frame = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._results_frame, anchor="nw",
        )
        self._results_frame.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all"),
            ),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(
                self._canvas_window, width=e.width,
            ),
        )
        self._canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

        self._render_empty()
        # If a job started in a previous instance of this panel (or a
        # previous app launch) is still active OR just finished while
        # the panel was rebuilt, attach to it so the operator picks up
        # where they left off.
        self._reattach_existing_job()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _update_status_idle(self) -> None:
        if not get_anthropic_key():
            self._status.configure(
                text=t("audit_status_no_key"), foreground=ERR_FG,
            )
        else:
            self._status.configure(
                text=t("audit_status_ready"), foreground=META_FG,
            )

    # ------------------------------------------------------------------
    # API key dialog
    # ------------------------------------------------------------------

    def _open_key_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(t("audit_key_dialog_title"))
        try:
            dlg.transient(self.winfo_toplevel())
        except tk.TclError:
            pass
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=14)
        frm.pack()
        ttk.Label(frm, text=t("audit_key_help"), wraplength=420, justify="left",
                  foreground=META_FG).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(frm, text="API key:").grid(row=1, column=0, sticky="w")
        var = tk.StringVar(value=get_anthropic_key())
        ent = ttk.Entry(frm, textvariable=var, width=58, show="•")
        ent.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        ent.focus_set()

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def _save():
            try:
                set_anthropic_key(var.get().strip())
            except OSError as exc:
                messagebox.showerror("Error", str(exc), parent=dlg)
                return
            dlg.destroy()
            self._update_status_idle()

        ttk.Button(btns, text=t("btn_save"), command=_save).pack(
            side="left", padx=(0, 6),
        )
        ttk.Button(btns, text=t("btn_cancel"), command=dlg.destroy).pack(
            side="left",
        )
        dlg.bind("<Return>", lambda _e: _save())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _picked_period_days(self) -> int:
        label = self._period_var.get()
        for k, days in PERIODS:
            if t(k) == label:
                return days
        return 7

    def _picked_model_kind(self) -> str:
        label = self._model_var.get()
        for k, kind in MODELS:
            if t(k) == label:
                return kind
        return "sonnet"

    def _run(self) -> None:
        # If a job is already in flight for this company (started here
        # or earlier), don't double-enqueue.
        active = latest_active_job(self._company.key)
        if active is not None:
            self._active_job_id = active.request_id
            self._begin_polling()
            return
        if not AnthropicAuditClient().is_configured():
            messagebox.showwarning(
                t("audit_run"), t("audit_status_no_key"),
                parent=self.winfo_toplevel(),
            )
            return
        days = self._picked_period_days()
        kind = self._picked_model_kind()
        limit = int(self._limit_var.get())

        try:
            tz = ZoneInfo(self._company.timezone or "UTC")
        except Exception:
            tz = timezone.utc
        until = datetime.now(tz)
        since = until - timedelta(days=days)
        since_ms = int(since.timestamp() * 1000)
        until_ms = int(until.timestamp() * 1000)

        params = {
            "since_ms": since_ms,
            "until_ms": until_ms,
            "model_kind": kind,
            "chat_limit": limit,
            "lang": current_language(),
            "period_days": days,
            "send_to_tg": bool(self._send_tg_var.get()),
        }
        job = get_queue().enqueue(self._company, params)
        self._active_job_id = job.request_id
        self._render_empty()
        self._begin_polling()

    # --- Job polling ---------------------------------------------------

    def _reattach_existing_job(self) -> None:
        """Pick up where a previous instance left off. Priority:
          1. an active job → start polling, render running state
          2. otherwise, the latest terminal job → render its outcome
             once (so the panel isn't blank after tab switch)."""
        active = latest_active_job(self._company.key)
        if active is not None:
            self._active_job_id = active.request_id
            self._begin_polling()
            return
        last = latest_terminal_job(self._company.key)
        if last is not None:
            self._render_job_terminal(last)

    def _begin_polling(self) -> None:
        try:
            self._run_btn.configure(state="disabled")
        except tk.TclError:
            return
        if self._poll_after_id is not None:
            try:
                self.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        self._poll_job_status()

    def _poll_job_status(self) -> None:
        if not self.winfo_exists() or not self._active_job_id:
            return
        job = load_job(self._company.key, self._active_job_id)
        if job is None:
            self._active_job_id = None
            self._update_status_idle()
            try:
                self._run_btn.configure(state="normal")
            except tk.TclError:
                pass
            return

        if job.status == STATUS_QUEUED:
            self._status.configure(
                text=f"{t('audit_running')} (queued · job={job.request_id})",
                foreground=META_FG,
            )
        elif job.status == STATUS_RUNNING:
            elapsed = max(0, int(time.time() * 1000) - int(job.started_at_ms or 0)) // 1000
            self._status.configure(
                text=f"{t('audit_running')} · {elapsed}s · job={job.request_id}",
                foreground=META_FG,
            )
        else:
            # terminal — render and stop polling
            self._render_job_terminal(job)
            self._active_job_id = None
            try:
                self._run_btn.configure(state="normal")
            except tk.TclError:
                pass
            return

        try:
            self._poll_after_id = self.after(
                JOB_POLL_INTERVAL_MS, self._poll_job_status,
            )
        except tk.TclError:
            pass

    def _render_job_terminal(self, job: AuditJob) -> None:
        if job.status == STATUS_FAILED:
            self._status.configure(
                text=f"{t('audit_failed')}: {job.error or '?'} · job={job.request_id}",
                foreground=ERR_FG,
            )
            return
        if job.status == STATUS_INTERRUPTED:
            self._status.configure(
                text=f"⏸ {job.error or 'interrupted'} · job={job.request_id} — re-run from the button above.",
                foreground="#d97706",
            )
            return
        # STATUS_DONE
        if not job.result_audit_id:
            self._status.configure(
                text=f"{t('audit_done')} · job={job.request_id}",
                foreground=OK_FG,
            )
            return
        rec = load_audit(self._company.key, job.result_audit_id)
        result = (rec or {}).get("audit") or {}
        elapsed = job.elapsed_s or 0.0
        meta = result.get("_meta") or {}
        usage = meta.get("usage") or {}
        data = meta.get("data") or {}
        sent = meta.get("records_sent", 0)
        cache_read = usage.get("cache_read_input_tokens") or 0
        in_t = usage.get("input_tokens") or 0
        out_t = usage.get("output_tokens") or 0
        tg_part = ""
        if (job.params or {}).get("send_to_tg"):
            if job.tg_err:
                tg_part = f" · TG: {t('audit_tg_failed')} — {job.tg_err}"
            else:
                tg_part = f" · TG: {t('audit_tg_sent')}"
        self._status.configure(
            text=(
                f"{t('audit_done')} · {elapsed:.1f}s · "
                f"chats={sent}/{data.get('total_dialogs', '?')} · "
                f"in={in_t} (cache={cache_read}) · out={out_t}"
                f"{tg_part}"
            ),
            foreground=OK_FG if not job.tg_err else "#d97706",
        )
        self._render_result(result)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_empty(self) -> None:
        for w in self._results_frame.winfo_children():
            w.destroy()

    def _render_result(self, data: dict) -> None:
        self._render_empty()
        # Reset per-recommendation selection state — new audit = new pool.
        self._rec_select_vars.clear()
        self._last_recs = list(data.get("recommendations") or [])
        meta = data.get("_meta") or {}
        self._last_audit_meta = {
            "audit_id": meta.get("audit_id") or "",
            "ts_ms": meta.get("ts_ms") or 0,
            "model_kind": (meta.get("usage") or {}).get("model")
            or meta.get("model_kind") or "",
        }

        s = data.get("summary") or {}
        self._render_summary(s, meta)

        findings = data.get("findings") or []
        if findings:
            ttk.Label(
                self._results_frame,
                text=t("audit_section_findings") + f" ({len(findings)})",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w", pady=(10, 4))
            for f in findings:
                self._render_finding(f)

        recs = self._last_recs
        if recs:
            ttk.Label(
                self._results_frame,
                text=t("audit_section_recommendations") + f" ({len(recs)})",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w", pady=(14, 4))
            for r in recs:
                self._render_recommendation(r)
        self._refresh_calibration_buttons()

    def _render_summary(self, s: dict, meta: dict) -> None:
        card = self._card(self._results_frame)
        ttk.Label(
            card, text=t("audit_section_summary"),
            font=("Segoe UI", 10, "bold"), background=CARD_BG,
        ).pack(anchor="w")
        line1 = (
            f"chats={s.get('total_chats', 0)} · "
            f"good={s.get('good_count', 0)} · "
            f"bad={s.get('bad_count', 0)}"
        )
        ttk.Label(
            card, text=line1, foreground=TEXT_FG, background=CARD_BG,
        ).pack(anchor="w", pady=(4, 2))
        common = s.get("common_failures") or []
        if common:
            ttk.Label(
                card, text=t("audit_common_failures") + ":",
                foreground=META_FG, background=CARD_BG,
            ).pack(anchor="w", pady=(4, 0))
            for line in common[:6]:
                ttk.Label(
                    card, text=f"• {line}", foreground=TEXT_FG,
                    background=CARD_BG, wraplength=900, justify="left",
                ).pack(anchor="w", padx=(10, 0))
        signals = s.get("top_signals") or []
        if signals:
            ttk.Label(
                card, text=t("audit_top_signals") + ":",
                foreground=META_FG, background=CARD_BG,
            ).pack(anchor="w", pady=(4, 0))
            for line in signals[:6]:
                ttk.Label(
                    card, text=f"• {line}", foreground=TEXT_FG,
                    background=CARD_BG, wraplength=900, justify="left",
                ).pack(anchor="w", padx=(10, 0))

    def _render_finding(self, f: dict) -> None:
        card = self._card(self._results_frame)
        sev = (f.get("severity") or "low").lower()
        sev_color = {"high": ERR_FG, "medium": "#d97706", "low": META_FG}.get(sev, META_FG)
        head = ttk.Frame(card, style="Card.TFrame")
        try:
            ttk.Style(self).configure("Card.TFrame", background=CARD_BG)
        except tk.TclError:
            pass
        head.pack(fill="x")
        ttk.Label(
            head,
            text=f"[{sev.upper()}] {f.get('kind', '?')} · {f.get('id', '')}",
            foreground=sev_color, background=CARD_BG,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        impact = f.get("estimated_impact_pct")
        if impact is not None:
            ttk.Label(
                head, text=f"impact ≈ {impact}%",
                foreground=META_FG, background=CARD_BG,
            ).pack(side="right")
        ttk.Label(
            card, text=f.get("pattern") or "—",
            background=CARD_BG, wraplength=900, justify="left",
        ).pack(anchor="w", pady=(4, 2))
        ev = f.get("evidence_chat_ids") or []
        if ev:
            ttk.Label(
                card,
                text=t("audit_evidence") + ": " + ", ".join(ev[:8])
                + (" …" if len(ev) > 8 else ""),
                foreground=META_FG, background=CARD_BG,
                wraplength=900, justify="left",
            ).pack(anchor="w")

    def _render_recommendation(self, r: dict) -> None:
        card = self._card(self._results_frame)
        head = tk.Frame(card, bg=CARD_BG)
        head.pack(fill="x")
        rid = r.get("id") or ""
        var = tk.BooleanVar(value=False)
        self._rec_select_vars[rid] = var
        cb = tk.Checkbutton(
            head, variable=var, bg=CARD_BG, activebackground=CARD_BG,
            command=self._refresh_calibration_buttons,
        )
        cb.pack(side="left", anchor="n", padx=(0, 6))
        ttk.Label(
            head,
            text=f"{rid} → {r.get('applies_to', '')}",
            font=("Segoe UI", 9, "bold"),
            background=CARD_BG, foreground=TEXT_FG,
            wraplength=860, justify="left",
        ).pack(side="left", anchor="w")
        rationale = r.get("rationale")
        if rationale:
            ttk.Label(
                card, text=rationale, foreground=META_FG, background=CARD_BG,
                wraplength=900, justify="left",
            ).pack(anchor="w", pady=(2, 4))
        # Diff: before / after
        before = (r.get("before") or "").rstrip()
        after = (r.get("after") or "").rstrip()
        for label_key, value, fg in (
            ("audit_before", before, "#9ca3af"),
            ("audit_after", after, OK_FG),
        ):
            if not value:
                continue
            ttk.Label(
                card, text=t(label_key) + ":", foreground=fg,
                background=CARD_BG, font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(4, 0))
            box = tk.Text(
                card, height=min(8, max(2, value.count("\n") + 2)),
                wrap="word", relief="flat",
                bg="#f3f4f6", fg=TEXT_FG, font=("Segoe UI", 9),
            )
            box.insert("1.0", value)
            box.configure(state="disabled")
            box.pack(fill="x", pady=(2, 0))
        linked = r.get("linked_findings") or []
        if linked:
            ttk.Label(
                card,
                text=t("audit_linked_findings") + ": " + ", ".join(linked),
                foreground=META_FG, background=CARD_BG,
            ).pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------------
    # Selection / calibration toolbar
    # ------------------------------------------------------------------

    def _selected_count(self) -> int:
        return sum(1 for v in self._rec_select_vars.values() if v.get())

    def _refresh_calibration_buttons(self) -> None:
        sel = self._selected_count()
        pending = get_pending_corrections(self._company.key)
        n_pending = len(pending)
        if sel == 0 and n_pending == 0:
            self._sel_status.configure(text="")
        elif sel and n_pending:
            self._sel_status.configure(
                text=f"{t('audit_selected')}: {sel} · "
                     f"{t('audit_pending')}: {n_pending}"
            )
        elif sel:
            self._sel_status.configure(text=f"{t('audit_selected')}: {sel}")
        else:
            self._sel_status.configure(text=f"{t('audit_pending')}: {n_pending}")
        self._take_btn.configure(
            state="normal" if sel >= 2 else "disabled",
        )

    def _take_to_corrections(self) -> None:
        if self._selected_count() < 2:
            return
        recs = [
            r for r in self._last_recs
            if self._rec_select_vars.get(r.get("id") or "", tk.BooleanVar()).get()
        ]
        if not recs:
            return
        added = add_to_pending(
            self._company.key, recs, self._last_audit_meta,
        )
        # Visually clear the selection (so the user sees they were taken).
        for var in self._rec_select_vars.values():
            var.set(False)
        self._refresh_calibration_buttons()
        messagebox.showinfo(
            t("audit_take_to_corrections"),
            f"{t('audit_take_added')}: {added}",
            parent=self.winfo_toplevel(),
        )

    @staticmethod
    def _card(parent: tk.Misc) -> tk.Frame:
        card = tk.Frame(
            parent, bg=CARD_BG,
            highlightbackground=CARD_BORDER, highlightthickness=1, bd=0,
        )
        card.pack(fill="x", pady=4, ipadx=10, ipady=8)
        return card

    def _on_wheel(self, event) -> None:
        try:
            if not self._canvas.winfo_exists():
                return
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass
