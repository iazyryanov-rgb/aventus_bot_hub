import json
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Optional
from zoneinfo import ZoneInfo

from ..crm_data_cache import load_snapshot, save_snapshot
from ..crm_field_types import (
    FIELD_TYPES_BY_COMPANY,
    all_known_types,
    get_field_type,
    load_all_overrides,
    merge_overrides,
)
from ..crm_lookup import call_crm_by_phone, fetch_active_loan_phone
from ..data import Company, load_raw


def _flatten(obj, prefix: str = "") -> list[tuple[str, str, str]]:
    """Flatten nested JSON into [(dotted.path, type, value_text), ...]."""
    rows: list[tuple[str, str, str]] = []
    if isinstance(obj, dict):
        if not obj:
            rows.append((prefix or "{}", "object", "{}"))
            return rows
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            rows.extend(_flatten(v, key))
    elif isinstance(obj, list):
        if not obj:
            rows.append((prefix or "[]", "array", "[]"))
            return rows
        for i, v in enumerate(obj):
            rows.extend(_flatten(v, f"{prefix}[{i}]"))
    elif obj is None:
        rows.append((prefix or "value", "null", ""))
    elif isinstance(obj, bool):
        rows.append((prefix or "value", "boolean", "true" if obj else "false"))
    elif isinstance(obj, int):
        rows.append((prefix or "value", "integer", str(obj)))
    elif isinstance(obj, float):
        rows.append((prefix or "value", "number", str(obj)))
    elif isinstance(obj, str):
        rows.append((prefix or "value", "string", obj))
    else:
        rows.append((prefix or "value", type(obj).__name__, str(obj)))
    return rows


class CrmDataPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company, kind: str) -> None:
        super().__init__(master)
        self._company = company
        self._kind = kind
        self._pending: dict[str, str] = {}  # field_name -> internal_type, unsaved
        self._editor: Optional[ttk.Combobox] = None

        ttk.Label(
            self,
            text="ДАННЫЕ ИЗ CRM",
            font=("Segoe UI", 9, "bold"),
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(14, 6))

        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Label(controls, text="Телефон:").pack(side="left")
        self._phone_var = tk.StringVar()
        phone_entry = ttk.Entry(controls, textvariable=self._phone_var, width=22)
        phone_entry.pack(side="left", padx=(4, 8))
        phone_entry.bind("<Return>", lambda _e: self._fetch())
        self._auto_btn = ttk.Button(
            controls, text="Активный из CRM DB", command=self._auto_phone
        )
        self._auto_btn.pack(side="left", padx=(0, 8))
        self._fetch_btn = ttk.Button(
            controls, text="Обновить", command=self._fetch
        )
        self._fetch_btn.pack(side="left")
        self._save_btn = ttk.Button(
            controls, text="Сохранить типы", command=self._save_overrides,
            state="disabled",
        )
        self._save_btn.pack(side="left", padx=(8, 0))

        meta = ttk.Frame(self)
        meta.pack(fill="x", padx=14, pady=(0, 8))
        self._actual_lbl = ttk.Label(meta, text="", foreground="#6b7280")
        self._actual_lbl.pack(side="left")
        self._status = ttk.Label(meta, text="", foreground="#6b7280")
        self._status.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        cols = ("key", "internal", "format", "value")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("key", text="Ключ")
        self.tree.heading("internal", text="Тип")
        self.tree.heading("format", text="Формат")
        self.tree.heading("value", text="Значение")
        self.tree.column("key", width=240, anchor="w")
        self.tree.column("internal", width=240, anchor="w")
        self.tree.column("format", width=80, anchor="w", stretch=False)
        self.tree.column("value", width=520, anchor="w")
        scl = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")

        self.tree.bind("<Double-Button-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._maybe_close_editor, add="+")

        self._render_from_cache()

    # ---------- helpers ----------

    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self._company.timezone or "UTC")
        except Exception:
            return ZoneInfo("UTC")

    def _format_actual(self, ts_ms: int, phone: str, http_code: int, count: int) -> str:
        try:
            dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=self._tz())
            stamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            stamp = "—"
        bits = [f"Актуально: {stamp}"]
        if phone:
            bits.append(f"phone {phone}")
        if http_code:
            bits.append(f"HTTP {http_code}")
        bits.append(f"ключей: {count}")
        return "  ·  ".join(bits)

    def _resolve_internal(self, field_path: str) -> str:
        if field_path in self._pending:
            return self._pending[field_path]
        return get_field_type(self._company.key, field_path)

    def _populate_rows(self, rows: list[list[str]]) -> None:
        self._close_editor()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for r in rows:
            if len(r) < 3:
                continue
            key, fmt, val = r[0], r[1], r[2]
            if val and len(val) > 500:
                val = val[:500] + "…"
            internal = self._resolve_internal(key)
            self.tree.insert("", "end", values=(key, internal or "—", fmt, val))

    # ---------- cache rendering ----------

    def _render_from_cache(self) -> None:
        snap = load_snapshot(self._company.key)
        if not snap:
            self._actual_lbl.configure(
                text="Кэш пуст. Нажмите «Обновить» чтобы получить данные.",
                foreground="#6b7280",
            )
            return
        phone = str(snap.get("phone") or "")
        if phone and not self._phone_var.get():
            self._phone_var.set(phone)
        rows = snap.get("rows") or []
        self._populate_rows(rows)
        self._actual_lbl.configure(
            text=self._format_actual(
                int(snap.get("ts_ms") or 0),
                phone,
                int(snap.get("http_code") or 0),
                len(rows),
            ),
            foreground="#111827",
        )

    # ---------- auto-fill phone ----------

    def _auto_phone(self) -> None:
        self._auto_btn.configure(state="disabled")
        self._status.configure(
            text="Ищем активный займ в CRM DB…", foreground="#6b7280"
        )
        threading.Thread(target=self._auto_worker, daemon=True).start()

    def _auto_worker(self) -> None:
        phone, err = fetch_active_loan_phone(self._company)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._auto_done(phone, err))

    def _auto_done(self, phone: Optional[str], err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._auto_btn.configure(state="normal")
        if err:
            self._status.configure(text=f"Ошибка: {err}", foreground="#dc2626")
            return
        self._phone_var.set(phone or "")
        self._status.configure(
            text=f"Подставлен номер: {phone}", foreground="#111827"
        )

    # ---------- CRM call ----------

    def _fetch(self) -> None:
        phone = self._phone_var.get().strip()
        if not phone:
            self._status.configure(
                text="Введите телефон или нажмите «Активный из CRM DB»",
                foreground="#dc2626",
            )
            return
        info = load_raw().get(self._company.key, {})
        host = info.get("crm_host") or ""
        token = info.get("crm_access_token") or ""
        header = info.get("crm_token_header") or ""
        if not (host and token and header):
            self._status.configure(
                text="В компании не заполнены поля CRM (host / token / header)",
                foreground="#dc2626",
            )
            return
        self._fetch_btn.configure(state="disabled")
        self._status.configure(text="Запрашиваем CRM…", foreground="#6b7280")
        threading.Thread(
            target=self._fetch_worker,
            args=(host, header, token, phone),
            daemon=True,
        ).start()

    def _fetch_worker(
        self, host: str, header: str, token: str, phone: str
    ) -> None:
        code, body, err = call_crm_by_phone(host, header, token, phone, timeout=15)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._fetch_done(phone, code, body, err))

    def _fetch_done(
        self, phone: str, code: int, body: str, err: Optional[str]
    ) -> None:
        if not self.winfo_exists():
            return
        self._fetch_btn.configure(state="normal")
        if err:
            self._status.configure(
                text=f"phone {phone} → {err}", foreground="#dc2626"
            )
            return
        if not body:
            self._status.configure(
                text=f"phone {phone} → HTTP {code}, тело пустое",
                foreground="#dc2626",
            )
            return
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            self._status.configure(
                text=f"phone {phone} → HTTP {code}, не JSON: {exc}",
                foreground="#dc2626",
            )
            return
        flat = _flatten(data)
        flat.sort(key=lambda kv: kv[0])
        rows_for_cache = [[k, t, str(v) if v is not None else ""] for k, t, v in flat]

        snapshot = {
            "ts_ms": int(time.time() * 1000),
            "phone": phone,
            "http_code": int(code),
            "rows": rows_for_cache,
        }
        save_snapshot(self._company.key, snapshot)

        self._populate_rows(rows_for_cache)
        self._actual_lbl.configure(
            text=self._format_actual(
                snapshot["ts_ms"], phone, code, len(rows_for_cache)
            ),
            foreground="#111827",
        )
        self._status.configure(text="Готово", foreground="#16a34a")

    # ---------- editing internal type ----------

    def _close_editor(self) -> None:
        if self._editor is not None:
            try:
                self._editor.destroy()
            except tk.TclError:
                pass
            self._editor = None

    def _maybe_close_editor(self, event: tk.Event) -> None:
        if self._editor is None:
            return
        if event.widget is self._editor:
            return
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if col == "#2" and iid:
            return
        self._close_editor()

    def _on_double_click(self, event: tk.Event) -> None:
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#2":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self._open_editor(iid)

    def _open_editor(self, iid: str) -> None:
        self._close_editor()
        bbox = self.tree.bbox(iid, column="internal")
        if not bbox:
            return
        x, y, w, h = bbox
        current = self.tree.set(iid, "internal")
        if current == "—":
            current = ""
        cb = ttk.Combobox(self.tree, values=all_known_types())
        cb.set(current)
        cb.place(x=x, y=y, width=w, height=h)
        cb.focus_set()
        cb.bind("<Return>", lambda _e: self._commit_editor(iid))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._commit_editor(iid))
        cb.bind("<Escape>", lambda _e: self._close_editor())
        cb.bind("<FocusOut>", lambda _e: self._commit_editor(iid))
        self._editor = cb

    def _commit_editor(self, iid: str) -> None:
        if self._editor is None:
            return
        new_val = self._editor.get().strip()
        key = self.tree.set(iid, "key")
        # Compare with the *resolved* type (overrides+pending+static), so
        # that an unchanged value doesn't pollute pending.
        baseline_overrides = load_all_overrides().get(self._company.key, {})
        baseline = baseline_overrides.get(key) or get_field_type(
            self._company.key, key
        )
        if new_val != baseline:
            self._pending[key] = new_val
        else:
            self._pending.pop(key, None)
        self.tree.set(iid, "internal", new_val or "—")
        self._close_editor()
        self._refresh_save_button()

    def _refresh_save_button(self) -> None:
        state = "normal" if self._pending else "disabled"
        self._save_btn.configure(state=state)

    def _save_overrides(self) -> None:
        if not self._pending:
            return
        try:
            merge_overrides(self._company.key, dict(self._pending))
        except OSError as exc:
            self._status.configure(
                text=f"Не удалось сохранить: {exc}", foreground="#dc2626"
            )
            return
        self._pending.clear()
        self._refresh_save_button()
        self._status.configure(
            text="Типы сохранены ✓", foreground="#16a34a"
        )
