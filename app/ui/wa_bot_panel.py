"""Per-company WhatsApp-Infobip bot configuration panels.

Three independent panels (rendered as separate tabs by BotPanel for
kind="whatsapp"):

  * WaBotOverviewPanel  — gateway, prod schema, CRM endpoints, lookup
    vars, result body fields.
  * WaBotFunctionsPanel — editable list of OpenAI tool/function specs.
  * WaBotPromptsPanel   — main + secondary prompt textareas.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..data import Company
from ..i18n import t
from ..wa_bot_config import (
    DEFAULT_BUILDER,
    GATEWAY_NAME,
    build_request_body,
    get_prod_schema,
    load_config,
    save_config,
)
from .colors import META_FG, OK_FG, TEXT_FG


class WaBotOverviewPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        cfg = load_config(company.key)

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

        lookup = ttk.LabelFrame(self, text=t("wa_bot_section_lookup"), padding=10)
        lookup.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        ttk.Label(
            lookup,
            text=t("wa_bot_lookup_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        tree = ttk.Treeview(
            lookup, columns=("local", "remote"), show="headings", height=8
        )
        tree.heading("local", text=t("wa_bot_local_var"))
        tree.heading("remote", text=t("wa_bot_remote_field"))
        tree.column("local", width=240)
        tree.column("remote", width=320)
        tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(lookup, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        for v in cfg.get("crm_lookup_vars") or []:
            tree.insert("", "end", values=(v.get("local", ""), v.get("remote", "")))

        result = ttk.LabelFrame(self, text=t("wa_bot_section_result"), padding=10)
        result.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        ttk.Label(
            result,
            text=t("wa_bot_result_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        tree2 = ttk.Treeview(
            result, columns=("key", "value"), show="headings", height=8
        )
        tree2.heading("key", text=t("wa_bot_field_key"))
        tree2.heading("value", text=t("wa_bot_field_value"))
        tree2.column("key", width=240)
        tree2.column("value", width=420)
        tree2.pack(side="left", fill="both", expand=True)
        scl2 = ttk.Scrollbar(result, orient="vertical", command=tree2.yview)
        tree2.configure(yscrollcommand=scl2.set)
        scl2.pack(side="right", fill="y")
        for f in cfg.get("result_post_fields") or []:
            tree2.insert("", "end", values=(f.get("key", ""), f.get("value", "")))


class WaBotFunctionsPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cfg: dict = load_config(company.key)

        ttk.Label(
            self,
            text=t("wa_bot_functions_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 4))

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
        ttk.Label(
            self, text=t("wa_bot_prompt_main_help"),
            foreground=META_FG, wraplength=900, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 4))
        self._main_prompt = tk.Text(self, height=10, wrap="word")
        self._main_prompt.pack(fill="x", padx=12, pady=(0, 8))
        self._main_prompt.insert("1.0", gpt.get("main_prompt") or "")

        # ---- Дополнительный промт ----
        ttk.Label(
            self, text=t("wa_bot_prompt_secondary"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        ttk.Label(
            self, text=t("wa_bot_prompt_secondary_help"),
            foreground=META_FG, wraplength=900, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 4))
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

        ttk.Label(
            struct, text=t("wa_bot_prompts_hint"),
            foreground=META_FG, wraplength=900, justify="left",
        ).pack(anchor="w", pady=(6, 0))

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

        ttk.Label(
            self,
            text=t("wa_bot_builder_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 8))

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
