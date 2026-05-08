import threading
import tkinter as tk
from tkinter import messagebox, ttk  # noqa: F401
from typing import Callable, Optional
from zoneinfo import available_timezones

from ..crm_lookup import call_crm_by_phone, fetch_active_loan_phone
from ..data import default_timezone_for_country, load_companies, load_raw, save_raw
from ..db import test_connection

FIELDS: list[tuple[str, str]] = [
    ("name", "Название"),
    ("country", "Страна"),
    ("webitel_host", "Webitel host"),
    ("webitel_access_token", "Webitel Access token"),
    ("crm_host", "CRM host (поиск по телефону)"),
    ("crm_results_host", "CRM results host (POST результата)"),
    ("crm_bot_id", "CRM Bot ID"),
    ("crm_access_token", "CRM Access token"),
    ("crm_token_header", "CRM header для токена"),
    ("crm_db_name", "CRM DB name (для Postgres)"),
    ("crm_db_port", "CRM DB port"),
]

DB_ENGINES = ("mysql", "postgres")

TIMEZONES = sorted(available_timezones())


class CompanyEditDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        company_key: Optional[str],
        on_saved: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master)
        self._is_new = company_key is None
        self._key = company_key
        self._on_saved = on_saved
        self._raw = load_raw()
        info = self._raw.get(company_key or "", {}) if not self._is_new else {}

        code = "" if self._is_new else (company_key or "").rstrip("_")
        name = info.get("name", "")
        if self._is_new:
            self.title("Новая компания")
        else:
            self.title(
                f"Редактировать: {code} — {name}" if name else f"Редактировать: {code}"
            )
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, padding=18)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Код *").grid(row=0, column=0, sticky="w", pady=5)
        self._code_entry = ttk.Entry(body, width=44)
        self._code_entry.insert(0, code)
        if not self._is_new:
            self._code_entry.configure(state="readonly")
        self._code_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=(10, 0))

        required_fields = {"name", "country", "webitel_host"}
        self._entries: dict[str, ttk.Entry] = {}
        for i, (field, label) in enumerate(FIELDS, start=1):
            shown = (label + " *") if field in required_fields else label
            ttk.Label(body, text=shown).grid(row=i, column=0, sticky="w", pady=5)
            e = ttk.Entry(body, width=44)
            value = info.get(field, "")
            e.insert(0, "" if value is None else str(value))
            e.grid(row=i, column=1, sticky="ew", pady=5, padx=(10, 0))
            self._entries[field] = e

        engine_row = len(FIELDS) + 1
        ttk.Label(body, text="CRM DB engine").grid(row=engine_row, column=0, sticky="w", pady=5)
        self._engine_var = tk.StringVar(
            value=str(info.get("crm_db_engine") or "mysql").lower()
        )
        if self._engine_var.get() not in DB_ENGINES:
            self._engine_var.set("mysql")
        engine_box = ttk.Combobox(
            body,
            textvariable=self._engine_var,
            values=list(DB_ENGINES),
            state="readonly",
            width=42,
        )
        engine_box.grid(row=engine_row, column=1, sticky="ew", pady=5, padx=(10, 0))
        engine_box.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_crm_test_button()
        )

        db_test_row = len(FIELDS) + 2
        db_test = ttk.Frame(body)
        db_test.grid(row=db_test_row, column=1, sticky="w", pady=(0, 4), padx=(10, 0))
        self._db_test_btn = ttk.Button(
            db_test, text="Проверить CRM DB", command=self._test_db
        )
        self._db_test_btn.pack(side="left")
        self._crm_test_btn = ttk.Button(
            db_test,
            text="Тест CRM по номеру",
            command=self._test_crm_request,
            state="disabled",
        )
        self._crm_test_btn.pack(side="left", padx=(8, 0))
        self._db_test_status = ttk.Label(db_test, text="", foreground="#6b7280")
        self._db_test_status.pack(side="left", padx=(10, 0))

        # Enable / disable "Тест CRM по номеру" based on field completeness.
        for fname in ("crm_host", "crm_access_token", "crm_token_header", "crm_db_port"):
            entry = self._entries.get(fname)
            if entry is not None:
                entry.bind("<KeyRelease>", lambda _e: self._refresh_crm_test_button())
                entry.bind("<FocusOut>", lambda _e: self._refresh_crm_test_button())
        self._refresh_crm_test_button()

        tz_row = len(FIELDS) + 3
        ttk.Label(body, text="Часовой пояс *").grid(row=tz_row, column=0, sticky="w", pady=5)
        self._timezone = ttk.Combobox(body, values=TIMEZONES, width=42)
        current_tz = (
            info.get("timezone")
            or default_timezone_for_country(info.get("country", ""))
        )
        self._timezone.set(current_tz)
        self._timezone.grid(row=tz_row, column=1, sticky="ew", pady=5, padx=(10, 0))

        # --- Grafana (per-company, used to query Webitel Postgres for
        # full chat coverage incl. bot-only). All optional — if absent,
        # the chats panel falls back to REST.
        grafana_info = info.get("grafana") or {}
        gf_section_row = tz_row + 1
        ttk.Label(
            body, text="Grafana (опционально)",
            font=("Segoe UI", 9, "bold"),
            foreground="#6b7280",
        ).grid(row=gf_section_row, column=0, columnspan=2,
               sticky="w", pady=(12, 4))
        gf_specs = [
            ("grafana_base_url", "Grafana host (URL)", False),
            ("grafana_user",     "Grafana login",      False),
            ("grafana_password", "Grafana password",   True),
        ]
        self._grafana_entries: dict[str, ttk.Entry] = {}
        for i, (field, label, is_password) in enumerate(gf_specs, start=1):
            ttk.Label(body, text=label).grid(
                row=gf_section_row + i, column=0, sticky="w", pady=5,
            )
            kw = {"width": 44}
            if is_password:
                kw["show"] = "•"
            e = ttk.Entry(body, **kw)
            # Map dialog-field names → JSON keys.
            json_key = {
                "grafana_base_url": "base_url",
                "grafana_user":     "user",
                "grafana_password": "password",
            }[field]
            e.insert(0, str(grafana_info.get(json_key, "") or ""))
            e.grid(row=gf_section_row + i, column=1, sticky="ew",
                   pady=5, padx=(10, 0))
            self._grafana_entries[field] = e

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

    def _refresh_crm_test_button(self) -> None:
        if self._is_new:
            self._crm_test_btn.configure(state="disabled")
            return
        required = ("crm_host", "crm_access_token", "crm_token_header", "crm_db_port")
        all_filled = all(
            (self._entries.get(f).get().strip() if self._entries.get(f) is not None else "")
            for f in required
        )
        self._crm_test_btn.configure(state="normal" if all_filled else "disabled")

    def _test_crm_request(self) -> None:
        if self._is_new:
            return
        host = self._entries["crm_host"].get().strip()
        token = self._entries["crm_access_token"].get().strip()
        header = self._entries["crm_token_header"].get().strip()
        if not (host and token and header):
            return
        self._crm_test_btn.configure(state="disabled")
        self._db_test_btn.configure(state="disabled")
        self._db_test_status.configure(
            text="Берём номер активного займа…", foreground="#6b7280"
        )
        threading.Thread(
            target=self._test_crm_worker,
            args=(host, header, token, self._key),
            daemon=True,
        ).start()

    def _test_crm_worker(
        self, host: str, header: str, token: str, company_key: Optional[str]
    ) -> None:
        if not company_key:
            self._after_test_crm(None, "Компания ещё не сохранена.")
            return
        company = next((c for c in load_companies() if c.key == company_key), None)
        if company is None:
            self._after_test_crm(None, "Не удалось загрузить компанию.")
            return
        phone, err = fetch_active_loan_phone(company)
        if err or not phone:
            self._after_test_crm(None, err or "Номер не найден")
            return
        # show phone-found progress
        if self.winfo_exists():
            self.after(
                0,
                lambda: self._db_test_status.configure(
                    text=f"Стучимся в CRM по {phone}…",
                    foreground="#6b7280",
                ),
            )
        code, body, http_err = call_crm_by_phone(host, header, token, phone)
        if http_err:
            self._after_test_crm(False, f"phone {phone} → {http_err}")
        else:
            self._after_test_crm(True, f"phone {phone} → HTTP {code}")

    def _after_test_crm(self, ok: Optional[bool], msg: str) -> None:
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_crm_result(ok, msg))

    def _render_crm_result(self, ok: Optional[bool], msg: str) -> None:
        if not self.winfo_exists():
            return
        self._db_test_btn.configure(state="normal")
        self._refresh_crm_test_button()
        if ok is True:
            self._db_test_status.configure(text="CRM OK ✓", foreground="#16a34a")
        else:
            self._db_test_status.configure(text=f"CRM: ошибка — {msg}", foreground="#dc2626")

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
        engine = (self._engine_var.get() or "mysql").lower()
        db_name_entry = self._entries.get("crm_db_name")
        db_name = db_name_entry.get().strip() if db_name_entry is not None else ""
        err = test_connection(port, engine=engine, database=db_name or None)
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
        if self._is_new:
            code = self._code_entry.get().strip().upper()
            if not code:
                messagebox.showerror("Ошибка", "Заполните код компании.", parent=self)
                return
            key = code if code.endswith("_") else code + "_"
            if key in self._raw:
                messagebox.showerror(
                    "Ошибка",
                    f"Компания с кодом {code} уже существует.",
                    parent=self,
                )
                return
        else:
            key = self._key or ""

        new_info = dict(self._raw.get(key, {}))
        for field, entry in self._entries.items():
            new_info[field] = entry.get().strip()
        new_info["timezone"] = self._timezone.get().strip() or default_timezone_for_country(
            new_info.get("country", "")
        )
        new_info["crm_db_engine"] = (self._engine_var.get() or "mysql").lower()

        # Grafana block — stored as nested dict so the rest of
        # companies.json stays flat. Stripped of empty fields so the
        # config file isn't littered with empty optional sections.
        gf_url = self._grafana_entries["grafana_base_url"].get().strip()
        gf_user = self._grafana_entries["grafana_user"].get().strip()
        gf_pass = self._grafana_entries["grafana_password"].get().strip()
        if gf_url or gf_user or gf_pass:
            new_info["grafana"] = {
                "base_url": gf_url,
                "user":     gf_user,
                "password": gf_pass,
            }
        else:
            new_info.pop("grafana", None)

        if self._is_new:
            missing = []
            if not new_info.get("name"):
                missing.append("Название")
            if not new_info.get("country"):
                missing.append("Страна")
            if not new_info.get("webitel_host"):
                missing.append("Webitel host")
            if not new_info.get("timezone"):
                missing.append("Часовой пояс")
            if missing:
                messagebox.showerror(
                    "Ошибка",
                    "Заполните обязательные поля:\n  • " + "\n  • ".join(missing),
                    parent=self,
                )
                return

        self._raw[key] = new_info
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
            self._on_saved(key)
        self.destroy()
