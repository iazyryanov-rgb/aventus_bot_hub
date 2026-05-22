"""Per-company WhatsApp-Infobip bot configuration panels.

Independent panels (rendered as separate tabs by BotPanel for
kind="whatsapp"):

  * WaBotOverviewPanel  — gateway, prod schema, CRM endpoints, lookup
    vars, result body fields.
  * WaBotSendersPanel   — live list of WhatsApp senders pulled from
    Infobip with quality / status / limit colour-coded — same view as
    Infobip portal's `Channels and Numbers · WhatsApp · Senders`.
  * WaBotFunctionsPanel — editable list of OpenAI tool/function specs.
  * WaBotPromptsPanel   — main + secondary prompt textareas.
  * WaBotBuilderPanel   — preview the OpenAI request body the bot will
    send.
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..crm_lookup import call_crm_by_phone, fetch_active_loan_phone
from ..data import Company, load_raw
from ..i18n import t
from ..wa_bot_overview import ArmMetrics
from ..wa_bot_config import (
    DEFAULT_BUILDER,
    GATEWAY_NAME,
    build_request_body,
    get_infobip_senders,
    get_prod_schema,
    load_config,
    refresh_infobip_senders,
    save_config,
)
from ..wa_senders_state import (
    STATUS_BAD,
    STATUS_WARN,
    format_phone,
    humanize_limit,
    humanize_quality,
    humanize_status,
)
from .colors import ERR_FG, META_FG, OK_FG, TEXT_FG


class WaBotOverviewPanel(ttk.Frame):
    """High-level overview — funnel конверсии WA-бота champion vs candidate.

    Layout — как сводная Excel-таблица: две группы (Champion / Candidate),
    каждую можно свернуть/развернуть `+/−`. В свёрнутом виде показываются
    только итоги по группе, ячейки подсвечены green (бо́льшее значение) /
    red (меньшее) при сравнении champion vs candidate. В развёрнутом виде
    под итогом появляются строки по дням, окрашенные градиентом
    «бледный → насыщённый» внутри своей группы (max → ярче).

    Метрики берутся из CRM: sms.smsProvider='infobip-wa-mass' →
    communication_history → collection_result_promise_to_pay →
    income / extension. Сплит champion/candidate — по последней цифре
    телефона, как делает Webitel router-schema.
    """

    PERIODS = (7, 14, 30)

    METRIC_COLS = (
        ("sent",           "wa_overview_col_sent"),
        ("engaged",        "wa_overview_col_engaged"),
        ("results",        "wa_overview_col_results"),
        ("extended",       "wa_overview_col_extended"),
        ("promises",       "wa_overview_col_promises"),
        ("promise_full",   "wa_overview_col_promise_full"),
        ("promise_ext",    "wa_overview_col_promise_ext"),
        ("fulfilled_full", "wa_overview_col_fulfilled_full"),
        ("fulfilled_ext",  "wa_overview_col_fulfilled_ext"),
    )

    # Соответствие колонок панели ↔ атрибутов ArmMetrics.
    _METRIC_ATTR = {
        "sent": "sent", "engaged": "engaged", "extended": "extended",
        "results": "results", "promises": "promises",
        "promise_full": "promise_full",
        "promise_ext": "promise_extension",
        "fulfilled_full": "fulfilled_full",
        "fulfilled_ext": "fulfilled_extension",
    }

    # Палитра. Цвета согласованы с дашбордом (#16a34a, #dc2626 уже живут
    # в colors.py как OK_FG / ERR_FG).
    _BG_NEUTRAL = "#ffffff"
    _BG_HEADER = "#f3f4f6"
    _BG_HIGHER = "#dcfce7"   # светло-зелёный для бо́льшей стороны
    _BG_LOWER = "#fee2e2"    # светло-красный для меньшей
    _BG_GRAD_LO = (250, 250, 250)  # начало градиента
    _BG_GRAD_HI = (74, 222, 128)    # конец (зелёный)
    _FG_TEXT = "#111827"

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._expanded = {"champion": True, "candidate": True}
        self._report = None
        self._cells: dict = {}  # for redraw on toggle

        ttk.Label(
            self,
            text=t("wa_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # --- Toolbar ---
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 4))
        ttk.Label(toolbar, text=t("wa_overview_period") + ":").pack(side="left")
        self._period_var = tk.IntVar(value=14)
        self._period_combo = ttk.Combobox(
            toolbar,
            textvariable=self._period_var,
            values=[str(p) for p in self.PERIODS],
            state="readonly",
            width=6,
        )
        self._period_combo.pack(side="left", padx=(6, 12))
        self._period_combo.bind("<<ComboboxSelected>>", lambda _e: self._reload())
        self._refresh_btn = ttk.Button(
            toolbar, text=t("btn_refresh"), command=self._reload_force,
        )
        self._refresh_btn.pack(side="left")
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        # --- A/B caption ---
        self._ab_caption = ttk.Label(
            self, text="", foreground=META_FG, wraplength=1100, justify="left",
        )
        self._ab_caption.pack(anchor="w", padx=14, pady=(2, 4))

        # --- Scrollable grid ---
        grid_box = ttk.Frame(self)
        grid_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._canvas = tk.Canvas(grid_box, highlightthickness=0, bg="#e5e7eb")
        self._canvas.pack(side="left", fill="both", expand=True)
        vscl = ttk.Scrollbar(grid_box, orient="vertical", command=self._canvas.yview)
        vscl.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=vscl.set)
        self._grid_frame = tk.Frame(self._canvas, bg="#e5e7eb")
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._grid_frame, anchor="nw",
        )
        self._grid_frame.bind(
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
        # Mouse wheel scrolling — Windows / Linux.
        self._canvas.bind_all(
            "<MouseWheel>",
            lambda e: self._canvas.yview_scroll(
                int(-e.delta / 120), "units",
            ),
        )

        self._cell_font = ("Segoe UI", 9)
        self._header_font = ("Segoe UI", 9, "bold")

        self.after(100, self._reload)

    # ------------------------------------------------------------------
    # Data load
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        self._refresh_btn.configure(state="disabled")
        self._status.configure(text=t("dash_loading"), foreground=META_FG)
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._cells.clear()
        days = int(self._period_var.get() or 14)
        threading.Thread(
            target=self._reload_worker, args=(days, False), daemon=True,
        ).start()

    def _reload_force(self) -> None:
        from .. import wa_bot_overview as _wbo
        _wbo.invalidate(self._company.key)
        self._reload()

    def _reload_worker(self, days: int, force: bool) -> None:
        from .. import wa_bot_overview as _wbo
        try:
            report = _wbo.compute_funnel(self._company, days=days, force=force)
            err: Optional[str] = report.error
        except Exception as exc:  # noqa: BLE001
            report, err = None, f"{type(exc).__name__}: {exc}"
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render(report, err))

    def _render(self, report, err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._refresh_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            self._ab_caption.configure(text="")
            return
        if not report or not report.days:
            self._status.configure(text=t("calib_no_data"), foreground=META_FG)
            self._ab_caption.configure(text="")
            return

        self._report = report

        champ_lbl = "—"
        if report.champion_schema:
            cid, cname = report.champion_schema
            champ_lbl = f"id={cid} ({cname})" if cname else f"id={cid}"
        cand_lbl = "—"
        if report.candidate_schema:
            cid, cname = report.candidate_schema
            cand_lbl = f"id={cid} ({cname})" if cname else f"id={cid}"
        digits = ", ".join(str(d) for d in report.candidate_digits)
        self._ab_caption.configure(
            text=t("wa_overview_ab_caption").format(
                champion=champ_lbl, candidate=cand_lbl, digits=digits,
            )
        )

        self._build_grid()

        when = report.fetched_at.strftime("%H:%M:%S") if report.fetched_at else ""
        self._status.configure(
            text=t("dash_updated") + " " + when, foreground=OK_FG,
        )

    # ------------------------------------------------------------------
    # Excel-pivot grid
    # ------------------------------------------------------------------

    def _build_grid(self) -> None:
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._cells.clear()

        report = self._report
        if not report:
            return

        # Equal-weighted columns so cells fill width nicely.
        n_cols = 1 + len(self.METRIC_COLS)  # date + metrics
        for c in range(n_cols):
            self._grid_frame.grid_columnconfigure(c, weight=1, uniform="m")

        # --- Header row ---
        self._make_cell(0, 0, t("wa_overview_col_arm_date"),
                        bg=self._BG_HEADER, font=self._header_font, anchor="w")
        for i, (cname, key) in enumerate(self.METRIC_COLS, start=1):
            self._make_cell(0, i, t(key),
                            bg=self._BG_HEADER, font=self._header_font)

        row_cursor = 1
        # --- Champion group ---
        row_cursor = self._render_arm("champion", row_cursor)
        # --- Candidate group ---
        row_cursor = self._render_arm("candidate", row_cursor)

    def _render_arm(self, arm: str, row: int) -> int:
        report = self._report
        total: ArmMetrics = (
            report.total_champion if arm == "champion" else report.total_candidate
        )
        other_total: ArmMetrics = (
            report.total_candidate if arm == "champion" else report.total_champion
        )
        per_day = [
            (d.date, getattr(d, arm))
            for d in report.days
        ]

        # Total row: name + expand toggle, then metric values comparing
        # vs the other arm.
        expanded = self._expanded.get(arm, True)
        toggle = "−" if expanded else "+"
        label = ("Candidate" if arm == "candidate" else "Champion")
        name_text = f" {toggle}  {label}  (Σ)"

        name_cell = self._make_cell(
            row, 0, name_text,
            bg=self._BG_HEADER,
            font=self._header_font,
            anchor="w",
        )
        name_cell.configure(cursor="hand2")
        name_cell.bind("<Button-1>", lambda _e, a=arm: self._toggle(a))

        for i, (cname, _key) in enumerate(self.METRIC_COLS, start=1):
            attr = self._METRIC_ATTR[cname]
            my = int(getattr(total, attr) or 0)
            other = int(getattr(other_total, attr) or 0)
            txt_my = self._fmt_metric_value(cname, my, total)
            if my == 0 and other == 0:
                bg = self._BG_HEADER
                txt = "—"
            elif my > other:
                bg = self._BG_HIGHER
                txt = txt_my
            elif my < other:
                bg = self._BG_LOWER
                txt = txt_my
            else:
                bg = self._BG_HEADER
                txt = txt_my
            self._make_cell(row, i, txt, bg=bg, font=self._header_font)
        row += 1

        if not expanded:
            return row

        # Compute per-metric max/min within this arm to build a gradient.
        metric_max: dict[str, int] = {}
        metric_min: dict[str, int] = {}
        for cname, _key in self.METRIC_COLS:
            attr = self._METRIC_ATTR[cname]
            vals = [int(getattr(m, attr) or 0) for _d, m in per_day]
            metric_max[cname] = max(vals) if vals else 0
            metric_min[cname] = min(vals) if vals else 0

        for d, m in per_day:
            self._make_cell(
                row, 0, "    " + d.strftime("%Y-%m-%d"),
                bg=self._BG_NEUTRAL, anchor="w",
            )
            for i, (cname, _key) in enumerate(self.METRIC_COLS, start=1):
                attr = self._METRIC_ATTR[cname]
                v = int(getattr(m, attr) or 0)
                bg = self._gradient_bg(v, metric_min[cname], metric_max[cname])
                if v == 0 and metric_max[cname] == 0:
                    txt = "—"
                else:
                    txt = self._fmt_metric_value(cname, v, m)
                self._make_cell(row, i, txt, bg=bg)
            row += 1
        return row

    @staticmethod
    def _fmt_metric_value(cname: str, value: int, row_metrics: "ArmMetrics") -> str:
        """Format a numeric cell. `engaged` and `results` get a `(% of ...)`
        suffix so the user sees the funnel ratio at a glance."""
        if cname == "engaged":
            denom = int(row_metrics.sent or 0)
            if denom > 0:
                pct = round(100 * value / denom)
                return f"{value} ({pct}%)"
        elif cname == "results":
            denom = int(row_metrics.engaged or 0)
            if denom > 0:
                pct = round(100 * value / denom)
                return f"{value} ({pct}%)"
        return str(value)

    def _toggle(self, arm: str) -> None:
        self._expanded[arm] = not self._expanded.get(arm, True)
        self._build_grid()

    def _make_cell(
        self,
        row: int,
        col: int,
        text: str,
        *,
        bg: str = "#ffffff",
        fg: Optional[str] = None,
        font: Optional[tuple] = None,
        anchor: str = "center",
    ) -> tk.Label:
        lbl = tk.Label(
            self._grid_frame,
            text=text,
            bg=bg,
            fg=fg or self._FG_TEXT,
            font=font or self._cell_font,
            anchor=anchor,
            padx=8, pady=4,
        )
        lbl.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
        self._cells[(row, col)] = lbl
        return lbl

    def _gradient_bg(self, value: int, vmin: int, vmax: int) -> str:
        """Light → green linear interp by value position in [vmin, vmax]."""
        if vmax <= 0 or vmax == vmin:
            return self._BG_NEUTRAL
        t = (value - vmin) / (vmax - vmin)
        t = max(0.0, min(1.0, t))
        r1, g1, b1 = self._BG_GRAD_LO
        r2, g2, b2 = self._BG_GRAD_HI
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"


class WaBotMappingPanel(ttk.Frame):
    """CRM-маппинг бота: gateway, prod schema id/name, CRM lookup/result
    URLs, переменные `local → remote` для CRM-ответа и поля POST-body
    регистрации результата. Раньше эта вкладка называлась «Обзор»; теперь
    «Обзор» — отдельный (пока пустой) таб для общей сводки, а здесь живёт
    именно маппинг."""

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg = load_config(company.key)
        cfg = self._cfg

        ttk.Label(
            self,
            text=t("wa_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        info = ttk.LabelFrame(self, text=t("wa_bot_section_meta"), padding=10)
        info.pack(fill="x", padx=12, pady=(8, 8))
        sname, sid = get_prod_schema(company.key)
        rows = [
            (t("wa_bot_gateway"), GATEWAY_NAME),
            (t("wa_bot_schema_name"), sname or "—"),
            (t("wa_bot_schema_id"), str(sid) if sid is not None else "—"),
            (t("wa_bot_crm_lookup_url"), cfg.get("crm_lookup_url") or "—"),
            (t("wa_bot_crm_result_url"), cfg.get("result_post_url") or "—"),
        ]
        for r, (k, v) in enumerate(rows):
            ttk.Label(info, text=k + ":", foreground=META_FG).grid(
                row=r, column=0, sticky="w", padx=(0, 8), pady=2
            )
            ttk.Label(info, text=v, foreground=TEXT_FG).grid(
                row=r, column=1, sticky="w", pady=2
            )
        # --- Actions row: live CRM probe + Webitel schema compare ---
        action_row = len(rows)
        ttk.Label(info, text=t("wa_bot_actions") + ":", foreground=META_FG).grid(
            row=action_row, column=0, sticky="w", padx=(0, 8), pady=(8, 2),
        )
        actions_box = ttk.Frame(info)
        actions_box.grid(row=action_row, column=1, sticky="w", pady=(8, 2))
        self._crm_test_btn = ttk.Button(
            actions_box,
            text=t("wa_bot_action_lookup_test"),
            command=self._test_crm_request,
        )
        self._crm_test_btn.pack(side="left")
        self._compare_btn = ttk.Button(
            actions_box,
            text=t("wa_bot_action_compare_schemas"),
            command=self._compare_with_schemas,
        )
        self._compare_btn.pack(side="left", padx=(8, 0))
        self._crm_test_status = ttk.Label(
            actions_box, text="", foreground=META_FG,
        )
        self._crm_test_status.pack(side="left", padx=(10, 0))

        # --- Lookup vars table (editable + can show CRM response) --------
        lookup = ttk.LabelFrame(self, text=t("wa_bot_section_lookup"), padding=10)
        lookup.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        lookup_tree_box = ttk.Frame(lookup)
        lookup_tree_box.pack(fill="both", expand=True)
        self._lookup_tree = ttk.Treeview(
            lookup_tree_box, columns=("local", "remote", "response"),
            show="headings", height=8,
        )
        self._lookup_tree.heading("local",    text=t("wa_bot_local_var"))
        self._lookup_tree.heading("remote",   text=t("wa_bot_remote_field"))
        self._lookup_tree.heading("response", text=t("wa_bot_col_in_response"))
        self._lookup_tree.column("local",    width=200, anchor="w")
        self._lookup_tree.column("remote",   width=260, anchor="w")
        self._lookup_tree.column("response", width=300, anchor="w")
        for tag, bg in (("ok", "#dcfce7"), ("warn", "#fee2e2")):
            self._lookup_tree.tag_configure(tag, background=bg)
        self._lookup_tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(
            lookup_tree_box, orient="vertical", command=self._lookup_tree.yview,
        )
        self._lookup_tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")

        self._lookup_iid_idx: dict[str, int] = {}
        for i, v in enumerate(cfg.get("crm_lookup_vars") or []):
            iid = self._lookup_tree.insert(
                "", "end",
                values=(v.get("local", ""), v.get("remote", ""), ""),
            )
            self._lookup_iid_idx[iid] = i
        self._lookup_tree.bind(
            "<Double-1>",
            lambda e: self._on_table_double_click(
                e, self._lookup_tree, "crm_lookup_vars",
                {"#1": "local", "#2": "remote"},
                self._lookup_iid_idx,
            ),
        )

        # --- Result POST body table (editable + schema compare) ----------
        result = ttk.LabelFrame(self, text=t("wa_bot_section_result"), padding=10)
        result.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        result_tree_box = ttk.Frame(result)
        result_tree_box.pack(fill="both", expand=True)
        self._result_tree = ttk.Treeview(
            result_tree_box, columns=("key", "value", "prod", "cand"),
            show="headings", height=8,
        )
        self._result_tree.heading("key",   text=t("wa_bot_field_key"))
        self._result_tree.heading("value", text=t("wa_bot_field_value"))
        self._result_tree.heading("prod",  text=t("wa_bot_col_prod_schema"))
        self._result_tree.heading("cand",  text=t("wa_bot_col_cand_schema"))
        self._result_tree.column("key",   width=170, anchor="w")
        self._result_tree.column("value", width=200, anchor="w")
        self._result_tree.column("prod",  width=200, anchor="w")
        self._result_tree.column("cand",  width=200, anchor="w")
        for tag, bg in (("ok", "#dcfce7"), ("warn", "#fee2e2")):
            self._result_tree.tag_configure(tag, background=bg)
        self._result_tree.pack(side="left", fill="both", expand=True)
        scl2 = ttk.Scrollbar(
            result_tree_box, orient="vertical", command=self._result_tree.yview,
        )
        self._result_tree.configure(yscrollcommand=scl2.set)
        scl2.pack(side="right", fill="y")

        self._result_iid_idx: dict[str, int] = {}
        for i, f in enumerate(cfg.get("result_post_fields") or []):
            iid = self._result_tree.insert(
                "", "end",
                values=(f.get("key", ""), f.get("value", ""), "", ""),
            )
            self._result_iid_idx[iid] = i
        self._result_tree.bind(
            "<Double-1>",
            lambda e: self._on_table_double_click(
                e, self._result_tree, "result_post_fields",
                {"#1": "key", "#2": "value"},
                self._result_iid_idx,
            ),
        )

        self._edit_status = ttk.Label(self, text="", foreground=META_FG)
        self._edit_status.pack(anchor="w", padx=14, pady=(0, 10))

    # --- CRM-by-phone probe ---------------------------------------------

    def _test_crm_request(self) -> None:
        info = (load_raw() or {}).get(self._company.key, {})
        host = str(info.get("crm_host") or "").strip()
        token = str(info.get("crm_access_token") or "").strip()
        header = str(info.get("crm_token_header") or "").strip()
        if not (host and token and header):
            self._crm_test_status.configure(
                text=t("wa_bot_crm_test_missing_creds"),
                foreground=ERR_FG,
            )
            return
        self._crm_test_btn.configure(state="disabled")
        self._crm_test_status.configure(
            text=t("wa_bot_crm_test_picking_phone"), foreground=META_FG,
        )
        threading.Thread(
            target=self._test_crm_worker,
            args=(host, header, token),
            daemon=True,
        ).start()

    def _test_crm_worker(self, host: str, header: str, token: str) -> None:
        phone, err = fetch_active_loan_phone(self._company)
        if err or not phone:
            self._after_crm_test(None, err or "phone not found", None)
            return
        if self.winfo_exists():
            self.after(
                0,
                lambda: self._crm_test_status.configure(
                    text=t("wa_bot_crm_test_calling").format(phone=phone),
                    foreground=META_FG,
                ),
            )
        code, body, http_err = call_crm_by_phone(host, header, token, phone)
        if http_err:
            self._after_crm_test(False, f"phone {phone} → {http_err}", None)
        else:
            parsed = None
            try:
                parsed = json.loads(body) if body else None
            except (json.JSONDecodeError, TypeError):
                parsed = None
            self._after_crm_test(True, f"phone {phone} → HTTP {code}", parsed)

    def _after_crm_test(
        self, ok: Optional[bool], msg: str, response: Optional[dict],
    ) -> None:
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_crm_test(ok, msg, response))

    def _render_crm_test(
        self, ok: Optional[bool], msg: str, response: Optional[dict],
    ) -> None:
        if not self.winfo_exists():
            return
        self._crm_test_btn.configure(state="normal")
        if ok is True:
            self._crm_test_status.configure(
                text=t("wa_bot_crm_test_ok").format(detail=msg),
                foreground=OK_FG,
            )
        else:
            self._crm_test_status.configure(
                text=t("wa_bot_crm_test_err").format(detail=msg),
                foreground=ERR_FG,
            )

        # Fill «В ответе CRM» column + color rows by presence/absence.
        if not isinstance(response, dict):
            return
        for iid, idx in self._lookup_iid_idx.items():
            items = self._cfg.get("crm_lookup_vars") or []
            if idx >= len(items):
                continue
            remote = (items[idx].get("remote") or "").strip()
            if not remote:
                self._lookup_tree.set(iid, "response", "—")
                self._lookup_tree.item(iid, tags=("warn",))
                continue
            present, val = _json_path_value(response, remote)
            if present:
                self._lookup_tree.set(iid, "response", _short_repr(val))
                self._lookup_tree.item(iid, tags=("ok",))
            else:
                self._lookup_tree.set(iid, "response", "—")
                self._lookup_tree.item(iid, tags=("warn",))

    # --- Inline edit on editable columns --------------------------------

    def _on_table_double_click(
        self,
        event,
        tree: ttk.Treeview,
        cfg_section: str,
        editable_cols: dict[str, str],
        iid_idx: dict[str, int],
    ) -> None:
        col = tree.identify_column(event.x)
        cfg_field = editable_cols.get(col)
        if cfg_field is None:
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        bbox = tree.bbox(iid, col)
        if not bbox:
            return
        x, y, w, h = bbox

        current = tree.set(iid, col)
        entry = ttk.Entry(tree)
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def commit(_e=None) -> None:
            new_val = entry.get().strip()
            entry.destroy()
            if new_val == current:
                return
            tree.set(iid, col, new_val)
            idx = iid_idx.get(iid)
            if idx is None:
                return
            items = self._cfg.setdefault(cfg_section, [])
            while len(items) <= idx:
                items.append({})
            items[idx][cfg_field] = new_val
            save_config(self._company.key, self._cfg)
            self._edit_status.configure(
                text=t("wa_bot_edit_saved"), foreground=OK_FG,
            )

        def cancel(_e=None) -> str:
            entry.destroy()
            return "break"

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    # --- Compare mapping vs live Webitel schemas (prod + candidate) -----

    def _compare_with_schemas(self) -> None:
        self._compare_btn.configure(state="disabled")
        self._crm_test_status.configure(
            text=t("wa_bot_compare_loading"), foreground=META_FG,
        )
        threading.Thread(
            target=self._compare_worker, daemon=True,
        ).start()

    def _compare_worker(self) -> None:
        from ..wa_bot_config import get_candidate_schema, get_prod_schema
        from ..data import load_raw as _load_raw
        from ..webitel import WebitelClient, WebitelError
        info = _load_raw().get(self._company.key, {}) or {}
        host = (info.get("webitel_host") or "").strip()
        token = (info.get("webitel_access_token") or "").strip()
        prod_name, prod_id = get_prod_schema(self._company.key)
        cand_name, cand_id = get_candidate_schema(self._company.key)
        if not host or not token or not prod_id:
            self._after_compare(None, t("wa_bot_compare_no_creds"))
            return
        client = WebitelClient(host, token)
        try:
            prod_extract = self._extract_post_signature(client.get_schema(int(prod_id)))
        except WebitelError as exc:
            self._after_compare(None, f"prod {prod_id}: {exc}")
            return
        cand_extract = None
        if cand_id:
            try:
                cand_extract = self._extract_post_signature(client.get_schema(int(cand_id)))
            except WebitelError as exc:
                cand_extract = {"_error": f"cand {cand_id}: {exc}"}
        self._after_compare(
            {
                "prod": {"id": prod_id, "name": prod_name, **prod_extract},
                "candidate": (
                    {"id": cand_id, "name": cand_name, **cand_extract}
                    if cand_extract is not None else None
                ),
            },
            None,
        )

    @staticmethod
    def _extract_post_signature(schema_obj: dict) -> dict:
        """Найти httpRequest-ноду с robot_phone_result и вытащить URL + поля body."""
        payload = schema_obj.get("payload") or {}
        for n in payload.get("nodes") or []:
            sch = n.get("schema") or {}
            url = (sch.get("url") or "")
            if "robot_phone_result" in url:
                data = sch.get("data") or ""
                fields = _parse_post_body(data)
                return {"url": url, "fields": fields}
        return {"url": "", "fields": {}}

    def _after_compare(self, snap: Optional[dict], err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_compare(snap, err))

    def _render_compare(self, snap: Optional[dict], err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._compare_btn.configure(state="normal")
        if err:
            self._crm_test_status.configure(text=err, foreground=ERR_FG)
            return

        prod = snap.get("prod") or {}
        cand = snap.get("candidate") or {}
        has_cand = bool(cand)

        prod_fields = prod.get("fields") or {}
        cand_fields = cand.get("fields") or {}

        # Заполняем prod/cand колонки для каждой строки и раскрашиваем по
        # совпадению с маппингом.
        all_ok = True
        any_filled = False
        for iid, idx in self._result_iid_idx.items():
            items = self._cfg.get("result_post_fields") or []
            if idx >= len(items):
                continue
            key = items[idx].get("key", "")
            mapping_val = items[idx].get("value", "")
            p_val = prod_fields.get(key, "")
            c_val = cand_fields.get(key, "") if has_cand else ""
            self._result_tree.set(iid, "prod", p_val)
            self._result_tree.set(iid, "cand", c_val)
            if has_cand:
                match = (mapping_val == p_val == c_val)
            else:
                match = (mapping_val == p_val)
            tag = "ok" if match else "warn"
            self._result_tree.item(iid, tags=(tag,))
            any_filled = True
            if not match:
                all_ok = False

        # Дополнительно — короткий статус по URL и итог.
        prod_url = prod.get("url") or ""
        cand_url = cand.get("url") if has_cand else None
        mapping_url = self._cfg.get("result_post_url") or ""
        url_ok = (mapping_url == prod_url) and (not has_cand or mapping_url == cand_url)
        if not url_ok:
            all_ok = False
        status_parts = []
        status_parts.append(
            t("wa_bot_compare_subtitle").format(
                prod=f"id={prod.get('id')}",
                candidate=(f"id={cand.get('id')}" if has_cand else "—"),
            )
        )
        if not url_ok:
            status_parts.append(
                f"URL: mapping={mapping_url} / prod={prod_url}"
                + (f" / cand={cand_url}" if has_cand else "")
            )
        status_parts.append(
            t("wa_bot_compare_match") if all_ok else t("wa_bot_compare_mismatch")
        )
        self._crm_test_status.configure(
            text=" · ".join(status_parts),
            foreground=OK_FG if all_ok else ERR_FG,
        )


def _json_path_value(obj, path: str) -> tuple[bool, object]:
    """Lookup dotted JSON path in `obj`. Returns (present, value).

    Поддерживает `foo`, `foo.bar`, `foo.bar.baz`. Если по пути не нашли —
    возвращает (False, None)."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return (False, None)
    return (True, cur)


def _short_repr(v) -> str:
    """Human-readable preview of any JSON value (truncated)."""
    if v is None:
        return "null"
    if isinstance(v, (str, int, float, bool)):
        s = str(v)
    else:
        import json as _j
        try:
            s = _j.dumps(v, ensure_ascii=False)
        except Exception:
            s = repr(v)
    return s if len(s) <= 60 else s[:57] + "…"


def _parse_post_body(data: str) -> dict:
    """Грубый JSON-парсер для body POST-результата (значения остаются как
    строки, даже если содержат `${...}` — это сравнивается со значениями
    из маппинга «как есть»)."""
    import json as _json
    try:
        return _json.loads(data) if data else {}
    except _json.JSONDecodeError:
        # Тело в схеме часто содержит переносы строк и неэкранированные
        # `${var}` — пробуем простой regex-парс на `"key": "value"`.
        import re
        out: dict = {}
        for m in re.finditer(r'"([^"]+)"\s*:\s*"([^"]*)"', data):
            out[m.group(1)] = m.group(2)
        return out


class WaBotFunctionsPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)


        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        self._fn_list = tk.Listbox(left, exportselection=False, width=28)
        self._fn_list.pack(side="left", fill="y")
        scl = ttk.Scrollbar(left, orient="vertical", command=self._fn_list.yview)
        self._fn_list.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        self._fn_list.bind("<<ListboxSelect>>", self._on_fn_select)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(right, text=t("wa_bot_fn_name")).grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        self._fn_name = ttk.Entry(right)
        self._fn_name.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        ttk.Label(right, text=t("wa_bot_fn_desc")).grid(
            row=1, column=0, sticky="nw", pady=(0, 2)
        )
        self._fn_desc = tk.Text(right, height=3, wrap="word")
        self._fn_desc.grid(row=1, column=1, sticky="ew", pady=(0, 4))
        ttk.Label(right, text=t("wa_bot_fn_params")).grid(
            row=2, column=0, sticky="nw", pady=(0, 2)
        )
        self._fn_params = tk.Text(right, height=20, wrap="none")
        self._fn_params.grid(row=2, column=1, sticky="nsew", pady=(0, 4))
        right.columnconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(toolbar, text=t("btn_add"), command=self._fn_add).pack(side="left")
        ttk.Button(toolbar, text=t("btn_delete"), command=self._fn_delete).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(toolbar, text=t("btn_save"), command=self._fn_save_current).pack(
            side="right"
        )
        self._fn_status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._fn_status.pack(side="right", padx=(0, 8))

        self._refresh_fn_list()
        if self._fn_list.size() > 0:
            self._fn_list.selection_set(0)
            self._on_fn_select(None)

    def _refresh_fn_list(self) -> None:
        self._fn_list.delete(0, "end")
        fns = (self._cfg.get("gpt") or {}).get("functions") or []
        for f in fns:
            self._fn_list.insert("end", f.get("name") or "(no name)")

    def _selected_fn_index(self) -> Optional[int]:
        sel = self._fn_list.curselection()
        return int(sel[0]) if sel else None

    def _on_fn_select(self, _e) -> None:
        idx = self._selected_fn_index()
        if idx is None:
            return
        fns = (self._cfg.get("gpt") or {}).get("functions") or []
        if idx >= len(fns):
            return
        f = fns[idx]
        self._fn_name.delete(0, "end")
        self._fn_name.insert(0, f.get("name") or "")
        self._fn_desc.delete("1.0", "end")
        self._fn_desc.insert("1.0", f.get("description") or "")
        self._fn_params.delete("1.0", "end")
        self._fn_params.insert(
            "1.0", json.dumps(f.get("parameters") or {}, ensure_ascii=False, indent=2)
        )

    def _fn_add(self) -> None:
        gpt = self._cfg.setdefault("gpt", {})
        fns = gpt.setdefault("functions", [])
        fns.append({
            "name": "new_function",
            "description": "",
            "enabled": True,
            "parameters": {"type": "object", "properties": {}},
            "enum_descriptions": {},
        })
        save_config(self._company.key, self._cfg)
        self._refresh_fn_list()
        self._fn_list.selection_clear(0, "end")
        self._fn_list.selection_set("end")
        self._on_fn_select(None)

    def _fn_delete(self) -> None:
        idx = self._selected_fn_index()
        if idx is None:
            return
        if not messagebox.askyesno("?", t("wa_bot_fn_confirm_delete")):
            return
        fns = (self._cfg.get("gpt") or {}).get("functions") or []
        if 0 <= idx < len(fns):
            fns.pop(idx)
            save_config(self._company.key, self._cfg)
            self._refresh_fn_list()

    def _fn_save_current(self) -> None:
        idx = self._selected_fn_index()
        if idx is None:
            return
        gpt = self._cfg.setdefault("gpt", {})
        fns = gpt.setdefault("functions", [])
        if idx >= len(fns):
            return
        try:
            params = json.loads(self._fn_params.get("1.0", "end").strip() or "{}")
        except json.JSONDecodeError as e:
            self._fn_status.configure(text=f"JSON error: {e}", foreground="#dc2626")
            return
        existing = fns[idx] if isinstance(fns[idx], dict) else {}
        fns[idx] = {
            **existing,
            "name": self._fn_name.get().strip(),
            "description": self._fn_desc.get("1.0", "end").strip(),
            "parameters": params,
        }
        save_config(self._company.key, self._cfg)
        self._refresh_fn_list()
        self._fn_list.selection_set(idx)
        self._fn_status.configure(text=t("wa_bot_saved"), foreground=OK_FG)


class WaBotPromptsPanel(ttk.Frame):
    """Prompts editor.

    Layout (top → bottom):
      * Основной промт — большое текстовое поле (system / developer message).
      * Дополнительный промт — короткое текстовое поле (стилевые правила).
      * Дерево «Что попадёт в тело запроса»: функции и enum-результаты,
        каждый узел можно включить/выключить и снабдить описанием. Иерархия
        повторяет структуру итогового JSON-тела.
      * Сгенерированное тело запроса — обновляется по нажатию кнопки.
    """

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)
        gpt = self._cfg.setdefault("gpt", {})
        gpt.setdefault("main_prompt", "")
        gpt.setdefault("secondary_prompt", "")
        gpt.setdefault("functions", [])
        gpt.setdefault("builder", dict(DEFAULT_BUILDER))

        self._iid_map: dict[str, tuple] = {}
        self._editor_target: Optional[tuple] = None

        # ---- Основной промт ----
        ttk.Label(
            self, text=t("wa_bot_prompt_main"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 2))
        self._main_prompt = tk.Text(self, height=10, wrap="word")
        self._main_prompt.pack(fill="x", padx=12, pady=(0, 8))
        self._main_prompt.insert("1.0", gpt.get("main_prompt") or "")

        # ---- Дополнительный промт ----
        ttk.Label(
            self, text=t("wa_bot_prompt_secondary"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        self._sec_prompt = tk.Text(self, height=4, wrap="word")
        self._sec_prompt.pack(fill="x", padx=12, pady=(0, 8))
        self._sec_prompt.insert("1.0", gpt.get("secondary_prompt") or "")

        # ---- Иерархия функций / результатов ----
        struct = ttk.LabelFrame(
            self, text=t("wa_bot_prompts_structure"), padding=8,
        )
        struct.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        struct_inner = ttk.Frame(struct)
        struct_inner.pack(fill="both", expand=True)

        tree_frame = ttk.Frame(struct_inner)
        tree_frame.pack(side="left", fill="both", expand=True)
        self._tree = ttk.Treeview(
            tree_frame,
            columns=("status", "desc"),
            show="tree headings",
            height=12,
        )
        self._tree.heading("#0", text=t("wa_bot_prompts_col_name"))
        self._tree.heading("status", text=t("wa_bot_prompts_col_enabled"))
        self._tree.heading("desc", text=t("wa_bot_prompts_col_desc"))
        self._tree.column("#0", width=300, anchor="w", stretch=True)
        self._tree.column("status", width=80, anchor="center", stretch=False)
        self._tree.column("desc", width=380, anchor="w", stretch=True)
        self._tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self._tree.yview,
        )
        self._tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_tree_double_click)

        ed = ttk.Frame(struct_inner)
        ed.pack(side="left", fill="y", padx=(10, 0))
        ttk.Label(ed, text=t("wa_bot_prompts_node_path") + ":").grid(
            row=0, column=0, sticky="w"
        )
        self._ed_path_var = tk.StringVar(value="")
        ttk.Label(
            ed, textvariable=self._ed_path_var,
            foreground=META_FG, wraplength=300, justify="left",
        ).grid(row=0, column=1, sticky="w", pady=(0, 4))

        ttk.Label(ed, text=t("wa_bot_prompts_node_name") + ":").grid(
            row=1, column=0, sticky="w"
        )
        self._ed_name = ttk.Entry(ed, width=36)
        self._ed_name.grid(row=1, column=1, sticky="ew", pady=(0, 4))
        self._ed_name.configure(state="readonly")

        ttk.Label(ed, text=t("wa_bot_prompts_node_desc") + ":").grid(
            row=2, column=0, sticky="nw", pady=(4, 2)
        )
        self._ed_desc = tk.Text(ed, width=42, height=8, wrap="word")
        self._ed_desc.grid(row=2, column=1, sticky="nsew", pady=(4, 4))
        ed.columnconfigure(1, weight=1)
        ed.rowconfigure(2, weight=1)

        self._ed_enabled_var = tk.BooleanVar(value=True)
        self._ed_enabled = ttk.Checkbutton(
            ed,
            text=t("wa_bot_prompts_node_enabled"),
            variable=self._ed_enabled_var,
        )
        self._ed_enabled.grid(row=3, column=1, sticky="w", pady=(0, 4))

        ed_btns = ttk.Frame(ed)
        ed_btns.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(
            ed_btns, text=t("wa_bot_prompts_apply"),
            command=self._apply_node_edits,
        ).pack(side="left")
        ttk.Button(
            ed_btns, text=t("wa_bot_prompts_toggle"),
            command=self._toggle_selected,
        ).pack(side="left", padx=(6, 0))


        # ---- Сгенерированное тело ----
        out = ttk.LabelFrame(
            self, text=t("wa_bot_builder_output"), padding=8,
        )
        out.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._body_text = tk.Text(out, height=10, wrap="none")
        self._body_text.pack(side="left", fill="both", expand=True)
        scl2 = ttk.Scrollbar(
            out, orient="vertical", command=self._body_text.yview,
        )
        self._body_text.configure(yscrollcommand=scl2.set)
        scl2.pack(side="right", fill="y")

        # ---- Toolbar ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(
            toolbar, text=t("wa_bot_builder_regenerate"),
            command=self._regenerate,
        ).pack(side="left")
        ttk.Button(
            toolbar, text=t("wa_bot_builder_copy"),
            command=self._copy_body,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            toolbar, text=t("btn_save"), command=self._save_all,
        ).pack(side="right")
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="right", padx=(0, 8))

        self._refresh_tree()
        self._regenerate()

    # ------------------------------------------------------------------
    # Tree
    # ------------------------------------------------------------------

    @staticmethod
    def _mark(enabled: bool) -> str:
        return "✓" if enabled else "—"

    @staticmethod
    def _short(s: str, n: int = 80) -> str:
        s = (s or "").replace("\n", " ").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    def _refresh_tree(self) -> None:
        prev_open: set = set()
        for iid, info in self._iid_map.items():
            try:
                if self._tree.item(iid, "open"):
                    prev_open.add(info)
            except tk.TclError:
                pass
        first_call = not self._iid_map

        self._tree.delete(*self._tree.get_children())
        self._iid_map.clear()

        gpt = self._cfg.get("gpt") or {}
        fns = gpt.get("functions") or []

        fns_root = self._tree.insert(
            "", "end",
            text=t("wa_bot_prompts_node_functions"),
            values=("", ""), open=True,
        )

        for fi, fn in enumerate(fns):
            open_fn = first_call or ("function", fi) in prev_open
            fn_iid = self._tree.insert(
                fns_root, "end",
                text=fn.get("name") or "(no name)",
                values=(
                    self._mark(fn.get("enabled", True)),
                    self._short(fn.get("description") or ""),
                ),
                open=open_fn,
            )
            self._iid_map[fn_iid] = ("function", fi)

            params = fn.get("parameters") or {}
            props = params.get("properties") or {}
            if not isinstance(props, dict):
                continue
            enum_meta = fn.get("enum_descriptions") or {}
            for prop_name, prop_def in props.items():
                if not isinstance(prop_def, dict):
                    continue
                values = prop_def.get("enum")
                if not isinstance(values, list) or not values:
                    continue
                open_prop = ("enum_param", fi, prop_name) in prev_open
                prop_iid = self._tree.insert(
                    fn_iid, "end",
                    text=prop_name,
                    values=("", self._short(prop_def.get("description") or "")),
                    open=open_prop,
                )
                self._iid_map[prop_iid] = ("enum_param", fi, prop_name)

                meta = enum_meta.get(prop_name) or {}
                for v in values:
                    vmeta = meta.get(v) or {}
                    v_iid = self._tree.insert(
                        prop_iid, "end",
                        text=v,
                        values=(
                            self._mark(vmeta.get("enabled", True)),
                            self._short(vmeta.get("description") or ""),
                        ),
                    )
                    self._iid_map[v_iid] = ("enum_value", fi, prop_name, v)

        # Restore selection on the same logical node, if present.
        if self._editor_target is not None:
            for iid, info in self._iid_map.items():
                if info == self._editor_target:
                    self._tree.selection_set(iid)
                    self._tree.see(iid)
                    break

    # ------------------------------------------------------------------
    # Tree interactions
    # ------------------------------------------------------------------

    def _on_tree_select(self, _e) -> None:
        sel = self._tree.selection()
        if not sel:
            self._editor_target = None
            self._set_editor("", "", True, enabled_visible=False, path=t("wa_bot_prompts_no_selection"))
            return
        info = self._iid_map.get(sel[0])
        if not info:
            self._editor_target = None
            self._set_editor("", "", True, enabled_visible=False, path=t("wa_bot_prompts_no_selection"))
            return
        gpt = self._cfg.get("gpt") or {}
        fns = gpt.get("functions") or []
        if info[0] == "function":
            _, fi = info
            fn = fns[fi]
            self._editor_target = info
            self._set_editor(
                fn.get("name") or "",
                fn.get("description") or "",
                fn.get("enabled", True),
                enabled_visible=True,
                path=t("wa_bot_prompts_node_functions"),
            )
        elif info[0] == "enum_value":
            _, fi, prop_name, v = info
            fn = fns[fi]
            meta = ((fn.get("enum_descriptions") or {}).get(prop_name) or {}).get(v) or {}
            self._editor_target = info
            self._set_editor(
                v,
                meta.get("description") or "",
                meta.get("enabled", True),
                enabled_visible=True,
                path=f"{fn.get('name') or '?'} → {prop_name}",
            )
        elif info[0] == "enum_param":
            _, fi, prop_name = info
            fn = fns[fi]
            params = fn.get("parameters") or {}
            prop = (params.get("properties") or {}).get(prop_name) or {}
            self._editor_target = info
            self._set_editor(
                prop_name,
                prop.get("description") or "",
                True,
                enabled_visible=False,
                path=fn.get("name") or "?",
            )
        else:
            self._editor_target = None
            self._set_editor("", "", True, enabled_visible=False, path="")

    def _set_editor(
        self, name: str, desc: str, enabled: bool,
        enabled_visible: bool, path: str,
    ) -> None:
        self._ed_name.configure(state="normal")
        self._ed_name.delete(0, "end")
        self._ed_name.insert(0, name)
        self._ed_name.configure(state="readonly")
        self._ed_path_var.set(path)
        self._ed_desc.delete("1.0", "end")
        self._ed_desc.insert("1.0", desc)
        self._ed_enabled_var.set(enabled)
        if enabled_visible:
            self._ed_enabled.state(["!disabled"])
        else:
            self._ed_enabled.state(["disabled"])

    def _on_tree_double_click(self, event) -> None:
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        info = self._iid_map.get(iid)
        if not info or info[0] not in ("function", "enum_value"):
            return
        self._tree.selection_set(iid)
        self._toggle(info)

    def _toggle_selected(self) -> None:
        if not self._editor_target:
            return
        if self._editor_target[0] not in ("function", "enum_value"):
            return
        self._toggle(self._editor_target)

    def _toggle(self, info: tuple) -> None:
        gpt = self._cfg.setdefault("gpt", {})
        fns = gpt.setdefault("functions", [])
        if info[0] == "function":
            _, fi = info
            fn = fns[fi]
            fn["enabled"] = not fn.get("enabled", True)
        elif info[0] == "enum_value":
            _, fi, prop_name, v = info
            ed = fns[fi].setdefault("enum_descriptions", {})
            pmeta = ed.setdefault(prop_name, {})
            vmeta = pmeta.setdefault(v, {})
            vmeta["enabled"] = not vmeta.get("enabled", True)
        self._refresh_tree()
        self._on_tree_select(None)
        self._regenerate()

    # ------------------------------------------------------------------
    # Editor
    # ------------------------------------------------------------------

    def _apply_node_edits(self) -> None:
        info = self._editor_target
        if not info or info[0] not in ("function", "enum_value"):
            return
        desc = self._ed_desc.get("1.0", "end").rstrip()
        enabled = bool(self._ed_enabled_var.get())
        gpt = self._cfg.setdefault("gpt", {})
        fns = gpt.setdefault("functions", [])
        if info[0] == "function":
            _, fi = info
            fns[fi]["description"] = desc
            fns[fi]["enabled"] = enabled
        else:
            _, fi, prop_name, v = info
            ed = fns[fi].setdefault("enum_descriptions", {})
            pmeta = ed.setdefault(prop_name, {})
            vmeta = pmeta.setdefault(v, {})
            vmeta["description"] = desc
            vmeta["enabled"] = enabled
        self._refresh_tree()
        self._regenerate()
        self._status.configure(text=t("wa_bot_saved"), foreground=OK_FG)

    # ------------------------------------------------------------------
    # Body / persistence
    # ------------------------------------------------------------------

    def _sync_prompts_into_cfg(self) -> None:
        gpt = self._cfg.setdefault("gpt", {})
        gpt["main_prompt"] = self._main_prompt.get("1.0", "end").rstrip()
        gpt["secondary_prompt"] = self._sec_prompt.get("1.0", "end").rstrip()

    def _regenerate(self) -> None:
        self._sync_prompts_into_cfg()
        body = build_request_body(self._cfg)
        self._body_text.delete("1.0", "end")
        self._body_text.insert(
            "1.0", json.dumps(body, ensure_ascii=False, indent=2),
        )
        self._status.configure(text=t("wa_bot_builder_generated"), foreground=OK_FG)

    def _copy_body(self) -> None:
        text = self._body_text.get("1.0", "end").rstrip()
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self._status.configure(text=t("wa_bot_builder_copied"), foreground=OK_FG)
        except tk.TclError:
            self._status.configure(text="—", foreground="#dc2626")

    def _save_all(self) -> None:
        self._sync_prompts_into_cfg()
        save_config(self._company.key, self._cfg)
        self._regenerate()
        self._status.configure(text=t("wa_bot_saved"), foreground=OK_FG)


# ----------------------------------------------------------------------
# Конструктор тела запроса в OpenAI Responses API
# ----------------------------------------------------------------------

OPENAI_MODELS = (
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4",
    "o1-mini",
    "o3-mini",
)
TOOL_CHOICE_KINDS = ("auto", "required", "none", "function")


class WaBotBuilderPanel(ttk.Frame):
    """Полноценный конструктор тела запроса в OpenAI Responses API.

    Подгружает model / instructions / tools из конфига компании, добавляет
    параметры запроса (tool_choice, temperature, max_output_tokens, store,
    parallel_tool_calls) и в реальном времени собирает корректный JSON
    body, который потом подставляется в Webitel-схему как payload
    `httpRequest` к `/v1/responses`."""

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)
        gpt = self._cfg.setdefault("gpt", {})
        gpt.setdefault("builder", dict(DEFAULT_BUILDER))
        b = {**DEFAULT_BUILDER, **(gpt.get("builder") or {})}


        # ---- Параметры запроса ----
        cfg_box = ttk.LabelFrame(self, text=t("wa_bot_builder_params"), padding=10)
        cfg_box.pack(fill="x", padx=12, pady=(0, 8))

        # row 0 — model + endpoint
        ttk.Label(cfg_box, text=t("wa_bot_builder_endpoint")).grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self._endpoint_var = tk.StringVar(value=b.get("endpoint", "/v1/responses"))
        ttk.Entry(cfg_box, textvariable=self._endpoint_var, width=24).grid(
            row=0, column=1, sticky="w", pady=2
        )
        ttk.Label(cfg_box, text=t("wa_bot_builder_model")).grid(
            row=0, column=2, sticky="w", padx=(16, 6), pady=2
        )
        self._model_var = tk.StringVar(value=b.get("model"))
        ttk.Combobox(
            cfg_box, textvariable=self._model_var, values=OPENAI_MODELS, width=22
        ).grid(row=0, column=3, sticky="w", pady=2)

        # row 1 — conversation var
        ttk.Label(cfg_box, text=t("wa_bot_builder_conv_var")).grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self._conv_var = tk.StringVar(value=b.get("conversation_var", ""))
        ttk.Entry(cfg_box, textvariable=self._conv_var, width=24).grid(
            row=1, column=1, sticky="w", pady=2
        )
        ttk.Label(cfg_box, text=t("wa_bot_builder_user_var")).grid(
            row=1, column=2, sticky="w", padx=(16, 6), pady=2
        )
        self._user_var = tk.StringVar(value=b.get("user_message_var"))
        ttk.Entry(cfg_box, textvariable=self._user_var, width=24).grid(
            row=1, column=3, sticky="w", pady=2
        )

        # row 2 — tool_choice + function
        ttk.Label(cfg_box, text=t("wa_bot_builder_tool_choice")).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self._tc_var = tk.StringVar(value=b.get("tool_choice", "auto"))
        ttk.Combobox(
            cfg_box, textvariable=self._tc_var, values=TOOL_CHOICE_KINDS,
            state="readonly", width=14,
        ).grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(cfg_box, text=t("wa_bot_builder_tool_choice_fn")).grid(
            row=2, column=2, sticky="w", padx=(16, 6), pady=2
        )
        self._tcf_var = tk.StringVar(value=b.get("tool_choice_function", ""))
        fn_names = [
            f.get("name", "") for f in (gpt.get("functions") or [])
        ]
        ttk.Combobox(
            cfg_box, textvariable=self._tcf_var, values=fn_names, width=24
        ).grid(row=2, column=3, sticky="w", pady=2)

        # row 3 — temperature, top_p
        ttk.Label(cfg_box, text=t("wa_bot_builder_temperature")).grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self._temp_var = tk.StringVar(value=str(b.get("temperature", 0.5)))
        ttk.Spinbox(
            cfg_box, from_=0.0, to=2.0, increment=0.1,
            textvariable=self._temp_var, width=8,
        ).grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(cfg_box, text=t("wa_bot_builder_top_p")).grid(
            row=3, column=2, sticky="w", padx=(16, 6), pady=2
        )
        self._topp_var = tk.StringVar(value=str(b.get("top_p", 1.0)))
        ttk.Spinbox(
            cfg_box, from_=0.0, to=1.0, increment=0.05,
            textvariable=self._topp_var, width=8,
        ).grid(row=3, column=3, sticky="w", pady=2)

        # row 4 — max_output_tokens, store, parallel
        ttk.Label(cfg_box, text=t("wa_bot_builder_max_tokens")).grid(
            row=4, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self._mot_var = tk.StringVar(value=str(b.get("max_output_tokens", 600)))
        ttk.Spinbox(
            cfg_box, from_=50, to=8000, increment=50,
            textvariable=self._mot_var, width=8,
        ).grid(row=4, column=1, sticky="w", pady=2)
        self._store_var = tk.BooleanVar(value=bool(b.get("store", True)))
        ttk.Checkbutton(
            cfg_box, text=t("wa_bot_builder_store"), variable=self._store_var,
        ).grid(row=4, column=2, sticky="w", padx=(16, 6), pady=2)
        self._par_var = tk.BooleanVar(value=bool(b.get("parallel_tool_calls", False)))
        ttk.Checkbutton(
            cfg_box, text=t("wa_bot_builder_parallel"), variable=self._par_var,
        ).grid(row=4, column=3, sticky="w", pady=2)

        # row 5 — strict tools
        self._strict_var = tk.BooleanVar(value=bool(b.get("strict_tools", False)))
        ttk.Checkbutton(
            cfg_box, text=t("wa_bot_builder_strict"), variable=self._strict_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        # ---- Шаблон client_content (вшивается в developer-message) ----
        ct_box = ttk.LabelFrame(
            self, text=t("wa_bot_builder_client_content"), padding=10
        )
        ct_box.pack(fill="x", padx=12, pady=(0, 8))
        self._content_text = tk.Text(ct_box, height=8, wrap="word")
        self._content_text.pack(fill="x")
        self._content_text.insert("1.0", b.get("client_content_template") or "")

        # ---- Сгенерированное тело запроса ----
        out_box = ttk.LabelFrame(self, text=t("wa_bot_builder_output"), padding=10)
        out_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._body_text = tk.Text(out_box, height=18, wrap="none")
        self._body_text.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(out_box, orient="vertical", command=self._body_text.yview)
        self._body_text.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")

        # ---- Toolbar ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(
            toolbar, text=t("wa_bot_builder_regenerate"),
            command=self._regenerate,
        ).pack(side="left")
        ttk.Button(
            toolbar, text=t("wa_bot_builder_copy"),
            command=self._copy_to_clipboard,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            toolbar, text=t("btn_save"),
            command=self._save,
        ).pack(side="right")
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="right", padx=(0, 8))

        self._regenerate()

    def _gather(self) -> dict:
        return {
            "endpoint": self._endpoint_var.get().strip(),
            "model": self._model_var.get().strip(),
            "conversation_var": self._conv_var.get().strip(),
            "user_message_var": self._user_var.get().strip(),
            "tool_choice": self._tc_var.get().strip() or "auto",
            "tool_choice_function": self._tcf_var.get().strip(),
            "temperature": self._safe_float(self._temp_var.get(), 0.5),
            "top_p": self._safe_float(self._topp_var.get(), 1.0),
            "max_output_tokens": self._safe_int(self._mot_var.get(), 600),
            "store": bool(self._store_var.get()),
            "parallel_tool_calls": bool(self._par_var.get()),
            "strict_tools": bool(self._strict_var.get()),
            "client_content_template": self._content_text.get("1.0", "end").rstrip(),
        }

    @staticmethod
    def _safe_float(v: str, default: float) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(v: str, default: int) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default

    def _regenerate(self) -> None:
        gpt = self._cfg.setdefault("gpt", {})
        gpt["builder"] = self._gather()
        body = build_request_body(self._cfg)
        self._body_text.delete("1.0", "end")
        self._body_text.insert("1.0", json.dumps(body, ensure_ascii=False, indent=2))
        self._status.configure(text=t("wa_bot_builder_generated"), foreground=OK_FG)

    def _copy_to_clipboard(self) -> None:
        text = self._body_text.get("1.0", "end").rstrip()
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self._status.configure(text=t("wa_bot_builder_copied"), foreground=OK_FG)
        except tk.TclError:
            self._status.configure(text="—", foreground="#dc2626")

    def _save(self) -> None:
        gpt = self._cfg.setdefault("gpt", {})
        gpt["builder"] = self._gather()
        save_config(self._company.key, self._cfg)
        self._status.configure(text=t("wa_bot_saved"), foreground=OK_FG)


# ---------------------------------------------------------------------------
# Senders panel — live mirror of Infobip portal's WhatsApp Senders table.
# ---------------------------------------------------------------------------

# Colour swatches for tag-driven row foregrounds. Greens / oranges / reds
# match what we use across the dashboard alert pages so the operator
# learns one palette.
_QUALITY_FG = {
    "HIGH":    OK_FG,
    "MEDIUM":  "#d97706",
    "LOW":     ERR_FG,
    "UNKNOWN": META_FG,
}

_LIMIT_FG = {
    "UNLIMITED":  OK_FG,
    "LIMIT_100K": OK_FG,
    "LIMIT_10K":  TEXT_FG,
    "LIMIT_2K":   "#d97706",
    "LIMIT_250":  ERR_FG,
    "LIMIT_NA":   META_FG,
}


def _status_fg(status: str) -> str:
    if status in STATUS_BAD:
        return ERR_FG
    if status in STATUS_WARN:
        return "#d97706"
    if status == "CONNECTED":
        return OK_FG
    return META_FG


class WaBotSendersPanel(ttk.Frame):
    """Live read-only view of every WhatsApp sender attached to the
    company's Infobip subaccount. Same columns as the Infobip portal's
    `Channels & Numbers · WhatsApp · Senders` page (DisplayName /
    Sender / Registration / Quality / Status / Messaging limit) plus a
    manual Refresh that drops the in-memory cache and re-pulls.

    Data loads on a daemon thread on panel construction; 30-min
    in-process cache lives in `app.infobip` so flipping between tabs
    doesn't hit Infobip every time."""

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company

        ttk.Label(
            self,
            text=t("wa_senders_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=14, pady=(0, 8))
        self._refresh_btn = ttk.Button(
            toolbar, text=t("btn_refresh"), command=self._reload,
        )
        self._refresh_btn.pack(side="left")
        self._status = ttk.Label(toolbar, text=t("dash_loading"), foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        cols = ("display", "sender", "registration", "quality", "status", "limit")
        self.tree = ttk.Treeview(
            self, columns=cols, show="headings", selectmode="browse",
        )
        self.tree.heading("display", text=t("wa_senders_col_display"))
        self.tree.heading("sender", text=t("wa_senders_col_sender"))
        self.tree.heading("registration", text=t("wa_senders_col_registration"))
        self.tree.heading("quality", text=t("wa_senders_col_quality"))
        self.tree.heading("status", text=t("wa_senders_col_status"))
        self.tree.heading("limit", text=t("wa_senders_col_limit"))
        self.tree.column("display", width=220, anchor="w")
        self.tree.column("sender", width=170, anchor="w")
        self.tree.column("registration", width=160, anchor="w")
        self.tree.column("quality", width=110, anchor="w")
        self.tree.column("status", width=140, anchor="w")
        self.tree.column("limit", width=160, anchor="w")
        scl = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=(0, 14))
        scl.pack(side="right", fill="y", padx=(0, 14), pady=(0, 14))

        self._reload()

    # ---------- data load ----------

    def _reload(self) -> None:
        self._refresh_btn.configure(state="disabled")
        self._status.configure(text=t("dash_loading"), foreground=META_FG)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        threading.Thread(target=self._reload_worker, daemon=True).start()

    def _reload_worker(self) -> None:
        try:
            senders = refresh_infobip_senders(self._company.key)
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001 — UI thread mustn't crash
            senders, err = [], f"{type(exc).__name__}: {exc}"
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render(senders, err))

    def _render(self, senders: list[dict], err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._refresh_btn.configure(state="normal")
        if err:
            self._status.configure(
                text=f"{t('wa_senders_err')}: {err}", foreground=ERR_FG,
            )
            return
        if not senders:
            self._status.configure(
                text=t("wa_senders_none"), foreground=META_FG,
            )
            return

        # Tag styling — Tk's Treeview only supports ONE tag's foreground
        # per row, so we pick the most-severe colour and apply it
        # row-wide. Status takes precedence (BANNED is the loudest
        # signal), then quality, then limit.
        configured_tags: set[str] = set()
        for s in senders:
            quality = str(s.get("qualityRating") or "")
            status = str(s.get("connectionStatus") or "")
            limit = str(s.get("limit") or "")
            registration = str(s.get("registrationStatus") or "")

            row_fg = _status_fg(status)
            if row_fg == OK_FG:
                # Promote a not-OK quality / limit colour onto an
                # otherwise-green row so the operator notices early.
                row_fg = (
                    _QUALITY_FG.get(quality, TEXT_FG)
                    if quality not in ("HIGH", "")
                    else _LIMIT_FG.get(limit, TEXT_FG)
                )
            tag = f"fg_{row_fg.lstrip('#')}"
            if tag not in configured_tags:
                self.tree.tag_configure(tag, foreground=row_fg)
                configured_tags.add(tag)

            self.tree.insert(
                "",
                "end",
                values=(
                    str(s.get("displayName") or "—"),
                    format_phone(str(s.get("sender") or "")),
                    registration or "—",
                    humanize_quality(quality),
                    humanize_status(status),
                    humanize_limit(limit),
                ),
                tags=(tag,),
            )
        self._status.configure(
            text=t("wa_senders_loaded").format(n=len(senders)),
            foreground=TEXT_FG,
        )
