import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Optional
from zoneinfo import ZoneInfo

from ..conversations_cache import load_cache, save_cache
from ..data import Company
from ..i18n import t
from ..webitel import (
    Agent,
    ChatDialog,
    ChatMessage,
    ChatPeer,
    WebitelClient,
    WebitelError,
)
from .. import grafana_pg

PERIODS: list[tuple[str, str]] = [
    ("Сегодня", "today"),
    ("Последние 24 часа", "24h"),
    ("Последние 7 дней", "7d"),
    ("Последние 30 дней", "30d"),
]

BG = "#ffffff"
INCOMING_BG = "#f3f4f6"
OUTGOING_BG = "#dbeafe"
META_FG = "#6b7280"
TEXT_FG = "#111827"


class ConversationsPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._all_dialogs: list[ChatDialog] = []
        self._members: dict[str, list[ChatPeer]] = {}
        self._collection_user_ids: set[str] = set()
        # Grafana-mode side-channels — populated when we pull dialogs from
        # Postgres (full coverage incl. bot-only). Members aren't fetched
        # in bulk in that mode (1500+ chats × 1 REST call = too slow);
        # classifier uses these to label rows without per-chat fetch.
        self._grafana_agent_by_chat: dict[str, str] = {}
        self._grafana_agent_id_by_chat: dict[str, int] = {}
        self._grafana_status_by_chat: dict[str, str] = {}  # bot|agent|queued_unanswered
        self._collection_agent_ids: set[int] = set()
        self._data_source: str = "rest"  # set to "grafana" when load succeeds
        self._sel_id: Optional[str] = None
        self._cache: dict = load_cache(company.key)

        ttk.Label(
            self,
            text=t("header_chats"),
            font=("Segoe UI", 9, "bold"),
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(14, 6))

        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        filters = ttk.Frame(self)
        filters.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Label(filters, text="Период:").pack(side="left")
        self._period_var = tk.StringVar(value=PERIODS[1][0])
        ttk.Combobox(
            filters,
            textvariable=self._period_var,
            values=[name for name, _ in PERIODS],
            state="readonly",
            width=20,
        ).pack(side="left", padx=(4, 14))
        ttk.Label(filters, text="Поиск:").pack(side="left")
        self._q_var = tk.StringVar()
        q_entry = ttk.Entry(filters, textvariable=self._q_var, width=22)
        q_entry.pack(side="left", padx=(4, 14))
        q_entry.bind("<Return>", lambda _e: self._reload())
        ttk.Label(filters, text="Телефон:").pack(side="left")
        self._phone_var = tk.StringVar()
        phone_entry = ttk.Entry(filters, textvariable=self._phone_var, width=18)
        phone_entry.pack(side="left", padx=(4, 14))
        phone_entry.bind("<Return>", lambda _e: self._apply_filters())
        self._collection_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filters,
            text="Только коллекшен",
            variable=self._collection_var,
            command=self._apply_filters,
        ).pack(side="left", padx=(0, 14))
        # Bot / agent type filter — operator wants quick split.
        ttk.Label(filters, text="Тип:").pack(side="left")
        self._kind_var = tk.StringVar(value="Все")
        kind_box = ttk.Combobox(
            filters,
            textvariable=self._kind_var,
            values=["Все", "🤖 Бот", "👤 Агент", "❓ Неизвестно"],
            state="readonly",
            width=14,
        )
        kind_box.pack(side="left", padx=(4, 14))
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        self._reload_btn = ttk.Button(filters, text="Обновить", command=self._reload)
        self._reload_btn.pack(side="left")
        self._status = ttk.Label(filters, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(14, 0))

        for var in (self._phone_var,):
            var.trace_add("write", lambda *_: self._apply_filters())

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        list_pane = ttk.Frame(paned)
        chat_pane = ttk.Frame(paned)
        paned.add(list_pane, weight=2)
        paned.add(chat_pane, weight=3)

        cols = ("title", "channel", "agent", "started", "last")
        self.tree = ttk.Treeview(list_pane, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("title", text="Имя")
        self.tree.heading("channel", text="Канал")
        self.tree.heading("agent", text="Агент / Бот")
        self.tree.heading("started", text="Начат")
        self.tree.heading("last", text="Последнее")
        self.tree.column("title", width=200, anchor="w")
        self.tree.column("channel", width=110, anchor="w")
        self.tree.column("agent", width=200, anchor="w")
        self.tree.column("started", width=140, anchor="w")
        self.tree.column("last", width=140, anchor="w")
        scl = ttk.Scrollbar(list_pane, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_dialog_select)

        self.chat_canvas = tk.Canvas(chat_pane, bg=BG, highlightthickness=0)
        cscl = ttk.Scrollbar(chat_pane, orient="vertical", command=self.chat_canvas.yview)
        self.chat_canvas.configure(yscrollcommand=cscl.set)
        self.chat_canvas.pack(side="left", fill="both", expand=True)
        cscl.pack(side="right", fill="y")
        self.chat_inner = tk.Frame(self.chat_canvas, bg=BG)
        self._chat_win = self.chat_canvas.create_window(
            (0, 0), window=self.chat_inner, anchor="nw"
        )
        self.chat_inner.bind(
            "<Configure>",
            lambda _e: self.chat_canvas.configure(
                scrollregion=self.chat_canvas.bbox("all")
            ),
        )
        self.chat_canvas.bind(
            "<Configure>",
            lambda e: self.chat_canvas.itemconfig(self._chat_win, width=e.width),
        )
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        self._show_chat_placeholder("Выберите диалог сверху")
        self._reload()

    # ---------- helpers ----------

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            x, y = self.chat_canvas.winfo_pointerxy()
            wx = self.chat_canvas.winfo_rootx()
            wy = self.chat_canvas.winfo_rooty()
            w = self.chat_canvas.winfo_width()
            h = self.chat_canvas.winfo_height()
            if not (wx <= x <= wx + w and wy <= y <= wy + h):
                return
        except tk.TclError:
            return
        self.chat_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self._company.timezone or "UTC")
        except Exception:
            return ZoneInfo("UTC")

    def _fmt_time(self, ms: int) -> str:
        if not ms:
            return ""
        try:
            return datetime.fromtimestamp(ms / 1000, tz=self._tz()).strftime(
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            return ""

    def _period_to_range(self) -> tuple[int, int]:
        kind = next((slug for name, slug in PERIODS if name == self._period_var.get()), "24h")
        tz = self._tz()
        now = datetime.now(tz)
        if kind == "today":
            since = datetime(now.year, now.month, now.day, tzinfo=tz)
        elif kind == "7d":
            since = now - timedelta(days=7)
        elif kind == "30d":
            since = now - timedelta(days=30)
        else:
            since = now - timedelta(hours=24)
        return int(since.timestamp() * 1000), int(now.timestamp() * 1000)

    def _clear_chat(self) -> None:
        for w in self.chat_inner.winfo_children():
            w.destroy()

    def _show_chat_placeholder(self, text: str) -> None:
        self._clear_chat()
        tk.Label(self.chat_inner, text=text, fg=META_FG, bg=BG).pack(pady=24)

    # ---------- dialogs list (network) ----------

    def _reload(self) -> None:
        self._reload_btn.configure(state="disabled")
        self._status.configure(text="Загрузка…", foreground=META_FG)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._sel_id = None
        self._all_dialogs = []
        self._members.clear()
        self._collection_user_ids.clear()
        self._show_chat_placeholder("Выберите диалог сверху")
        since, until = self._period_to_range()
        q = self._q_var.get().strip() or None
        threading.Thread(
            target=self._reload_worker, args=(since, until, q), daemon=True
        ).start()

    # ---------- Grafana data path -----------------------------------

    # Overlap when delta-fetching: re-pull the last N minutes so we
    # catch chats that were "in flight" during the previous sync (their
    # closed_at / agent_id / bridged status may have updated).
    _GRAFANA_DELTA_OVERLAP_MS = 10 * 60 * 1000

    def _grafana_dialogs(
        self,
        since_ms: int,
        until_ms: int,
        agent_name_by_id: dict[int, str],
        phone_query: Optional[str],
    ) -> list[ChatDialog]:
        """Pull dialogs from Webitel's Postgres via Grafana with a
        local incremental cache. Behaviour:

          - Cached rows live in `self._cache["grafana_rows"]`
            (chat_id → row dict).
          - `self._cache["grafana_coverage"]` tracks the time window
            the cache is known to cover.
          - On each call we fetch ONLY the missing range from the
            Postgres side (typically the tail since the last sync)
            and merge into the cache. A 10-min overlap re-checks
            recently-updated chats so agent-pickup / closed_at
            transitions land in cache.
          - Display = cache filtered to [since_ms, until_ms].
        """
        # Per-company filter — stored in companies.json.
        wa_number = ""
        try:
            from ..wa_bot_config import load_raw as _wa_load_raw
            wa_cfg = (
                ((_wa_load_raw().get(self._company.key) or {})
                 .get("bots") or {})
                .get("whatsapp") or {}
            )
            wa_number = str(wa_cfg.get("bot_phone_number") or "").strip()
        except Exception:
            wa_number = ""

        cache = self._cache
        cached_rows: dict = cache.setdefault("grafana_rows", {})
        coverage: dict = cache.setdefault("grafana_coverage", {})
        cov_since = coverage.get("since_ms")
        cov_until = coverage.get("until_ms")

        # Decide what to actually fetch.
        if cov_since is None or int(cov_since) > since_ms:
            # Cache doesn't cover the older edge of the requested period
            # — fetch the whole [since_ms, until_ms] block.
            fetch_from = since_ms
            fetch_to = until_ms
        else:
            # Cache covers the older edge already; just re-pull the tail
            # with a small overlap so recently-mutated chats are refreshed.
            fetch_from = max(
                since_ms,
                int(cov_until or since_ms) - self._GRAFANA_DELTA_OVERLAP_MS,
            )
            fetch_to = until_ms

        new_rows: list[dict] = []
        if fetch_to > fetch_from:
            new_rows = grafana_pg.list_chat_conversations(
                fetch_from, fetch_to,
                company_key=self._company.key,
                channel=None,
                whatsapp_number=wa_number or None,
                limit=5000,
            )

        # Merge new rows into cache. Last-write-wins by chat_id.
        fresh_count = 0
        updated_count = 0
        for r in new_rows:
            chat_id = str(r.get("id") or "")
            if not chat_id:
                continue
            if chat_id in cached_rows:
                updated_count += 1
            else:
                fresh_count += 1
            cached_rows[chat_id] = r

        # Update coverage window.
        coverage["since_ms"] = (
            min(int(cov_since or fetch_from), fetch_from)
            if cov_since is not None else fetch_from
        )
        coverage["until_ms"] = max(int(cov_until or fetch_to), fetch_to)
        cache["grafana_coverage"] = coverage
        cache["grafana_rows"] = cached_rows
        save_cache(self._company.key, cache)

        # Reset side-channels — rebuilt from cache below.
        self._grafana_agent_by_chat = {}
        self._grafana_agent_id_by_chat = {}
        self._grafana_status_by_chat = {}
        self._grafana_fresh_count = fresh_count
        self._grafana_reused_count = max(
            0, len(cached_rows) - fresh_count - updated_count,
        )
        self._grafana_updated_count = updated_count

        # Filter cached rows for display.
        ph = (phone_query or "").strip().lower() or None
        out: list[ChatDialog] = []
        for chat_id, r in cached_rows.items():
            try:
                created_at = int(float(r.get("created_at_ms") or 0))
            except (TypeError, ValueError):
                created_at = 0
            if not (since_ms <= created_at <= until_ms):
                continue
            from_phone = str(r.get("from_phone") or "")
            peer_name = str(r.get("peer_name") or "")
            if ph:
                hay = f"{from_phone} {peer_name}".lower()
                if ph not in hay:
                    continue
            queued = bool(r.get("queued"))
            bridged = bool(r.get("bridged"))
            agent_id_raw = r.get("agent_id")
            try:
                agent_id_int = int(agent_id_raw) if agent_id_raw is not None else None
            except (TypeError, ValueError):
                agent_id_int = None
            if agent_id_int and bridged:
                self._grafana_agent_by_chat[chat_id] = (
                    agent_name_by_id.get(agent_id_int) or f"agent {agent_id_int}"
                )
                self._grafana_agent_id_by_chat[chat_id] = agent_id_int
                self._grafana_status_by_chat[chat_id] = "agent"
            elif queued:
                self._grafana_status_by_chat[chat_id] = "queued_unanswered"
            else:
                self._grafana_status_by_chat[chat_id] = "bot"

            try:
                last = int(float(r.get("closed_at_ms") or 0)) or created_at
            except (TypeError, ValueError):
                last = created_at

            out.append(ChatDialog(
                id=chat_id,
                title=peer_name or from_phone or chat_id[:8],
                peer_name=peer_name,
                peer_id=from_phone,
                peer_type="user",
                via_name=str(r.get("channel") or ""),
                started_at_ms=created_at,
                last_msg_at_ms=last,
                last_msg_text="",
            ))
        out.sort(key=lambda d: -d.started_at_ms)
        return out

    def _reload_worker(self, since: int, until: int, q: Optional[str]) -> None:
        client = WebitelClient(
            self._company.webitel_host, self._company.webitel_access_token
        )

        # Resolve agents once — needed by both data sources for collection
        # filtering and (in Grafana mode) for agent_id → name lookup.
        try:
            agents = client.list_agents()
        except WebitelError:
            agents = []
        collection_ids = {
            a.user_id
            for a in agents
            if a.user_id and "collection" in (a.team_name or "").lower()
        }
        agent_name_by_id: dict[int, str] = {a.id: a.name for a in agents if a.id}
        collection_agent_ids = {
            a.id for a in agents
            if a.id and "collection" in (a.team_name or "").lower()
        }

        # Try Grafana (full coverage incl. bot-only). Fall back to REST
        # on any error — Grafana might be down or creds missing.
        dialogs: list[ChatDialog] = []
        used_grafana = False
        if grafana_pg.is_configured(self._company.key):
            try:
                dialogs = self._grafana_dialogs(
                    since, until, agent_name_by_id, q,
                )
                used_grafana = True
            except Exception as e:  # noqa: BLE001 — fall back gracefully
                # Telegram-style error trace would be too noisy here;
                # we just log and use REST.
                print(f"[conversations] grafana fetch failed, fallback REST: {e}")

        if not used_grafana:
            try:
                dialogs = client.list_dialogs(
                    date_since_ms=since, date_until_ms=until, q=q, size=200
                )
            except WebitelError as e:
                if not self.winfo_exists():
                    return
                self.after(0, lambda: self._on_load_error(str(e)))
                return
            self._grafana_agent_by_chat = {}
            self._grafana_status_by_chat = {}
            self._collection_agent_ids = set()
            self._data_source = "rest"
        else:
            self._collection_agent_ids = collection_agent_ids
            self._data_source = "grafana"

        cache = self._cache
        cached_dialogs = cache.setdefault("dialogs", {})
        cached_members = cache.setdefault("members", {})
        cached_messages = cache.setdefault("messages", {})

        # Bulk member fetch — only in REST mode (~200 chats). In
        # Grafana mode we have 1000+ chats; pre-fetching members would
        # make the panel hang for 30+ seconds. Members are loaded
        # lazily for the chat the operator clicks.
        needs_members: list[ChatDialog] = []
        if self._data_source != "grafana":
            for d in dialogs:
                old = cached_dialogs.get(d.id) or {}
                updated = (old.get("last_msg_at_ms", 0) or 0) < d.last_msg_at_ms
                if updated and d.id in cached_messages:
                    cached_messages.pop(d.id, None)
                if d.id not in cached_members or updated:
                    needs_members.append(d)

            if needs_members:
                def _fetch(d: ChatDialog) -> tuple[str, list[ChatPeer]]:
                    try:
                        return d.id, client.list_dialog_members(d.id)
                    except WebitelError:
                        return d.id, []

                with ThreadPoolExecutor(max_workers=12) as pool:
                    for did, members in pool.map(_fetch, needs_members):
                        cached_members[did] = [asdict(m) for m in members]

        # Persist updated dialog snapshots
        for d in dialogs:
            cached_dialogs[d.id] = asdict(d)
        save_cache(self._company.key, cache)

        # Build in-memory members map for the rendered period
        members_map: dict[str, list[ChatPeer]] = {}
        for d in dialogs:
            raw = cached_members.get(d.id, [])
            members_map[d.id] = [ChatPeer(**r) for r in raw]

        if not self.winfo_exists():
            return
        fresh = len(needs_members)
        reused = len(dialogs) - fresh
        self.after(
            0,
            lambda: self._on_load_done(dialogs, members_map, collection_ids, fresh, reused),
        )

    def _on_load_error(self, err: str) -> None:
        if not self.winfo_exists():
            return
        self._reload_btn.configure(state="normal")
        self._status.configure(text=f"Ошибка: {err}", foreground="#dc2626")

    def _on_load_done(
        self,
        dialogs: list[ChatDialog],
        members_map: dict[str, list[ChatPeer]],
        collection_user_ids: set[str],
        fresh: int = 0,
        reused: int = 0,
    ) -> None:
        if not self.winfo_exists():
            return
        self._all_dialogs = dialogs
        self._members = members_map
        self._collection_user_ids = collection_user_ids
        self._reload_btn.configure(state="normal")
        self._apply_filters()
        if fresh or reused:
            extra = f"  ·  новых: {fresh}, из кеша: {reused}"
            base = self._status.cget("text")
            self._status.configure(text=base + extra)

    # ---------- filters / render ----------

    def _classify(self, chat_id: str) -> tuple[str, str]:
        """Return (kind, display_label) for a chat:
          * 'agent' — at least one member with type='user' (real Webitel
            human account). Display = agent's name.
          * 'bot' — no user member; the chat sits inside a routing schema.
            Display = bot/schema name with 🤖 prefix.
          * 'unknown' — empty member list and nothing in side-channels.

        In Grafana mode we usually have NO member list (we skip the bulk
        per-chat REST fetch). The side-channel maps populated by
        `_grafana_dialogs` carry status + agent name and take precedence
        when no member-list snapshot is loaded yet.
        """
        members = self._members.get(chat_id, [])
        if members:
            for p in members:
                if (p.type or "").lower() == "user":
                    return "agent", f"👤 {p.name or 'agent ' + p.id}"
            for p in members:
                if (p.type or "").lower() != "user":
                    name = p.name or "bot"
                    return "bot", f"🤖 {name}"
            return "unknown", "❓ —"

        # No members loaded — try Grafana side-channel.
        status = self._grafana_status_by_chat.get(chat_id)
        if status == "agent":
            name = self._grafana_agent_by_chat.get(chat_id, "agent")
            return "agent", f"👤 {name}"
        if status == "queued_unanswered":
            return "agent", "👤 в очереди"
        if status == "bot":
            return "bot", "🤖 бот"
        return "unknown", "❓ —"

    def _is_collection(self, chat_id: str) -> bool:
        # Member-based check (REST mode or after detail fetch loaded peers).
        if self._collection_user_ids:
            for p in self._members.get(chat_id, []):
                if p.type == "user" and p.id in self._collection_user_ids:
                    return True
        # Grafana mode: check the agent_id we got from cc_member_attempt.
        agent_id = self._grafana_agent_id_by_chat.get(chat_id)
        if agent_id and agent_id in self._collection_agent_ids:
            return True
        return False

    def _selected_kind_filter(self) -> Optional[str]:
        v = self._kind_var.get()
        if v.startswith("🤖"):
            return "bot"
        if v.startswith("👤"):
            return "agent"
        if v.startswith("❓"):
            return "unknown"
        return None  # "Все"

    def _matches(self, d: ChatDialog, kind: str) -> bool:
        phone = self._phone_var.get().strip()
        if phone:
            haystack = f"{d.peer_id} {d.peer_name}".lower()
            if phone.lower() not in haystack:
                return False
        if self._collection_var.get() and not self._is_collection(d.id):
            return False
        kind_filter = self._selected_kind_filter()
        if kind_filter and kind != kind_filter:
            return False
        return True

    def _apply_filters(self) -> None:
        if not self.winfo_exists():
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        shown = 0
        n_bot = 0
        n_agent = 0
        n_unknown = 0
        for d in self._all_dialogs:
            kind, label = self._classify(d.id)
            if kind == "bot":
                n_bot += 1
            elif kind == "agent":
                n_agent += 1
            else:
                n_unknown += 1
            if not self._matches(d, kind):
                continue
            self.tree.insert(
                "",
                "end",
                iid=d.id,
                values=(
                    d.title or d.peer_name or d.peer_id or d.id[:8],
                    d.via_name or d.peer_type,
                    label,
                    self._fmt_time(d.started_at_ms),
                    self._fmt_time(d.last_msg_at_ms),
                ),
                tags=(kind,),
            )
            shown += 1
        # Subtle row colouring so bot/agent are visually distinct.
        self.tree.tag_configure("bot",   foreground="#6d28d9")
        self.tree.tag_configure("agent", foreground="#0f766e")
        self.tree.tag_configure("unknown", foreground="#6b7280")
        total = len(self._all_dialogs)
        breakdown = (
            f"бот: {n_bot} · агент: {n_agent}"
            + (f" · ?: {n_unknown}" if n_unknown else "")
        )
        src_tag = " · pg" if self._data_source == "grafana" else " · rest"
        if shown == total:
            text = f"Диалогов: {total}  ·  {breakdown}{src_tag}"
        else:
            text = f"Диалогов: {shown} из {total}  ·  {breakdown}{src_tag}"
        self._status.configure(text=text, foreground=TEXT_FG)

    # ---------- messages ----------

    def _on_dialog_select(self, _e: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        cid = sel[0]
        if cid == self._sel_id:
            return
        self._sel_id = cid
        self._show_chat_placeholder("Загрузка сообщений…")
        threading.Thread(target=self._messages_worker, args=(cid,), daemon=True).start()

    def _messages_worker(self, chat_id: str) -> None:
        cached_msgs = self._cache.get("messages", {}).get(chat_id)
        if cached_msgs:
            try:
                msgs = [ChatMessage(**m) for m in cached_msgs.get("msgs", [])]
                peers = {
                    k: ChatPeer(**v) for k, v in (cached_msgs.get("peers", {}) or {}).items()
                }
            except (TypeError, ValueError):
                msgs, peers = [], {}
            if msgs and self.winfo_exists() and self._sel_id == chat_id:
                self.after(0, lambda: self._render_chat(msgs, peers, None))
                return

        try:
            client = WebitelClient(
                self._company.webitel_host, self._company.webitel_access_token
            )
            msgs, peers = client.get_dialog_messages(chat_id, limit=500)
            err: Optional[str] = None
        except WebitelError as e:
            msgs, peers, err = [], {}, str(e)

        if err is None:
            self._cache.setdefault("messages", {})[chat_id] = {
                "msgs": [asdict(m) for m in msgs],
                "peers": {k: asdict(v) for k, v in peers.items()},
            }
            save_cache(self._company.key, self._cache)

        if not self.winfo_exists() or self._sel_id != chat_id:
            return
        self.after(0, lambda: self._render_chat(msgs, peers, err))

    def _render_chat(
        self,
        msgs: list[ChatMessage],
        peers: dict[str, ChatPeer],
        err: Optional[str],
    ) -> None:
        if not self.winfo_exists():
            return
        self._clear_chat()
        if err:
            tk.Label(
                self.chat_inner, text=f"Ошибка: {err}", fg="#dc2626", bg=BG
            ).pack(pady=20)
            return
        if not msgs:
            tk.Label(
                self.chat_inner, text="Сообщений нет", fg=META_FG, bg=BG
            ).pack(pady=20)
            return
        msgs = sorted(msgs, key=lambda m: m.date_ms)
        agent_peer_types = {"bot", "user"}
        for m in msgs:
            peer = peers.get(m.sender_id)
            if peer and peer.type:
                is_client = peer.type.lower() not in agent_peer_types
            else:
                is_client = True
            self._add_bubble(m, peer, is_client)
        self.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def _add_bubble(
        self, m: ChatMessage, peer: Optional[ChatPeer], is_client: bool
    ) -> None:
        bg = INCOMING_BG if is_client else OUTGOING_BG
        side = "left" if is_client else "right"
        anchor = "w" if is_client else "e"
        sender_name = (peer.name if peer and peer.name else None) or (
            "Клиент" if is_client else "Агент"
        )

        row = tk.Frame(self.chat_inner, bg=BG)
        row.pack(fill="x", padx=12, pady=4)
        bubble = tk.Frame(row, bg=bg)
        bubble.pack(side=side, anchor=anchor)
        meta = f"{sender_name} · {self._fmt_time(m.date_ms)}"
        tk.Label(
            bubble,
            text=meta,
            bg=bg,
            fg=META_FG,
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=10, pady=(4, 0))
        tk.Label(
            bubble,
            text=m.text or "—",
            bg=bg,
            fg=TEXT_FG,
            wraplength=620,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=10, pady=(0, 6))
