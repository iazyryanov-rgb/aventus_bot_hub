import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..alerts import (
    ALERT_TEMPLATES,
    ALERT_TEMPLATE_BY_SLUG,
    TelegramError,
    delete_bot_alert,
    get_bot_alerts,
    load_alerts_config,
    send_telegram_message,
)
from ..data import Company
from ..i18n import t

BOT_KIND_NAMES = {
    "voice": "Voice Bot",
    "whatsapp": "WhatsApp Infobip bot",
    "agents": "Agents",
}


class AlertsPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company, kind: str) -> None:
        super().__init__(master)
        self._company = company
        self._kind = kind
        self._cfg = load_alerts_config()

        ttk.Label(
            self,
            text=t("header_alerts"),
            font=("Segoe UI", 9, "bold"),
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(14, 6))

        code = company.key.rstrip("_")
        bot_label = BOT_KIND_NAMES.get(kind, kind)
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country}) · {bot_label}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 12))

        # Telegram channel block (credentials hidden)
        ch = ttk.LabelFrame(self, text="Telegram-канал (общий для всех проектов)", padding=12)
        ch.pack(fill="x", padx=14, pady=(0, 10))
        btn_row = ttk.Frame(ch)
        btn_row.pack(fill="x")
        self._test_btn = ttk.Button(
            btn_row, text="Отправить тестовое сообщение", command=self._send_test
        )
        self._test_btn.pack(side="left")
        self._test_status = ttk.Label(btn_row, text="", foreground="#6b7280")
        self._test_status.pack(side="left", padx=(12, 0))

        # Planner block
        sched = ttk.LabelFrame(self, text="Планировщик алертов", padding=12)
        sched.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        toolbar = ttk.Frame(sched)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Добавить", command=self._add).pack(side="left")
        self._edit_btn = ttk.Button(
            toolbar, text="Изменить", command=self._edit, state="disabled"
        )
        self._edit_btn.pack(side="left", padx=(8, 0))
        self._del_btn = ttk.Button(
            toolbar, text="Удалить", command=self._delete, state="disabled"
        )
        self._del_btn.pack(side="left", padx=(8, 0))
        self._send_btn = ttk.Button(
            toolbar, text="Отправить пробный", command=self._send_one, state="disabled"
        )
        self._send_btn.pack(side="left", padx=(8, 0))

        cols = ("name", "template", "trigger", "schedule", "start", "enabled")
        self.tree = ttk.Treeview(sched, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Имя")
        self.tree.heading("template", text="Шаблон")
        self.tree.heading("trigger", text="Триггер")
        self.tree.heading("schedule", text="Периодичность")
        self.tree.heading("start", text="Старт")
        self.tree.heading("enabled", text="Статус")
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("template", width=220, anchor="w")
        self.tree.column("trigger", width=110, anchor="w", stretch=False)
        self.tree.column("schedule", width=170, anchor="w")
        self.tree.column("start", width=70, anchor="w", stretch=False)
        self.tree.column("enabled", width=100, anchor="w", stretch=False)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", lambda _e: self._edit())

        self._row_to_alert: dict[str, dict] = {}
        self._reload_alerts()

        # Templates reference (collapsible-like, just a labelframe)
        ref = ttk.LabelFrame(self, text="Доступные шаблоны (поля для фикса)", padding=12)
        ref.pack(fill="x", padx=14, pady=(0, 14))
        for _slug, title, desc in ALERT_TEMPLATES:
            row = ttk.Frame(ref)
            row.pack(fill="x", pady=2, anchor="w")
            ttk.Label(row, text=title, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Label(row, text=desc, foreground="#374151", wraplength=900, justify="left").pack(
                anchor="w", padx=(16, 0)
            )

    # ------- planner -------

    def _reload_alerts(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_alert.clear()
        for alert in get_bot_alerts(self._company.key, self._kind):
            slug = alert.get("template", "")
            tpl = ALERT_TEMPLATE_BY_SLUG.get(slug)
            tpl_title = tpl[1] if tpl else slug or "—"
            mode = alert.get("trigger_mode") or "event"
            mode_label = "По событию" if mode == "event" else "По времени"
            iid = self.tree.insert(
                "",
                "end",
                values=(
                    alert.get("name", ""),
                    tpl_title,
                    mode_label,
                    alert.get("schedule", "") or "—",
                    alert.get("start_time") or "—",
                    "Включён" if alert.get("enabled", True) else "Выключен",
                ),
            )
            self._row_to_alert[iid] = alert
        self._update_buttons()

    def _selected_alert(self) -> Optional[dict]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._row_to_alert.get(sel[0])

    def _on_select(self, _e: tk.Event) -> None:
        self._update_buttons()

    def _update_buttons(self) -> None:
        state = "normal" if self._selected_alert() else "disabled"
        self._edit_btn.configure(state=state)
        self._del_btn.configure(state=state)
        self._send_btn.configure(state=state)

    def _add(self) -> None:
        from .alert_edit_dialog import AlertEditDialog
        AlertEditDialog(self, self._company, self._kind, None, on_saved=self._on_saved)

    def _edit(self) -> None:
        a = self._selected_alert()
        if not a:
            return
        from .alert_edit_dialog import AlertEditDialog
        AlertEditDialog(self, self._company, self._kind, a, on_saved=self._on_saved)

    def _delete(self) -> None:
        a = self._selected_alert()
        if not a:
            return
        if not messagebox.askyesno(
            "Удалить алерт",
            f"Удалить «{a.get('name', '')}»?",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            delete_bot_alert(self._company.key, self._kind, a.get("id", ""))
        except OSError as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{exc}", parent=self.winfo_toplevel())
            return
        self._reload_alerts()

    def _on_saved(self, _alert: dict) -> None:
        self._reload_alerts()

    # ------- telegram test -------

    def _build_test_text_for_alert(self, alert: dict) -> str:
        slug = alert.get("template", "")
        tpl = ALERT_TEMPLATE_BY_SLUG.get(slug)
        title = tpl[1] if tpl else "Alert"
        bot_label = BOT_KIND_NAMES.get(self._kind, self._kind)
        return (
            f"⚠️ #{self._company.name} | #{bot_label}\n"
            f"{title}\n"
            f"📛 Alert: {alert.get('name', '')}\n"
            f"🕒 Schedule: {alert.get('schedule') or '—'}"
            f"{(' (start ' + alert['start_time'] + ')') if alert.get('start_time') else ''}\n"
            f"📝 Notes: {alert.get('notes') or '—'}"
        )

    def _send_one(self) -> None:
        a = self._selected_alert()
        if not a:
            return
        self._send_btn.configure(state="disabled")
        self._test_status.configure(text="Отправка пробного…", foreground="#6b7280")
        text = self._build_test_text_for_alert(a)
        threading.Thread(target=self._send_worker, args=(text,), daemon=True).start()

    def _send_test(self) -> None:
        self._test_btn.configure(state="disabled")
        self._test_status.configure(text="Отправка…", foreground="#6b7280")
        bot_label = BOT_KIND_NAMES.get(self._kind, self._kind)
        text = (
            f"⚠️ #{self._company.name} | #{bot_label}\n"
            f"✅ Aventus Bot Hub — channel test\n"
            f"🌐 {self._company.country}"
        )
        threading.Thread(target=self._send_worker, args=(text,), daemon=True).start()

    def _send_worker(self, text: str) -> None:
        tg = self._cfg.get("telegram", {})
        token = tg.get("bot_token", "")
        chat_id = tg.get("chat_id", "")
        err: Optional[str] = None
        try:
            send_telegram_message(token, chat_id, text)
        except TelegramError as e:
            err = str(e)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._send_done(err))

    def _send_done(self, err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._test_btn.configure(state="normal")
        self._update_buttons()
        if err:
            self._test_status.configure(text=f"Ошибка: {err}", foreground="#dc2626")
        else:
            self._test_status.configure(text="Сообщение отправлено ✓", foreground="#16a34a")
