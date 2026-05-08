import tkinter as tk
from tkinter import ttk

from typing import Optional

from ..action_trees import (
    BOT_KINDS,
    compute_readiness,
    get_configured_text,
    get_format_choice,
    get_tree,
    get_value_source,
    set_configured_text,
    set_format_choice,
    set_value_source,
)
from ..crm_field_types import all_known_types
from ..crm_results import get_body_schema
from ..data import Company
from ..i18n import t
from .colors import META_FG, TBD_FG, TEXT_FG


class ActionTreePanel(ttk.Frame):
    """Read-only viewer for a company's action tree. Same content for all
    bot kinds (Voice / WhatsApp / Agents) of the same company."""

    def __init__(self, master: tk.Misc, company: Company, kind: str) -> None:
        super().__init__(master)
        self._company = company
        self._kind = kind
        self._tree_def: dict = {}
        self._iid_to_var: dict[str, str] = {}
        self._editor: Optional[ttk.Combobox] = None

        ttk.Label(
            self,
            text=t("tree_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))

        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        schema = get_body_schema(company.key) or []
        tree_def_for_check = get_tree(company.key) or {}
        if schema and tree_def_for_check:
            self._render_readiness(company.key, schema, tree_def_for_check)
        elif schema:
            names = [f.get("name", "") for f in schema if f.get("name")]
            ttk.Label(
                self,
                text=(
                    f"Целевые переменные результата ({len(names)}): "
                    + ", ".join(names)
                ),
                wraplength=1100,
                justify="left",
                foreground=META_FG,
            ).pack(anchor="w", padx=14, pady=(0, 10))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        tree_def = get_tree(company.key)
        if not tree_def:
            ttk.Label(
                body,
                text=(
                    "Дерево для этой компании ещё не определено. "
                    "Опишите его в app/action_trees.py."
                ),
                foreground=META_FG,
                justify="left",
            ).pack(anchor="w", pady=20)
            return

        self.tree = ttk.Treeview(body, show="tree", selectmode="browse")
        self.tree.tag_configure("var", foreground="#1d4ed8")
        self.tree.tag_configure("value", foreground=TEXT_FG)
        self.tree.tag_configure("tbd", foreground=TBD_FG)
        self.tree.tag_configure("clickable", foreground="#16a34a")
        scl = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")

        self.tree.bind("<Double-Button-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Button-1>", self._maybe_close_editor, add="+")

        self._tree_def = tree_def
        self._render_tree(tree_def)

    # ---------- readiness checklist ----------

    def _render_readiness(
        self, company_key: str, schema: list[dict], tree_def: dict
    ) -> None:
        names = [f.get("name", "") for f in schema if f.get("name")]
        status = compute_readiness(company_key, tree_def, names)

        wrap = ttk.Frame(self)
        wrap.pack(anchor="w", fill="x", padx=14, pady=(0, 10))
        ttk.Label(
            wrap,
            text=f"Готовность переменных результата ({len(names)})",
            foreground=META_FG,
        ).pack(anchor="w", pady=(0, 4))

        grid = ttk.Frame(wrap)
        grid.pack(anchor="w")

        kinds = list(BOT_KINDS.keys())
        # header
        ttk.Label(grid, text=t("tree_col_var"), foreground=META_FG, width=18).grid(
            row=0, column=0, sticky="w", padx=(0, 18)
        )
        for col, kind in enumerate(kinds, start=1):
            ttk.Label(
                grid, text=BOT_KINDS[kind], foreground=META_FG, width=22
            ).grid(row=0, column=col, sticky="w", padx=(0, 18))

        glyphs = {
            "ok": ("✓", "#16a34a"),
            "missing": ("✗", "#dc2626"),
            "no_tree": ("—", TBD_FG),
        }

        for r, name in enumerate(names, start=1):
            ttk.Label(grid, text=name).grid(
                row=r, column=0, sticky="w", padx=(0, 18)
            )
            per = status.get(name) or {}
            for col, kind in enumerate(kinds, start=1):
                glyph, color = glyphs.get(per.get(kind, "no_tree"))
                ttk.Label(grid, text=glyph, foreground=color).grid(
                    row=r, column=col, sticky="w", padx=(0, 18)
                )

        # Test buttons row — one per bot kind.
        btn_row = ttk.Frame(wrap)
        btn_row.pack(anchor="w", pady=(8, 0))
        for kind, kind_label in BOT_KINDS.items():
            ttk.Button(
                btn_row,
                text=f"🧪 Тест {kind_label}",
                command=lambda k=kind, kl=kind_label: self._run_test(k, kl),
            ).pack(side="left", padx=(0, 8))

    def _run_test(self, bot_kind: str, bot_kind_label: str) -> None:
        from .action_tree_test_dialog import ActionTreeTestDialog
        ActionTreeTestDialog(self, self._company, bot_kind, bot_kind_label)

    # ---------- render ----------

    def _render_tree(self, tree_def: dict) -> None:
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._iid_to_var.clear()
        variables = tree_def.get("variables") or {}
        roots = list(tree_def.get("roots") or [])
        if not roots:
            single = tree_def.get("root")
            if single:
                roots = [single]
        roots = [r for r in roots if r in variables]
        if not roots:
            self.tree.insert(
                "", "end",
                text="(дерево пусто — задайте roots и переменные)",
                tags=("tbd",),
            )
            return
        for root_var in roots:
            self._add_variable("", root_var, variables, visited=set())

    def _add_variable(
        self,
        parent_iid: str,
        var_name: str,
        variables: dict,
        visited: set[str],
    ) -> None:
        var_def = variables.get(var_name)
        if not var_def:
            self.tree.insert(
                parent_iid, "end",
                text=f"⚠ переменная «{var_name}» не описана",
                tags=("tbd",),
            )
            return
        if var_name in visited:
            self.tree.insert(
                parent_iid, "end",
                text=f"↩ цикл на «{var_name}»",
                tags=("tbd",),
            )
            return
        visited = visited | {var_name}

        label = var_def.get("label") or var_name

        # «Заполняющая» переменная — сама не имеет values, у неё указан
        # источник значения (другое имя внутреннего типа из CRM-данных, либо
        # `user_input`). Может также иметь `format_options` — тогда строка
        # становится кликабельной (двойной клик переключает формат).
        # Источник можно переопределить правым кликом → выбрать тип.
        if "value_source" in var_def:
            static_source = var_def.get("value_source")
            value_source = get_value_source(
                self._company.key, var_name, static_source
            )

            if value_source == "configured_text":
                # Свободно-текстовое значение, сохраняемое в overrides.
                stored = get_configured_text(self._company.key, var_name)
                if stored:
                    src_text = f"текст: {stored}  (двойной клик — изменить)"
                    tag = "clickable"
                else:
                    src_text = (
                        "значение не задано  (двойной клик — указать)"
                    )
                    tag = "tbd"
                text = f"📥  {label}  ←  {src_text}"
                var_iid = self.tree.insert(
                    parent_iid, "end", text=text, tags=(tag,), open=True
                )
                self._iid_to_var[var_iid] = var_name
                nxt = var_def.get("next_variable")
                if nxt:
                    self._add_variable(var_iid, nxt, variables, visited)
                return

            if value_source == "user_input":
                src_text = "ввод пользователем"
            elif value_source:
                src_text = f"из CRM: {value_source}"
            else:
                src_text = "источник не задан — TBD  (правый клик — выбрать)"
            fmt_options = var_def.get("format_options") or []
            text = f"📥  {label}  ←  {src_text}"
            if fmt_options:
                current = get_format_choice(
                    self._company.key, var_name, fmt_options[0]
                )
                text += f"  ·  формат: {current}  (двойной клик — сменить)"
                tag = "clickable"
            elif not value_source:
                tag = "tbd"
            else:
                tag = "var"
            var_iid = self.tree.insert(
                parent_iid, "end", text=text, tags=(tag,), open=True
            )
            self._iid_to_var[var_iid] = var_name
            nxt = var_def.get("next_variable")
            if nxt:
                self._add_variable(var_iid, nxt, variables, visited)
            return

        var_iid = self.tree.insert(
            parent_iid, "end",
            text=f"📋  {label}",
            tags=("var",),
            open=True,
        )
        self._iid_to_var[var_iid] = var_name

        values = var_def.get("values") or []
        if not values:
            self.tree.insert(
                var_iid, "end",
                text="(значения не заданы)",
                tags=("tbd",),
            )
            return

        for val in values:
            v_value = val.get("value", "")
            v_label = val.get("label") or v_value
            next_var = val.get("next_variable")
            text = f"▸  {v_label}  ({v_value})"
            val_iid = self.tree.insert(
                var_iid, "end",
                text=text,
                tags=("value",),
                open=True,
            )
            if next_var:
                self._add_variable(val_iid, next_var, variables, visited)

    # ---------- editors ----------

    def _close_editor(self) -> None:
        if self._editor is not None:
            try:
                self._editor.destroy()
            except tk.TclError:
                pass
            self._editor = None  # Combobox or Entry — both share this slot

    def _maybe_close_editor(self, event: tk.Event) -> None:
        if self._editor is None:
            return
        if event.widget is self._editor:
            return
        self._close_editor()

    def _on_right_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        var_name = self._iid_to_var.get(iid)
        if not var_name:
            return
        var_def = (self._tree_def.get("variables") or {}).get(var_name) or {}
        if "value_source" not in var_def:
            return
        self._open_source_editor(iid, var_name, var_def)

    def _open_source_editor(
        self, iid: str, var_name: str, var_def: dict
    ) -> None:
        self._close_editor()
        bbox = self.tree.bbox(iid)
        if not bbox:
            return
        x, y, w, h = bbox
        # Build options: "(не задано)" / "user_input" / все известные типы.
        options: list[str] = ["(не задано)", "user_input"] + list(all_known_types())
        # Dedup, preserve order
        seen: set[str] = set()
        uniq: list[str] = []
        for o in options:
            if o not in seen:
                seen.add(o)
                uniq.append(o)
        cb = ttk.Combobox(self.tree, values=uniq, height=20)
        current = get_value_source(
            self._company.key, var_name, var_def.get("value_source")
        )
        cb.set(current if current else "(не задано)")
        # Pop near the click region — anchor to the row's right side so the
        # context-menu feel is preserved.
        cb_w = max(220, min(360, w))
        cb.place(x=min(x + 200, w - cb_w), y=y, width=cb_w, height=h)
        cb.focus_set()
        cb.bind("<<ComboboxSelected>>", lambda _e: self._commit_source(var_name, cb))
        cb.bind("<Return>", lambda _e: self._commit_source(var_name, cb))
        cb.bind("<Escape>", lambda _e: self._close_editor())
        cb.bind("<FocusOut>", lambda _e: self._commit_source(var_name, cb))
        self._editor = cb

    def _commit_source(self, var_name: str, cb: ttk.Combobox) -> None:
        if self._editor is None or self._editor is not cb:
            return
        new_val = cb.get().strip()
        if new_val == "(не задано)":
            new_val = ""
        set_value_source(self._company.key, var_name, new_val)
        self._close_editor()
        self._render_tree(self._tree_def)

    # ---------- click-to-cycle format ----------

    def _on_double_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        var_name = self._iid_to_var.get(iid)
        if not var_name:
            return
        var_def = (self._tree_def.get("variables") or {}).get(var_name) or {}
        # configured_text — открыть Entry для свободного ввода текста.
        if get_value_source(
            self._company.key, var_name, var_def.get("value_source")
        ) == "configured_text":
            self._open_text_editor(iid, var_name)
            return
        fmt_options = var_def.get("format_options") or []
        if not fmt_options:
            return
        current = get_format_choice(
            self._company.key, var_name, fmt_options[0]
        )
        try:
            idx = fmt_options.index(current)
        except ValueError:
            idx = -1
        nxt = fmt_options[(idx + 1) % len(fmt_options)]
        set_format_choice(self._company.key, var_name, nxt)
        self._render_tree(self._tree_def)

    def _open_text_editor(self, iid: str, var_name: str) -> None:
        self._close_editor()
        bbox = self.tree.bbox(iid)
        if not bbox:
            return
        x, y, w, h = bbox
        ent = ttk.Entry(self.tree)
        ent.insert(0, get_configured_text(self._company.key, var_name))
        ent.place(x=x + 100, y=y, width=max(280, w - 100), height=h)
        ent.focus_set()
        ent.select_range(0, "end")
        ent.bind("<Return>", lambda _e: self._commit_text(var_name, ent))
        ent.bind("<Escape>", lambda _e: self._close_editor())
        ent.bind("<FocusOut>", lambda _e: self._commit_text(var_name, ent))
        self._editor = ent  # reusing the same slot

    def _commit_text(self, var_name: str, widget: tk.Widget) -> None:
        if self._editor is None or self._editor is not widget:
            return
        value = widget.get().strip()
        set_configured_text(self._company.key, var_name, value)
        self._close_editor()
        self._render_tree(self._tree_def)
