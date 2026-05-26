"""Per-company viewer of ElevenLabs voice-bot conversations.

Lists recent conversations for the company's voice agent (agent_id from
`data/voice_bot_config/<COMPANY>.json`, set on the «Промпты» tab). Double-
clicking a row opens a detail window with the full transcript, the
parameters the agent sent into the `save_call_result` webhook (and the
HTTP status the CRM replied), and the call metadata. Read-only.

Wired into [app/ui/bot_panel.py](bot_panel.py) under `kind == "voice"`.
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..data import Company
from ..elevenlabs import (
    ElevenLabsError,
    extract_save_call_result_from_transcript,
    get_conversation,
    get_elevenlabs_key,
    list_conversations,
)
from ..i18n import t
from ..sectors import DEFAULT_SECTOR, SECTORS
from ..voice_bot_config import load_config
from .colors import ERR_FG, META_FG, OK_FG, TBD_FG, TEXT_FG


def _fmt_time(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    try:
        return _dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "—"


def _fmt_duration(secs: Optional[int]) -> str:
    if not secs:
        return "—"
    try:
        s = int(secs)
    except (ValueError, TypeError):
        return "—"
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60:02d}s"


class VoiceBotConversationsPanel(ttk.Frame):
    """List recent ElevenLabs conversations for this company's agent."""

    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        cfg = load_config(company.key, self._sector)
        self._agent_id: str = str(cfg.get("elevenlabs_agent_id") or "").strip()
        # Detail cache: conversation_id → full detail dict (avoids re-pulling
        # when the operator reopens the same row).
        self._detail_cache: dict[str, dict] = {}

        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})  ·  {t('sector_' + self._sector)}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        if not self._agent_id:
            ttk.Label(
                self,
                text=t("voice_bot_conv_no_agent"),
                foreground=TBD_FG,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=14, pady=12)
            return

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(
            toolbar,
            text=f"agent_id: {self._agent_id}",
            foreground=META_FG,
            font=("Consolas", 9),
        ).pack(side="left")
        self._refresh_btn = ttk.Button(
            toolbar,
            text=t("voice_bot_conv_refresh"),
            command=self._refresh,
            style="Accent.TButton",
        )
        self._refresh_btn.pack(side="left", padx=(12, 0))
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        cols = ("start", "duration", "status", "successful", "summary")
        self.tree = ttk.Treeview(
            self, columns=cols, show="headings", selectmode="browse",
        )
        self.tree.heading("start", text=t("voice_bot_conv_col_start"))
        self.tree.heading("duration", text=t("voice_bot_conv_col_duration"))
        self.tree.heading("status", text=t("voice_bot_conv_col_status"))
        self.tree.heading("successful", text=t("voice_bot_conv_col_successful"))
        self.tree.heading("summary", text=t("voice_bot_conv_col_summary"))
        self.tree.column("start", width=160, anchor="w")
        self.tree.column("duration", width=80, anchor="w")
        self.tree.column("status", width=90, anchor="w")
        self.tree.column("successful", width=110, anchor="w")
        self.tree.column("summary", width=600, anchor="w")
        scl = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        scl.pack(side="right", fill="y", pady=(0, 12))

        self.tree.tag_configure("ok", foreground=OK_FG)
        self.tree.tag_configure("fail", foreground=ERR_FG)
        self.tree.tag_configure("unknown", foreground=META_FG)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

        # iid → conversation_id (Treeview iids may not equal cid because
        # cid can contain characters Tk doesn't love; we just map).
        self._iid_to_cid: dict[str, str] = {}
        self._cid_to_meta: dict[str, dict] = {}

        # Auto-load on open.
        self._refresh()

    # ------------------------------------------------------------------
    # List loading
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        self._refresh_btn.configure(state="disabled")
        self._status.configure(
            text=t("voice_bot_conv_loading"), foreground=META_FG,
        )
        threading.Thread(target=self._list_worker, daemon=True).start()

    def _list_worker(self) -> None:
        try:
            resp = list_conversations(
                agent_id=self._agent_id,
                page_size=50,
                api_key=get_elevenlabs_key(self._company.key),
            )
            convos = resp.get("conversations") or []
            err: Optional[str] = None
        except ElevenLabsError as exc:
            convos, err = [], str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_list(convos, err))

    def _render_list(
        self, convos: list[dict], err: Optional[str],
    ) -> None:
        self._refresh_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            return
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._iid_to_cid.clear()
        self._cid_to_meta.clear()
        for c in convos:
            cid = c.get("conversation_id") or ""
            if not cid:
                continue
            start = _fmt_time(c.get("start_time_unix_secs"))
            duration = _fmt_duration(c.get("call_duration_secs"))
            status = str(c.get("status") or "—")
            successful = str(c.get("call_successful") or "—")
            summary = (c.get("transcript_summary") or "").replace("\n", " ")
            if len(summary) > 200:
                summary = summary[:197] + "…"
            tag = (
                "ok" if successful == "success"
                else "fail" if successful == "failure"
                else "unknown"
            )
            iid = self.tree.insert(
                "", "end",
                values=(start, duration, status, successful, summary),
                tags=(tag,),
            )
            self._iid_to_cid[iid] = cid
            self._cid_to_meta[cid] = c
        self._status.configure(
            text=t("voice_bot_conv_loaded").format(n=len(self._iid_to_cid)),
            foreground=OK_FG,
        )

    # ------------------------------------------------------------------
    # Detail window
    # ------------------------------------------------------------------

    def _on_double_click(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        cid = self._iid_to_cid.get(sel[0])
        if not cid:
            return
        meta = self._cid_to_meta.get(cid) or {}
        if cid in self._detail_cache:
            self._open_detail_window(cid, meta, self._detail_cache[cid], None)
            return
        # Loading toplevel
        self._status.configure(
            text=t("voice_bot_conv_loading_detail").format(cid=cid),
            foreground=META_FG,
        )
        threading.Thread(
            target=self._detail_worker, args=(cid, meta), daemon=True,
        ).start()

    def _detail_worker(self, cid: str, meta: dict) -> None:
        try:
            det = get_conversation(
                cid, api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            det, err = {}, str(exc)
        if not self.winfo_exists():
            return
        if err is None:
            self._detail_cache[cid] = det
        self.after(0, lambda: self._open_detail_window(cid, meta, det, err))

    def _open_detail_window(
        self, cid: str, meta: dict, det: dict, err: Optional[str],
    ) -> None:
        self._status.configure(text="", foreground=META_FG)
        if err:
            messagebox.showerror(
                t("voice_bot_conv_detail_title"), err,
                parent=self.winfo_toplevel(),
            )
            return
        ConversationDetailWindow(
            self.winfo_toplevel(), cid=cid, meta=meta, detail=det,
        )


class ConversationDetailWindow(tk.Toplevel):
    """Modal-ish window with metadata + transcript + tool calls."""

    def __init__(
        self, master: tk.Misc, *, cid: str, meta: dict, detail: dict,
    ) -> None:
        super().__init__(master)
        self.title(t("voice_bot_conv_detail_title") + f" — {cid}")
        self.geometry("1100x720")
        self.transient(master)

        cmeta = detail.get("metadata") or {}
        analysis = detail.get("analysis") or {}

        # Top: metadata grid
        header = ttk.Frame(self, padding=10)
        header.pack(fill="x")
        rows = [
            (t("voice_bot_conv_meta_cid"), cid),
            (t("voice_bot_conv_meta_agent"),
             f"{detail.get('agent_name') or '—'}  ({detail.get('agent_id') or '—'})"),
            (t("voice_bot_conv_meta_start"),
             _fmt_time(cmeta.get("start_time_unix_secs") or meta.get("start_time_unix_secs"))),
            (t("voice_bot_conv_meta_duration"),
             _fmt_duration(cmeta.get("call_duration_secs") or meta.get("call_duration_secs"))),
            (t("voice_bot_conv_meta_status"),
             str(detail.get("status") or meta.get("status") or "—")),
            (t("voice_bot_conv_meta_successful"),
             str(analysis.get("call_successful") or meta.get("call_successful") or "—")),
            (t("voice_bot_conv_meta_termination"),
             str(cmeta.get("termination_reason") or "—")),
            (t("voice_bot_conv_meta_error"),
             str(cmeta.get("error") or "—")),
        ]
        for i, (k, v) in enumerate(rows):
            ttk.Label(header, text=k + ":", foreground=META_FG).grid(
                row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 8), pady=2,
            )
            ttk.Label(
                header, text=str(v), foreground=TEXT_FG,
                wraplength=420, justify="left",
            ).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 24), pady=2,
            )

        # Notebook with Transcript / Save call result / Raw JSON
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        nb.add(self._build_transcript_tab(nb, detail), text=t("voice_bot_conv_tab_transcript"))
        nb.add(
            self._build_save_call_result_tab(nb, detail),
            text=t("voice_bot_conv_tab_save_result"),
        )
        nb.add(self._build_summary_tab(nb, analysis), text=t("voice_bot_conv_tab_summary"))
        nb.add(self._build_raw_tab(nb, detail), text=t("voice_bot_conv_tab_raw"))

        ttk.Button(self, text=t("btn_close"), command=self.destroy).pack(
            side="right", padx=10, pady=(0, 10),
        )

    # ---- Tabs ----

    def _build_transcript_tab(self, parent: tk.Misc, det: dict) -> tk.Frame:
        f = ttk.Frame(parent)
        txt = tk.Text(f, wrap="word", font=("Segoe UI", 10))
        scl = ttk.Scrollbar(f, command=txt.yview)
        txt.configure(yscrollcommand=scl.set)
        txt.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")

        txt.tag_configure("role_agent", foreground="#1d4ed8", font=("Segoe UI", 10, "bold"))
        txt.tag_configure("role_user", foreground="#16a34a", font=("Segoe UI", 10, "bold"))
        txt.tag_configure("role_other", foreground=META_FG, font=("Segoe UI", 10, "bold"))
        txt.tag_configure("toolcall", foreground="#a16207", font=("Consolas", 9))
        txt.tag_configure("meta", foreground=META_FG, font=("Segoe UI", 9, "italic"))

        for turn in det.get("transcript") or []:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "?")
            tag = (
                "role_agent" if role == "agent"
                else "role_user" if role == "user"
                else "role_other"
            )
            tsecs = turn.get("time_in_call_secs")
            time_label = f"[{int(tsecs)}s] " if isinstance(tsecs, (int, float)) else ""
            txt.insert("end", f"{time_label}{role.upper()}:\n", tag)
            msg = turn.get("message") or ""
            if msg:
                txt.insert("end", f"  {msg}\n", "")
            for tc in turn.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                tname = tc.get("tool_name") or tc.get("name") or "?"
                params_raw = tc.get("params_as_json") or tc.get("parameters") or ""
                if isinstance(params_raw, str):
                    try:
                        params_pretty = json.dumps(
                            json.loads(params_raw), ensure_ascii=False, indent=2,
                        )
                    except (ValueError, TypeError):
                        params_pretty = params_raw
                else:
                    params_pretty = json.dumps(
                        params_raw, ensure_ascii=False, indent=2,
                    )
                txt.insert(
                    "end",
                    f"  → tool_call: {tname}\n{params_pretty}\n",
                    "toolcall",
                )
            for tr in turn.get("tool_results") or []:
                if not isinstance(tr, dict):
                    continue
                code = tr.get("response_status_code") or tr.get("status_code") or "—"
                body = tr.get("result_value") or tr.get("response") or tr.get("body") or ""
                if isinstance(body, (dict, list)):
                    body = json.dumps(body, ensure_ascii=False, indent=2)
                txt.insert(
                    "end",
                    f"  ← tool_result HTTP {code}\n{body}\n",
                    "toolcall",
                )
            txt.insert("end", "\n")
        txt.configure(state="disabled")
        return f

    def _build_save_call_result_tab(self, parent: tk.Misc, det: dict) -> tk.Frame:
        f = ttk.Frame(parent, padding=10)
        scr = extract_save_call_result_from_transcript(det)
        if not scr:
            ttk.Label(
                f, text=t("voice_bot_conv_no_save_call_result"),
                foreground=TBD_FG, wraplength=900, justify="left",
            ).pack(anchor="w")
            return f
        ttk.Label(
            f,
            text=t("voice_bot_conv_save_call_result_header"),
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        status_code = scr.get("status_code")
        status_color = (
            OK_FG if isinstance(status_code, int) and 200 <= status_code < 300
            else ERR_FG if isinstance(status_code, int)
            else META_FG
        )
        ttk.Label(
            f, text=f"HTTP {status_code}",
            foreground=status_color, font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            f, text=t("voice_bot_conv_save_call_result_params"),
            foreground=META_FG,
        ).pack(anchor="w")
        params_txt = tk.Text(f, height=14, wrap="word", font=("Consolas", 9))
        params_txt.pack(fill="x", pady=(2, 8))
        params_txt.insert(
            "1.0",
            json.dumps(scr.get("params") or {}, ensure_ascii=False, indent=2),
        )
        params_txt.configure(state="disabled")

        if scr.get("response"):
            ttk.Label(
                f, text=t("voice_bot_conv_save_call_result_response"),
                foreground=META_FG,
            ).pack(anchor="w")
            resp_txt = tk.Text(f, height=8, wrap="word", font=("Consolas", 9))
            resp_txt.pack(fill="both", expand=True, pady=(2, 0))
            body = scr.get("response")
            if isinstance(body, (dict, list)):
                body_str = json.dumps(body, ensure_ascii=False, indent=2)
            else:
                body_str = str(body)
            resp_txt.insert("1.0", body_str)
            resp_txt.configure(state="disabled")
        return f

    def _build_summary_tab(self, parent: tk.Misc, analysis: dict) -> tk.Frame:
        f = ttk.Frame(parent, padding=10)
        title = analysis.get("call_summary_title") or "—"
        ttk.Label(
            f, text=title, font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        summary = analysis.get("transcript_summary") or "(empty)"
        sw = tk.Text(f, wrap="word", font=("Segoe UI", 10), height=12)
        sw.insert("1.0", summary)
        sw.configure(state="disabled")
        sw.pack(fill="x", pady=(0, 12))

        ttk.Label(
            f, text=t("voice_bot_conv_data_collection"),
            font=("Segoe UI", 9, "bold"), foreground=META_FG,
        ).pack(anchor="w")
        dc = analysis.get("data_collection_results_list") or []
        if not dc:
            ttk.Label(
                f, text=t("voice_bot_conv_no_data_collection"),
                foreground=TBD_FG,
            ).pack(anchor="w", pady=(2, 0))
        else:
            dc_txt = tk.Text(f, wrap="word", font=("Consolas", 9), height=10)
            dc_txt.insert(
                "1.0",
                json.dumps(dc, ensure_ascii=False, indent=2),
            )
            dc_txt.configure(state="disabled")
            dc_txt.pack(fill="both", expand=True, pady=(2, 0))
        return f

    def _build_raw_tab(self, parent: tk.Misc, det: dict) -> tk.Frame:
        f = ttk.Frame(parent)
        txt = tk.Text(f, wrap="none", font=("Consolas", 9))
        scl_y = ttk.Scrollbar(f, orient="vertical", command=txt.yview)
        scl_x = ttk.Scrollbar(f, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=scl_y.set, xscrollcommand=scl_x.set)
        txt.grid(row=0, column=0, sticky="nsew")
        scl_y.grid(row=0, column=1, sticky="ns")
        scl_x.grid(row=1, column=0, sticky="ew")
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        txt.insert("1.0", json.dumps(det, ensure_ascii=False, indent=2))
        txt.configure(state="disabled")
        return f
