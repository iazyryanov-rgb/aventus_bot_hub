"""Calls panel — mirror of the Chats panel but for voice calls with
Webitel transcripts.

Lists Webitel /calls/history entries that have a transcript attached
(`has_transcript=true`), shows them in a familiar Чаты-style filter +
list layout, and renders the per-phrase transcription text on the
right when the operator picks a call.

Webitel transcripts come from `/storage/transcript_file/{id}/phrases`
(see memory `webitel_call_transcription_api.md`). Their `channel`
field is the audio stream id (0/1) or operator's name; we map it to
agent/client using the call's `agent_id` (and fall back to a default
labelling when ambiguous).

Read-only — no writes back to Webitel.
"""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Optional
from zoneinfo import ZoneInfo

from ..data import Company
from ..i18n import t
from ..webitel import WebitelClient, WebitelError


PERIODS: list[tuple[str, str]] = [
    ("Сегодня", "today"),
    ("Последние 24 часа", "24h"),
    ("Последние 7 дней", "7d"),
    ("Последние 30 дней", "30d"),
]

BG = "#ffffff"
CLIENT_BG = "#f3f4f6"   # left, same hue as Chats incoming
AGENT_BG = "#dbeafe"    # right, same hue as Chats outgoing
META_FG = "#6b7280"
TEXT_FG = "#111827"


class CallsPanel(ttk.Frame):
    """Voice-calls counterpart to ConversationsPanel."""

    PAGE_SIZE = 200
    MAX_PAGES = 5  # 1000 calls max — UI list above that is unusable anyway

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._calls: list[dict] = []
        self._agent_name_by_id: dict[int, str] = {}
        self._sel_id: Optional[str] = None

        ttk.Label(
            self,
            text=t("header_calls"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        filters = ttk.Frame(self)
        filters.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Label(filters, text=t("calls_period")).pack(side="left")
        self._period_var = tk.StringVar(value=PERIODS[1][0])
        ttk.Combobox(
            filters,
            textvariable=self._period_var,
            values=[name for name, _ in PERIODS],
            state="readonly",
            width=20,
        ).pack(side="left", padx=(4, 14))
        ttk.Label(filters, text=t("calls_phone")).pack(side="left")
        self._phone_var = tk.StringVar()
        phone_entry = ttk.Entry(filters, textvariable=self._phone_var, width=18)
        phone_entry.pack(side="left", padx=(4, 14))
        phone_entry.bind("<Return>", lambda _e: self._apply_filters())
        self._phone_var.trace_add("write", lambda *_: self._apply_filters())
        ttk.Label(filters, text=t("calls_direction")).pack(side="left")
        self._dir_labels = {
            "all":     t("calls_dir_all"),
            "inbound": t("calls_dir_inbound"),
            "outbound": t("calls_dir_outbound"),
        }
        self._dir_var = tk.StringVar(value=self._dir_labels["all"])
        dir_box = ttk.Combobox(
            filters,
            textvariable=self._dir_var,
            values=[self._dir_labels[k] for k in ("all", "inbound", "outbound")],
            state="readonly",
            width=14,
        )
        dir_box.pack(side="left", padx=(4, 14))
        dir_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        self._reload_btn = ttk.Button(
            filters, text=t("btn_refresh"), command=self._reload,
        )
        self._reload_btn.pack(side="left")
        self._status = ttk.Label(filters, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(14, 0))

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        list_pane = ttk.Frame(paned)
        chat_pane = ttk.Frame(paned)
        paned.add(list_pane, weight=2)
        paned.add(chat_pane, weight=3)

        cols = ("started", "direction", "phone", "agent", "queue", "duration", "transcript")
        self.tree = ttk.Treeview(
            list_pane, columns=cols, show="headings", selectmode="browse",
        )
        self.tree.heading("started",   text=t("calls_col_started"))
        self.tree.heading("direction", text=t("calls_col_direction"))
        self.tree.heading("phone",     text=t("calls_col_phone"))
        self.tree.heading("agent",     text=t("calls_col_agent"))
        self.tree.heading("queue",     text=t("calls_col_queue"))
        self.tree.heading("duration",  text=t("calls_col_duration"))
        self.tree.heading("transcript", text=t("calls_col_transcript"))
        self.tree.column("started",   width=140, anchor="w", stretch=False)
        self.tree.column("direction", width=80,  anchor="w", stretch=False)
        self.tree.column("phone",     width=140, anchor="w", stretch=False)
        self.tree.column("agent",     width=160, anchor="w")
        self.tree.column("queue",     width=180, anchor="w")
        self.tree.column("duration",  width=70,  anchor="center", stretch=False)
        self.tree.column("transcript", width=80, anchor="center", stretch=False)
        scl = ttk.Scrollbar(
            list_pane, orient="vertical", command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_call_select)

        # Transcript canvas
        self.chat_canvas = tk.Canvas(chat_pane, bg=BG, highlightthickness=0)
        cscl = ttk.Scrollbar(
            chat_pane, orient="vertical", command=self.chat_canvas.yview,
        )
        self.chat_canvas.configure(yscrollcommand=cscl.set)
        self.chat_canvas.pack(side="left", fill="both", expand=True)
        cscl.pack(side="right", fill="y")
        self.chat_inner = tk.Frame(self.chat_canvas, bg=BG)
        self._chat_win = self.chat_canvas.create_window(
            (0, 0), window=self.chat_inner, anchor="nw",
        )
        self.chat_inner.bind(
            "<Configure>",
            lambda _e: self.chat_canvas.configure(
                scrollregion=self.chat_canvas.bbox("all"),
            ),
        )
        self.chat_canvas.bind(
            "<Configure>",
            lambda e: self.chat_canvas.itemconfig(self._chat_win, width=e.width),
        )
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        self._show_placeholder(t("calls_pick_one"))
        self._reload()

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

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
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception:
            return ""

    @staticmethod
    def _fmt_dur(seconds: int) -> str:
        if not seconds:
            return "—"
        m, s = divmod(int(seconds), 60)
        if m:
            return f"{m}m {s:02d}s"
        return f"{s}s"

    def _period_to_range(self) -> tuple[int, int]:
        kind = next(
            (slug for name, slug in PERIODS if name == self._period_var.get()),
            "24h",
        )
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

    # ------------------------------------------------------------------
    # Reload (network)
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        self._reload_btn.configure(state="disabled")
        self._status.configure(
            text=t("calls_loading"), foreground=META_FG,
        )
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._sel_id = None
        self._calls = []
        self._show_placeholder(t("calls_pick_one"))
        since, until = self._period_to_range()
        threading.Thread(
            target=self._reload_worker, args=(since, until), daemon=True,
        ).start()

    def _reload_worker(self, since_ms: int, until_ms: int) -> None:
        client = WebitelClient(
            self._company.webitel_host, self._company.webitel_access_token,
        )
        try:
            agents = client.list_agents()
        except WebitelError:
            agents = []
        agent_name_by_id = {a.id: a.name for a in agents if a.id}

        calls: list[dict] = []
        fields = (
            "fields=id&fields=created_at&fields=answered_at"
            "&fields=direction&fields=destination&fields=from"
            "&fields=talk_sec&fields=agent_id&fields=queue"
            "&fields=transcripts&fields=files&fields=cause"
        )
        try:
            for page in range(1, self.MAX_PAGES + 1):
                data = client._get(
                    f"/calls/history?size={self.PAGE_SIZE}&page={page}"
                    f"&has_transcript=true"
                    f"&created_at.from={since_ms}&created_at.to={until_ms}"
                    f"&{fields}"
                )
                items = data.get("items") or []
                if not items:
                    break
                calls.extend(items)
                if not data.get("next") or len(items) < self.PAGE_SIZE:
                    break
        except WebitelError as e:
            if not self.winfo_exists():
                return
            self.after(0, lambda: self._on_load_error(str(e)))
            return

        if not self.winfo_exists():
            return
        self.after(
            0,
            lambda: self._on_load_done(calls, agent_name_by_id),
        )

    def _on_load_error(self, err: str) -> None:
        if not self.winfo_exists():
            return
        self._reload_btn.configure(state="normal")
        self._status.configure(
            text=t("calls_err").format(err=err), foreground="#dc2626",
        )

    def _on_load_done(
        self, calls: list[dict], agent_name_by_id: dict[int, str],
    ) -> None:
        if not self.winfo_exists():
            return
        self._calls = calls
        self._agent_name_by_id = agent_name_by_id
        self._reload_btn.configure(state="normal")
        self._apply_filters()

    # ------------------------------------------------------------------
    # Filters / render
    # ------------------------------------------------------------------

    def _selected_direction(self) -> str:
        v = self._dir_var.get()
        for slug, label in self._dir_labels.items():
            if v == label:
                return slug
        return "all"

    def _phone_of(self, call: dict) -> str:
        # outbound: destination is the client; inbound: `from.number` is the client
        direction = (call.get("direction") or "").lower()
        if direction == "outbound":
            return str(call.get("destination") or "")
        frm = call.get("from") or {}
        return str(frm.get("number") or call.get("destination") or "")

    def _agent_label(self, call: dict) -> str:
        aid = call.get("agent_id")
        try:
            aid_int = int(aid) if aid is not None else None
        except (TypeError, ValueError):
            aid_int = None
        if aid_int:
            name = self._agent_name_by_id.get(aid_int)
            return name or f"agent {aid_int}"
        return "—"

    def _matches(self, call: dict) -> bool:
        phone_q = self._phone_var.get().strip()
        if phone_q:
            hay = f"{call.get('destination','')} {(call.get('from') or {}).get('number','')}"
            if phone_q.lower() not in hay.lower():
                return False
        d = self._selected_direction()
        if d != "all":
            if (call.get("direction") or "").lower() != d:
                return False
        return True

    def _apply_filters(self) -> None:
        if not self.winfo_exists():
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        shown = 0
        for c in self._calls:
            if not self._matches(c):
                continue
            cid = str(c.get("id") or "")
            if not cid:
                continue
            started_ms = self._ms(c.get("created_at"))
            transcripts = c.get("transcripts") or []
            tr_mark = "✓" if transcripts else "—"
            queue_name = ((c.get("queue") or {}).get("name") or "")[:60]
            direction = (c.get("direction") or "").lower()
            self.tree.insert(
                "",
                "end",
                iid=cid,
                values=(
                    self._fmt_time(started_ms),
                    direction or "—",
                    self._phone_of(c),
                    self._agent_label(c),
                    queue_name,
                    self._fmt_dur(int(c.get("talk_sec") or 0)),
                    tr_mark,
                ),
                tags=(direction or "unknown",),
            )
            shown += 1
        self.tree.tag_configure("inbound",  foreground="#0f766e")
        self.tree.tag_configure("outbound", foreground="#1d4ed8")
        self.tree.tag_configure("unknown",  foreground=META_FG)
        total = len(self._calls)
        if shown == total:
            text = t("calls_count_all").format(n=total)
        else:
            text = t("calls_count_filtered").format(n=shown, total=total)
        self._status.configure(text=text, foreground=TEXT_FG)

    @staticmethod
    def _ms(v) -> int:
        if v is None or v == "":
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # Transcript pane
    # ------------------------------------------------------------------

    def _clear_chat(self) -> None:
        for w in self.chat_inner.winfo_children():
            w.destroy()

    def _show_placeholder(self, text: str) -> None:
        self._clear_chat()
        tk.Label(self.chat_inner, text=text, fg=META_FG, bg=BG).pack(pady=24)

    def _on_call_select(self, _e: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        cid = sel[0]
        if cid == self._sel_id:
            return
        self._sel_id = cid
        self._show_placeholder(t("calls_loading_transcript"))
        threading.Thread(
            target=self._transcript_worker, args=(cid,), daemon=True,
        ).start()

    def _call_by_id(self, cid: str) -> Optional[dict]:
        for c in self._calls:
            if str(c.get("id") or "") == cid:
                return c
        return None

    def _transcript_worker(self, call_id: str) -> None:
        call = self._call_by_id(call_id)
        transcripts = (call or {}).get("transcripts") or []
        if not transcripts:
            if self.winfo_exists() and self._sel_id == call_id:
                self.after(0, lambda: self._show_placeholder(t("calls_no_transcript")))
            return
        # Use the first transcript (locale is whichever Webitel produced).
        transcript_id = transcripts[0].get("id")
        if not transcript_id:
            if self.winfo_exists() and self._sel_id == call_id:
                self.after(0, lambda: self._show_placeholder(t("calls_no_transcript")))
            return
        client = WebitelClient(
            self._company.webitel_host, self._company.webitel_access_token,
        )
        phrases: list[dict] = []
        try:
            for page in range(1, 10):
                data = client._get(
                    f"/storage/transcript_file/{int(transcript_id)}/phrases"
                    f"?page={page}&size=500"
                )
                items = data.get("items") or []
                if not items:
                    break
                phrases.extend(items)
                if not data.get("next"):
                    break
        except WebitelError as e:
            if self.winfo_exists() and self._sel_id == call_id:
                self.after(0, lambda: self._show_placeholder(
                    t("calls_err").format(err=str(e)),
                ))
            return
        if not self.winfo_exists() or self._sel_id != call_id:
            return
        self.after(0, lambda: self._render_transcript(call or {}, phrases))

    def _render_transcript(self, call: dict, phrases: list[dict]) -> None:
        if not self.winfo_exists():
            return
        self._clear_chat()
        if not phrases:
            tk.Label(
                self.chat_inner, text=t("calls_transcript_empty"),
                fg=META_FG, bg=BG,
            ).pack(pady=24)
            return

        # Decide which `channel` value belongs to the agent. The Webitel
        # convention varies — sometimes `channel` is "0"/"1" (audio stream
        # id), sometimes the operator's full name. We pick whichever channel
        # value appears first in a recording leg that matches the agent
        # heuristically: outbound calls = caller stream is agent, inbound
        # = caller stream is client.
        direction = (call.get("direction") or "").lower()
        channels = []
        for p in phrases:
            ch = p.get("channel")
            if ch is None:
                ch_norm = "0"
            else:
                ch_norm = str(ch)
            if ch_norm not in channels:
                channels.append(ch_norm)
        # When two channels exist, the first one to appear is typically the
        # caller side. For outbound calls the caller is our agent; for
        # inbound — the client.
        agent_channel: Optional[str] = None
        if len(channels) >= 2:
            agent_channel = channels[0] if direction == "outbound" else channels[1]
        elif len(channels) == 1:
            agent_channel = channels[0] if direction == "outbound" else None

        head_meta = []
        head_meta.append(self._fmt_time(self._ms(call.get("created_at"))))
        head_meta.append((call.get("direction") or "—"))
        head_meta.append(self._phone_of(call))
        head_meta.append(self._agent_label(call))
        head_meta.append(self._fmt_dur(int(call.get("talk_sec") or 0)))
        tk.Label(
            self.chat_inner,
            text="  ·  ".join(head_meta),
            fg=META_FG, bg=BG,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(8, 6))

        for ph in phrases:
            ch = ph.get("channel")
            ch_norm = "0" if ch is None else str(ch)
            is_agent = (
                agent_channel is not None and ch_norm == agent_channel
            )
            text = str(ph.get("phrase") or "").strip()
            if not text:
                continue
            start = float(ph.get("start_sec") or 0.0)
            row_frame = tk.Frame(self.chat_inner, bg=BG)
            row_frame.pack(fill="x", padx=12, pady=2)
            bg = AGENT_BG if is_agent else CLIENT_BG
            side = "right" if is_agent else "left"
            anchor = "e" if is_agent else "w"
            speaker = (
                t("calls_speaker_agent")
                if is_agent else t("calls_speaker_client")
            )
            bubble = tk.Frame(row_frame, bg=bg)
            bubble.pack(side=side, anchor=anchor)
            tk.Label(
                bubble,
                text=f"{speaker} · {self._fmt_sec(start)}",
                bg=bg, fg=META_FG,
                font=("Segoe UI", 8),
            ).pack(anchor="w", padx=10, pady=(4, 0))
            tk.Label(
                bubble,
                text=text,
                bg=bg, fg=TEXT_FG,
                wraplength=520,
                justify="left",
                font=("Segoe UI", 10),
            ).pack(anchor="w", padx=10, pady=(0, 6))

        self.update_idletasks()
        self.chat_canvas.yview_moveto(0.0)

    @staticmethod
    def _fmt_sec(start_sec: float) -> str:
        s = max(0.0, float(start_sec))
        m, rem = divmod(s, 60)
        return f"{int(m):02d}:{rem:05.2f}"
