"""Per-company viewer + editor of the voice-bot CRM-result registration tool.

Shows the structure of `data/voice_bot_tools/<COMPANY>/save_call_result.json`
(ElevenLabs webhook tool) as a hierarchy on the left, and per-node editor
on the right. Save button appears at the top of the editor whenever the
operator changes something; click → JSON file is rewritten on disk and
the tree is re-rendered to reflect new values.

Editable per node kind:

* Endpoint URL row     → `api_schema.url`
* Header row           → header value (and name) under `api_schema.request_headers[]`
* Constant property    → `constant_value`, `required`
* Dynamic-var property → `dynamic_variable` (free text), `required`
* LLM-prompt property  → `description` (multiline), `enum` (one per line), `required`
* Enum-value leaf      → read-only (edit at parent property level — the
                         description holds all per-value bullets)
* Section header       → not editable

For PE_ the LLM branching tree (which contact_result values are valid
under each contact_type) is hardcoded in `PE_CONTACT_RESULT_TREE` below;
other companies fall back to a flat per-LLM-field render.
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Optional

from ..data import Company
from ..elevenlabs import (
    ElevenLabsError,
    extract_tool_meta,
    get_elevenlabs_key,
    get_tool,
    list_tools,
    set_elevenlabs_key,
    update_tool,
)
from ..i18n import t
from ..paths import data_dir
from ..sectors import DEFAULT_SECTOR, SECTORS
from ..voice_bot_config import get_tool_id, set_tool_id_override
from .colors import ERR_FG, META_FG, OK_FG, TBD_FG, TEXT_FG


PE_CONTACT_RESULT_TREE: dict[str, list[str]] = {
    "contact_client": [
        "result_promise_of_payment",
        "result_refusal_to_pay",
        "result_paid_according_to_the_client",
        "result_call_back_later",
        "result_hung_up",
    ],
    "contact_third_party": [
        "result_will_transmit_information",
        "result_refusal_to_transfer_information",
        "result_hung_up",
        "result_does_not_know_the_client",
    ],
    "contact_unknown": [
        "result_hung_up",
        "result_call_back_later",
    ],
    "contact_negative": [
        "result_phone_out_of_reach",
        "result_number_is_invalid",
        "result_voicemail",
        "result_no_answer",
        "result_silence",
        "result_busy",
        "result_drop",
    ],
}


HIERARCHIES: dict[str, dict] = {
    "PE_": {
        "contact_result_tree": PE_CONTACT_RESULT_TREE,
        "promise_under": ("contact_client", "result_promise_of_payment"),
        "tail_fields": ["promise_date", "promise_amount", "comment"],
    },
}


def _tool_file(
    company_key: str, sector: str = DEFAULT_SECTOR,
) -> Path:
    return (
        data_dir()
        / "voice_bot_tools" / company_key / sector / "save_call_result.json"
    )


def _legacy_tool_file(company_key: str) -> Path:
    """Pre-sector path. Kept for one-shot migration."""
    return (
        data_dir()
        / "voice_bot_tools" / company_key / "save_call_result.json"
    )


def _migrate_legacy_tool(company_key: str) -> None:
    legacy = _legacy_tool_file(company_key)
    if not legacy.exists() or legacy.is_dir():
        return
    target = _tool_file(company_key, DEFAULT_SECTOR)
    if target.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(target)
    except OSError:
        pass


def _load_tool(
    company_key: str, sector: str = DEFAULT_SECTOR,
) -> Optional[dict]:
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    _migrate_legacy_tool(company_key)
    p = _tool_file(company_key, sector)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_tool(
    company_key: str, tool: dict, sector: str = DEFAULT_SECTOR,
) -> None:
    """Write `tool` back to ``data/voice_bot_tools/<COMPANY>/<sector>/save_call_result.json``,
    creating parent dirs as needed. Pretty-printed UTF-8, no ASCII escapes."""
    if sector not in SECTORS:
        sector = DEFAULT_SECTOR
    p = _tool_file(company_key, sector)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(tool, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _props_by_id(tool: dict) -> dict[str, dict]:
    schema = (tool.get("api_schema") or {}).get("request_body_schema") or {}
    props = schema.get("properties") or []
    return {p.get("id"): p for p in props if isinstance(p, dict) and p.get("id")}


class VoiceBotResultsPanel(ttk.Frame):
    """Hierarchical viewer + per-node editor for save_call_result tool."""

    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        self._tool: Optional[dict] = _load_tool(company.key, self._sector)
        self._props: dict[str, dict] = _props_by_id(self._tool) if self._tool else {}
        # iid → payload dict ({"kind": ..., "title": ..., "ref": ..., ...})
        self._iid_payload: dict[str, dict] = {}
        # Stable key (unique-per-node) of currently shown payload; we use it
        # to re-select the same node after a tree refresh.
        self._current_key: Optional[str] = None
        # Per-editor state: list of dicts {var, getter, applier}.
        self._editors: list[dict] = []
        # Dirty flag — true when any editor widget changed value.
        self._dirty: bool = False

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

        # ---- Top toolbar (panel-wide actions) — всегда видим, даже когда
        #      локального снапшота tool'а ещё нет: пикер должен быть
        #      доступен для bootstrap'а.
        tool_id = get_tool_id(company.key, self._sector, "save_call_result")
        self._tool_id = tool_id
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 8))
        self._tool_id_var = tk.StringVar(
            value=f"tool_id: {tool_id}" if tool_id
            else t("voice_bot_results_no_tool_id"),
        )
        ttk.Label(
            toolbar,
            textvariable=self._tool_id_var,
            foreground=META_FG if tool_id else TBD_FG,
            font=("Consolas", 9),
        ).pack(side="left")
        if tool_id and self._tool:
            self._push_btn = ttk.Button(
                toolbar,
                text=t("voice_bot_results_push"),
                command=self._push_tool,
                style="Accent.TButton",
            )
            self._push_btn.pack(side="left", padx=(12, 0))
        else:
            self._push_btn = None
        ttk.Button(
            toolbar,
            text=t("voice_bot_results_pick_tool"),
            command=self._pick_tool_dialog,
        ).pack(side="left", padx=(6, 0))
        if self._tool:
            ttk.Button(
                toolbar,
                text=t("voice_bot_results_copy_json"),
                command=self._copy_json,
            ).pack(side="left", padx=(6, 0))
        # Кнопка «Ключ ElevenLabs для <COMPANY>» убрана: ключ один на все
        # проекты (задаётся через Promts → API ключ ElevenLabs), per-company
        # override в `data/api_keys.json:elevenlabs_by_company` остаётся
        # как fallback, но из UI больше не предлагаем.
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        if not self._tool:
            ttk.Label(
                self,
                text=t("voice_bot_results_no_file").format(
                    path=str(_tool_file(company.key, self._sector)),
                ),
                foreground=TBD_FG,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=14, pady=12)
            ttk.Label(
                self,
                text=t("voice_bot_results_no_file_hint"),
                foreground=META_FG,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=14, pady=(0, 12))
            return

        # ---- Body: left tree | right editor ----
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(body)
        body.add(left, weight=1)
        right = ttk.Frame(body)
        body.add(right, weight=1)

        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.tag_configure(
            "section", foreground="#1d4ed8", font=("Segoe UI", 9, "bold"),
        )
        self.tree.tag_configure("const", foreground=TEXT_FG)
        self.tree.tag_configure("dyn", foreground="#16a34a")
        self.tree.tag_configure("field", foreground="#1d4ed8")
        self.tree.tag_configure("enum", foreground=TEXT_FG)
        self.tree.tag_configure("tbd", foreground=TBD_FG)
        scl = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right pane header row: detail label + Save button (hidden initially)
        right_header = ttk.Frame(right)
        right_header.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(
            right_header, text=t("voice_bot_results_detail_header"),
            foreground=META_FG,
        ).pack(side="left")
        self._save_btn = ttk.Button(
            right_header,
            text=t("voice_bot_results_save_edits"),
            command=self._save_edits,
            style="Accent.TButton",
        )
        # Don't pack yet — appears on first dirty change.
        self._save_btn_packed = False

        self._detail_title = ttk.Label(
            right, text="", font=("Segoe UI", 10, "bold"),
            wraplength=600, justify="left",
        )
        self._detail_title.pack(anchor="w", padx=8, pady=(0, 4))
        # Editor area — replaced per node selection.
        self._editor_frame = ttk.Frame(right)
        self._editor_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._render_tree()

    # ------------------------------------------------------------------
    # Tree rendering (left side)
    # ------------------------------------------------------------------

    def _render_tree(self) -> None:
        assert self._tool is not None
        # Reset state
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._iid_payload.clear()
        # Re-derive props in case body schema mutated.
        self._props = _props_by_id(self._tool)

        schema = self._tool.get("api_schema") or {}

        # 1. Endpoint section
        ep_iid = self.tree.insert(
            "", "end",
            text=f"📡  {t('voice_bot_results_section_endpoint')}",
            tags=("section",), open=True,
        )
        self._add_payload(
            ep_iid,
            kind="section",
            title=t("voice_bot_results_section_endpoint"),
            stable_key="section_endpoint",
        )
        url = schema.get("url") or ""
        method = schema.get("method") or "POST"
        url_iid = self.tree.insert(
            ep_iid, "end", text=f"{method}  {url or '—'}", tags=("const",),
        )
        self._add_payload(
            url_iid,
            kind="endpoint_url",
            title=t("voice_bot_results_section_endpoint"),
            stable_key="endpoint_url",
        )
        headers = schema.get("request_headers")
        if isinstance(headers, list):
            for i, h in enumerate(headers):
                if not isinstance(h, dict):
                    continue
                name = h.get("name") or "—"
                val = h.get("value") or ""
                h_iid = self.tree.insert(
                    ep_iid, "end", text=f"{name}: {val}", tags=("const",),
                )
                self._add_payload(
                    h_iid,
                    kind="header",
                    title=f"Header: {name}",
                    header_index=i,
                    stable_key=f"header_{i}_{name}",
                )

        # 2. Constants section
        const_props = [
            p for p in self._props.values() if p.get("value_type") == "constant"
        ]
        if const_props:
            c_iid = self.tree.insert(
                "", "end",
                text=f"🔒  {t('voice_bot_results_section_constants')}",
                tags=("section",), open=True,
            )
            self._add_payload(
                c_iid, kind="section",
                title=t("voice_bot_results_section_constants"),
                stable_key="section_constants",
            )
            for p in const_props:
                pid = p.get("id") or ""
                label = f"{pid} = {p.get('constant_value') or ''}"
                p_iid = self.tree.insert(
                    c_iid, "end", text=label, tags=("const",),
                )
                self._add_payload(
                    p_iid, kind="property",
                    title=pid,
                    property_id=pid,
                    stable_key=f"prop_{pid}",
                )

        # 3. Dynamic-variable section
        dyn_props = [
            p for p in self._props.values()
            if p.get("value_type") == "dynamic_variable"
        ]
        if dyn_props:
            d_iid = self.tree.insert(
                "", "end",
                text=f"🔗  {t('voice_bot_results_section_dynamic')}",
                tags=("section",), open=True,
            )
            self._add_payload(
                d_iid, kind="section",
                title=t("voice_bot_results_section_dynamic"),
                stable_key="section_dynamic",
            )
            for p in dyn_props:
                pid = p.get("id") or ""
                label = (
                    f"{pid}  ←  {{{{ {p.get('dynamic_variable') or ''} }}}}"
                )
                p_iid = self.tree.insert(
                    d_iid, "end", text=label, tags=("dyn",),
                )
                self._add_payload(
                    p_iid, kind="property",
                    title=pid,
                    property_id=pid,
                    stable_key=f"prop_{pid}",
                )

        # 4. LLM-filled fields section
        llm_props = [
            p for p in self._props.values() if p.get("value_type") == "llm_prompt"
        ]
        if llm_props:
            l_iid = self.tree.insert(
                "", "end",
                text=f"🌳  {t('voice_bot_results_section_llm')}",
                tags=("section",), open=True,
            )
            self._add_payload(
                l_iid, kind="section",
                title=t("voice_bot_results_section_llm"),
                stable_key="section_llm",
            )
            hierarchy = HIERARCHIES.get(self._company.key)
            if hierarchy:
                self._render_branching(l_iid, hierarchy)
            else:
                for p in llm_props:
                    self._render_flat_field(l_iid, p)

    def _render_branching(self, parent: str, hierarchy: dict) -> None:
        contact_type_prop = self._props.get("contact_type") or {}
        contact_result_prop = self._props.get("contact_result") or {}
        promise_type_prop = self._props.get("promise_type") or {}

        ct_iid = self.tree.insert(
            parent, "end",
            text="📋  contact_type",
            tags=("field",), open=True,
        )
        self._add_payload(
            ct_iid, kind="property",
            title="contact_type",
            property_id="contact_type",
            stable_key="prop_contact_type",
        )

        tree_map: dict[str, list[str]] = hierarchy.get("contact_result_tree") or {}
        promise_under = hierarchy.get("promise_under")
        promise_enum = list(promise_type_prop.get("enum") or [])

        for ct_value in contact_type_prop.get("enum") or []:
            ct_node = self.tree.insert(
                ct_iid, "end",
                text=f"▸  {ct_value}",
                tags=("enum",), open=False,
            )
            self._add_payload(
                ct_node, kind="enum_value",
                title=ct_value,
                property_id="contact_type",
                value=ct_value,
                stable_key=f"enum_contact_type_{ct_value}",
            )
            cr_iid = self.tree.insert(
                ct_node, "end",
                text="📋  contact_result",
                tags=("field",), open=True,
            )
            self._add_payload(
                cr_iid, kind="property",
                title="contact_result",
                property_id="contact_result",
                stable_key=f"prop_contact_result_under_{ct_value}",
            )
            for cr_value in tree_map.get(ct_value, []):
                cr_node = self.tree.insert(
                    cr_iid, "end",
                    text=f"▸  {cr_value}",
                    tags=("enum",), open=False,
                )
                self._add_payload(
                    cr_node, kind="enum_value",
                    title=cr_value,
                    property_id="contact_result",
                    value=cr_value,
                    stable_key=f"enum_contact_result_{ct_value}_{cr_value}",
                )
                if promise_under and (ct_value, cr_value) == tuple(promise_under):
                    pt_iid = self.tree.insert(
                        cr_node, "end",
                        text="📋  promise_type",
                        tags=("field",), open=True,
                    )
                    self._add_payload(
                        pt_iid, kind="property",
                        title="promise_type",
                        property_id="promise_type",
                        stable_key="prop_promise_type",
                    )
                    for pt_value in promise_enum:
                        label = pt_value if pt_value else "(empty)"
                        pt_node = self.tree.insert(
                            pt_iid, "end",
                            text=f"▸  {label}",
                            tags=("enum",), open=False,
                        )
                        self._add_payload(
                            pt_node, kind="enum_value",
                            title=label,
                            property_id="promise_type",
                            value=pt_value,
                            stable_key=f"enum_promise_type_{pt_value}",
                        )

        for name in hierarchy.get("tail_fields") or []:
            p = self._props.get(name)
            if not p:
                continue
            iid = self.tree.insert(
                parent, "end",
                text=f"📝  {name}",
                tags=("field",), open=False,
            )
            self._add_payload(
                iid, kind="property",
                title=name,
                property_id=name,
                stable_key=f"prop_{name}",
            )

    def _render_flat_field(self, parent: str, prop: dict) -> None:
        name = prop.get("id") or ""
        iid = self.tree.insert(
            parent, "end",
            text=f"📋  {name}",
            tags=("field",), open=False,
        )
        self._add_payload(
            iid, kind="property",
            title=name,
            property_id=name,
            stable_key=f"prop_{name}",
        )
        for ev in prop.get("enum") or []:
            label = ev if ev else "(empty)"
            ev_iid = self.tree.insert(
                iid, "end",
                text=f"▸  {label}",
                tags=("enum",), open=False,
            )
            self._add_payload(
                ev_iid, kind="enum_value",
                title=label,
                property_id=name,
                value=ev,
                stable_key=f"enum_{name}_{ev}",
            )

    def _add_payload(
        self, iid: str, *, kind: str, title: str,
        stable_key: str,
        property_id: str = "",
        value: str = "",
        header_index: int = -1,
    ) -> None:
        self._iid_payload[iid] = {
            "kind": kind,
            "title": title,
            "stable_key": stable_key,
            "property_id": property_id,
            "value": value,
            "header_index": header_index,
        }

    # ------------------------------------------------------------------
    # Selection → build editor
    # ------------------------------------------------------------------

    def _on_select(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        new_payload = self._iid_payload.get(sel[0])
        if not new_payload:
            return
        # If user has unsaved edits on a previous node, confirm.
        if self._dirty and self._current_key != new_payload["stable_key"]:
            if not messagebox.askyesno(
                t("voice_bot_results_unsaved_title"),
                t("voice_bot_results_unsaved_body"),
                parent=self.winfo_toplevel(),
            ):
                # Re-select the previous iid (best-effort)
                self._reselect_by_stable_key(self._current_key)
                return
            self._set_dirty(False)
        self._current_key = new_payload["stable_key"]
        self._detail_title.configure(text=new_payload.get("title") or "")
        self._build_editor(new_payload)

    def _reselect_by_stable_key(self, key: Optional[str]) -> bool:
        if not key:
            return False
        for iid, payload in self._iid_payload.items():
            if payload.get("stable_key") == key:
                self.tree.selection_set(iid)
                return True
        return False

    # ------------------------------------------------------------------
    # Editor construction (right side)
    # ------------------------------------------------------------------

    def _clear_editor(self) -> None:
        for child in self._editor_frame.winfo_children():
            child.destroy()
        self._editors.clear()

    def _build_editor(self, payload: dict) -> None:
        self._clear_editor()
        kind = payload.get("kind")
        if kind == "section":
            self._build_readonly_text(t("voice_bot_results_section_readonly"))
            return
        if kind == "endpoint_url":
            self._build_endpoint_editor()
            return
        if kind == "header":
            self._build_header_editor(payload.get("header_index", -1))
            return
        if kind == "property":
            self._build_property_editor(payload.get("property_id") or "")
            return
        if kind == "enum_value":
            self._build_enum_value_view(
                payload.get("property_id") or "",
                payload.get("value") or "",
            )
            return
        self._build_readonly_text(f"(unknown kind: {kind})")

    # ---- Read-only display for section / enum-value leaves ----

    def _build_readonly_text(self, text: str) -> None:
        ttk.Label(
            self._editor_frame, text=text, foreground=META_FG,
            wraplength=560, justify="left",
        ).pack(anchor="w", pady=4)

    def _build_enum_value_view(self, property_id: str, value: str) -> None:
        prop = self._props.get(property_id) or {}
        target_key = value if value else "(empty)"
        bullet_text = ""
        desc = prop.get("description") or ""
        for line in desc.split("\n"):
            stripped = line.strip()
            if stripped.startswith(f"- {target_key}:"):
                bullet_text = stripped[len(f"- {target_key}:"):].strip()
                break
        ttk.Label(
            self._editor_frame,
            text=t("voice_bot_results_enum_value_header").format(
                value=target_key, prop=property_id,
            ),
            foreground=META_FG, wraplength=560, justify="left",
        ).pack(anchor="w", pady=(2, 6))
        if bullet_text:
            box = tk.Text(
                self._editor_frame, height=8, wrap="word",
                font=("Segoe UI", 9),
            )
            box.insert("1.0", bullet_text)
            box.configure(state="disabled")
            box.pack(fill="both", expand=False, pady=(0, 6))
        else:
            ttk.Label(
                self._editor_frame,
                text=t("voice_bot_results_enum_value_no_bullet"),
                foreground=TBD_FG, wraplength=560, justify="left",
            ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self._editor_frame,
            text=t("voice_bot_results_enum_value_hint").format(prop=property_id),
            foreground=META_FG, wraplength=560, justify="left",
        ).pack(anchor="w", pady=(4, 0))

    # ---- Endpoint URL editor ----

    def _build_endpoint_editor(self) -> None:
        tool = self._tool or {}
        schema = tool.get("api_schema") or {}
        # Tool-level name (как он называется в ElevenLabs) — нужно менять
        # под каждый тенант (PE_save_call_result → AR1_save_call_result).
        ttk.Label(
            self._editor_frame, text=t("voice_bot_results_tool_name_label"),
            foreground=META_FG,
        ).pack(anchor="w", pady=(0, 2))
        name_var = self._make_var(str(tool.get("name") or ""))
        ttk.Entry(
            self._editor_frame, textvariable=name_var, width=60,
        ).pack(fill="x", pady=(0, 8))
        self._register_editor(
            getter=lambda: name_var.get().strip(),
            applier=lambda v: tool.__setitem__("name", v),
        )
        # Tool-level description (LLM-промт, что делает этот tool).
        ttk.Label(
            self._editor_frame,
            text=t("voice_bot_results_tool_desc_label"),
            foreground=META_FG,
        ).pack(anchor="w", pady=(0, 2))
        tool_desc = tk.Text(
            self._editor_frame, height=4, wrap="word", font=("Segoe UI", 9),
        )
        tool_desc.insert("1.0", str(tool.get("description") or ""))
        tool_desc.pack(fill="x", pady=(0, 8))
        self._bind_text_dirty(tool_desc)
        self._register_editor(
            getter=lambda: tool_desc.get("1.0", "end-1c"),
            applier=lambda v: tool.__setitem__("description", v),
        )

        ttk.Label(
            self._editor_frame, text="url:", foreground=META_FG,
        ).pack(anchor="w", pady=(4, 2))
        url_var = self._make_var(str(schema.get("url") or ""))
        ttk.Entry(
            self._editor_frame, textvariable=url_var, width=80,
        ).pack(fill="x", pady=(0, 8))
        self._register_editor(
            getter=lambda: url_var.get().strip(),
            applier=lambda v: schema.__setitem__("url", v),
        )
        ttk.Label(
            self._editor_frame,
            text=f"method: {schema.get('method') or 'POST'} · content_type: {schema.get('content_type') or '—'}",
            foreground=META_FG,
        ).pack(anchor="w", pady=(0, 4))

    # ---- Header editor ----

    def _build_header_editor(self, header_index: int) -> None:
        schema = (self._tool or {}).get("api_schema") or {}
        headers = schema.get("request_headers")
        if not isinstance(headers, list) or header_index < 0 or header_index >= len(headers):
            self._build_readonly_text("(header missing)")
            return
        header = headers[header_index]
        ttk.Label(
            self._editor_frame, text="name:", foreground=META_FG,
        ).pack(anchor="w", pady=(4, 2))
        name_var = self._make_var(str(header.get("name") or ""))
        ttk.Entry(
            self._editor_frame, textvariable=name_var, width=60,
        ).pack(fill="x", pady=(0, 8))
        self._register_editor(
            getter=lambda: name_var.get().strip(),
            applier=lambda v: header.__setitem__("name", v),
        )
        ttk.Label(
            self._editor_frame, text="value:", foreground=META_FG,
        ).pack(anchor="w", pady=(0, 2))
        val_var = self._make_var(str(header.get("value") or ""))
        ttk.Entry(
            self._editor_frame, textvariable=val_var, width=80,
        ).pack(fill="x", pady=(0, 8))
        self._register_editor(
            getter=lambda: val_var.get(),
            applier=lambda v: header.__setitem__("value", v),
        )

    # ---- Property editor (constant / dynamic / llm_prompt) ----

    def _build_property_editor(self, property_id: str) -> None:
        prop = self._props.get(property_id)
        if not prop:
            self._build_readonly_text(f"(property {property_id} missing)")
            return
        value_type = prop.get("value_type") or "?"

        # Rename — позволяет менять `id` поля (имя property в
        # request_body_schema). Применяется к копии prop в `self._props`
        # И к сырому списку под ``api_schema.request_body_schema.properties``
        # (нужно искать его по старому id, потому что _props — это маппинг
        # `{id → dict}`, который пересоздаётся при render_tree).
        ttk.Label(
            self._editor_frame, text=t("voice_bot_results_prop_id_label"),
            foreground=META_FG,
        ).pack(anchor="w", pady=(0, 2))
        id_var = self._make_var(property_id)
        ttk.Entry(
            self._editor_frame, textvariable=id_var, width=40,
        ).pack(fill="x", pady=(0, 6))
        ttk.Label(
            self._editor_frame, text=t("voice_bot_results_prop_id_hint"),
            foreground=META_FG, wraplength=560, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        def _rename_property(new_id: str) -> None:
            new_id = (new_id or "").strip()
            if not new_id or new_id == property_id:
                return
            schema = ((self._tool or {}).get("api_schema") or {})
            body = schema.get("request_body_schema") or {}
            props_list = body.get("properties") or []
            if isinstance(props_list, list):
                for p in props_list:
                    if isinstance(p, dict) and p.get("id") == property_id:
                        p["id"] = new_id
                        break
            elif isinstance(props_list, dict) and property_id in props_list:
                props_list[new_id] = props_list.pop(property_id)
            # `prop` уже ссылается на тот же dict, что и в props_list —
            # обновляем id в нём же, чтобы было консистентно если рендер
            # не вызвался.
            prop["id"] = new_id

        self._register_editor(
            getter=lambda: id_var.get(),
            applier=_rename_property,
        )

        ttk.Label(
            self._editor_frame,
            text=f"value_type: {value_type}",
            foreground=META_FG,
        ).pack(anchor="w", pady=(4, 6))

        if value_type == "constant":
            ttk.Label(
                self._editor_frame, text="constant_value:", foreground=META_FG,
            ).pack(anchor="w", pady=(0, 2))
            cv_var = self._make_var(str(prop.get("constant_value") or ""))
            ttk.Entry(
                self._editor_frame, textvariable=cv_var, width=60,
            ).pack(fill="x", pady=(0, 8))
            self._register_editor(
                getter=lambda: cv_var.get(),
                applier=lambda v: prop.__setitem__("constant_value", v),
            )
        elif value_type == "dynamic_variable":
            ttk.Label(
                self._editor_frame, text="dynamic_variable:", foreground=META_FG,
            ).pack(anchor="w", pady=(0, 2))
            dv_var = self._make_var(str(prop.get("dynamic_variable") or ""))
            ttk.Entry(
                self._editor_frame, textvariable=dv_var, width=60,
            ).pack(fill="x", pady=(0, 8))
            ttk.Label(
                self._editor_frame,
                text=t("voice_bot_results_dyn_hint"),
                foreground=META_FG, wraplength=560, justify="left",
            ).pack(anchor="w", pady=(0, 8))
            self._register_editor(
                getter=lambda: dv_var.get().strip(),
                applier=lambda v: prop.__setitem__("dynamic_variable", v),
            )
        else:
            # llm_prompt — show description + enum (if any)
            ttk.Label(
                self._editor_frame,
                text=t("voice_bot_results_desc_label"),
                foreground=META_FG,
            ).pack(anchor="w", pady=(0, 2))
            desc_text = tk.Text(
                self._editor_frame, height=14, wrap="word",
                font=("Segoe UI", 9),
            )
            desc_text.insert("1.0", str(prop.get("description") or ""))
            desc_text.pack(fill="both", expand=True, pady=(0, 8))
            self._bind_text_dirty(desc_text)
            self._register_editor(
                getter=lambda: desc_text.get("1.0", "end-1c"),
                applier=lambda v: prop.__setitem__("description", v),
            )

            if isinstance(prop.get("enum"), list):
                ttk.Label(
                    self._editor_frame,
                    text=t("voice_bot_results_enum_label"),
                    foreground=META_FG,
                ).pack(anchor="w", pady=(4, 2))
                # Render enum as one value per line (empty line = "" enum value)
                lines: list[str] = []
                for v in (prop.get("enum") or []):
                    lines.append("" if v == "" else str(v))
                enum_text = tk.Text(
                    self._editor_frame, height=min(10, max(3, len(lines) + 1)),
                    wrap="none", font=("Consolas", 9),
                )
                enum_text.insert("1.0", "\n".join(lines))
                enum_text.pack(fill="x", pady=(0, 4))
                self._bind_text_dirty(enum_text)
                ttk.Label(
                    self._editor_frame,
                    text=t("voice_bot_results_enum_hint"),
                    foreground=META_FG, wraplength=560, justify="left",
                ).pack(anchor="w", pady=(0, 8))

                def _enum_getter() -> list:
                    raw = enum_text.get("1.0", "end-1c")
                    # Preserve empty entries from blank lines (those map to "" enum value).
                    return [line for line in raw.split("\n")]

                self._register_editor(
                    getter=_enum_getter,
                    applier=lambda v: prop.__setitem__("enum", v),
                )

        # Required checkbox for everyone.
        req_var = tk.BooleanVar(value=bool(prop.get("required")))
        req_var.trace_add("write", lambda *_: self._set_dirty(True))
        ttk.Checkbutton(
            self._editor_frame, variable=req_var,
            text=t("voice_bot_results_required_label"),
        ).pack(anchor="w", pady=(4, 4))
        self._register_editor(
            getter=lambda: bool(req_var.get()),
            applier=lambda v: prop.__setitem__("required", v),
        )

    # ---- Editor helpers ----

    def _make_var(self, initial: str) -> tk.StringVar:
        var = tk.StringVar(value=initial)
        var.trace_add("write", lambda *_: self._set_dirty(True))
        return var

    def _bind_text_dirty(self, widget: tk.Text) -> None:
        widget.edit_modified(False)
        def _on_mod(_e: tk.Event) -> None:
            if widget.edit_modified():
                widget.edit_modified(False)
                self._set_dirty(True)
        widget.bind("<<Modified>>", _on_mod)

    def _register_editor(
        self, *, getter: Callable[[], Any], applier: Callable[[Any], None],
    ) -> None:
        self._editors.append({"getter": getter, "applier": applier})

    # ------------------------------------------------------------------
    # Dirty + Save
    # ------------------------------------------------------------------

    def _set_dirty(self, on: bool) -> None:
        self._dirty = on
        if on:
            if not self._save_btn_packed:
                self._save_btn.pack(side="right")
                self._save_btn_packed = True
        else:
            if self._save_btn_packed:
                self._save_btn.pack_forget()
                self._save_btn_packed = False

    def _save_edits(self) -> None:
        if not self._dirty or not self._tool:
            return
        try:
            for ed in self._editors:
                ed["applier"](ed["getter"]())
        except Exception as exc:  # noqa: BLE001 — surface any apply error
            messagebox.showerror(
                t("voice_bot_results_save_edits"), str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        try:
            _save_tool(self._company.key, self._tool, self._sector)
        except OSError as exc:
            messagebox.showerror(
                t("voice_bot_results_save_edits"), str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        self._set_dirty(False)
        # Re-render tree (display might change: constant value labels, headers).
        prev_key = self._current_key
        self._render_tree()
        # Re-select the same logical node. If the stable key disappeared
        # (e.g. enum got renamed), clear the editor so we don't show stale
        # widgets from the previous selection.
        if not self._reselect_by_stable_key(prev_key):
            self._clear_editor()
            self._detail_title.configure(text="")
            self._current_key = None
        self._status.configure(
            text=t("voice_bot_results_save_edits_done"), foreground=OK_FG,
        )

    # ------------------------------------------------------------------
    # ElevenLabs PATCH action
    # ------------------------------------------------------------------

    def _push_tool(self) -> None:
        if not self._tool or not self._tool_id:
            return
        if self._dirty:
            messagebox.showwarning(
                t("voice_bot_results_push"),
                t("voice_bot_results_push_dirty_warning"),
                parent=self.winfo_toplevel(),
            )
            return
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        latest = _load_tool(self._company.key, self._sector)
        if latest is None:
            messagebox.showerror(
                t("voice_bot_results_push"),
                t("voice_bot_results_no_file").format(
                    path=str(_tool_file(self._company.key, self._sector)),
                ),
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            t("voice_bot_results_push"),
            t("voice_bot_results_push_confirm").format(
                tool_id=self._tool_id,
                name=latest.get("name") or "—",
                file=str(_tool_file(self._company.key, self._sector)),
            ),
            parent=self.winfo_toplevel(),
        ):
            return
        self._status.configure(
            text=t("voice_bot_results_pushing"), foreground=META_FG,
        )
        if self._push_btn is not None:
            self._push_btn.configure(state="disabled")
        threading.Thread(
            target=self._push_worker, args=(self._tool_id, latest), daemon=True,
        ).start()

    def _push_worker(self, tool_id: str, body: dict) -> None:
        try:
            update_tool(
                tool_id, body,
                api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            err = str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._apply_pushed(err))

    def _apply_pushed(self, err: Optional[str]) -> None:
        if self._push_btn is not None:
            self._push_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_results_push"), err,
                parent=self.winfo_toplevel(),
            )
            return
        self._status.configure(
            text=t("voice_bot_results_pushed"), foreground=OK_FG,
        )
        # Event-trigger: алерт о применённой правке tool в проде.
        try:
            from ..voice_bot_alerts import dispatch_tool_pushed_alert
            dispatch_tool_pushed_alert(
                self._company, self._sector,
                tool_id=self._tool_id or "",
                tool=self._tool or {},
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[voice_bot_results_panel] tool-pushed alert failed: {exc}")

    # ------------------------------------------------------------------
    # Per-company key dialog
    # ------------------------------------------------------------------

    def _set_company_key(self) -> None:
        company_key = self._company.key
        company_label = company_key.rstrip("_")
        current = get_elevenlabs_key(company_key)
        global_key = get_elevenlabs_key()
        is_per_company = bool(current) and current != global_key
        hint = t("voice_bot_results_set_key_dialog_help").format(
            company=company_label,
            status=(
                t("voice_bot_results_set_key_status_per_company")
                if is_per_company
                else t("voice_bot_results_set_key_status_fallback_global")
                if current
                else t("voice_bot_results_set_key_status_none")
            ),
            shown=(
                (current[:8] + "…" + current[-4:]) if current else "—"
            ),
        )
        new = simpledialog.askstring(
            t("voice_bot_results_set_key").format(company=company_label),
            hint,
            parent=self.winfo_toplevel(),
            initialvalue=(current if is_per_company else ""),
            show="*",
        )
        if new is None:
            return
        set_elevenlabs_key(new.strip(), company_key=company_key)
        if new.strip():
            self._status.configure(
                text=t("voice_bot_results_key_saved").format(
                    company=company_label,
                ),
                foreground=OK_FG,
            )
        else:
            self._status.configure(
                text=t("voice_bot_results_key_cleared").format(
                    company=company_label,
                ),
                foreground=OK_FG,
            )

    # ------------------------------------------------------------------
    # Copy JSON to clipboard
    # ------------------------------------------------------------------

    def _copy_json(self) -> None:
        path = _tool_file(self._company.key, self._sector)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._status.configure(text=str(exc), foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_results_copy_json"), str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        top = self.winfo_toplevel()
        top.clipboard_clear()
        top.clipboard_append(text)
        top.update()
        self._status.configure(
            text=t("voice_bot_results_copied").format(n=len(text)),
            foreground=OK_FG,
        )

    # ------------------------------------------------------------------
    # Pick tool from workspace
    # ------------------------------------------------------------------

    def _pick_tool_dialog(self) -> None:
        """Список tool'ов воркспейса → выбор → запись override + fetch
        body + перерисовка дерева."""
        if self._dirty:
            messagebox.showwarning(
                t("voice_bot_results_pick_tool"),
                t("voice_bot_results_push_dirty_warning"),
                parent=self.winfo_toplevel(),
            )
            return
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        self._status.configure(
            text=t("voice_bot_results_listing_tools"), foreground=META_FG,
        )
        threading.Thread(target=self._list_tools_worker, daemon=True).start()

    def _list_tools_worker(self) -> None:
        try:
            tools = list_tools(api_key=get_elevenlabs_key(self._company.key))
            err: Optional[str] = None
        except ElevenLabsError as exc:
            tools, err = [], str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_tool_picker(tools, err))

    def _render_tool_picker(
        self, tools: list[dict], err: Optional[str],
    ) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_results_pick_tool"), err,
                parent=self.winfo_toplevel(),
            )
            return
        if not tools:
            self._status.configure(
                text=t("voice_bot_results_no_tools"), foreground=META_FG,
            )
            messagebox.showinfo(
                t("voice_bot_results_pick_tool"),
                t("voice_bot_results_no_tools_long"),
                parent=self.winfo_toplevel(),
            )
            return

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(t("voice_bot_results_pick_tool"))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        tree = ttk.Treeview(
            dialog, columns=("name", "tool_id"),
            show="headings", height=min(15, max(5, len(tools))),
        )
        tree.heading("name", text=t("voice_bot_results_tool_name"))
        tree.heading("tool_id", text=t("voice_bot_tool_id"))
        tree.column("name", width=320, anchor="w")
        tree.column("tool_id", width=360, anchor="w")
        # Если уже привязан tool — выделим его как текущий.
        current = self._tool_id
        focused = None
        for tool in tools:
            tid, name = extract_tool_meta(tool)
            iid = tree.insert(
                "", "end", values=(name or "—", tid),
            )
            if tid and tid == current:
                focused = iid
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        if focused:
            tree.selection_set(focused)
            tree.see(focused)

        def use_selected() -> None:
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            picked_name = str(vals[0]) if vals[0] != "—" else ""
            picked_id = str(vals[1])
            if not picked_id:
                return
            if not messagebox.askyesno(
                t("voice_bot_results_pick_tool"),
                t("voice_bot_results_pick_confirm").format(
                    name=picked_name or "—",
                    tool_id=picked_id,
                ),
                parent=dialog,
            ):
                return
            dialog.destroy()
            self._status.configure(
                text=t("voice_bot_results_fetching_tool"), foreground=META_FG,
            )
            threading.Thread(
                target=self._fetch_picked_tool_worker,
                args=(picked_id, picked_name),
                daemon=True,
            ).start()

        btns = ttk.Frame(dialog)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text=t("btn_cancel"), command=dialog.destroy).pack(
            side="right",
        )
        ttk.Button(
            btns, text=t("voice_bot_results_use_tool"), command=use_selected,
            style="Accent.TButton",
        ).pack(side="right", padx=(0, 6))
        tree.bind("<Double-1>", lambda _e: use_selected())

    def _fetch_picked_tool_worker(
        self, tool_id: str, tool_name: str,
    ) -> None:
        try:
            tool = get_tool(
                tool_id, api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            tool, err = None, str(exc)
        if not self.winfo_exists():
            return
        self.after(
            0, lambda: self._apply_picked_tool(tool_id, tool_name, tool, err),
        )

    def _apply_picked_tool(
        self, tool_id: str, tool_name: str,
        tool: Optional[dict], err: Optional[str],
    ) -> None:
        if err or not isinstance(tool, dict):
            self._status.configure(
                text=err or "empty response", foreground=ERR_FG,
            )
            messagebox.showerror(
                t("voice_bot_results_pick_tool"),
                err or "empty response",
                parent=self.winfo_toplevel(),
            )
            return
        # Persist override + write the tool snapshot to the standard path.
        set_tool_id_override(
            self._company.key, self._sector, "save_call_result", tool_id,
        )
        try:
            _save_tool(self._company.key, tool, self._sector)
        except OSError as exc:
            self._status.configure(text=str(exc), foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_results_pick_tool"), str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        # Update tool_id label + internal state. The Push button visibility
        # was bound to the initial __init__ state — ask the user to re-open
        # the tab so the toolbar rebuilds and the tree appears (cheap UX
        # compromise that avoids a full toolbar/tree reconstruction here).
        self._tool_id = tool_id
        self._tool_id_var.set(f"tool_id: {tool_id}")
        self._tool = tool
        self._props = _props_by_id(tool)
        # If we already had a tree built, refresh it in place.
        if hasattr(self, "tree"):
            prev_key = self._current_key
            self._render_tree()
            if not self._reselect_by_stable_key(prev_key):
                self._clear_editor() if hasattr(self, "_clear_editor") else None
                if hasattr(self, "_detail_title"):
                    self._detail_title.configure(text="")
                self._current_key = None
            self._status.configure(
                text=t("voice_bot_results_pick_done").format(name=tool_name or "—"),
                foreground=OK_FG,
            )
        else:
            # Bootstrap path: было «no_file», теперь снапшот появился —
            # сообщаем пользователю про переоткрытие таба, чтобы поднялись
            # дерево + Push.
            self._status.configure(
                text=t("voice_bot_results_pick_done_reopen").format(
                    name=tool_name or "—",
                ),
                foreground=OK_FG,
            )
            messagebox.showinfo(
                t("voice_bot_results_pick_tool"),
                t("voice_bot_results_pick_done_reopen").format(
                    name=tool_name or "—",
                ),
                parent=self.winfo_toplevel(),
            )
