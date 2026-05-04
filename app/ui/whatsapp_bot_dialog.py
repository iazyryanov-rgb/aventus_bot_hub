import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from ..data import Company, load_bot, save_bot

FIELDS: list[tuple[str, str, str]] = [
    ("prod_schema_id", "Prod schema ID (chat)", "int"),
    ("prod_schema_name", "Prod schema name", "str"),
    ("gate_id", "Webitel WhatsApp gate ID", "str"),
]


class WhatsAppBotDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        company: Company,
        on_saved: Optional[Callable[[Company], None]] = None,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._on_saved = on_saved
        info = load_bot(company.key, "whatsapp")

        code = company.key.rstrip("_")
        self.title(f"WhatsApp bot: {code} — {company.name}")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, padding=18)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Компания").grid(row=0, column=0, sticky="w", pady=5)
        co_entry = ttk.Entry(body, width=44)
        co_entry.insert(0, f"{code} — {company.name}")
        co_entry.configure(state="readonly")
        co_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=(10, 0))

        self._entries: dict[str, tuple[ttk.Entry, str]] = {}
        for i, (field, label, kind) in enumerate(FIELDS, start=1):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=5)
            e = ttk.Entry(body, width=44)
            value = info.get(field, "")
            e.insert(0, "" if value is None else str(value))
            e.grid(row=i, column=1, sticky="ew", pady=5, padx=(10, 0))
            self._entries[field] = (e, kind)

        body.columnconfigure(1, weight=1)

        btns = ttk.Frame(self, padding=(18, 0, 18, 18))
        btns.grid(row=1, column=0, sticky="ew")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self._center_on(master.winfo_toplevel())
        self.grab_set()
        self._entries["prod_schema_id"][0].focus_set()

    def _center_on(self, target: tk.Misc) -> None:
        try:
            mx = target.winfo_rootx()
            my = target.winfo_rooty()
            mw = target.winfo_width()
            mh = target.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"+{mx + max(0, (mw - w) // 2)}+{my + max(0, (mh - h) // 3)}")
        except tk.TclError:
            pass

    def _save(self) -> None:
        info: dict = {}
        for field, (entry, kind) in self._entries.items():
            value = entry.get().strip()
            if kind == "int":
                if value == "":
                    info[field] = None
                else:
                    try:
                        info[field] = int(value)
                    except ValueError:
                        messagebox.showerror(
                            "Ошибка",
                            f"Поле «{field}» должно быть числом.",
                            parent=self,
                        )
                        return
            else:
                info[field] = value
        try:
            save_bot(self._company.key, "whatsapp", info)
        except OSError as exc:
            messagebox.showerror(
                "Ошибка",
                f"Не удалось сохранить файл:\n{exc}",
                parent=self,
            )
            return
        if self._on_saved:
            self._on_saved(self._company)
        self.destroy()
