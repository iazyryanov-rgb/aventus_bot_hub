import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Optional
from zoneinfo import ZoneInfo

from ..crm_payments import fetch_payments_per_day
from ..dashboard_cache import (
    get_snapshot,
    load_cache,
    put_snapshot,
    save_cache,
)
from ..data import Company
from ..settings import load_settings, save_settings
from ..webitel import WebitelClient, WebitelError

PERIODS: list[tuple[str, int]] = [
    ("Сегодня", 1),
    ("Последние 7 дней", 7),
    ("Последние 30 дней", 30),
]

SECTORS: list[tuple[str, str]] = [
    ("Все", "all"),
    ("Collection", "collection"),
    ("КЦ", "cc"),
]

REFRESH_OPTIONS: list[tuple[str, int]] = [
    ("Выкл", 0),
    ("1 мин", 1),
    ("5 мин", 5),
    ("15 мин", 15),
    ("30 мин", 30),
]
DEFAULT_REFRESH_MIN = 5

CARD_BG = "#f9fafb"
CARD_BORDER = "#e5e7eb"
META_FG = "#6b7280"
TEXT_FG = "#111827"
AGENTS_COLOR = "#ea580c"
RESPONDED_COLOR = "#16a34a"   # зелёный — чаты с ответом бота/агента
PENDING_COLOR = "#dc2626"     # красный — чаты без ответа
INBOUND_COLOR = "#2563eb"     # синий — входящие звонки
OUTBOUND_COLOR = "#7c3aed"    # фиолетовый — исходящие звонки
PAYMENTS_COLOR = "#f59e0b"    # жёлтый — линия успешных платежей


def _fmt_money(v: float) -> str:
    try:
        return f"{int(round(v)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def _bot_responded(d: dict) -> bool:
    """Heuristic from /chat/dialogs list: in WhatsApp/messenger dialogs,
    `dialog.id` equals the bot/agent's channel id, while the client peer has
    a different channel id. So if last message sender id == dialog id, the
    bot/agent had the last word — i.e. the client got an answer."""
    msg = d.get("message") or {}
    sender = (msg.get("sender") or {}).get("id")
    if not sender:
        return False
    return str(sender) == str(d.get("id"))

STATUS_RANK = {"online": 3, "pause": 2, "offline": 1}


def _better_status(a: str, b: str) -> str:
    return a if STATUS_RANK.get(a, 0) >= STATUS_RANK.get(b, 0) else b


class StatCard(tk.Frame):
    def __init__(self, master: tk.Misc, title: str, accent: str) -> None:
        super().__init__(
            master,
            bg=CARD_BG,
            highlightbackground=CARD_BORDER,
            highlightthickness=1,
            bd=0,
        )
        tk.Label(
            self, text=title, fg=META_FG, bg=CARD_BG, font=("Segoe UI", 9)
        ).pack(anchor="w", padx=14, pady=(10, 0))
        self._value = tk.Label(
            self, text="—", fg=accent, bg=CARD_BG, font=("Segoe UI", 22, "bold")
        )
        self._value.pack(anchor="w", padx=14, pady=(2, 12))
        self._sub = tk.Label(
            self, text="", fg=META_FG, bg=CARD_BG, font=("Segoe UI", 9)
        )
        self._sub.pack(anchor="w", padx=14, pady=(0, 10))

    def set_value(self, value: str, sub: str = "") -> None:
        self._value.configure(text=value)
        self._sub.configure(text=sub)


class _Tooltip:
    """Minimal tk-canvas tooltip — single hover bubble with white text."""

    def __init__(self, parent: tk.Misc) -> None:
        self._parent = parent
        self._tw: Optional[tk.Toplevel] = None
        self._lbl: Optional[tk.Label] = None

    def show(self, x_root: int, y_root: int, text: str) -> None:
        if self._tw is None or not self._tw.winfo_exists():
            self._tw = tk.Toplevel(self._parent)
            try:
                self._tw.wm_overrideredirect(True)
            except tk.TclError:
                pass
            self._tw.attributes("-topmost", True)
            self._lbl = tk.Label(
                self._tw,
                text=text,
                bg="#111827",
                fg="#ffffff",
                padx=8,
                pady=4,
                font=("Segoe UI", 9),
            )
            self._lbl.pack()
        else:
            if self._lbl is not None:
                self._lbl.configure(text=text)
        try:
            self._tw.wm_geometry(f"+{x_root + 12}+{y_root + 16}")
        except tk.TclError:
            pass

    def hide(self) -> None:
        if self._tw is not None:
            try:
                self._tw.destroy()
            except tk.TclError:
                pass
            self._tw = None
            self._lbl = None


class BarChart(tk.Canvas):
    """Grouped + stacked bar chart.

    `groups` is a list of (group_name, segments) pairs. Each group renders as
    one bar per day; segments stack inside that bar from bottom up. Use a
    single-segment group for a non-stacked metric."""

    def __init__(self, master: tk.Misc, height: int = 220) -> None:
        super().__init__(master, height=height, bg="#ffffff", highlightthickness=0)
        self._groups: list[tuple[str, list[tuple[str, list[int], str]]]] = []
        self._lines: list[tuple[str, list[int], str]] = []
        self._labels: list[str] = []
        self._tt = _Tooltip(self)
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Leave>", lambda _e: self._tt.hide())

    def set_data(
        self,
        labels: list[str],
        groups: list[tuple[str, list[tuple[str, list[int], str]]]],
        lines: Optional[list[tuple]] = None,
    ) -> None:
        """`lines` items are tuples (name, values, color) or
        (name, values, color, tooltips) where `tooltips` is a list of
        per-point custom text strings (multi-line allowed)."""
        self._labels = labels
        self._groups = groups
        self._lines = lines or []
        self._redraw()

    def _redraw(self) -> None:
        self._tt.hide()
        self.delete("all")
        if not self._labels or not self._groups:
            return
        w = max(self.winfo_width(), 200)
        h = max(self.winfo_height(), 160)
        pad_l, pad_r, pad_t, pad_b = 40, 14, 38, 28
        chart_w = w - pad_l - pad_r
        chart_h = h - pad_t - pad_b
        n = len(self._labels)
        if n == 0:
            return

        # Max value = max stacked total across all groups & days, plus lines
        max_val = 0
        for _gn, segments in self._groups:
            for di in range(n):
                total = 0
                for _sn, values, _c in segments:
                    if di < len(values):
                        total += values[di]
                if total > max_val:
                    max_val = total
        for _ln, lvalues, _c in self._lines:
            for v in lvalues:
                if v > max_val:
                    max_val = v
        max_val = max_val or 1

        # Y axis ticks
        for i in range(5):
            y = pad_t + chart_h - (chart_h * i / 4)
            v = int(round(max_val * i / 4))
            self.create_line(pad_l, y, w - pad_r, y, fill="#f3f4f6")
            self.create_text(
                pad_l - 6, y, text=str(v), anchor="e",
                fill=META_FG, font=("Segoe UI", 8),
            )

        n_groups = len(self._groups)
        slot_w = chart_w / n
        bar_w = max(10, slot_w / (n_groups + 1))
        for di, label in enumerate(self._labels):
            x_center = pad_l + slot_w * di + slot_w / 2
            for gi, (gname, segments) in enumerate(self._groups):
                x0 = x_center - (n_groups * bar_w) / 2 + gi * bar_w + 2
                x1 = x0 + bar_w - 4
                accum = 0
                base_y = pad_t + chart_h
                for sn, values, color in segments:
                    v = values[di] if di < len(values) else 0
                    if v <= 0:
                        continue
                    seg_h = chart_h * (v / max_val)
                    y1 = base_y - chart_h * (accum / max_val)
                    y0 = y1 - seg_h
                    rect = self.create_rectangle(
                        x0, y0, x1, y1, fill=color, outline=""
                    )
                    tip = f"{label} · {gname}: {sn} = {v}"
                    self.tag_bind(
                        rect, "<Enter>",
                        lambda e, t=tip: self._tt.show(e.x_root, e.y_root, t),
                    )
                    self.tag_bind(
                        rect, "<Motion>",
                        lambda e, t=tip: self._tt.show(e.x_root, e.y_root, t),
                    )
                    self.tag_bind(rect, "<Leave>", lambda _e: self._tt.hide())
                    accum += v
                if accum:
                    y_top = base_y - chart_h * (accum / max_val)
                    self.create_text(
                        (x0 + x1) / 2, y_top - 2, text=str(accum),
                        anchor="s", fill=TEXT_FG, font=("Segoe UI", 8),
                    )
            self.create_text(
                x_center, pad_t + chart_h + 6, text=label, anchor="n",
                fill=META_FG, font=("Segoe UI", 8),
            )

        # Line series overlay
        for line in self._lines:
            line_name = line[0]
            lvalues = line[1]
            lcolor = line[2]
            tips = line[3] if len(line) > 3 else None
            pts: list[float] = []
            for di in range(n):
                v = lvalues[di] if di < len(lvalues) else 0
                x = pad_l + slot_w * di + slot_w / 2
                y = pad_t + chart_h - chart_h * (v / max_val)
                pts.extend([x, y])
            if len(pts) >= 4:
                self.create_line(*pts, fill=lcolor, width=2, smooth=False)
            for di in range(n):
                v = lvalues[di] if di < len(lvalues) else 0
                x = pad_l + slot_w * di + slot_w / 2
                y = pad_t + chart_h - chart_h * (v / max_val)
                dot = self.create_oval(
                    x - 3, y - 3, x + 3, y + 3,
                    fill=lcolor, outline="#ffffff", width=1,
                )
                day_label = self._labels[di] if di < len(self._labels) else ""
                if tips and di < len(tips) and tips[di]:
                    tip = tips[di]
                else:
                    tip = f"{day_label} · {line_name}: {v}"
                self.tag_bind(
                    dot, "<Enter>",
                    lambda e, t=tip: self._tt.show(e.x_root, e.y_root, t),
                )
                self.tag_bind(
                    dot, "<Motion>",
                    lambda e, t=tip: self._tt.show(e.x_root, e.y_root, t),
                )
                self.tag_bind(dot, "<Leave>", lambda _e: self._tt.hide())

        # Legend at the top (above the chart) so it never overlaps day labels.
        seen: set[tuple[str, str]] = set()
        legend: list[tuple[str, str]] = []
        for _gn, segments in self._groups:
            for sn, _v, color in segments:
                key = (sn, color)
                if key in seen:
                    continue
                seen.add(key)
                legend.append(key)
        for ln, _v, color in self._lines:
            key = (ln, color)
            if key in seen:
                continue
            seen.add(key)
            legend.append(key)
        lx, ly = pad_l, 16
        for name, color in legend:
            self.create_rectangle(lx, ly - 6, lx + 12, ly + 4, fill=color, outline="")
            self.create_text(
                lx + 16, ly - 1, text=name, anchor="w",
                fill=TEXT_FG, font=("Segoe UI", 9),
            )
            lx += 16 + len(name) * 7 + 22


class DashboardPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company
        self._cache: dict = load_cache(company.key)
        self._auto_after_id: Optional[str] = None
        self._auto_minutes: int = int(
            load_settings().get("dashboard_refresh_min", DEFAULT_REFRESH_MIN) or 0
        )

        ttk.Label(
            self,
            text="ДАШБОРД",
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))

        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Label(controls, text="Период:").pack(side="left")
        self._period_var = tk.StringVar(value=PERIODS[1][0])
        period_box = ttk.Combobox(
            controls,
            textvariable=self._period_var,
            values=[name for name, _ in PERIODS],
            state="readonly",
            width=22,
        )
        period_box.pack(side="left", padx=(4, 14))
        period_box.bind("<<ComboboxSelected>>", lambda _e: self._on_period_change())

        ttk.Label(controls, text="Сектор:").pack(side="left")
        self._sector_var = tk.StringVar(value="Collection")
        sector_box = ttk.Combobox(
            controls,
            textvariable=self._sector_var,
            values=[name for name, _ in SECTORS],
            state="readonly",
            width=12,
        )
        sector_box.pack(side="left", padx=(4, 14))
        sector_box.bind("<<ComboboxSelected>>", lambda _e: self._on_period_change())

        ttk.Label(controls, text="Авто-обновление:").pack(side="left")
        current_label = next(
            (n for n, m in REFRESH_OPTIONS if m == self._auto_minutes),
            f"{self._auto_minutes} мин" if self._auto_minutes else "Выкл",
        )
        self._auto_var = tk.StringVar(value=current_label)
        auto_box = ttk.Combobox(
            controls,
            textvariable=self._auto_var,
            values=[n for n, _ in REFRESH_OPTIONS],
            state="readonly",
            width=10,
        )
        auto_box.pack(side="left", padx=(4, 14))
        auto_box.bind("<<ComboboxSelected>>", lambda _e: self._on_auto_change())

        self._reload_btn = ttk.Button(controls, text="Обновить", command=self._reload)
        self._reload_btn.pack(side="left")
        self._status = ttk.Label(controls, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(14, 0))

        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=14, pady=(0, 12))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.columnconfigure(2, weight=1)
        self._card_dialogs = StatCard(cards, "Чатов / WhatsApp", RESPONDED_COLOR)
        self._card_dialogs.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._card_calls = StatCard(cards, "Звонков", INBOUND_COLOR)
        self._card_calls.grid(row=0, column=1, sticky="nsew", padx=6)
        self._card_agents = StatCard(
            cards, "Агентов сейчас (уникально)", AGENTS_COLOR
        )
        self._card_agents.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        chart_box = ttk.Frame(self)
        chart_box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        ttk.Label(
            chart_box, text="Коммуникации по дням", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w")
        self._chart = BarChart(chart_box, height=240)
        self._chart.pack(fill="both", expand=True, pady=(6, 0))

        self.bind("<Destroy>", self._on_destroy, add="+")

        self._render_from_cache()
        self._reload()

    # ---------- helpers ----------

    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self._company.timezone or "UTC")
        except Exception:
            return ZoneInfo("UTC")

    def _period_days(self) -> int:
        return next((d for n, d in PERIODS if n == self._period_var.get()), 7)

    def _sector_key(self) -> str:
        return next((s for n, s in SECTORS if n == self._sector_var.get()), "all")

    def _snapshot_key(self) -> str:
        return f"{self._period_days()}_{self._sector_key()}"

    @staticmethod
    def _is_collection_queue(q) -> bool:
        cal = getattr(q, "calendar", None)
        return bool(cal and "collection" in (cal.name or "").lower())

    @staticmethod
    def _is_cc_queue(q) -> bool:
        return "CC" in (getattr(q, "name", None) or "")

    def _period_range(self) -> tuple[int, int, list[datetime]]:
        days = self._period_days()
        tz = self._tz()
        now = datetime.now(tz)
        start = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        buckets = [start + timedelta(days=i) for i in range(days)]
        return int(start.timestamp() * 1000), int(now.timestamp() * 1000), buckets

    # ---------- auto refresh ----------

    def _on_destroy(self, _e: tk.Event) -> None:
        if self._auto_after_id:
            try:
                self.after_cancel(self._auto_after_id)
            except tk.TclError:
                pass
            self._auto_after_id = None

    def _schedule_auto(self) -> None:
        if self._auto_after_id:
            try:
                self.after_cancel(self._auto_after_id)
            except tk.TclError:
                pass
            self._auto_after_id = None
        if self._auto_minutes <= 0 or not self.winfo_exists():
            return
        self._auto_after_id = self.after(
            self._auto_minutes * 60 * 1000, self._auto_tick
        )

    def _auto_tick(self) -> None:
        self._auto_after_id = None
        if not self.winfo_exists():
            return
        self._reload(auto=True)

    def _on_auto_change(self) -> None:
        label = self._auto_var.get()
        minutes = next((m for n, m in REFRESH_OPTIONS if n == label), 0)
        self._auto_minutes = minutes
        s = load_settings()
        s["dashboard_refresh_min"] = minutes
        save_settings(s)
        self._schedule_auto()

    def _on_period_change(self) -> None:
        self._render_from_cache()
        self._reload()

    # ---------- cache rendering ----------

    def _render_from_cache(self) -> None:
        snap = get_snapshot(self._cache, self._snapshot_key())
        if not snap:
            self._card_dialogs.set_value("…")
            self._card_calls.set_value("…")
            self._card_agents.set_value("…")
            self._status.configure(text="Нет данных в кеше — загружаем…", foreground=META_FG)
            return
        self._apply_snapshot(snap, from_cache=True)

    def _apply_snapshot(self, snap: dict, from_cache: bool) -> None:
        agents = snap.get("agents", {}) or {}
        online = int(agents.get("online") or 0)
        pause = int(agents.get("pause") or 0)
        total = int(agents.get("total") or 0)
        dialogs_total = int(snap.get("dialogs_total") or 0)
        dialogs_responded = int(snap.get("dialogs_responded") or 0)
        dialogs_pending = int(snap.get("dialogs_pending") or 0)
        self._card_dialogs.set_value(
            str(dialogs_total),
            sub=f"ответили: {dialogs_responded} · ждут ответа: {dialogs_pending}",
        )
        self._card_agents.set_value(
            str(online), sub=f"online · pause {pause} · total {total}"
        )
        labels = list(snap.get("buckets") or [])
        d_responded = list(snap.get("d_responded") or [])
        d_pending = list(snap.get("d_pending") or [])
        if not d_responded and not d_pending:
            d_responded = list(snap.get("d_counts") or [])
            d_pending = [0] * len(d_responded)
        c_counts = list(snap.get("c_counts") or [])
        c_inbound = list(snap.get("c_inbound") or [])
        c_outbound = list(snap.get("c_outbound") or [])
        if not c_inbound and not c_outbound and c_counts:
            # legacy snapshot — fall back to single bucket
            c_outbound = c_counts
            c_inbound = [0] * len(c_counts)
        calls_total = int(snap.get("calls_total") or 0)
        ci_total = sum(c_inbound)
        co_total = sum(c_outbound)
        self._card_calls.set_value(
            str(calls_total),
            sub=f"входящих: {ci_total} · исходящих: {co_total}",
        )
        p_counts = list(snap.get("p_counts") or [])
        p_sums = list(snap.get("p_sums") or [])
        p_breakdown = list(snap.get("p_breakdown") or [])
        lines = []
        if p_sums and any(p_sums):
            tips: list[str] = []
            for i, label in enumerate(labels):
                bk = p_breakdown[i] if i < len(p_breakdown) else {}
                count = int(bk.get("count", 0) or 0)
                total = float(bk.get("sum", 0) or 0)
                avg = total / count if count else 0.0
                close_c = int(bk.get("close_count", 0) or 0)
                close_s = float(bk.get("close_sum", 0) or 0)
                prol_c = int(bk.get("prolong_count", 0) or 0)
                prol_s = float(bk.get("prolong_sum", 0) or 0)
                part_c = int(bk.get("partial_count", 0) or 0)
                part_s = float(bk.get("partial_sum", 0) or 0)
                tips.append(
                    f"{label} · Платежи\n"
                    f"Сумма: {_fmt_money(total)}\n"
                    f"Кол-во: {count}  · средний {_fmt_money(avg)}\n"
                    f"Закрытие: {close_c}  ({_fmt_money(close_s)})\n"
                    f"Пролонгация: {prol_c}  ({_fmt_money(prol_s)})\n"
                    f"Частичный: {part_c}  ({_fmt_money(part_s)})"
                )
            lines = [("Платежи (сумма)", p_sums, PAYMENTS_COLOR, tips)]
        elif any(p_counts):
            # legacy snapshot — fall back to count-line
            lines = [("Платежи", p_counts, PAYMENTS_COLOR)]
        self._chart.set_data(
            labels,
            [
                (
                    "Чаты",
                    [
                        ("Ответили клиенту", d_responded, RESPONDED_COLOR),
                        ("Ждут ответа", d_pending, PENDING_COLOR),
                    ],
                ),
                (
                    "Звонки",
                    [
                        ("Входящие", c_inbound, INBOUND_COLOR),
                        ("Исходящие", c_outbound, OUTBOUND_COLOR),
                    ],
                ),
            ],
            lines=lines,
        )
        ts = snap.get("ts_ms")
        if ts:
            tz = self._tz()
            stamp = datetime.fromtimestamp(int(ts) / 1000, tz=tz).strftime(
                "%d.%m %H:%M"
            )
            tag = "из кеша" if from_cache else "обновлено"
            self._status.configure(text=f"{tag} · {stamp}", foreground=TEXT_FG)
        else:
            self._status.configure(text="Готово", foreground=TEXT_FG)

    # ---------- network ----------

    def _reload(self, auto: bool = False) -> None:
        if not auto:
            self._reload_btn.configure(state="disabled")
        if not auto:
            self._status.configure(text="Загрузка…", foreground=META_FG)
        threading.Thread(target=self._worker, args=(auto,), daemon=True).start()

    def _worker(self, auto: bool) -> None:
        client = WebitelClient(
            self._company.webitel_host, self._company.webitel_access_token
        )
        period_days = self._period_days()
        sector = self._sector_key()
        snap_key = f"{period_days}_{sector}"
        since_ms, until_ms, buckets = self._period_range()
        err: Optional[str] = None

        try:
            dialogs_list = self._fetch_dialogs(client, since_ms, until_ms)
        except WebitelError as e:
            dialogs_list = []
            err = str(e)
        try:
            calls_list = self._fetch_calls(client, since_ms, until_ms)
        except WebitelError as e:
            calls_list = []
            if err is None:
                err = str(e)

        tz = self._tz()
        d_counts = [0] * len(buckets)
        d_responded = [0] * len(buckets)
        d_pending = [0] * len(buckets)
        for d in dialogs_list:
            ts = self._to_ms(d.get("started") or d.get("date"))
            idx = self._bucket_index(ts, buckets, tz)
            if 0 <= idx < len(buckets):
                d_counts[idx] += 1
                if _bot_responded(d):
                    d_responded[idx] += 1
                else:
                    d_pending[idx] += 1
        c_counts = [0] * len(buckets)
        c_inbound = [0] * len(buckets)
        c_outbound = [0] * len(buckets)
        for c in calls_list:
            ts = self._to_ms(c.get("created_at") or c.get("answered_at"))
            idx = self._bucket_index(ts, buckets, tz)
            if 0 <= idx < len(buckets):
                c_counts[idx] += 1
                direction = str(c.get("direction") or "").lower()
                if direction == "inbound":
                    c_inbound[idx] += 1
                else:
                    c_outbound[idx] += 1

        # Unique agents across queues (an agent may sit in many queues).
        unique: dict[int, str] = {}
        try:
            queues = client.list_queues(types=[0, 1, 4, 5, 10])
        except WebitelError:
            queues = []
        if sector == "collection":
            queues = [q for q in queues if self._is_collection_queue(q)]
        elif sector == "cc":
            queues = [q for q in queues if self._is_cc_queue(q)]
        if queues:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(
                    pool.map(
                        lambda q: self._safe_queue_agents(client, q.id), queues
                    )
                )
            for pairs in results:
                for aid, status in pairs:
                    prev = unique.get(aid)
                    unique[aid] = status if prev is None else _better_status(prev, status)
        ag_total = len(unique)
        ag_online = sum(1 for s in unique.values() if s == "online")
        ag_pause = sum(1 for s in unique.values() if s == "pause")

        # CRM-DB: payments per day (optional, per-company)
        try:
            day_dates = [b.date() for b in buckets]
            pay_map = fetch_payments_per_day(self._company, day_dates) or {}
        except Exception:
            pay_map = {}
        p_counts: list[int] = []
        p_sums: list[float] = []
        p_breakdown: list[dict] = []
        for d in day_dates:
            stats = pay_map.get(d.strftime("%Y-%m-%d")) or {}
            p_counts.append(int(stats.get("count", 0) or 0))
            p_sums.append(float(stats.get("sum", 0) or 0))
            p_breakdown.append(
                {
                    "count": int(stats.get("count", 0) or 0),
                    "sum": float(stats.get("sum", 0) or 0),
                    "close_count": int(stats.get("close_count", 0) or 0),
                    "close_sum": float(stats.get("close_sum", 0) or 0),
                    "prolong_count": int(stats.get("prolong_count", 0) or 0),
                    "prolong_sum": float(stats.get("prolong_sum", 0) or 0),
                    "partial_count": int(stats.get("partial_count", 0) or 0),
                    "partial_sum": float(stats.get("partial_sum", 0) or 0),
                }
            )

        snapshot = {
            "ts_ms": int(time.time() * 1000),
            "dialogs_total": len(dialogs_list),
            "dialogs_responded": sum(d_responded),
            "dialogs_pending": sum(d_pending),
            "calls_total": len(calls_list),
            "calls_inbound": sum(c_inbound),
            "calls_outbound": sum(c_outbound),
            "payments_total": sum(p_counts),
            "payments_sum_total": sum(p_sums),
            "agents": {"online": ag_online, "pause": ag_pause, "total": ag_total},
            "buckets": [b.strftime("%d.%m") for b in buckets],
            "d_counts": d_counts,
            "d_responded": d_responded,
            "d_pending": d_pending,
            "c_counts": c_counts,
            "c_inbound": c_inbound,
            "c_outbound": c_outbound,
            "p_counts": p_counts,
            "p_sums": p_sums,
            "p_breakdown": p_breakdown,
        }
        put_snapshot(self._cache, snap_key, snapshot)
        save_cache(self._company.key, self._cache)

        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_after_fetch(snapshot, err, auto))

    @staticmethod
    def _safe_queue_agents(client: WebitelClient, qid: int) -> list[tuple[int, str]]:
        try:
            return client.list_queue_agents(qid)
        except WebitelError:
            return []

    MAX_PAGES = 80  # safety cap: up to 40k items per metric per period

    def _fetch_dialogs(self, client: WebitelClient, since: int, until: int) -> list[dict]:
        out: list[dict] = []
        for page in range(1, self.MAX_PAGES + 1):
            path = (
                f"/chat/dialogs?size=500&page={page}"
                f"&date.since={since}&date.until={until}"
            )
            data = client._get(path)
            items = data.get("data") or []
            out.extend(items)
            if not data.get("next") or not items:
                break
        return out

    def _fetch_calls(self, client: WebitelClient, since: int, until: int) -> list[dict]:
        out: list[dict] = []
        for page in range(1, self.MAX_PAGES + 1):
            path = (
                f"/calls/history?size=500&page={page}"
                f"&created_at.from={since}&created_at.to={until}"
                f"&fields=id&fields=created_at&fields=answered_at"
                f"&fields=direction"
            )
            data = client._get(path)
            items = data.get("items") or []
            out.extend(items)
            if not data.get("next") or not items:
                break
        return out

    @staticmethod
    def _to_ms(v) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bucket_index(
        ts_ms: Optional[int], buckets: list[datetime], tz: ZoneInfo
    ) -> int:
        if ts_ms is None:
            return -1
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=tz)
        except Exception:
            return -1
        for i, b in enumerate(buckets):
            if b <= dt < b + timedelta(days=1):
                return i
        return -1

    def _render_after_fetch(
        self, snapshot: dict, error: Optional[str], auto: bool
    ) -> None:
        if not self.winfo_exists():
            return
        if not auto:
            self._reload_btn.configure(state="normal")
        self._apply_snapshot(snapshot, from_cache=False)
        if error:
            self._status.configure(
                text=f"Часть данных не загрузилась: {error}",
                foreground="#dc2626",
            )
        self._schedule_auto()
