"""Per-company Voice bot configuration panel (ElevenLabs Conversational AI).

Сейчас единственная вкладка — Prompts: редактор system prompt + first
message с возможностью Pull/Push в ElevenLabs по agent_id. Анналог
`WaBotPromptsPanel`, только без functions-tree и builder — у 11labs
агента это всё хранится на их стороне, нас интересует только промт.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from ..data import Company
from ..elevenlabs import (
    ElevenLabsError,
    extract_prompt,
    get_agent,
    get_elevenlabs_key,
    list_agents,
    set_elevenlabs_key,
    update_agent_prompt,
)
from ..i18n import t
from ..voice_bot_config import SIP_DYNAMIC_VARS, load_config, save_config
from .colors import ERR_FG, META_FG, OK_FG, TBD_FG, TEXT_FG


def _expected_agent_prefix(company_key: str) -> str:
    """Конвенция именования голосовых агентов в ElevenLabs: company key без
    trailing ``_``, плюс ``1`` если последний символ не цифра. Примеры:

      * ``CO_``  → ``CO1``
      * ``CO2_`` → ``CO2``
      * ``PE_``  → ``PE1``
      * ``AR_``  → ``AR1``

    Используется как префикс фильтра агентов в picker'е (агент должен
    называться ``<prefix>_<что-то>``).
    """
    base = (company_key or "").rstrip("_")
    if not base:
        return ""
    return base if base[-1].isdigit() else base + "1"


class VoiceBotOverviewPanel(ttk.Frame):
    """Voice-bot summary card grid for this company.

    Pulls recent ElevenLabs conversations for the agent registered in
    voice_bot_config (``elevenlabs_agent_id``), filters by selected
    period (today / 7d / 30d), and aggregates basic operational metrics:
    total calls, successful vs failed, duration, and ElevenLabs cost
    (credits). The cost requires a per-conversation detail fetch, so a
    parallel thread pool drives the second pass."""

    PERIODS = (
        ("voice_bot_overview_period_today", 1),
        ("voice_bot_overview_period_7d", 7),
        ("voice_bot_overview_period_30d", 30),
    )

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)
        self._agent_id: str = str(self._cfg.get("elevenlabs_agent_id") or "").strip()

        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        if not self._agent_id:
            ttk.Label(
                self,
                text=t("voice_bot_conv_no_agent"),
                foreground=TBD_FG, wraplength=900, justify="left",
            ).pack(anchor="w", padx=14, pady=12)
            return

        # ---- Toolbar: period selector + refresh + status ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(
            toolbar,
            text=t("voice_bot_overview_period_label") + ":",
            foreground=META_FG,
        ).pack(side="left")
        self._period_var = tk.StringVar(value=t(self.PERIODS[0][0]))
        period_box = ttk.Combobox(
            toolbar,
            textvariable=self._period_var,
            values=[t(k) for k, _ in self.PERIODS],
            state="readonly",
            width=16,
        )
        period_box.pack(side="left", padx=(6, 12))
        period_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
        self._refresh_btn = ttk.Button(
            toolbar,
            text=t("voice_bot_conv_refresh"),
            command=self._refresh,
            style="Accent.TButton",
        )
        self._refresh_btn.pack(side="left")
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        # ---- Cards grid ----
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=12, pady=(0, 12))
        self._cards: dict[str, ttk.Label] = {}
        defs = [
            ("total", t("voice_bot_overview_card_total"), 0, 0),
            ("successful", t("voice_bot_overview_card_successful"), 0, 1),
            ("failed", t("voice_bot_overview_card_failed"), 0, 2),
            ("duration_total", t("voice_bot_overview_card_duration_total"), 1, 0),
            ("duration_avg", t("voice_bot_overview_card_duration_avg"), 1, 1),
            ("duration_max", t("voice_bot_overview_card_duration_max"), 1, 2),
            ("cost_total", t("voice_bot_overview_card_cost_total"), 2, 0),
            ("cost_avg", t("voice_bot_overview_card_cost_avg"), 2, 1),
            ("success_rate", t("voice_bot_overview_card_success_rate"), 2, 2),
        ]
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform="card")
        for key, label, row, col in defs:
            box = ttk.LabelFrame(cards, text=label, padding=10)
            box.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            big = ttk.Label(
                box, text="—",
                font=("Segoe UI", 18, "bold"),
                foreground=TEXT_FG,
            )
            big.pack(anchor="w")
            self._cards[key] = big

        # Auto-load on open
        self.after(50, self._refresh)

    # ------------------------------------------------------------------
    # Refresh / aggregation
    # ------------------------------------------------------------------

    def _period_days(self) -> int:
        current = self._period_var.get()
        for key, days in self.PERIODS:
            if t(key) == current:
                return days
        return 7

    def _refresh(self) -> None:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        days = self._period_days()
        self._refresh_btn.configure(state="disabled")
        self._status.configure(
            text=t("voice_bot_overview_loading"), foreground=META_FG,
        )
        threading.Thread(
            target=self._refresh_worker, args=(days,), daemon=True,
        ).start()

    def _refresh_worker(self, days: int) -> None:
        import time as _time
        from concurrent.futures import ThreadPoolExecutor
        try:
            from ..elevenlabs import list_conversations, get_conversation
            api_key = get_elevenlabs_key(self._company.key)
            cutoff = int(_time.time()) - days * 86400
            convs: list[dict] = []
            cursor = ""
            for _ in range(20):  # hard pagination cap
                r = list_conversations(
                    agent_id=self._agent_id, page_size=100,
                    cursor=cursor, api_key=api_key,
                )
                page = r.get("conversations") or []
                convs.extend(page)
                if not r.get("has_more"):
                    break
                page_min = min(
                    (c.get("start_time_unix_secs") or 0) for c in page
                ) if page else 0
                if page_min and page_min < cutoff:
                    break
                cursor = r.get("next_cursor") or ""
                if not cursor:
                    break
            in_period = [
                c for c in convs
                if (c.get("start_time_unix_secs") or 0) >= cutoff
            ]
            # Sequential progress callback to status during detail fetch
            cost_total = 0
            details_done = 0
            details_total = len(in_period)
            if not self.winfo_exists():
                return
            self.after(
                0,
                lambda: self._status.configure(
                    text=t("voice_bot_overview_loading_details").format(
                        done=0, total=details_total,
                    ),
                    foreground=META_FG,
                ),
            )

            def fetch_cost(conv: dict) -> int:
                try:
                    det = get_conversation(
                        conv["conversation_id"], api_key=api_key,
                    )
                    return int(((det.get("metadata") or {}).get("cost") or 0))
                except Exception:  # noqa: BLE001
                    return 0

            with ThreadPoolExecutor(max_workers=8) as ex:
                costs = []
                for i, cost in enumerate(ex.map(fetch_cost, in_period)):
                    costs.append(cost)
                    if self.winfo_exists() and (i + 1) % 5 == 0:
                        done = i + 1
                        self.after(
                            0,
                            lambda d=done, t_=details_total:
                                self._status.configure(
                                    text=t("voice_bot_overview_loading_details").format(
                                        done=d, total=t_,
                                    ),
                                    foreground=META_FG,
                                ),
                        )
                cost_total = sum(costs)
            stats = _aggregate_conversations(in_period, cost_total)
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001
            stats, err = None, str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_stats(stats, err))

    def _render_stats(
        self, stats: Optional[dict], err: Optional[str],
    ) -> None:
        self._refresh_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            return
        if not stats:
            self._status.configure(
                text=t("voice_bot_overview_no_data"),
                foreground=TBD_FG,
            )
            for lbl in self._cards.values():
                lbl.configure(text="—")
            return

        total = stats["total"]
        successful = stats["successful"]
        failed = stats["failed"]
        rate = (
            f"{(successful * 100 / total):.0f}%" if total else "—"
        )
        self._cards["total"].configure(text=str(total))
        self._cards["successful"].configure(text=str(successful))
        self._cards["failed"].configure(text=str(failed))
        self._cards["duration_total"].configure(
            text=_fmt_hms(stats["duration_total"]),
        )
        self._cards["duration_avg"].configure(
            text=_fmt_hms(stats["duration_avg"]),
        )
        self._cards["duration_max"].configure(
            text=_fmt_hms(stats["duration_max"]),
        )
        self._cards["cost_total"].configure(
            text=f"{stats['cost_total']} cr",
        )
        self._cards["cost_avg"].configure(
            text=(
                f"{stats['cost_avg']:.1f} cr" if total else "—"
            ),
        )
        self._cards["success_rate"].configure(text=rate)
        self._status.configure(
            text=t("voice_bot_overview_loaded").format(
                n=total, days=self._period_days(),
            ),
            foreground=OK_FG,
        )


def _aggregate_conversations(convs: list[dict], cost_total: int) -> dict:
    total = len(convs)
    successful = sum(1 for c in convs if c.get("call_successful") == "success")
    failed = sum(1 for c in convs if c.get("call_successful") == "failure")
    durations = [int(c.get("call_duration_secs") or 0) for c in convs]
    dur_total = sum(durations)
    dur_avg = (dur_total / total) if total else 0
    dur_max = max(durations) if durations else 0
    cost_avg = (cost_total / total) if total else 0.0
    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "duration_total": dur_total,
        "duration_avg": int(dur_avg),
        "duration_max": dur_max,
        "cost_total": cost_total,
        "cost_avg": cost_avg,
    }


def _fmt_hms(secs: int) -> str:
    s = int(secs or 0)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m:02d}m"


def _normalize_sip_header_to_dyn_var(name: str) -> str:
    """Convert a Webitel SIP-header (``sip_h_X-<a>-<b>-<c>``) to the
    ElevenLabs dynamic-variable form (``sip_<a>_<b>_<c>``). Mirrors how
    ElevenLabs auto-normalizes incoming custom SIP headers."""
    n = name or ""
    if n.lower().startswith("sip_h_x-"):
        n = n[len("sip_h_X-"):]
    return "sip_" + n.lower().replace("-", "_")


def _extract_bridge_endpoints(node: dict) -> list[dict]:
    sch = node.get("schema") or {}
    eps = sch.get("endpoints") or []
    return [e for e in eps if isinstance(e, dict)]


def _extract_httprequest_exports(node: dict) -> list[dict]:
    sch = node.get("schema") or {}
    out = sch.get("exportVariables") or sch.get("exports") or []
    return [v for v in out if isinstance(v, dict)]


def _extract_set_vars(node: dict) -> list[dict]:
    sch = node.get("schema") or {}
    out = sch.get("set") or []
    return [v for v in out if isinstance(v, dict)]


class VoiceBotMappingPanel(ttk.Frame):
    """Viewer of the Webitel voice routing schema for this company.

    Pulls the schema from Webitel (``GET /routing/schema/<id>``) using
    the company's host + token, then renders the structurally important
    bits: bridge endpoints (gateway, dialString, SIP headers →
    normalized ElevenLabs dynamic_variables), httpRequest nodes (CRM
    lookup URL + exported variables), and ``set`` test-data nodes.
    Read-only; edits to the schema happen in Webitel UI.
    """

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)
        self._schema: Optional[dict] = None

        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        schema_id = self._cfg.get("webitel_schema_id") or 0
        schema_name = self._cfg.get("webitel_schema_name") or ""
        gateway_id = self._cfg.get("webitel_gateway_id") or ""
        gateway_name = self._cfg.get("webitel_gateway_name") or ""

        meta = ttk.LabelFrame(
            self, text=t("voice_bot_mapping_section_schema"), padding=10,
        )
        meta.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(
            meta, foreground=META_FG,
            text=t("voice_bot_mapping_schema_label") + ":",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(
            meta, text=f"{schema_name or '—'}  (id={schema_id or '—'})",
            foreground=TEXT_FG,
        ).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(
            meta, foreground=META_FG,
            text=t("voice_bot_mapping_gateway_label") + ":",
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(
            meta, text=f"{gateway_name or '—'}  (id={gateway_id or '—'})",
            foreground=TEXT_FG,
        ).grid(row=1, column=1, sticky="w", pady=2)
        if schema_id:
            ttk.Button(
                meta, text=t("voice_bot_mapping_open_in_webitel"),
                command=self._open_in_webitel,
            ).grid(row=0, column=2, rowspan=2, padx=(20, 0), sticky="w")
        self._pull_btn = ttk.Button(
            meta, text=t("voice_bot_mapping_pull"),
            command=self._pull, style="Accent.TButton",
        )
        self._pull_btn.grid(row=0, column=3, rowspan=2, padx=(6, 0), sticky="w")
        self._status = ttk.Label(meta, text="", foreground=META_FG)
        self._status.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        if not schema_id:
            ttk.Label(
                self, text=t("voice_bot_mapping_no_schema_id"),
                foreground=TBD_FG, wraplength=900, justify="left",
            ).pack(anchor="w", padx=14, pady=12)
            return

        # ---- Scrollable body for rendered sections ----
        body_wrap = ttk.Frame(self)
        body_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        canvas = tk.Canvas(body_wrap, highlightthickness=0)
        vscroll = ttk.Scrollbar(
            body_wrap, orient="vertical", command=canvas.yview,
        )
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        self._body = ttk.Frame(canvas)
        self._body_window = canvas.create_window(
            (0, 0), window=self._body, anchor="nw",
        )
        self._body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._body_window, width=e.width),
        )

        self.after(50, self._pull)

    # ------------------------------------------------------------------
    # Webitel pull
    # ------------------------------------------------------------------

    def _open_in_webitel(self) -> None:
        import webbrowser
        host = (self._company.webitel_host or "").rstrip("/")
        sid = self._cfg.get("webitel_schema_id") or 0
        if not host or not sid:
            return
        webbrowser.open(f"{host}/flow/{sid}/voice")

    def _pull(self) -> None:
        self._pull_btn.configure(state="disabled")
        self._status.configure(
            text=t("voice_bot_mapping_loading"), foreground=META_FG,
        )
        threading.Thread(target=self._pull_worker, daemon=True).start()

    def _pull_worker(self) -> None:
        try:
            from ..webitel import WebitelClient
            sid = int(self._cfg.get("webitel_schema_id") or 0)
            client = WebitelClient(
                self._company.webitel_host,
                self._company.webitel_access_token,
            )
            schema = client.get_schema(sid)
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001 — webitel client can raise many things
            schema, err = None, str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render(schema, err))

    def _render(self, schema: Optional[dict], err: Optional[str]) -> None:
        self._pull_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            return
        self._schema = schema or {}
        for child in self._body.winfo_children():
            child.destroy()
        nodes = (self._schema.get("payload") or {}).get("nodes") or []
        nodes = [n for n in nodes if isinstance(n, dict)]
        bridges = [n for n in nodes if n.get("label") == "bridge"]
        https = [n for n in nodes if n.get("label") == "httpRequest"]
        sets = [n for n in nodes if n.get("label") == "set"]
        others = [
            n for n in nodes
            if n.get("label") not in ("bridge", "httpRequest", "set")
        ]

        for n in bridges:
            self._render_bridge(n)
        for n in https:
            self._render_httprequest(n)
        for n in sets:
            self._render_set(n)
        if others:
            others_box = ttk.LabelFrame(
                self._body,
                text=t("voice_bot_mapping_section_other_nodes"),
                padding=8,
            )
            others_box.pack(fill="x", pady=(0, 8))
            for n in others:
                ttk.Label(
                    others_box,
                    text=f"• {n.get('label','?')}  id={n.get('id','')}",
                    foreground=TEXT_FG,
                ).pack(anchor="w")

        self._status.configure(
            text=t("voice_bot_mapping_loaded").format(
                bridges=len(bridges), https=len(https),
                sets=len(sets), others=len(others),
            ),
            foreground=OK_FG,
        )

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _render_bridge(self, node: dict) -> None:
        nid = node.get("id", "")
        eps = _extract_bridge_endpoints(node)
        title = t("voice_bot_mapping_bridge_title").format(id=nid)
        box = ttk.LabelFrame(self._body, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        for i, ep in enumerate(eps):
            gw = ep.get("gateway") or {}
            gw_name = gw.get("name") or "—"
            gw_id = gw.get("id") or "—"
            dial = ep.get("dialString") or "—"
            ttk.Label(
                box,
                text=t("voice_bot_mapping_endpoint_header").format(
                    n=i + 1, gw=gw_name, gw_id=gw_id, dial=dial,
                ),
                foreground=TEXT_FG, font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(0, 4))
            params = [p for p in (ep.get("parameters") or []) if isinstance(p, dict)]
            sip_params = [p for p in params if (p.get("key") or "").lower().startswith("sip_h_x-")]
            if not sip_params:
                ttk.Label(
                    box, text=t("voice_bot_mapping_no_sip_headers"),
                    foreground=TBD_FG,
                ).pack(anchor="w", pady=(0, 2))
                continue
            tv = ttk.Treeview(
                box,
                columns=("sip", "norm", "src"),
                show="headings",
                height=min(15, max(3, len(sip_params))),
            )
            tv.heading("sip", text=t("voice_bot_mapping_col_sip"))
            tv.heading("norm", text=t("voice_bot_mapping_col_normalized"))
            tv.heading("src", text=t("voice_bot_mapping_col_source"))
            tv.column("sip", width=240, anchor="w")
            tv.column("norm", width=220, anchor="w")
            tv.column("src", width=320, anchor="w")
            for p in sip_params:
                k = p.get("key") or ""
                v = p.get("value")
                if v is None:
                    v = ""
                tv.insert(
                    "", "end",
                    values=(k, _normalize_sip_header_to_dyn_var(k), str(v)),
                )
            tv.pack(fill="x", pady=(0, 6))

    def _render_httprequest(self, node: dict) -> None:
        nid = node.get("id", "")
        sch = node.get("schema") or {}
        url = sch.get("url") or sch.get("requestUrl") or "—"
        method = sch.get("method") or sch.get("requestMethod") or "POST"
        body_data = sch.get("data") or ""
        exports = _extract_httprequest_exports(node)
        title = t("voice_bot_mapping_httprequest_title").format(id=nid)
        box = ttk.LabelFrame(self._body, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            box, text=f"{method}  {url}",
            foreground=TEXT_FG, font=("Consolas", 9),
            wraplength=900, justify="left",
        ).pack(anchor="w", pady=(0, 4))
        if body_data and body_data != "{}":
            ttk.Label(
                box, text=f"body: {body_data}",
                foreground=META_FG, font=("Consolas", 9),
                wraplength=900, justify="left",
            ).pack(anchor="w", pady=(0, 4))
        if not exports:
            ttk.Label(
                box, text=t("voice_bot_mapping_no_exports"),
                foreground=TBD_FG,
            ).pack(anchor="w")
            return
        tv = ttk.Treeview(
            box,
            columns=("var", "path"),
            show="headings",
            height=min(20, max(3, len(exports))),
        )
        tv.heading("var", text=t("voice_bot_mapping_col_channel_var"))
        tv.heading("path", text=t("voice_bot_mapping_col_crm_path"))
        tv.column("var", width=240, anchor="w")
        tv.column("path", width=540, anchor="w")
        for e in exports:
            tv.insert(
                "", "end",
                values=(e.get("key") or "", e.get("value") or ""),
            )
        tv.pack(fill="x", pady=(2, 0))

    def _render_set(self, node: dict) -> None:
        nid = node.get("id", "")
        rows = _extract_set_vars(node)
        title = t("voice_bot_mapping_set_title").format(id=nid, n=len(rows))
        box = ttk.LabelFrame(self._body, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        if not rows:
            ttk.Label(
                box, text=t("voice_bot_mapping_set_empty"),
                foreground=TBD_FG,
            ).pack(anchor="w")
            return
        tv = ttk.Treeview(
            box,
            columns=("var", "val"),
            show="headings",
            height=min(20, max(3, len(rows))),
        )
        tv.heading("var", text=t("voice_bot_mapping_col_var"))
        tv.heading("val", text=t("voice_bot_mapping_col_value"))
        tv.column("var", width=220, anchor="w")
        tv.column("val", width=540, anchor="w")
        for r in rows:
            tv.insert(
                "", "end",
                values=(r.get("key") or "", str(r.get("value", ""))),
            )
        tv.pack(fill="x")


class VoiceBotPromptsPanel(ttk.Frame):
    """Prompts editor for the company's ElevenLabs voice agent.

    Layout (top → bottom):
      * Header — компания, agent_id, кнопка задать API key.
      * Тулбар Pull / Push / Save / List agents — между ElevenLabs и
        локальным конфигом.
      * Основной промт — большое текстовое поле (system prompt).
      * First message — короткое текстовое поле.
      * Подсказка по dynamic_variables (SIP-headers из bridge-ноды).
    """

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)

        # ---- Заголовок + agent_id + API key dialog ----
        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        meta = ttk.LabelFrame(self, text=t("voice_bot_section_meta"), padding=10)
        meta.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(meta, text=t("voice_bot_agent_id") + ":", foreground=META_FG).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=2,
        )
        self._agent_id_var = tk.StringVar(
            value=str(self._cfg.get("elevenlabs_agent_id") or ""),
        )
        ttk.Entry(
            meta, textvariable=self._agent_id_var, width=40,
        ).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Button(
            meta, text=t("voice_bot_list_agents"), command=self._pick_agent_dialog,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0), pady=2)
        ttk.Button(
            meta, text=t("voice_bot_set_key"), command=self._set_api_key,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0), pady=2)

        sname = self._cfg.get("webitel_schema_name") or "—"
        sid = self._cfg.get("webitel_schema_id")
        gname = self._cfg.get("webitel_gateway_name") or "—"
        ttk.Label(
            meta,
            text=t("voice_bot_webitel_schema") + ":", foreground=META_FG,
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(
            meta, text=f"{sname} (id={sid})  →  gateway {gname}",
            foreground=TEXT_FG,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=2)

        # ---- Тулбар Pull / Push / Save ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 8))
        self._pull_btn = ttk.Button(
            toolbar, text=t("voice_bot_pull"), command=self._pull_from_elevenlabs,
        )
        self._pull_btn.pack(side="left")
        self._push_btn = ttk.Button(
            toolbar, text=t("voice_bot_push"), command=self._push_to_elevenlabs,
            style="Accent.TButton",
        )
        self._push_btn.pack(side="left", padx=(6, 0))
        ttk.Button(
            toolbar, text=t("btn_save"), command=self._save_local,
        ).pack(side="left", padx=(6, 0))
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        # ---- Основной промт ----
        ttk.Label(
            self, text=t("voice_bot_prompt_main"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(8, 2))
        self._main_prompt = tk.Text(self, wrap="word")
        self._main_prompt.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._main_prompt.insert("1.0", str(self._cfg.get("main_prompt") or ""))

        # ---- First message ----
        ttk.Label(
            self, text=t("voice_bot_first_message"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        self._first_message = tk.Text(self, height=3, wrap="word")
        self._first_message.pack(fill="x", padx=12, pady=(0, 8))
        self._first_message.insert("1.0", str(self._cfg.get("first_message") or ""))

        # ---- SIP dynamic_variables (только список placeholder'ов, per-company) ----
        vars_box = ttk.LabelFrame(
            self, text=t("voice_bot_section_dynamic_vars"), padding=8,
        )
        vars_box.pack(fill="x", padx=12, pady=(0, 12))
        dyn_vars = list(self._cfg.get("dynamic_variables") or SIP_DYNAMIC_VARS)
        ttk.Label(
            vars_box,
            text="  ".join(f"{{{{ {v} }}}}" for v in dyn_vars),
            foreground=TEXT_FG, font=("Consolas", 9),
            wraplength=900, justify="left",
        ).pack(anchor="w")

    # ------------------------------------------------------------------
    # Local persistence
    # ------------------------------------------------------------------

    def _sync_into_cfg(self) -> None:
        self._cfg["main_prompt"] = self._main_prompt.get("1.0", "end").rstrip()
        self._cfg["first_message"] = self._first_message.get("1.0", "end").rstrip()
        self._cfg["elevenlabs_agent_id"] = self._agent_id_var.get().strip()

    def _save_local(self) -> None:
        self._sync_into_cfg()
        save_config(self._company.key, self._cfg)
        self._status.configure(text=t("voice_bot_saved_local"), foreground=OK_FG)

    # ------------------------------------------------------------------
    # ElevenLabs API actions
    # ------------------------------------------------------------------

    def _set_api_key(self) -> None:
        current = get_elevenlabs_key()
        hint = (
            f"{t('voice_bot_key_dialog_help')}\n\n"
            f"{t('voice_bot_key_current')}: "
            + (current[:8] + "…" + current[-4:] if current else "—")
        )
        new = simpledialog.askstring(
            t("voice_bot_key_dialog_title"), hint,
            parent=self.winfo_toplevel(),
            initialvalue=current,
            show="*",
        )
        if new is None:
            return
        set_elevenlabs_key(new.strip())
        self._status.configure(
            text=t("voice_bot_key_saved") if new.strip() else t("voice_bot_key_cleared"),
            foreground=OK_FG,
        )

    def _pick_agent_dialog(self) -> None:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        self._status.configure(
            text=t("voice_bot_listing_agents"), foreground=META_FG,
        )
        threading.Thread(target=self._list_agents_worker, daemon=True).start()

    def _list_agents_worker(self) -> None:
        try:
            agents = list_agents(
                api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            agents, err = [], str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_agent_picker(agents, err))

    def _render_agent_picker(
        self, agents: list[dict], err: Optional[str],
    ) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_section_meta"), err,
                parent=self.winfo_toplevel(),
            )
            return
        if not agents:
            self._status.configure(
                text=t("voice_bot_no_agents"), foreground=META_FG,
            )
            messagebox.showinfo(
                t("voice_bot_section_meta"),
                t("voice_bot_no_agents_long"),
                parent=self.winfo_toplevel(),
            )
            return

        prefix = _expected_agent_prefix(self._company.key)
        total = len(agents)

        def _matches(a: dict) -> bool:
            if not prefix:
                return True
            n = (a.get("name") or "").strip()
            return n == prefix or n.startswith(prefix + "_")

        filtered = [a for a in agents if _matches(a)] if prefix else list(agents)
        show_all_fallback = bool(prefix) and not filtered
        visible_agents = agents if show_all_fallback else filtered

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(t("voice_bot_list_agents"))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        if prefix:
            if show_all_fallback:
                label_text = t("voice_bot_agent_filter_none").format(
                    prefix=prefix, total=total,
                )
                label_color = TBD_FG
            else:
                label_text = t("voice_bot_agent_filter_match").format(
                    prefix=prefix, n=len(filtered), total=total,
                )
                label_color = META_FG
            ttk.Label(
                dialog, text=label_text, foreground=label_color,
                wraplength=600, justify="left",
            ).pack(anchor="w", padx=10, pady=(10, 4))

        tree = ttk.Treeview(
            dialog, columns=("name", "agent_id"),
            show="headings", height=min(15, max(5, len(visible_agents))),
        )
        tree.heading("name", text=t("voice_bot_agent_name"))
        tree.heading("agent_id", text=t("voice_bot_agent_id"))
        tree.column("name", width=320, anchor="w")
        tree.column("agent_id", width=320, anchor="w")
        for a in visible_agents:
            tree.insert("", "end", values=(a.get("name") or "—", a.get("agent_id") or ""))
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def use_selected() -> None:
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            self._agent_id_var.set(vals[1])
            dialog.destroy()
            self._status.configure(
                text=t("voice_bot_agent_selected"), foreground=OK_FG,
            )

        btns = ttk.Frame(dialog)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text=t("btn_cancel"), command=dialog.destroy).pack(side="right")
        ttk.Button(
            btns, text=t("voice_bot_use_agent"), command=use_selected,
            style="Accent.TButton",
        ).pack(side="right", padx=(0, 6))
        tree.bind("<Double-1>", lambda _e: use_selected())

    def _pull_from_elevenlabs(self) -> None:
        if not self._require_key_and_id():
            return
        self._status.configure(text=t("voice_bot_pulling"), foreground=META_FG)
        agent_id = self._agent_id_var.get().strip()
        threading.Thread(
            target=self._pull_worker, args=(agent_id,), daemon=True,
        ).start()

    def _pull_worker(self, agent_id: str) -> None:
        try:
            agent = get_agent(
                agent_id, api_key=get_elevenlabs_key(self._company.key),
            )
            prompt, first_msg = extract_prompt(agent)
            err: Optional[str] = None
        except ElevenLabsError as exc:
            agent, prompt, first_msg, err = {}, "", "", str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._apply_pulled(agent, prompt, first_msg, err))

    def _apply_pulled(
        self, agent: dict, prompt: str, first_msg: str, err: Optional[str],
    ) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_pull"), err, parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            t("voice_bot_pull"),
            t("voice_bot_pull_confirm").format(
                name=agent.get("name") or "—",
                prompt_len=len(prompt),
                first_msg_len=len(first_msg),
            ),
            parent=self.winfo_toplevel(),
        ):
            self._status.configure(text=t("voice_bot_pull_cancelled"), foreground=META_FG)
            return
        self._main_prompt.delete("1.0", "end")
        self._main_prompt.insert("1.0", prompt)
        self._first_message.delete("1.0", "end")
        self._first_message.insert("1.0", first_msg)
        self._status.configure(text=t("voice_bot_pulled"), foreground=OK_FG)

    def _push_to_elevenlabs(self) -> None:
        if not self._require_key_and_id():
            return
        self._sync_into_cfg()
        prompt = self._cfg.get("main_prompt") or ""
        first_msg = self._cfg.get("first_message") or ""
        if not prompt and not first_msg:
            messagebox.showwarning(
                t("voice_bot_push"),
                t("voice_bot_push_empty"),
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            t("voice_bot_push"),
            t("voice_bot_push_confirm").format(
                agent_id=self._cfg.get("elevenlabs_agent_id") or "",
                prompt_len=len(prompt),
                first_msg_len=len(first_msg),
            ),
            parent=self.winfo_toplevel(),
        ):
            return
        self._status.configure(text=t("voice_bot_pushing"), foreground=META_FG)
        agent_id = self._cfg["elevenlabs_agent_id"]
        threading.Thread(
            target=self._push_worker,
            args=(agent_id, prompt, first_msg),
            daemon=True,
        ).start()

    def _push_worker(
        self, agent_id: str, prompt: str, first_msg: str,
    ) -> None:
        try:
            update_agent_prompt(
                agent_id,
                system_prompt=prompt,
                first_message=first_msg,
                api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            err = str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._apply_pushed(err))

    def _apply_pushed(self, err: Optional[str]) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_push"), err, parent=self.winfo_toplevel(),
            )
            return
        # Локальный save после успешного push — фиксируем как «деплой».
        save_config(self._company.key, self._cfg)
        self._status.configure(text=t("voice_bot_pushed"), foreground=OK_FG)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _require_key_and_id(self) -> bool:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return False
        if not self._agent_id_var.get().strip():
            messagebox.showwarning(
                t("voice_bot_agent_id"),
                t("voice_bot_agent_id_missing"),
                parent=self.winfo_toplevel(),
            )
            return False
        return True
