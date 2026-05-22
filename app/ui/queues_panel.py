import re
import threading
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk
from typing import Optional

from ..alert_format import render_alert_html
from ..alerts import (
    TelegramError,
    ensure_company_topic,
    load_alerts_config,
    send_telegram_message,
)
from ..data import Company
from ..i18n import t
from ..sectors import DEFAULT_SECTOR, SECTOR_CC, SECTOR_COLLECTION, SECTORS
from ..webitel import QUEUE_TYPE_NAMES, Queue, WebitelClient, WebitelError

AGENT_QUEUE_TYPES = (0, 1, 4, 5, 10)


# CC sector queue checklist. Each entry: (category, channel, expected name).
# Categories: Unsigned, Unfinished, Auto-creation, Phone confirmation,
# Inbound (hotline), Telesales, Other. Channels: Predictive (Agent),
# VoiceBot, Inbound. Names are taken verbatim from the operator's catalog
# — matching ignores case and treats Cyrillic СС / Latin CC as equal,
# so naming drift in Webitel doesn't break the check.
CC_CHECKLIST: tuple[tuple[str, str, str], ...] = (
    # Unsigned (CC_Uns)
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned Agents_40%_repeat Сегодня"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned Агенты _100%_new сегодня"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned Агент _100%_new вчера"),
    ("Unsigned",         "Predictive (Agent)", "СС_Unsigned_Today_Sun и HollyD_Agent_100%"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned_Agents_Night"),
    ("Unsigned",         "Predictive (Agent)", "CC_Unsigned appliactions_call_backs"),
    ("Unsigned",         "VoiceBot",           "CC_Unsigned 60%_VoiceBot_repeat сегодня"),
    ("Unsigned",         "VoiceBot",           "CC_Unsigned 60%_VoiceBot_repeat вчера"),
    ("Unsigned",         "VoiceBot",           "CC_unsigned_IVR_small"),
    ("Unsigned",         "VoiceBot",           "CC_Unsigned_telesales_VoiceBot"),
    ("Unsigned",         "Inbound",            "CC_Inbound_Unsigned"),
    # Unfinished (CC_Unf)
    ("Unfinished",       "Predictive (Agent)", "CC_Unfinished_Agents_Night"),
    ("Unfinished",       "Predictive (Agent)", "CC_Unsigned Agents_40%_repeat вчера"),
    ("Unfinished",       "Predictive (Agent)", "СС_Unfinished_Today_Agent_50%"),
    ("Unfinished",       "Predictive (Agent)", "СС_Unfinished_Today_Sun&HollyD_Agent_100%"),
    ("Unfinished",       "Predictive (Agent)", "СС_Unfinished_Yesterday_Agent_20%"),
    ("Unfinished",       "Predictive (Agent)", "CC_Unfinished_after_VB"),
    ("Unfinished",       "Predictive (Agent)", "CC_ Today_Documents_agents>1/2 часа"),
    ("Unfinished",       "VoiceBot",           "CC_Documents_VoiceBot<1/2 часа"),
    ("Unfinished",       "VoiceBot",           "СС_Unfinished_Today_Bot_50%"),
    ("Unfinished",       "VoiceBot",           "СС_Unfinished_Yesterday_Bot_ 80%"),
    ("Unfinished",       "VoiceBot",           "CC_Unfinished_ 10-15days_100%_Voicebot"),
    ("Unfinished",       "Inbound",            "CC_Verification_calls_after_BOT"),
    ("Unfinished",       "Inbound",            "CC_Unfinished_Inb_VB"),
    # Auto-creation
    ("Auto-creation",    "Predictive (Agent)", "CC_Autocreation_Unsigned_Reapeat_50%_agent"),
    ("Auto-creation",    "VoiceBot",           "CC_Autocreation_Unsigned_Reapeat_50%Bot"),
    # Phone confirmation
    ("Phone confirmation", "VoiceBot",         "CC_Phone_confirmation"),
    # Inbound (hotline)
    ("Inbound (hotline)", "Inbound",           "CC_HotLine"),
    # Telesales
    ("Telesales",        "Inbound",            "CC Входящий Сон и Продано"),
    # Other
    ("Other",            "Predictive (Agent)", "CC_Callbacks"),
    ("Other",            "Predictive (Agent)", "СС_Duplicates"),
)


def _normalize_queue_name(name: str) -> str:
    """Case-insensitive + Cyrillic-СС-to-Latin-CC + whitespace-squash
    comparison helper. Lets the CC checklist match queues even with
    typos / locale drift in their Webitel name."""
    n = (name or "").strip().lower()
    # СС → cc after lower() → replace Cyrillic с (U+0441) with Latin c.
    n = n.replace("с", "c")
    n = " ".join(n.split())
    return n

COLS = ("name", "id", "calendar", "schema", "type", "enabled", "team", "agents")


def _fmt_lookup(lk) -> str:
    return f"{lk.id} — {lk.name}" if lk else "—"


def _schema_summary(q: Queue) -> str:
    schemas = [
        ("main", q.schema),
        ("do", q.do_schema),
        ("after", q.after_schema),
        ("form", q.form_schema),
    ]
    set_ones = [(label, s) for label, s in schemas if s]
    if not set_ones:
        return "—"
    primary_label, primary = set_ones[0]
    text = primary.name
    if len(set_ones) > 1:
        text += f"  (+{len(set_ones) - 1})"
    return text


class SchemaPopup(tk.Toplevel):
    def __init__(self, master: tk.Misc, queue: Queue) -> None:
        super().__init__(master)
        self.title(f"Схемы: {queue.name} (id={queue.id})")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)

        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        rows = [
            ("Пре-схема", queue.do_schema),
            ("Схема", queue.schema),
            ("Пост-схема", queue.after_schema),
            ("Процессинг", queue.form_schema),
        ]
        for i, (label, sch) in enumerate(rows):
            ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")).grid(
                row=i, column=0, sticky="w", padx=(0, 16), pady=5
            )
            ttk.Label(body, text=_fmt_lookup(sch)).grid(
                row=i, column=1, sticky="w", pady=5
            )

        btns = ttk.Frame(self, padding=(18, 0, 18, 18))
        btns.pack(fill="x")
        ttk.Button(btns, text="Закрыть", command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        try:
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width()
            mh = master.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"+{mx + max(0, (mw - w) // 2)}+{my + max(0, (mh - h) // 3)}")
        except tk.TclError:
            pass
        self.grab_set()


class QueuesPanel(ttk.Frame):
    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        self._row_to_queue: dict[str, Queue] = {}
        self._all_queues: list[Queue] = []

        # Initial sector filter follows the parent sector (CC tab → CC,
        # Collection tab → Collection). User can still relax it via the
        # combobox.
        initial_filter = "Collection" if self._sector == SECTOR_COLLECTION else "КЦ"
        self._f_sector = tk.StringVar(value=initial_filter)
        self._f_enabled = tk.StringVar(value="Все")
        self._f_coll = tk.StringVar(value="Все")
        self._f_group = tk.StringVar(value="Все")
        self._f_sub = tk.StringVar(value="Все")

        ttk.Label(
            self,
            text=t("header_queues"),
            font=("Segoe UI", 9, "bold"),
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(14, 6))

        head = ttk.Frame(self)
        head.pack(fill="x", padx=14, pady=(0, 8))
        code = company.key.rstrip("_")
        ttk.Label(
            head,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        self._status = ttk.Label(head, text="Загрузка…", foreground="#6b7280")
        self._status.pack(side="right")
        self._reload_btn = ttk.Button(head, text="Обновить", command=self._reload)
        self._reload_btn.pack(side="right", padx=(0, 8))

        # ---- Sector-specific checklist ----
        if self._sector == SECTOR_CC:
            self._build_cc_checklist()
        else:
            self._build_collection_checklist()

    def _build_collection_checklist(self) -> None:
        # Collection checklist: enabled queues for G1/G2/G3 × Main/APTP/BPTP
        cl = ttk.LabelFrame(
            self,
            text="Чек-лист Collection (включенные · G1/G2/G3 × Main/APTP/BPTP)",
            padding=8,
        )
        cl.pack(fill="x", padx=14, pady=(0, 8))
        self._cl_groups = ("G1", "G2", "G3")
        self._cl_types = ("Main", "APTP", "BPTP", "Chat")
        self._cl_cells: dict[tuple[str, str], ttk.Label] = {}
        self._all_chat_queues: list[Queue] = []
        ttk.Label(cl, text="").grid(row=0, column=0, padx=12, pady=2)
        for j, tp in enumerate(self._cl_types, start=1):
            ttk.Label(cl, text=tp, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=j, padx=12, pady=2
            )
        for i, g in enumerate(self._cl_groups, start=1):
            ttk.Label(cl, text=g, font=("Segoe UI", 9, "bold")).grid(
                row=i, column=0, padx=12, pady=2, sticky="w"
            )
            for j, tp in enumerate(self._cl_types, start=1):
                lbl = ttk.Label(
                    cl, text="—", foreground="#9ca3af", font=("Segoe UI", 10)
                )
                lbl.grid(row=i, column=j, padx=12, pady=2)
                self._cl_cells[(g, tp)] = lbl
        self._cl_summary = ttk.Label(cl, text="", foreground="#6b7280")
        self._cl_summary.grid(
            row=len(self._cl_groups) + 1,
            column=0,
            columnspan=len(self._cl_types) + 1,
            sticky="w",
            padx=12,
            pady=(6, 0),
        )
        cl_actions = ttk.Frame(cl)
        cl_actions.grid(
            row=len(self._cl_groups) + 2,
            column=0,
            columnspan=len(self._cl_types) + 1,
            sticky="w",
            padx=12,
            pady=(4, 0),
        )
        self._cl_alert_btn = ttk.Button(
            cl_actions,
            text="Отправить алерт в Telegram",
            command=self._send_checklist_alert,
        )
        self._cl_alert_status = ttk.Label(cl_actions, text="", foreground="#6b7280")
        # buttons hidden by default; appear when coverage incomplete
        self._cl_actions = cl_actions
        self._build_filters_and_body()

    # ----- CC sector checklist -----

    def _build_cc_checklist(self) -> None:
        cl = ttk.LabelFrame(
            self,
            text="Чек-лист CC (включенные очереди по категориям)",
            padding=8,
        )
        cl.pack(fill="both", padx=14, pady=(0, 8))
        # Treeview: одна строка на ожидаемую очередь, сгруппирована по
        # категории и каналу. Колонки: статус | канал | имя.
        tv = ttk.Treeview(
            cl, columns=("status", "channel", "name"),
            show="tree headings", selectmode="browse",
            height=min(18, max(8, len(CC_CHECKLIST) // 2)),
        )
        tv.heading("#0", text="Категория")
        tv.heading("status", text="Статус")
        tv.heading("channel", text="Канал")
        tv.heading("name", text="Имя очереди")
        tv.column("#0", width=200, anchor="w", stretch=False)
        tv.column("status", width=120, anchor="w", stretch=False)
        tv.column("channel", width=180, anchor="w", stretch=False)
        tv.column("name", width=420, anchor="w")
        tv.tag_configure("ok", foreground="#16a34a")
        tv.tag_configure("miss", foreground="#dc2626")
        # build category → parent iid map
        self._cc_cat_iids: dict[str, str] = {}
        self._cc_item_keys: dict[str, tuple[str, str, str]] = {}
        cats_seen: list[str] = []
        for cat, channel, name in CC_CHECKLIST:
            if cat not in self._cc_cat_iids:
                cat_iid = tv.insert("", "end", text=cat, open=True)
                self._cc_cat_iids[cat] = cat_iid
                cats_seen.append(cat)
            row_iid = tv.insert(
                self._cc_cat_iids[cat], "end",
                text="",
                values=("—", channel, name),
                tags=("miss",),
            )
            self._cc_item_keys[row_iid] = (cat, channel, name)
        scl = ttk.Scrollbar(cl, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=scl.set)
        tv.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")
        self._cc_tree = tv

        self._cl_summary = ttk.Label(self, text="", foreground="#6b7280")
        self._cl_summary.pack(anchor="w", padx=14, pady=(0, 2))
        cl_actions = ttk.Frame(self)
        cl_actions.pack(anchor="w", padx=14, pady=(0, 8))
        self._cl_alert_btn = ttk.Button(
            cl_actions,
            text="Отправить алерт в Telegram",
            command=self._send_checklist_alert,
        )
        self._cl_alert_status = ttk.Label(cl_actions, text="", foreground="#6b7280")
        self._cl_actions = cl_actions
        self._cc_total = len(CC_CHECKLIST)
        self._cc_missing: list[tuple[str, str, str]] = []
        self._build_filters_and_body()

    def _refresh_cc_checklist(self) -> None:
        self._cc_missing = []
        # Build a normalized index of currently visible queues for matching.
        all_visible = list(self._all_queues) + list(self._all_chat_queues)
        index: dict[str, Queue] = {}
        for q in all_visible:
            if not q.enabled:
                continue
            index[_normalize_queue_name(q.name)] = q
        for row_iid, (cat, channel, name) in self._cc_item_keys.items():
            found = index.get(_normalize_queue_name(name))
            if found is not None:
                self._cc_tree.item(
                    row_iid,
                    values=(f"✓  id {found.id}", channel, name),
                    tags=("ok",),
                )
            else:
                self._cc_tree.item(
                    row_iid,
                    values=("✗  нет", channel, name),
                    tags=("miss",),
                )
                self._cc_missing.append((cat, channel, name))
        ok = self._cc_total - len(self._cc_missing)
        if not self._cc_missing:
            self._cl_summary.configure(
                text=f"Все {self._cc_total} очередей CC на месте.",
                foreground="#16a34a",
            )
            self._cl_alert_btn.pack_forget()
            self._cl_alert_status.pack_forget()
        else:
            self._cl_summary.configure(
                text=f"Покрытие CC: {ok}/{self._cc_total} — есть пробелы.",
                foreground="#dc2626",
            )
            self._cl_alert_btn.pack(side="left")
            self._cl_alert_status.pack(side="left", padx=(12, 0))
            self._cl_alert_btn.configure(state="normal")
            self._cl_alert_status.configure(text="", foreground="#6b7280")

    def _build_filters_and_body(self) -> None:
        filters = ttk.Frame(self)
        filters.pack(fill="x", padx=14, pady=(0, 8))

        def add_filter(label: str, var: tk.StringVar, values: list[str], width: int) -> None:
            ttk.Label(filters, text=label).pack(side="left")
            cb = ttk.Combobox(
                filters,
                textvariable=var,
                values=values,
                width=width,
                state="readonly",
            )
            cb.pack(side="left", padx=(4, 14))

        add_filter("Сектор:", self._f_sector, ["Все", "Collection", "КЦ"], 12)
        add_filter("Статус:", self._f_enabled, ["Все", "Включенные"], 14)
        add_filter("Префикс:", self._f_coll, ["Все", "Только Collection"], 18)
        add_filter("Группа:", self._f_group, ["Все", "G1", "G2", "G3"], 8)
        add_filter("Тип:", self._f_sub, ["Все", "Main", "APTP", "BPTP"], 10)

        for var in (
            self._f_sector,
            self._f_enabled,
            self._f_coll,
            self._f_group,
            self._f_sub,
        ):
            var.trace_add("write", lambda *_: self._apply_filters())

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.tree = ttk.Treeview(body, columns=COLS, show="headings", selectmode="browse")
        self.tree.heading("name", text="Имя")
        self.tree.heading("id", text="ID")
        self.tree.heading("calendar", text="Календарь")
        self.tree.heading("schema", text="Схема")
        self.tree.heading("type", text="Тип")
        self.tree.heading("enabled", text="Статус")
        self.tree.heading("team", text="Команда")
        self.tree.heading("agents", text="Онлайн / Офлайн / На перерыве / Всего")
        self.tree.column("name", width=300, anchor="w")
        self.tree.column("id", width=60, anchor="w", stretch=False)
        self.tree.column("calendar", width=180, anchor="w")
        self.tree.column("schema", width=240, anchor="w")
        self.tree.column("type", width=200, anchor="w")
        self.tree.column("enabled", width=100, anchor="w", stretch=False)
        self.tree.column("team", width=130, anchor="w")
        self.tree.column("agents", width=240, anchor="center", stretch=False)

        self.tree.tag_configure("link", foreground="#2563eb")

        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.bind("<Button-1>", self._on_cell_click)
        self.tree.bind("<Motion>", self._on_motion)

        self._reload()

    def _reload(self) -> None:
        self._reload_btn.configure(state="disabled")
        self._status.configure(text="Загрузка…", foreground="#6b7280")
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_queue.clear()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            client = WebitelClient(
                self._company.webitel_host, self._company.webitel_access_token
            )
            queues = client.list_queues(types=list(AGENT_QUEUE_TYPES))
            error: Optional[str] = None
        except WebitelError as exc:
            queues = []
            error = str(exc)
        chat_queues: list[Queue] = []
        if not error:
            try:
                chat_queues = client.list_queues(types=[6])
            except WebitelError:
                chat_queues = []
        if queues and not error:
            def fetch_agents(q: Queue) -> None:
                try:
                    statuses = client.list_queue_agent_statuses(q.id)
                    q.agents_total = len(statuses)
                    q.agents_online = sum(1 for s in statuses if s == "online")
                    q.agents_offline = sum(1 for s in statuses if s == "offline")
                    q.agents_pause = sum(1 for s in statuses if s == "pause")
                except WebitelError:
                    pass
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(fetch_agents, queues))
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render(queues, error, chat_queues))

    def _render(
        self,
        queues: list[Queue],
        error: Optional[str],
        chat_queues: Optional[list[Queue]] = None,
    ) -> None:
        if not self.winfo_exists():
            return
        self._reload_btn.configure(state="normal")
        if error is not None:
            self._status.configure(text=f"Ошибка: {error}", foreground="#dc2626")
            return
        queues = [q for q in queues if q.type in AGENT_QUEUE_TYPES]
        queues.sort(key=lambda q: (q.type, q.name.lower()))
        self._all_queues = queues
        self._all_chat_queues = chat_queues or []
        self._refresh_checklist()
        self._apply_filters()

    def _refresh_checklist(self) -> None:
        if self._sector == SECTOR_CC:
            self._refresh_cc_checklist()
            return
        self._cl_missing: list[tuple[str, str]] = []
        self._cl_present: list[tuple[str, str, Queue]] = []
        for g in self._cl_groups:
            for tp in self._cl_types:
                found = self._find_collection(g, tp)
                lbl = self._cl_cells[(g, tp)]
                if found is not None:
                    lbl.configure(text=f"✓  id {found.id}", foreground="#16a34a")
                    self._cl_present.append((g, tp, found))
                else:
                    lbl.configure(text="✗  нет", foreground="#dc2626")
                    self._cl_missing.append((g, tp))
        total = len(self._cl_groups) * len(self._cl_types)
        ok = total - len(self._cl_missing)
        if not self._cl_missing:
            self._cl_summary.configure(
                text=f"Все {total} очередей на месте.",
                foreground="#16a34a",
            )
            self._cl_alert_btn.pack_forget()
            self._cl_alert_status.pack_forget()
        else:
            self._cl_summary.configure(
                text=f"Покрытие: {ok}/{total} — есть пробелы.",
                foreground="#dc2626",
            )
            self._cl_alert_btn.pack(side="left")
            self._cl_alert_status.pack(side="left", padx=(12, 0))
            self._cl_alert_btn.configure(state="normal")
            self._cl_alert_status.configure(text="", foreground="#6b7280")

    def _build_checklist_alert_text(self) -> str:
        if self._sector == SECTOR_CC:
            total = self._cc_total
            ok = total - len(self._cc_missing)
            bullets = [
                f"{cat} · {channel} — {name}"
                for cat, channel, name in self._cc_missing
            ]
            return render_alert_html(
                severity="warning",
                title="Queues check · CC",
                company_code=self._company.code,
                company_name=self._company.name,
                webitel_host=self._company.webitel_host,
                category="Agents",
                metrics=[
                    ("Coverage", f"{ok} / {total}"),
                    ("Missing", str(len(self._cc_missing))),
                    ("Configured", str(ok)),
                ],
                bullets=bullets,
                body="The following CC queues are not enabled or not present:",
            )
        total = len(self._cl_groups) * len(self._cl_types)
        ok = total - len(self._cl_missing)
        bullets = [f"{g} — {tp}" for g, tp in self._cl_missing]
        return render_alert_html(
            severity="warning",
            title="Queues check · Collection",
            company_code=self._company.code,
            company_name=self._company.name,
            webitel_host=self._company.webitel_host,
            category="Agents",
            metrics=[
                ("Coverage", f"{ok} / {total}"),
                ("Missing", str(len(self._cl_missing))),
                ("Configured", str(ok)),
            ],
            bullets=bullets,
            body="The following queues are not enabled or not present:",
        )

    def _send_checklist_alert(self) -> None:
        empty = (
            not self._cc_missing if self._sector == SECTOR_CC
            else not self._cl_missing
        )
        if empty:
            return
        self._cl_alert_btn.configure(state="disabled")
        self._cl_alert_status.configure(text="Отправка…", foreground="#6b7280")
        text = self._build_checklist_alert_text()
        threading.Thread(
            target=self._send_alert_worker, args=(text,), daemon=True
        ).start()

    def _send_alert_worker(self, text: str) -> None:
        cfg = load_alerts_config()
        tg = cfg.get("telegram", {})
        topic_id = ensure_company_topic(cfg, self._company)
        err: Optional[str] = None
        try:
            send_telegram_message(
                tg.get("bot_token", ""), tg.get("chat_id", ""), text,
                parse_mode="HTML",
                message_thread_id=topic_id,
            )
        except TelegramError as e:
            err = str(e)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._send_alert_done(err))

    def _send_alert_done(self, err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._cl_alert_btn.configure(state="normal")
        if err:
            self._cl_alert_status.configure(text=f"Ошибка: {err}", foreground="#dc2626")
        else:
            self._cl_alert_status.configure(text="Отправлено ✓", foreground="#16a34a")

    def _find_collection(self, group: str, sub: str) -> Optional[Queue]:
        if sub == "Chat":
            return self._find_collection_chat(group)
        for q in self._all_queues:
            name = q.name or ""
            if not q.enabled:
                continue
            if not name.lstrip().lower().startswith("collection"):
                continue
            if not self._has_token(name, group):
                continue
            if not self._has_token(name, sub):
                continue
            return q
        return None

    def _find_collection_chat(self, group: str) -> Optional[Queue]:
        for q in self._all_chat_queues:
            if not q.enabled:
                continue
            name = q.name or ""
            if "collection" not in name.lower():
                continue
            if not self._has_token(name, group):
                continue
            return q
        return None

    @staticmethod
    def _has_token(name: str, token: str) -> bool:
        pattern = r"(?:^|[^A-Za-z0-9])" + re.escape(token) + r"(?:$|[^A-Za-z0-9])"
        return re.search(pattern, name, re.IGNORECASE) is not None

    @staticmethod
    def _is_collection_sector(q: Queue) -> bool:
        cal = q.calendar
        return bool(cal and "collection" in (cal.name or "").lower())

    @staticmethod
    def _is_cc_sector(q: Queue) -> bool:
        return "CC" in (q.name or "")

    def _matches(self, q: Queue) -> bool:
        sector = self._f_sector.get()
        if sector == "Collection" and not self._is_collection_sector(q):
            return False
        if sector == "КЦ" and not self._is_cc_sector(q):
            return False
        if self._f_enabled.get() == "Включенные" and not q.enabled:
            return False
        name = q.name or ""
        if self._f_coll.get() == "Только Collection" and not name.lstrip().lower().startswith("collection"):
            return False
        g = self._f_group.get()
        if g != "Все" and not self._has_token(name, g):
            return False
        s = self._f_sub.get()
        if s != "Все" and not self._has_token(name, s):
            return False
        return True

    def _apply_filters(self) -> None:
        if not self.winfo_exists():
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_queue.clear()
        shown = 0
        for q in self._all_queues:
            if not self._matches(q):
                continue
            if q.agents_total is None:
                agents_text = "—"
            else:
                on = q.agents_online or 0
                off = q.agents_offline or 0
                pause = q.agents_pause or 0
                agents_text = f"{on} / {off} / {pause} / {q.agents_total}"
            iid = self.tree.insert(
                "",
                "end",
                values=(
                    q.name,
                    q.id,
                    _fmt_lookup(q.calendar),
                    _schema_summary(q),
                    f"{q.type} — {QUEUE_TYPE_NAMES.get(q.type, '?')}",
                    "Включена" if q.enabled else "Выключена",
                    q.team.name if q.team else "—",
                    agents_text,
                ),
            )
            self._row_to_queue[iid] = q
            shown += 1
        total = len(self._all_queues)
        text = f"Очередей: {shown} из {total}" if shown != total else f"Очередей: {total}"
        self._status.configure(text=text, foreground="#111827")

    def _column_at(self, x: int) -> Optional[str]:
        col = self.tree.identify_column(x)
        if not col:
            return None
        try:
            idx = int(col.lstrip("#")) - 1
        except ValueError:
            return None
        if 0 <= idx < len(COLS):
            return COLS[idx]
        return None

    def _on_cell_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        col = self._column_at(event.x)
        q = self._row_to_queue.get(iid)
        if not q or not col:
            return
        if col == "name":
            url = f"{self._company.webitel_host.rstrip('/')}/contact-center/queues/{q.id}/general"
            webbrowser.open(url)
        elif col == "calendar" and q.calendar:
            url = f"{self._company.webitel_host.rstrip('/')}/lookups/calendars/{q.calendar.id}/general"
            webbrowser.open(url)
        elif col == "schema":
            SchemaPopup(self, q)

    def _on_motion(self, event: tk.Event) -> None:
        cursor = ""
        iid = self.tree.identify_row(event.y)
        col = self._column_at(event.x)
        if iid and col:
            q = self._row_to_queue.get(iid)
            if q:
                if col == "name":
                    cursor = "hand2"
                elif col == "calendar" and q.calendar:
                    cursor = "hand2"
                elif col == "schema" and any(
                    [q.schema, q.do_schema, q.after_schema, q.form_schema]
                ):
                    cursor = "hand2"
        if str(self.tree.cget("cursor")) != cursor:
            self.tree.configure(cursor=cursor)
