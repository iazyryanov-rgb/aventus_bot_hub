import threading
import tkinter as tk
from tkinter import messagebox, ttk  # noqa: F401
from typing import Callable, Optional
from zoneinfo import available_timezones

from ..data import default_timezone_for_country, load_raw, save_raw
from ..db import test_connection

FIELDS: list[tuple[str, str]] = [
    ("name", "Название"),
    ("country", "Страна"),
    ("webitel_host", "Webitel host"),
    ("webitel_access_token", "Webitel Access token"),
    ("crm_host", "CRM host (поиск по телефону)"),
    ("crm_access_token", "CRM Access token"),
    ("crm_token_header", "CRM header для токена"),
    ("crm_db_port", "CRM DB port"),
]

TIMEZONES = sorted(available_timezones())


class CompanyEditDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        company_key: str,
        on_saved: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master)
        self._key = company_key
        self._on_saved = on_saved
        self._raw = load_raw()
        info = self._raw.get(company_key, {})

        code = company_key.rstrip("_")
        name = info.get("name", "")
        self.title(f"Редактировать: {code} — {name}" if name else f"Редактировать: {code}")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, padding=18)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Код").grid(row=0, column=0, sticky="w", pady=5)
        code_entry = ttk.Entry(body, width=44)
        code_entry.insert(0, code)
        code_entry.configure(state="readonly")
        code_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=(10, 0))

        self._entries: dict[str, ttk.Entry] = {}
        for i, (field, label) in enumerate(FIELDS, start=1):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=5)
            e = ttk.Entry(body, width=44)
            value = info.get(field, "")
            e.insert(0, "" if value is None else str(value))
            e.grid(row=i, column=1, sticky="ew", pady=5, padx=(10, 0))
            self._entries[field] = e

        db_test_row = len(FIELDS) + 1
        db_test = ttk.Frame(body)
        db_test.grid(row=db_test_row, column=1, sticky="w", pady=(0, 4), padx=(10, 0))
        self._db_test_btn = ttk.Button(
            db_test, text="Проверить CRM DB", command=self._test_db
        )
        self._db_test_btn.pack(side="left")
        self._db_test_status = ttk.Label(db_test, text="", foreground="#6b7280")
        self._db_test_status.pack(side="left", padx=(10, 0))

        tz_row = len(FIELDS) + 2
        ttk.Label(body, text="Часовой пояс").grid(row=tz_row, column=0, sticky="w", pady=5)
        self._timezone = ttk.Combobox(body, values=TIMEZONES, width=42)
        current_tz = (
            info.get("timezone")
            or default_timezone_for_country(info.get("country", ""))
        )
        self._timezone.set(current_tz)
        self._timezone.grid(row=tz_row, column=1, sticky="ew", pady=5, padx=(10, 0))

        body.columnconfigure(1, weight=1)

        btns = ttk.Frame(self, padding=(18, 0, 18, 18))
        btns.grid(row=1, column=0, sticky="ew")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self._center_on(master.winfo_toplevel())
        self.grab_set()
        self._entries["name"].focus_set()

    def _center_on(self, target: tk.Misc) -> None:
        try:
            mx = target.winfo_rootx()
            my = target.winfo_rooty()
            mw = target.winfo_width()
            mh = target.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = mx + max(0, (mw - w) // 2)
            y = my + max(0, (mh - h) // 3)
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _test_db(self) -> None:
        port_str = self._entries["crm_db_port"].get().strip()
        if not port_str:
            self._db_test_status.configure(
                text="Заполните поле порта.", foreground="#dc2626"
            )
            return
        try:
            port = int(port_str)
        except ValueError:
            self._db_test_status.configure(
                text="Порт должен быть числом.", foreground="#dc2626"
            )
            return
        self._db_test_btn.configure(state="disabled")
        self._db_test_status.configure(text="Проверка…", foreground="#6b7280")
        threading.Thread(
            target=self._test_db_worker, args=(port,), daemon=True
        ).start()

    def _test_db_worker(self, port: int) -> None:
        err = test_connection(port)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._test_db_done(err))

    def _test_db_done(self, err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._db_test_btn.configure(state="normal")
        if err is None:
            self._db_test_status.configure(
                text="Подключение успешно ✓", foreground="#16a34a"
            )
        else:
            self._db_test_status.configure(
                text=f"Ошибка: {err}", foreground="#dc2626"
            )

    def _save(self) -> None:
        new_info = dict(self._raw.get(self._key, {}))
        for field, entry in self._entries.items():
            new_info[field] = entry.get().strip()
        new_info["timezone"] = self._timezone.get().strip() or default_timezone_for_country(
            new_info.get("country", "")
        )
        self._raw[self._key] = new_info
        try:
            save_raw(self._raw)
        except OSError as exc:
            messagebox.showerror(
                "Ошибка",
                f"Не удалось сохранить файл:\n{exc}",
                parent=self,
            )
            return
        if self._on_saved:
            self._on_saved(self._key)
        self.destroy()
