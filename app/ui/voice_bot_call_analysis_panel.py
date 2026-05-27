"""Panel «Анализ звонков» — ИИ-аудит ElevenLabs voice-bot conversations.

UX:
  * Шапка: компания + сектор + agent_id.
  * Период (Сегодня / 7d / 30d / Свой), max_calls, model_kind (sonnet/opus),
    кнопка «Проанализировать».
  * Статус + прогресс-бар.
  * Summary-карточка (calls_analyzed, common_failures).
  * Список suggestions: для каждой — чекбокс, severity, target, title,
    rationale, evidence, before/after. Множественный выбор.
  * Низ: «Применить выбранные локально» (изменения уходят в
    `data/voice_bot_config/.../<sector>.json` и/или
    `data/voice_bot_tools/.../save_call_result.json`, push отдельно
    делается на вкладках Промты / Результаты).

Состояние результата живёт в `data/voice_bot_analysis/<KEY>/<sector>.json`,
чтобы при перезаходе панели/перезапуске exe прогон не терялся.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..data import Company
from ..i18n import t
from ..sectors import DEFAULT_SECTOR, SECTORS
from ..voice_bot_analysis import (
    DEFAULT_MAX_CALLS,
    apply_suggestion,
    load_analysis_state,
    run_analysis,
    save_analysis_state,
)
from ..voice_bot_config import BLOCK_TITLES, load_config
from .colors import ERR_FG, META_FG, OK_FG, TBD_FG, TEXT_FG


SEVERITY_COLOR = {
    "low":    "#16a34a",   # green
    "medium": "#d97706",   # orange
    "high":   "#dc2626",   # red
}


PERIOD_PRESETS = (
    ("voice_analysis_period_today",  1),
    ("voice_analysis_period_7d",     7),
    ("voice_analysis_period_30d",   30),
)


def _period_window(days: int) -> tuple[int, int]:
    """Return (since_ts, until_ts) for the last `days` days, ending now."""
    now = int(time.time())
    since = now - days * 86400
    return since, now


def _fmt_dt(ts: int) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _block_label(block_id: str) -> str:
    key = f"voice_bot_block_{block_id}"
    val = t(key)
    if val and val != key:
        return val
    return BLOCK_TITLES.get(block_id, block_id)


class VoiceBotCallAnalysisPanel(ttk.Frame):
    """ИИ-анализ звонков. Один экземпляр на (company, sector)."""

    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR

        cfg = load_config(company.key, self._sector)
        self._agent_id: str = str(cfg.get("elevenlabs_agent_id") or "").strip()

        # ---- header ----
        ttk.Label(
            self, text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"), foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=(
                f"{code} — {company.name} ({company.country})  ·  "
                f"{t('sector_' + self._sector)}"
            ),
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 2))
        ttk.Label(
            self,
            text=(
                f"{t('voice_bot_agent_id')}: "
                + (self._agent_id or t("voice_bot_agent_id_missing"))
            ),
            foreground=META_FG if self._agent_id else ERR_FG,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        ttk.Label(
            self, text=t("voice_analysis_help"),
            foreground=META_FG, wraplength=900, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # ---- toolbar: period + max_calls + model + run ----
        toolbar = ttk.LabelFrame(
            self, text=t("voice_analysis_run_section"), padding=10,
        )
        toolbar.pack(fill="x", padx=12, pady=(0, 8))

        ttk.Label(toolbar, text=t("voice_analysis_period") + ":").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=2,
        )
        self._period_var = tk.StringVar(value=str(PERIOD_PRESETS[1][1]))  # 7d
        period_box = ttk.Combobox(
            toolbar, textvariable=self._period_var,
            values=[str(d) for _k, d in PERIOD_PRESETS],
            state="readonly", width=8,
        )
        period_box.grid(row=0, column=1, sticky="w", pady=2)
        # подпись справа от dropdown'а
        self._period_labels = {
            str(d): t(k) for k, d in PERIOD_PRESETS
        }
        self._period_caption = ttk.Label(
            toolbar, text=self._period_labels.get(self._period_var.get(), ""),
            foreground=META_FG,
        )
        self._period_caption.grid(
            row=0, column=2, sticky="w", padx=(8, 0), pady=2,
        )
        period_box.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._period_caption.configure(
                text=self._period_labels.get(self._period_var.get(), ""),
            ),
        )

        ttk.Label(toolbar, text=t("voice_analysis_max_calls") + ":").grid(
            row=0, column=3, sticky="w", padx=(18, 6), pady=2,
        )
        self._max_calls_var = tk.IntVar(value=DEFAULT_MAX_CALLS)
        ttk.Spinbox(
            toolbar, from_=5, to=200, increment=5,
            textvariable=self._max_calls_var, width=6,
        ).grid(row=0, column=4, sticky="w", pady=2)

        ttk.Label(toolbar, text=t("voice_analysis_model") + ":").grid(
            row=0, column=5, sticky="w", padx=(18, 6), pady=2,
        )
        self._model_var = tk.StringVar(value="sonnet")
        ttk.Combobox(
            toolbar, textvariable=self._model_var,
            values=["sonnet", "opus"], state="readonly", width=8,
        ).grid(row=0, column=6, sticky="w", pady=2)

        self._run_btn = ttk.Button(
            toolbar, text=t("voice_analysis_run"),
            command=self._on_run, style="Accent.TButton",
        )
        self._run_btn.grid(row=0, column=7, sticky="w", padx=(18, 0), pady=2)

        # ---- status row ----
        status_row = ttk.Frame(self)
        status_row.pack(fill="x", padx=12, pady=(0, 6))
        self._status = ttk.Label(
            status_row, text="", foreground=META_FG,
        )
        self._status.pack(side="left")
        self._progress = ttk.Progressbar(
            status_row, mode="indeterminate", length=140,
        )
        # pack только когда работаем

        # ---- summary card (lazy) ----
        self._summary_frame = ttk.LabelFrame(
            self, text=t("voice_analysis_summary"), padding=10,
        )
        # pack по факту наличия данных

        self._summary_text = tk.Text(
            self._summary_frame, wrap="word", height=4,
            relief="flat", bg=self.winfo_toplevel().cget("bg"),
        )
        self._summary_text.pack(fill="x")
        self._summary_text.configure(state="disabled")

        # ---- suggestions area: scrollable Frame ----
        sg_box = ttk.LabelFrame(
            self, text=t("voice_analysis_suggestions"), padding=4,
        )
        sg_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        canvas = tk.Canvas(sg_box, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(sg_box, orient="vertical", command=canvas.yview)
        sb.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=sb.set)
        self._sg_canvas = canvas
        self._sg_inner = ttk.Frame(canvas)
        self._sg_inner_id = canvas.create_window(
            (0, 0), window=self._sg_inner, anchor="nw",
        )
        self._sg_inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(self._sg_inner_id, width=e.width),
        )
        # mouse-wheel scroll
        canvas.bind_all("<MouseWheel>", self._on_mousewheel_global, add="+")

        # ---- bottom toolbar: apply / reset ----
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        self._apply_btn = ttk.Button(
            bottom, text=t("voice_analysis_apply_selected"),
            command=self._on_apply_selected, style="Accent.TButton",
        )
        self._apply_btn.pack(side="left")
        ttk.Button(
            bottom, text=t("voice_analysis_select_all"),
            command=lambda: self._set_all_selected(True),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            bottom, text=t("voice_analysis_select_none"),
            command=lambda: self._set_all_selected(False),
        ).pack(side="left", padx=(8, 0))
        self._apply_status = ttk.Label(
            bottom, text="", foreground=META_FG,
        )
        self._apply_status.pack(side="left", padx=(12, 0))

        # Storage of current rendered suggestions: list of dicts
        # {"sg": {...}, "var": BooleanVar, "applied": bool}
        self._rows: list[dict] = []

        # restore previous run if any
        prev = load_analysis_state(company.key, self._sector)
        if prev and prev.get("result"):
            self._render_result(prev["result"], prev)
            ts = prev.get("ran_at_ts") or 0
            self._status.configure(
                text=t("voice_analysis_loaded_from_disk").format(
                    when=_fmt_dt(ts),
                    calls=prev.get("calls_fetched") or 0,
                ),
                foreground=META_FG,
            )
        else:
            self._status.configure(
                text=t("voice_analysis_no_runs_yet"),
                foreground=META_FG,
            )

        # Worker state.
        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle / destroy hygiene
    # ------------------------------------------------------------------

    def destroy(self) -> None:  # type: ignore[override]
        self._cancel.set()
        try:
            self._sg_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        super().destroy()

    def _on_mousewheel_global(self, e: tk.Event) -> None:
        # Скроллим только если курсор над нашим canvas'ом
        try:
            w = e.widget.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        widget = w
        while widget is not None:
            if widget is self._sg_canvas or widget is self._sg_inner:
                self._sg_canvas.yview_scroll(int(-e.delta / 120), "units")
                return
            widget = getattr(widget, "master", None)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _on_run(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        if not self._agent_id:
            messagebox.showwarning(
                t("voice_analysis_run"),
                t("voice_bot_agent_id_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        try:
            days = int(self._period_var.get() or "7")
        except ValueError:
            days = 7
        since, until = _period_window(days)
        try:
            max_calls = max(1, int(self._max_calls_var.get() or DEFAULT_MAX_CALLS))
        except (TypeError, ValueError):
            max_calls = DEFAULT_MAX_CALLS
        model_kind = (self._model_var.get() or "sonnet").strip()

        self._run_btn.configure(state="disabled")
        self._progress.pack(side="left", padx=(12, 0))
        self._progress.start(80)
        self._status.configure(
            text=t("voice_analysis_running"),
            foreground=META_FG,
        )
        self._apply_status.configure(text="")
        self._cancel.clear()

        self._worker = threading.Thread(
            target=self._run_worker,
            args=(since, until, max_calls, model_kind),
            daemon=True,
        )
        self._worker.start()

    def _progress_cb(self, stage: str, done: int, total: int) -> None:
        # Called from worker thread — only update status text safely.
        if not self.winfo_exists():
            return
        try:
            if stage == "list":
                msg = t("voice_analysis_fetching_list").format(n=done)
            elif stage == "detail":
                msg = t("voice_analysis_fetching_detail").format(
                    done=done, total=total,
                )
            elif stage == "llm_call":
                msg = t("voice_analysis_llm_call").format(n=done)
            elif stage == "fetch_start":
                msg = t("voice_analysis_fetching_list").format(n=0)
            else:
                msg = stage
            self.after(0, lambda m=msg: self._status.configure(text=m))
        except Exception:
            pass

    def _run_worker(
        self, since_ts: int, until_ts: int,
        max_calls: int, model_kind: str,
    ) -> None:
        result = run_analysis(
            self._company.key, self._sector,
            since_ts=since_ts, until_ts=until_ts,
            max_calls=max_calls, model_kind=model_kind,
            progress_cb=self._progress_cb,
        )
        if self._cancel.is_set() or not self.winfo_exists():
            return
        # сохраняем целиком, включая ok/error — пригодится при reopen
        save_payload = {
            **result,
            "ran_at_ts": int(time.time()),
            "params": {
                "since_ts": since_ts, "until_ts": until_ts,
                "max_calls": max_calls, "model_kind": model_kind,
            },
        }
        save_analysis_state(self._company.key, self._sector, save_payload)
        self.after(0, lambda: self._on_done(save_payload))

    def _on_done(self, payload: dict) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._run_btn.configure(state="normal")
        if not payload.get("ok"):
            err = payload.get("error") or "?"
            self._status.configure(
                text=t("voice_analysis_failed").format(err=err),
                foreground=ERR_FG,
            )
            return
        self._status.configure(
            text=t("voice_analysis_done").format(
                calls=payload.get("calls_fetched") or 0,
                model=payload.get("model") or "?",
            ),
            foreground=OK_FG,
        )
        self._render_result(payload.get("result") or {}, payload)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _clear_suggestions(self) -> None:
        for ch in list(self._sg_inner.winfo_children()):
            ch.destroy()
        self._rows = []

    def _render_summary(self, result: dict, payload: dict) -> None:
        self._summary_frame.pack_forget()
        summary = (result.get("summary") or "").strip()
        common = result.get("common_failures") or []
        calls_n = result.get("calls_analyzed") or payload.get("calls_fetched") or 0
        params = payload.get("params") or {}
        period = ""
        if "since_ts" in params and "until_ts" in params:
            period = (
                f"{_fmt_dt(int(params['since_ts']))} → "
                f"{_fmt_dt(int(params['until_ts']))}"
            )
        lines: list[str] = []
        meta = []
        meta.append(t("voice_analysis_calls").format(n=calls_n))
        if period:
            meta.append(period)
        meta.append(f"model={payload.get('model') or '?'}")
        lines.append("  ·  ".join(meta))
        if summary:
            lines.append("")
            lines.append(summary)
        if common:
            lines.append("")
            lines.append(t("voice_analysis_common_failures") + ":")
            for c in common:
                lines.append(f"  • {c}")
        self._summary_text.configure(state="normal")
        self._summary_text.delete("1.0", "end")
        self._summary_text.insert("1.0", "\n".join(lines))
        self._summary_text.configure(
            state="disabled",
            height=max(3, min(12, len(lines))),
        )
        self._summary_frame.pack(fill="x", padx=12, pady=(0, 8))

    def _severity_pill(self, parent: tk.Misc, sev: str) -> tk.Widget:
        sev = sev or "low"
        color = SEVERITY_COLOR.get(sev, META_FG)
        lbl = tk.Label(
            parent, text=sev.upper(),
            font=("Segoe UI", 8, "bold"),
            fg="white", bg=color,
            padx=8, pady=1,
        )
        return lbl

    def _target_label(self, sg: dict) -> str:
        target = sg.get("target") or ""
        if target == "prompt_block":
            bid = sg.get("block_id") or "?"
            return t("voice_analysis_target_block").format(
                block=_block_label(bid),
            )
        if target == "tool_property":
            pid = sg.get("tool_property") or "?"
            field = sg.get("tool_field") or "?"
            return t("voice_analysis_target_tool").format(
                prop=pid, field=field,
            )
        return target or "—"

    def _render_suggestion(self, sg: dict, applied_ids: set[str]) -> None:
        sid = sg.get("id") or f"s-{len(self._rows):03d}"
        already = sid in applied_ids
        row = ttk.Frame(self._sg_inner, padding=(6, 6))
        row.pack(fill="x", padx=4, pady=(0, 6))

        # header row
        head = ttk.Frame(row)
        head.pack(fill="x")
        var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(head, variable=var)
        cb.pack(side="left")
        if already:
            cb.configure(state="disabled")
            var.set(False)
        pill = self._severity_pill(head, sg.get("severity") or "low")
        pill.pack(side="left", padx=(2, 8))
        ttk.Label(
            head, text=self._target_label(sg),
            foreground=META_FG, font=("Consolas", 9),
        ).pack(side="left")
        ttk.Label(
            head, text="  ·  " + (sg.get("title") or "—"),
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=(4, 0))
        if already:
            ttk.Label(
                head, text="  ✓ " + t("voice_analysis_applied"),
                foreground=OK_FG, font=("Segoe UI", 9, "bold"),
            ).pack(side="right")

        # rationale
        rat = (sg.get("rationale") or "").strip()
        if rat:
            ttk.Label(
                row, text=rat,
                foreground=TEXT_FG, wraplength=860, justify="left",
            ).pack(anchor="w", padx=(28, 0), pady=(2, 0))

        # evidence (collapsed list)
        ev = sg.get("evidence") or []
        if ev:
            ev_frame = ttk.Frame(row)
            ev_frame.pack(anchor="w", fill="x", padx=(28, 0), pady=(4, 0))
            ttk.Label(
                ev_frame, text=t("voice_analysis_evidence") + ":",
                foreground=META_FG, font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w")
            for q in ev[:5]:
                ttk.Label(
                    ev_frame, text="„" + str(q).strip() + "“",
                    foreground=TBD_FG, wraplength=820, justify="left",
                ).pack(anchor="w", padx=(8, 0))

        # before / after
        diff_kind = sg.get("diff_kind") or "?"
        before = (sg.get("before") or "")
        after = (sg.get("after") or "")
        diff = ttk.Frame(row)
        diff.pack(anchor="w", fill="x", padx=(28, 0), pady=(6, 0))
        ttk.Label(
            diff, text=f"{t('voice_analysis_diff_kind')}: {diff_kind}",
            foreground=META_FG, font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", columnspan=2)

        if before:
            ttk.Label(
                diff, text=t("voice_analysis_before") + ":",
                foreground=ERR_FG,
            ).grid(row=1, column=0, sticky="nw", padx=(0, 6), pady=(2, 0))
            tb = tk.Text(
                diff, wrap="word", height=min(8, max(2, before.count("\n") + 2)),
                font=("Consolas", 9),
            )
            tb.grid(row=1, column=1, sticky="ew", pady=(2, 0))
            tb.insert("1.0", before)
            tb.configure(state="disabled")
        ttk.Label(
            diff, text=t("voice_analysis_after") + ":",
            foreground=OK_FG,
        ).grid(row=2, column=0, sticky="nw", padx=(0, 6), pady=(2, 0))
        ta = tk.Text(
            diff, wrap="word", height=min(8, max(2, after.count("\n") + 2)),
            font=("Consolas", 9),
        )
        ta.grid(row=2, column=1, sticky="ew", pady=(2, 0))
        ta.insert("1.0", after)
        ta.configure(state="disabled")
        diff.grid_columnconfigure(1, weight=1)

        ttk.Separator(self._sg_inner, orient="horizontal").pack(
            fill="x", padx=8, pady=(0, 2),
        )

        self._rows.append({
            "sg": sg,
            "var": var,
            "applied": already,
        })

    def _render_result(self, result: dict, payload: dict) -> None:
        self._clear_suggestions()
        self._render_summary(result, payload)
        applied_ids = set(payload.get("applied_ids") or [])
        suggestions = result.get("suggestions") or []
        if not suggestions:
            ttk.Label(
                self._sg_inner, text=t("voice_analysis_no_suggestions"),
                foreground=META_FG,
            ).pack(anchor="w", padx=10, pady=10)
            return
        for sg in suggestions:
            self._render_suggestion(sg, applied_ids)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _set_all_selected(self, value: bool) -> None:
        for row in self._rows:
            if not row["applied"]:
                row["var"].set(value)

    def _on_apply_selected(self) -> None:
        selected = [
            row for row in self._rows
            if not row["applied"] and row["var"].get()
        ]
        if not selected:
            self._apply_status.configure(
                text=t("voice_analysis_apply_nothing_selected"),
                foreground=META_FG,
            )
            return
        if not messagebox.askyesno(
            t("voice_analysis_apply_selected"),
            t("voice_analysis_apply_confirm").format(n=len(selected)),
            parent=self.winfo_toplevel(),
        ):
            return
        ok_n, fail = 0, []
        applied_ids: list[str] = []
        for row in selected:
            sg = row["sg"]
            ok, msg = apply_suggestion(
                self._company.key, self._sector, sg,
            )
            if ok:
                ok_n += 1
                row["applied"] = True
                applied_ids.append(sg.get("id") or "")
            else:
                fail.append((sg.get("id") or "?", msg))
        # update saved state with applied_ids merged
        state = load_analysis_state(self._company.key, self._sector) or {}
        prev_applied = set(state.get("applied_ids") or [])
        prev_applied.update(a for a in applied_ids if a)
        state["applied_ids"] = sorted(prev_applied)
        save_analysis_state(self._company.key, self._sector, state)
        # Snapshot the post-apply state of the prompt blocks as a
        # version of kind="analysis" so the operator can roll back to
        # this exact AI-applied combination later via the «Версии»
        # dialog in Prompts.
        if ok_n > 0:
            try:
                from ..voice_bot_config import load_config
                from ..voice_bot_prompt_versions import KIND_ANALYSIS, save_version
                cfg_after = load_config(self._company.key, self._sector)
                save_version(
                    self._company.key, self._sector, KIND_ANALYSIS,
                    blocks=cfg_after.get("main_prompt_blocks") or {},
                    first_message=cfg_after.get("first_message") or "",
                    meta={
                        "applied_ids": [s.get("id") for s in (sg["sg"] for sg in selected)],
                        "applied_titles": [
                            sg["sg"].get("title") or "" for sg in selected
                        ],
                        "analysis_ran_at": int(
                            (load_analysis_state(self._company.key, self._sector) or {})
                            .get("ran_at_ts") or 0
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[voice_bot_call_analysis] save Analysis version failed: {exc}")
        # re-render to disable applied rows
        if state.get("result"):
            self._render_result(state["result"], state)
        if fail:
            details = "\n".join(f"  • {sid}: {msg}" for sid, msg in fail[:10])
            self._apply_status.configure(
                text=t("voice_analysis_apply_result_partial").format(
                    ok=ok_n, fail=len(fail),
                ),
                foreground=ERR_FG,
            )
            messagebox.showwarning(
                t("voice_analysis_apply_selected"),
                t("voice_analysis_apply_failures") + ":\n\n" + details,
                parent=self.winfo_toplevel(),
            )
        else:
            self._apply_status.configure(
                text=t("voice_analysis_apply_result_ok").format(n=ok_n),
                foreground=OK_FG,
            )
