import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from ..alerts import (
    ALERT_TEMPLATES,
    SCHEDULE_PRESETS,
    templates_for_kind,
    upsert_bot_alert,
)
from ..data import Company


class AlertEditDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        company: Company,
        kind: str,
        alert: Optional[dict],
        on_saved: Optional[Callable[[dict], None]] = None,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._kind = kind
        self._alert = dict(alert) if alert else {}
        self._on_saved = on_saved

        is_new = not alert
        self.title("Новый алерт" if is_new else f"Алерт: {alert.get('name', '')}")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, padding=18)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Имя").grid(row=0, column=0, sticky="w", pady=5)
        self._name = ttk.Entry(body, width=44)
        self._name.insert(0, self._alert.get("name", ""))
        self._name.grid(row=0, column=1, sticky="ew", pady=5, padx=(10, 0))

        ttk.Label(body, text="Шаблон").grid(row=1, column=0, sticky="w", pady=5)
        # Фильтруем шаблоны под выбранный тип бота. Если у нас уже
        # сохранён шаблон, не входящий в фильтр (например, legacy
        # значение или ручной импорт alerts.json) — добавляем его в
        # хвост списка, чтобы оператор мог его открыть и пересохранить.
        kind_templates = list(templates_for_kind(kind))
        current_slug = self._alert.get("template") or ""
        if current_slug and current_slug not in {s for s, _, _ in kind_templates}:
            for t_tuple in ALERT_TEMPLATES:
                if t_tuple[0] == current_slug:
                    kind_templates.append(t_tuple)
                    break
        self._template_titles = [title for _, title, _ in kind_templates]
        self._template_slugs = [slug for slug, _, _ in kind_templates]
        self._template = ttk.Combobox(
            body, values=self._template_titles, state="readonly", width=42
        )
        fallback = self._template_slugs[0] if self._template_slugs else ""
        try:
            self._template.current(
                self._template_slugs.index(current_slug or fallback)
            )
        except ValueError:
            if self._template_slugs:
                self._template.current(0)
        self._template.grid(row=1, column=1, sticky="ew", pady=5, padx=(10, 0))
        self._template.bind("<<ComboboxSelected>>", lambda _e: self._on_template_change())

        ttk.Label(body, text="Триггер").grid(row=2, column=0, sticky="w", pady=5)
        mode_frame = ttk.Frame(body)
        mode_frame.grid(row=2, column=1, sticky="w", pady=5, padx=(10, 0))
        self._mode_var = tk.StringVar(value=self._alert.get("trigger_mode") or "event")
        ttk.Radiobutton(
            mode_frame,
            text="По событию (проверка по интервалу)",
            variable=self._mode_var,
            value="event",
            command=self._on_mode_change,
        ).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(
            mode_frame,
            text="По времени",
            variable=self._mode_var,
            value="time",
            command=self._on_mode_change,
        ).pack(side="left")

        ttk.Label(body, text="Периодичность").grid(row=3, column=0, sticky="w", pady=5)
        self._schedule = ttk.Combobox(body, values=SCHEDULE_PRESETS, width=42)
        current_schedule = self._alert.get("schedule") or SCHEDULE_PRESETS[0]
        self._schedule.set(current_schedule)
        self._schedule.grid(row=3, column=1, sticky="ew", pady=5, padx=(10, 0))

        self._st_label = ttk.Label(body, text="Время старта")
        self._st_label.grid(row=4, column=0, sticky="w", pady=5)
        st_frame = ttk.Frame(body)
        st_frame.grid(row=4, column=1, sticky="w", pady=5, padx=(10, 0))
        self._st_frame = st_frame

        current_st = self._alert.get("start_time", "") or ""
        if current_st and ":" in current_st:
            try:
                _h_str, _m_str = current_st.split(":", 1)
                init_h, init_m = int(_h_str), int(_m_str)
            except ValueError:
                init_h, init_m = 9, 0
        else:
            init_h, init_m = 9, 0

        self._st_use = tk.BooleanVar(value=bool(current_st))
        self._st_hour = tk.StringVar(value=f"{init_h:02d}")
        self._st_min = tk.StringVar(value=f"{init_m:02d}")

        ttk.Checkbutton(
            st_frame,
            text="Использовать",
            variable=self._st_use,
            command=self._on_start_toggle,
        ).pack(side="left", padx=(0, 12))

        self._st_hour_box = ttk.Spinbox(
            st_frame,
            from_=0,
            to=23,
            width=3,
            format="%02.0f",
            textvariable=self._st_hour,
            wrap=True,
        )
        self._st_hour_box.pack(side="left")
        ttk.Label(st_frame, text=":").pack(side="left", padx=2)
        self._st_min_box = ttk.Spinbox(
            st_frame,
            from_=0,
            to=59,
            increment=5,
            width=3,
            format="%02.0f",
            textvariable=self._st_min,
            wrap=True,
        )
        self._st_min_box.pack(side="left")
        self._on_start_toggle()

        self._st_hint = ttk.Label(
            body,
            text="в таймзоне компании · без галочки — считать от старта приложения",
            foreground="#6b7280",
        )
        self._st_hint.grid(row=5, column=1, sticky="w", padx=(10, 0))

        ttk.Label(body, text="Заметки").grid(row=6, column=0, sticky="nw", pady=(10, 5))
        self._notes = tk.Text(body, width=44, height=4, wrap="word")
        self._notes.insert("1.0", self._alert.get("notes", ""))
        self._notes.grid(row=6, column=1, sticky="ew", pady=(10, 5), padx=(10, 0))

        self._enabled_var = tk.BooleanVar(value=self._alert.get("enabled", True))
        ttk.Checkbutton(
            body, text="Включён", variable=self._enabled_var
        ).grid(row=7, column=1, sticky="w", pady=(8, 0), padx=(10, 0))

        self._wh_var = tk.BooleanVar(
            value=bool(self._alert.get("working_hours_only", False))
        )
        ttk.Checkbutton(
            body,
            text="Только в рабочее время (Пн–Пт, 09:00–18:00 локально)",
            variable=self._wh_var,
        ).grid(row=8, column=1, sticky="w", pady=(2, 0), padx=(10, 0))

        # AI-audit-specific fields (only visible when template == ai_audit)
        self._ai_label = ttk.Label(
            body, text="AI-аудит", foreground="#6b7280",
            font=("Segoe UI", 9, "bold"),
        )
        self._ai_label.grid(row=9, column=0, sticky="w", pady=(12, 4))
        self._ai_frame = ttk.Frame(body)
        self._ai_frame.grid(row=9, column=1, sticky="ew", pady=(12, 4), padx=(10, 0))

        ttk.Label(self._ai_frame, text="Модель:").grid(row=0, column=0, sticky="w")
        self._ai_model = tk.StringVar(value=self._alert.get("model_kind") or "sonnet")
        ttk.Combobox(
            self._ai_frame, textvariable=self._ai_model,
            values=("sonnet", "opus"), state="readonly", width=10,
        ).grid(row=0, column=1, sticky="w", padx=(4, 14))

        ttk.Label(self._ai_frame, text="Чатов max:").grid(row=0, column=2, sticky="w")
        self._ai_chat_limit = tk.IntVar(value=int(self._alert.get("chat_limit") or 500))
        ttk.Spinbox(
            self._ai_frame, from_=10, to=1000, increment=50,
            textvariable=self._ai_chat_limit, width=6,
        ).grid(row=0, column=3, sticky="w", padx=(4, 14))

        ttk.Label(self._ai_frame, text="Период (дн):").grid(row=0, column=4, sticky="w")
        self._ai_period = tk.IntVar(value=int(self._alert.get("period_days") or 1))
        ttk.Spinbox(
            self._ai_frame, from_=1, to=30, increment=1,
            textvariable=self._ai_period, width=4,
        ).grid(row=0, column=5, sticky="w", padx=(4, 0))

        self._on_mode_change()
        self._on_template_change()

        btns = ttk.Frame(self, padding=(18, 0, 18, 18))
        btns.grid(row=1, column=0, sticky="ew")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        try:
            tgt = master.winfo_toplevel()
            mx = tgt.winfo_rootx()
            my = tgt.winfo_rooty()
            mw = tgt.winfo_width()
            mh = tgt.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"+{mx + max(0, (mw - w) // 2)}+{my + max(0, (mh - h) // 3)}")
        except tk.TclError:
            pass
        self.grab_set()
        self._name.focus_set()

    def _on_start_toggle(self) -> None:
        state = "normal" if self._st_use.get() else "disabled"
        self._st_hour_box.configure(state=state)
        self._st_min_box.configure(state=state)

    def _current_template_slug(self) -> str:
        idx = self._template.current()
        if 0 <= idx < len(self._template_slugs):
            return self._template_slugs[idx]
        return ""

    def _on_template_change(self) -> None:
        if self._current_template_slug() == "ai_audit":
            self._ai_label.grid()
            self._ai_frame.grid()
        else:
            self._ai_label.grid_remove()
            self._ai_frame.grid_remove()

    def _on_mode_change(self) -> None:
        if self._mode_var.get() == "time":
            self._st_label.grid()
            self._st_frame.grid()
            self._st_hint.grid()
        else:
            self._st_label.grid_remove()
            self._st_frame.grid_remove()
            self._st_hint.grid_remove()

    def _save(self) -> None:
        name = self._name.get().strip()
        if not name:
            messagebox.showerror("Ошибка", "Введите имя алерта.", parent=self)
            return
        idx = self._template.current()
        if idx < 0:
            messagebox.showerror("Ошибка", "Выберите шаблон.", parent=self)
            return
        mode = self._mode_var.get() or "event"
        if mode == "time" and self._st_use.get():
            try:
                h = int(self._st_hour.get().strip())
                m = int(self._st_min.get().strip())
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Ошибка",
                    "Время старта должно быть HH:MM (00–23, 00–59).",
                    parent=self,
                )
                return
            start_time = f"{h:02d}:{m:02d}"
        else:
            start_time = ""
        new_alert = {
            **self._alert,
            "name": name,
            "template": self._template_slugs[idx],
            "schedule": self._schedule.get().strip() or SCHEDULE_PRESETS[0],
            "trigger_mode": mode,
            "start_time": start_time,
            "notes": self._notes.get("1.0", "end").strip(),
            "enabled": bool(self._enabled_var.get()),
            "working_hours_only": bool(self._wh_var.get()),
        }
        if self._template_slugs[idx] == "ai_audit":
            try:
                cl = int(self._ai_chat_limit.get())
                pd = int(self._ai_period.get())
            except (TypeError, ValueError, tk.TclError):
                messagebox.showerror(
                    "Ошибка", "Чатов и период должны быть числами.", parent=self,
                )
                return
            new_alert.update({
                "model_kind": (self._ai_model.get() or "sonnet").strip(),
                "chat_limit": max(1, cl),
                "period_days": max(1, pd),
            })
        try:
            saved = upsert_bot_alert(self._company.key, self._kind, new_alert)
        except OSError as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{exc}", parent=self)
            return
        if self._on_saved:
            self._on_saved(saved)
        self.destroy()
