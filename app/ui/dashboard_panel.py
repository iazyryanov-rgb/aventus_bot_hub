import json
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Optional
from zoneinfo import ZoneInfo

from ..calendar_cache import get_calendar_accepts
from ..crm_payments import fetch_payments_per_day
from ..crm_results_count import count_results_today
from ..i18n import t
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


def _safe_count_crm_results_today(company) -> Optional[int]:
    try:
        return count_results_today(company)
    except Exception:
        return None


def _safe_fetch_payments(company, day_dates):
    try:
        return fetch_payments_per_day(company, day_dates) or {}
    except Exception:
        return {}


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


class FunnelChart(tk.Frame):
    """Per-queue outbound-call funnel. One compact row per queue with 3
    horizontal bars (Total → After AMD → Handled), each normalised within
    its own row. The widget is a fixed-width card — does not stretch to
    the full window width.

    Render input: list of dicts ordered descending by `attempts`:
        {"name": str, "attempts": int, "amd_machine": int,
         "handled": int, "abandoned": int, "uniq": int}
    """

    BAR_MAX_PX = 130
    BAR_HEIGHT = 14
    QUEUE_LABEL_WIDTH_PX = 200
    BAR_BG = "#f1f5f9"
    STAGE_LABELS = ("total", "AMD pass", "handled")
    # One palette per queue (rotates if there are more queues than
    # palettes). Each entry = (stage1, stage2, stage3) — three shades of
    # the same hue so the funnel narrowing reads visually within the row,
    # while different queues are clearly distinguished by colour.
    QUEUE_PALETTES: tuple[tuple[str, str, str], ...] = (
        ("#7c3aed", "#a78bfa", "#c4b5fd"),  # purple
        ("#2563eb", "#60a5fa", "#93c5fd"),  # blue
        ("#16a34a", "#4ade80", "#86efac"),  # green
        ("#ea580c", "#fb923c", "#fdba74"),  # orange
        ("#db2777", "#f472b6", "#f9a8d4"),  # pink
        ("#0891b2", "#22d3ee", "#67e8f9"),  # cyan
        ("#ca8a04", "#facc15", "#fde047"),  # amber
        ("#475569", "#94a3b8", "#cbd5e1"),  # slate
    )

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(
            master,
            bg=CARD_BG,
            highlightbackground=CARD_BORDER,
            highlightthickness=1,
            bd=0,
        )
        self._holder = tk.Frame(self, bg=CARD_BG)
        self._holder.pack(anchor="w", padx=14, pady=12)

    def render(
        self,
        queues: list[dict],
        *,
        global_total: int = 0,
        amd_machine_total: int = 0,
        crm_total: Optional[int] = None,
    ) -> None:
        """Render per-queue mini-funnels. `queues` should already be
        sorted descending by attempts. `global_total`/`amd_machine_total`
        / `crm_total` are shown as a small footer summary."""
        for w in self._holder.winfo_children():
            w.destroy()
        if not queues:
            tk.Label(
                self._holder, text="нет данных за сегодня",
                bg=CARD_BG, fg=META_FG, font=("Segoe UI", 10),
            ).pack(anchor="w")
            return

        # Header row — neutral grey labels (each queue brings its own
        # colour, so per-stage colour-coding here would just clash).
        header = tk.Frame(self._holder, bg=CARD_BG)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(
            header, text="Очередь",
            bg=CARD_BG, fg=META_FG, font=("Segoe UI", 9, "bold"),
            width=int(self.QUEUE_LABEL_WIDTH_PX / 7) + 2, anchor="w",
        ).pack(side="left")
        for label in self.STAGE_LABELS:
            tk.Label(
                header, text=label,
                bg=CARD_BG, fg=META_FG, font=("Segoe UI", 9, "bold"),
                width=int(self.BAR_MAX_PX / 7) + 14, anchor="w",
            ).pack(side="left", padx=(0, 6))

        # Anchor bars across queues by the LARGEST queue's attempts so
        # bars are comparable between rows.
        anchor = max((int(q.get("attempts") or 0) for q in queues), default=1)
        anchor = max(1, anchor)

        for i, q in enumerate(queues):
            palette = self.QUEUE_PALETTES[i % len(self.QUEUE_PALETTES)]
            self._render_queue_row(q, anchor=anchor, palette=palette)

        # Footer summary (global numbers)
        footer = tk.Frame(self._holder, bg=CARD_BG)
        footer.pack(fill="x", pady=(8, 0))
        bits = [f"всего: <b>{global_total}</b>"]
        if amd_machine_total > 0 and global_total:
            pct = round(amd_machine_total * 100 / global_total)
            bits.append(f"AMD-MACHINE: {amd_machine_total} ({pct}%)")
        if crm_total is not None:
            bits.append(f"CRM: {crm_total}")
        tk.Label(
            footer, text=" · ".join(b.replace("<b>", "").replace("</b>", "") for b in bits),
            bg=CARD_BG, fg=META_FG, font=("Segoe UI", 9),
        ).pack(anchor="w")

    def _render_queue_row(
        self, q: dict, *, anchor: int, palette: tuple[str, str, str],
    ) -> None:
        name = str(q.get("name") or "")
        attempts = int(q.get("attempts") or 0)
        amd_machine = int(q.get("amd_machine") or 0)
        handled = int(q.get("handled") or 0)
        passed_amd = max(attempts - amd_machine, 0)

        row = tk.Frame(self._holder, bg=CARD_BG)
        row.pack(fill="x", pady=3)
        # Coloured dot in the queue name to anchor the row's hue.
        name_holder = tk.Frame(row, bg=CARD_BG)
        name_holder.pack(side="left")
        tk.Label(
            name_holder, text="●",
            bg=CARD_BG, fg=palette[0], font=("Segoe UI", 11),
        ).pack(side="left", padx=(0, 4))
        tk.Label(
            name_holder, text=name,
            bg=CARD_BG, fg=TEXT_FG, font=("Segoe UI", 9),
            width=int(self.QUEUE_LABEL_WIDTH_PX / 7) - 2, anchor="w",
        ).pack(side="left")

        for i, value in enumerate((attempts, passed_amd, handled)):
            self._render_stage(row, value, anchor, color=palette[i])

    def _render_stage(
        self, parent: tk.Frame, value: int, anchor: int, *, color: str,
    ) -> None:
        cell = tk.Frame(parent, bg=CARD_BG)
        cell.pack(side="left", padx=(0, 6))
        ratio = max(0.0, min(1.0, value / anchor)) if anchor else 0.0
        bar_px = max(2, int(ratio * self.BAR_MAX_PX)) if value else 0
        canvas = tk.Canvas(
            cell, width=self.BAR_MAX_PX, height=self.BAR_HEIGHT,
            bg=self.BAR_BG, highlightthickness=0,
        )
        canvas.pack(side="left")
        if bar_px > 0:
            canvas.create_rectangle(
                0, 0, bar_px, self.BAR_HEIGHT,
                fill=color, outline="",
            )
        tk.Label(
            cell, text=str(value),
            bg=CARD_BG, fg=color, font=("Segoe UI", 9, "bold"),
            width=5, anchor="w",
        ).pack(side="left", padx=(4, 0))


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
        self._top_extras: dict = {}
        self._highlight_range: Optional[tuple[float, float]] = None
        self._tt = _Tooltip(self)
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Leave>", lambda _e: self._tt.hide())

    def set_highlight(self, start_label, end_label) -> None:
        if start_label is None or end_label is None:
            self._highlight_range = None
        else:
            try:
                self._highlight_range = (float(start_label), float(end_label))
            except (TypeError, ValueError):
                self._highlight_range = None
        self._redraw()

    def set_data(
        self,
        labels: list[str],
        groups: list[tuple[str, list[tuple[str, list[int], str]]]],
        lines: Optional[list[tuple]] = None,
        top_extras: Optional[dict] = None,
    ) -> None:
        """`lines` items are tuples (name, values, color) or
        (name, values, color, tooltips) where `tooltips` is a list of
        per-point custom text strings (multi-line allowed).

        `top_extras` maps `(group_idx, bucket_idx) -> (text, color)` and is
        rendered above the bar's accumulated total."""
        self._labels = labels
        self._groups = groups
        self._lines = lines or []
        self._top_extras = top_extras or {}
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

        # Max value for the Y-axis = stacked totals across groups only.
        # Lines (e.g. payments) are drawn against their own independent
        # scale so a high-magnitude line doesn't squash the bars.
        max_val = 0
        for _gn, segments in self._groups:
            for di in range(n):
                total = 0
                for _sn, values, _c in segments:
                    if di < len(values):
                        total += values[di]
                if total > max_val:
                    max_val = total
        max_val = max_val or 1
        max_lines = 0
        for _ln, lvalues, _c, *_rest in self._lines:
            for v in lvalues:
                if v > max_lines:
                    max_lines = v
        max_lines = max_lines or 1

        # Highlight band (e.g. queue working hours).
        if self._highlight_range is not None:
            try:
                lvals = [float(x) for x in self._labels]
            except ValueError:
                lvals = []
            if lvals:
                hs, he = self._highlight_range
                slot_w_h = chart_w / n
                # Find index by closest label.
                def _idx_for(val: float) -> float:
                    nearest = min(range(len(lvals)), key=lambda i: abs(lvals[i] - val))
                    return nearest
                # Map to x-positions covering the FULL slot of the bucket.
                if hs <= he:
                    i0 = _idx_for(hs)
                    i1 = _idx_for(he)
                    x_start = pad_l + slot_w_h * i0
                    x_end = pad_l + slot_w_h * (i1 + 1)
                    self.create_rectangle(
                        x_start, pad_t, x_end, pad_t + chart_h,
                        fill="#fef9c3", outline="",
                    )

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
                extra = self._top_extras.get((gi, di))
                if extra:
                    extra_text, extra_color = extra
                    if extra_text:
                        y_above = base_y - chart_h * (accum / max_val) - 12
                        self.create_text(
                            (x0 + x1) / 2, y_above - 2, text=extra_text,
                            anchor="s", fill=extra_color,
                            font=("Segoe UI", 8, "bold"),
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
            # Reserve a band so the line doesn't overlap the very top labels.
            line_band = chart_h * 0.85
            line_top = pad_t + (chart_h - line_band)
            for di in range(n):
                v = lvalues[di] if di < len(lvalues) else 0
                x = pad_l + slot_w * di + slot_w / 2
                y = line_top + line_band - line_band * (v / max_lines)
                pts.extend([x, y])
            if len(pts) >= 4:
                self.create_line(*pts, fill=lcolor, width=2, smooth=False)
            for di in range(n):
                v = lvalues[di] if di < len(lvalues) else 0
                x = pad_l + slot_w * di + slot_w / 2
                y = line_top + line_band - line_band * (v / max_lines)
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
        for ln, _v, color, *_rest in self._lines:
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


class QueueChecklistCard(ttk.Frame):
    """Грид-карточка G1/G2/G3 × Main/APTP/BPTP/Chat. Каждая ячейка — id
    очереди (или ✗); при наведении на ячейку зовётся `on_hover(start, end)`
    с диапазоном рабочих часов из календаря очереди (или None при leave)."""

    def __init__(self, master, on_hover=None) -> None:
        super().__init__(master, style="Card.TFrame")
        self._on_hover = on_hover
        try:
            ttk.Style(self).configure("Card.TFrame", background=CARD_BG)
        except tk.TclError:
            pass

        ttk.Label(
            self,
            text=t("dash_card_queues"),
            foreground=META_FG,
            background=CARD_BG,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=10, pady=(8, 4))
        self._grid = ttk.Frame(self, style="Card.TFrame")
        self._grid.pack(fill="x", padx=10, pady=(0, 8))

    def set_grid(self, rows: list) -> None:
        for w in self._grid.winfo_children():
            w.destroy()
        if not rows:
            ttk.Label(
                self._grid, text="—", foreground=META_FG, background=CARD_BG,
            ).grid(row=0, column=0, sticky="w")
            return
        # Header row.
        ttk.Label(
            self._grid, text="", background=CARD_BG,
        ).grid(row=0, column=0, padx=(0, 8))
        for ci, sub in enumerate(DashboardPanel.SUBS, start=1):
            ttk.Label(
                self._grid, text=sub, foreground=META_FG, background=CARD_BG,
                font=("Segoe UI", 8, "bold"),
            ).grid(row=0, column=ci, padx=(0, 12))
        for ri, row in enumerate(rows, start=1):
            grp = DashboardPanel.GROUPS[ri - 1] if ri - 1 < len(DashboardPanel.GROUPS) else f"G{ri}"
            ttk.Label(
                self._grid, text=grp, foreground=META_FG, background=CARD_BG,
                font=("Segoe UI", 8, "bold"),
            ).grid(row=ri, column=0, sticky="w", padx=(0, 8))
            for ci, cell in enumerate(row, start=1):
                if cell.get("present"):
                    text = f"✓ id {cell['id']}"
                    color = "#16a34a"
                else:
                    text = "✗ нет"
                    color = "#dc2626"
                lbl = tk.Label(
                    self._grid, text=text, fg=color, bg=CARD_BG,
                    font=("Segoe UI", 9), cursor="hand2",
                )
                lbl.grid(row=ri, column=ci, sticky="w", padx=(0, 12))
                if cell.get("present"):
                    hs = cell.get("hour_start")
                    he = cell.get("hour_end")
                    name = cell.get("name") or ""
                    tip = name + (
                        f"  ·  {hs:02d}:00–{he:02d}:00"
                        if hs is not None and he is not None
                        else ""
                    )
                    lbl.bind(
                        "<Enter>",
                        lambda _e, s=hs, e=he, t=tip: self._fire(s, e, t),
                    )
                    lbl.bind("<Leave>", lambda _e: self._fire(None, None, ""))

    def _fire(self, start, end, _tip):
        if self._on_hover:
            try:
                self._on_hover(start, end)
            except Exception:
                pass


BACKGROUND_REFRESH_MIN = 15  # фон-рефрешер тикает реже, чем foreground


class DashboardPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        company: Company,
        background: bool = False,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._background = background
        self._cache: dict = load_cache(company.key)
        self._auto_after_id: Optional[str] = None
        self._worker_running: bool = False
        if background:
            self._auto_minutes: int = BACKGROUND_REFRESH_MIN
        else:
            self._auto_minutes = int(
                load_settings().get("dashboard_refresh_min", DEFAULT_REFRESH_MIN) or 0
            )

        ttk.Label(
            self,
            text=t("dash_header"),
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
        ttk.Label(controls, text=t("dash_period")).pack(side="left")
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

        ttk.Label(controls, text=t("dash_sector")).pack(side="left")
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

        ttk.Label(controls, text=t("dash_auto")).pack(side="left")
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
        self._card_dialogs = StatCard(cards, t("dash_card_chats"), RESPONDED_COLOR)
        self._card_dialogs.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._queues_card = QueueChecklistCard(
            cards, on_hover=self._on_queue_hover
        )
        self._queues_card.grid(row=0, column=1, sticky="nsew", padx=6)
        self._card_agents = StatCard(
            cards, t("dash_card_agents"), AGENTS_COLOR
        )
        self._card_agents.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        # Воронка исходящих за сегодня: 4 стадии в виде горизонтальных
        # баров, ширина каждой = доля от total. Компактный блок (не тянется
        # на всю ширину окна — функцию «обзор drop-off» он покрывает
        # лучше чем 3 карточки в ряд с длинной подписью).
        funnel_box = ttk.Frame(self)
        funnel_box.pack(anchor="w", fill="x", padx=14, pady=(0, 8))
        self._funnel_title = ttk.Label(
            funnel_box,
            text=t("dash_funnel"),
            font=("Segoe UI", 10, "bold"),
        )
        self._funnel_title.pack(anchor="w")
        self._funnel = FunnelChart(funnel_box)
        self._funnel.pack(anchor="w", pady=(6, 0))

        # Communications chart with day/hour toggle. Title row holds two
        # segmented-style buttons — only one chart is shown at a time.
        chart_section = ttk.Frame(self)
        chart_section.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        title_bar = ttk.Frame(chart_section)
        title_bar.pack(fill="x")
        self._chart_view_var = tk.StringVar(value="days")
        self._chart_title = ttk.Label(
            title_bar, text=t("dash_chart_days"),
            font=("Segoe UI", 10, "bold"),
        )
        self._chart_title.pack(side="left")
        toggle = ttk.Frame(title_bar)
        toggle.pack(side="right")
        self._chart_btn_days = ttk.Button(
            toggle, text="📅 По дням",
            command=lambda: self._set_chart_view("days"),
        )
        self._chart_btn_days.pack(side="left", padx=(0, 4))
        self._chart_btn_hours = ttk.Button(
            toggle, text="🕐 По часам",
            command=lambda: self._set_chart_view("hours"),
        )
        self._chart_btn_hours.pack(side="left")

        # Day chart container.
        self._chart_days_box = ttk.Frame(chart_section)
        self._chart = BarChart(self._chart_days_box, height=240)
        self._chart.pack(fill="both", expand=True, pady=(6, 0))

        # Hour chart container — same parent, hidden by default.
        self._chart_hours_box = ttk.Frame(chart_section)
        self._hour_chart = BarChart(self._chart_hours_box, height=240)
        self._hour_chart.pack(fill="both", expand=True, pady=(6, 0))
        # Hour-chart subtitle (timezone) lives inside the hour container
        # so it shows only when that view is active.
        self._hour_title = ttk.Label(
            self._chart_hours_box,
            text=f"08–20 ({company.timezone or 'UTC'})",
            foreground=META_FG, font=("Segoe UI", 9),
        )
        self._hour_title.pack(anchor="w", pady=(0, 4), before=self._hour_chart)

        self._set_chart_view("days")

        self.bind("<Destroy>", self._on_destroy, add="+")

        self._render_from_cache()
        self._reload()

    def _set_chart_view(self, view: str) -> None:
        """Toggle between days and hours chart. Only one is packed at
        a time — minimises vertical space + makes the active view obvious.
        Active button is rendered with the Accent style; inactive in
        normal. Also re-renders the chats counter — when the operator
        is looking at hours, "Чатов" should be today only (not the whole
        period)."""
        view = "hours" if view == "hours" else "days"
        self._chart_view_var.set(view)
        try:
            if view == "days":
                self._chart_hours_box.pack_forget()
                self._chart_days_box.pack(fill="both", expand=True, pady=(6, 0))
                self._chart_title.configure(text=t("dash_chart_days"))
                self._chart_btn_days.configure(style="Accent.TButton")
                self._chart_btn_hours.configure(style="TButton")
            else:
                self._chart_days_box.pack_forget()
                self._chart_hours_box.pack(fill="both", expand=True, pady=(6, 0))
                self._chart_title.configure(text=t("dash_chart_hours"))
                self._chart_btn_hours.configure(style="Accent.TButton")
                self._chart_btn_days.configure(style="TButton")
        except tk.TclError:
            pass
        snap = getattr(self, "_last_snapshot", None)
        if snap:
            self._render_dialogs_card_from_snapshot(snap)

    def _render_dialogs_card_from_snapshot(self, snap: dict) -> None:
        """Pick the right total / responded / pending based on the
        current chart-view toggle: period numbers when 'days', today
        only when 'hours'."""
        view = getattr(self, "_chart_view_var", None)
        is_hours = bool(view and view.get() == "hours")
        if is_hours:
            total = int(snap.get("today_dialogs_total") or 0)
            responded = int(snap.get("today_dialogs_responded") or 0)
            pending = int(snap.get("today_dialogs_pending") or 0)
            scope = "сегодня"
        else:
            total = int(snap.get("dialogs_total") or 0)
            responded = int(snap.get("dialogs_responded") or 0)
            pending = int(snap.get("dialogs_pending") or 0)
            scope = "за период"
        self._card_dialogs.set_value(
            str(total),
            sub=f"ответили: {responded} · ждут ответа: {pending} · {scope}",
        )

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
            self._queues_card.set_grid([])
            self._card_agents.set_value("…")
            self._status.configure(text=t("dash_no_cache"), foreground=META_FG)
            return
        self._apply_snapshot(snap, from_cache=True)

    def _apply_snapshot(self, snap: dict, from_cache: bool) -> None:
        agents = snap.get("agents", {}) or {}
        online = int(agents.get("online") or 0)
        pause = int(agents.get("pause") or 0)
        total = int(agents.get("total") or 0)
        # Stash the snapshot so the toggle handler can re-render counters
        # without reloading data.
        self._last_snapshot = snap
        self._render_dialogs_card_from_snapshot(snap)
        self._card_agents.set_value(
            str(online), sub=f"online · pause {pause} · total {total}"
        )
        labels = list(snap.get("buckets") or [])
        d_responded = list(snap.get("d_responded") or [])
        d_pending = list(snap.get("d_pending") or [])
        c_inbound = list(snap.get("c_inbound") or [])
        c_outbound = list(snap.get("c_outbound") or [])
        co_amd = list(snap.get("co_amd") or [0] * len(c_outbound))
        co_to_op = list(snap.get("co_to_op") or [0] * len(c_outbound))
        co_talk = list(snap.get("co_talk") or [0] * len(c_outbound))
        # Pad-on-mismatch (legacy snapshots).
        while len(co_amd) < len(c_outbound): co_amd.append(0)
        while len(co_to_op) < len(c_outbound): co_to_op.append(0)
        while len(co_talk) < len(c_outbound): co_talk.append(0)
        calls_total = int(snap.get("calls_total") or 0)
        ci_total = sum(c_inbound)
        co_total = sum(c_outbound)
        self._queues_card.set_grid(snap.get("queue_grid") or [])

        # Воронка только за сегодня (в TZ компании).
        co_today = snap.get("co_today") or {}
        t_total = int(co_today.get("total") or 0)
        t_machine = int(co_today.get("amd_machine") or 0)
        t_human = int(co_today.get("amd_human") or 0)
        t_notsure = int(co_today.get("amd_notsure") or 0)
        t_handled = int(co_today.get("handled") or 0)
        t_abandoned = int(co_today.get("abandoned") or 0)
        t_queues = co_today.get("queues") or {}
        t_crm = co_today.get("crm_results_today")

        def _pct(num: int, den: int) -> str:
            if not den:
                return "—"
            return f"{round(num * 100 / den)}%"

        # Build per-queue mini-funnels (Total → AMD pass → Handled).
        queue_rows: list[dict] = []
        if isinstance(t_queues, dict) and t_queues:
            for name, stat in t_queues.items():
                if not isinstance(stat, dict):
                    # Legacy snapshot format — still show as flat row.
                    queue_rows.append({
                        "name": name,
                        "attempts": int(stat),
                        "amd_machine": 0,
                        "handled": 0,
                        "abandoned": 0,
                    })
                    continue
                queue_rows.append({
                    "name": name,
                    "attempts":    int(stat.get("attempts") or 0),
                    "amd_machine": int(stat.get("amd_machine") or 0),
                    "handled":     int(stat.get("handled") or 0),
                    "abandoned":   int(stat.get("abandoned") or 0),
                })
            queue_rows.sort(key=lambda r: -r["attempts"])

        crm_count = int(t_crm) if isinstance(t_crm, int) else None
        self._funnel.render(
            queue_rows,
            global_total=t_total,
            amd_machine_total=t_machine,
            crm_total=crm_count,
        )
        try:
            today_label = snap.get("h_today") or ""
            self._funnel_title.configure(
                text=(
                    "Воронка исходящих звонков · сегодня"
                    + (f" {today_label}" if today_label else "")
                )
            )
        except tk.TclError:
            pass
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
            lines = [(t("series_payments_sum"), p_sums, PAYMENTS_COLOR, tips)]
        self._chart.set_data(
            labels,
            [
                (
                    "Чаты",
                    [
                        (t("series_responded"), d_responded, RESPONDED_COLOR),
                        (t("series_pending"), d_pending, PENDING_COLOR),
                    ],
                ),
                (
                    "Звонки",
                    [
                        (t("series_inbound"), c_inbound, INBOUND_COLOR),
                        # Исходящие — стек воронки снизу вверх:
                        # реальные разговоры → переведено (но не разговор) →
                        # AMD HUMAN (не доведено до оператора) → остальные попытки.
                        (
                            t("series_real_talk"),
                            list(co_talk),
                            "#6d28d9",
                        ),
                        (
                            t("series_to_operator"),
                            [max(0, op - tk) for op, tk in zip(co_to_op, co_talk)],
                            "#8b5cf6",
                        ),
                        (
                            t("series_amd_passed"),
                            [max(0, am - op) for am, op in zip(co_amd, co_to_op)],
                            "#a78bfa",
                        ),
                        (
                            t("series_other_attempts"),
                            [max(0, ob - am) for ob, am in zip(c_outbound, co_amd)],
                            OUTBOUND_COLOR,
                        ),
                    ],
                ),
            ],
            lines=lines,
        )
        h_today = snap.get("h_today") or ""
        tz_label = self._company.timezone or "UTC"
        # The chart's main title is the toggle's section header; here
        # we only show the time-window + tz subtitle next to the bars.
        subtitle = f"08–20 ({tz_label})"
        if h_today:
            subtitle += f" · {t('dash_today')} {h_today}"
        try:
            self._hour_title.configure(text=subtitle)
        except tk.TclError:
            pass
        h_labels = list(snap.get("h_buckets") or [])
        h_d_resp = list(snap.get("h_d_responded") or [])
        h_d_pen = list(snap.get("h_d_pending") or [])
        h_ci = list(snap.get("h_c_inbound") or [])
        h_co = list(snap.get("h_c_outbound") or [])
        if h_labels:
            self._hour_chart.set_data(
                h_labels,
                [
                    (
                        "Чаты",
                        [
                            (t("series_responded"), h_d_resp, RESPONDED_COLOR),
                            (t("series_pending"), h_d_pen, PENDING_COLOR),
                        ],
                    ),
                    (
                        "Звонки",
                        [
                            (t("series_inbound"), h_ci, INBOUND_COLOR),
                            (t("series_outbound"), h_co, OUTBOUND_COLOR),
                        ],
                    ),
                ],
                lines=[],
            )
        else:
            self._hour_chart.set_data([], [], lines=[])

        ts = snap.get("ts_ms")
        # Surface the dialogs data source on the right of the status
        # line. `pg` = Postgres via Grafana (full coverage); `rest` =
        # legacy REST path (filtered, undercount); `rest!` = REST after
        # a Grafana attempt failed → operator should know it's stale.
        src = getattr(self, "_last_dialogs_source", "")
        if src == "grafana":
            src_tag = "  ·  src: pg"
            src_color = TEXT_FG
        elif src == "rest-fallback":
            err = getattr(self, "_last_dialogs_error", "")
            src_tag = f"  ·  src: rest! (Grafana fail: {err[:60]})"
            src_color = "#dc2626"
        elif src == "rest":
            src_tag = "  ·  src: rest"
            src_color = META_FG
        else:
            src_tag = ""
            src_color = TEXT_FG
        if ts:
            tz = self._tz()
            stamp = datetime.fromtimestamp(int(ts) / 1000, tz=tz).strftime(
                "%d.%m %H:%M"
            )
            tag = t("dash_from_cache") if from_cache else t("dash_updated")
            self._status.configure(
                text=f"{tag} · {stamp}{src_tag}",
                foreground=src_color if src == "rest-fallback" else TEXT_FG,
            )
        else:
            self._status.configure(text=t("dash_ready"), foreground=TEXT_FG)

    # ---------- network ----------

    def _on_queue_hover(self, hour_start, hour_end) -> None:
        try:
            self._hour_chart.set_highlight(hour_start, hour_end)
        except Exception:
            pass

    def _reload(self, auto: bool = False) -> None:
        # Debounce: don't fire a new worker while the previous one for the
        # same panel hasn't finished.
        if getattr(self, "_worker_running", False):
            return
        # Skip-on-fresh: foreground panels open right after a background
        # refresh have a snapshot younger than 30 sec — no point re-fetching.
        if not auto:
            snap = get_snapshot(self._cache, self._snapshot_key())
            if snap and (time.time() * 1000 - int(snap.get("ts_ms") or 0)) < 30_000:
                self._apply_snapshot(snap, from_cache=True)
                return
        self._worker_running = True
        if not auto:
            self._reload_btn.configure(state="disabled")
        if not auto:
            self._status.configure(text=t("dash_loading"), foreground=META_FG)
        threading.Thread(target=self._worker, args=(auto,), daemon=True).start()

    def _worker(self, auto: bool) -> None:
        try:
            self._worker_inner(auto)
            self._worker_running = False
            return
        except Exception as exc:
            self._worker_running = False
            # Never let an uncaught error leave the button disabled or stop
            # auto-refresh — log a status and re-schedule.
            msg = f"{type(exc).__name__}: {exc}"
            def _on_err() -> None:
                if not self.winfo_exists():
                    return
                if not auto:
                    try:
                        self._reload_btn.configure(state="normal")
                    except tk.TclError:
                        pass
                try:
                    self._status.configure(
                        text=f"Ошибка обновления: {msg}", foreground="#dc2626"
                    )
                except tk.TclError:
                    pass
                self._schedule_auto()
            try:
                self.after(0, _on_err)
            except tk.TclError:
                pass

    def _worker_inner(self, auto: bool) -> None:
        client = WebitelClient(
            self._company.webitel_host, self._company.webitel_access_token
        )
        period_days = self._period_days()
        sector = self._sector_key()
        snap_key = f"{period_days}_{sector}"
        since_ms, until_ms, buckets = self._period_range()
        tz = self._tz()
        err: Optional[str] = None

        # Все независимые HTTP/DB запросы пускаем параллельно — это даёт
        # самый заметный выигрыш на медленных эндпоинтах.
        day_dates = [b.date() for b in buckets]
        with ThreadPoolExecutor(max_workers=8) as pool:
            f_dialogs = pool.submit(self._fetch_dialogs, client, since_ms, until_ms)
            f_calls = pool.submit(self._fetch_calls, client, since_ms, until_ms)
            f_aq = pool.submit(client.list_queues, [0, 1, 4, 5, 10])
            f_cq = pool.submit(client.list_queues, [6])
            f_pay = pool.submit(_safe_fetch_payments, self._company, day_dates)
            f_crm = pool.submit(_safe_count_crm_results_today, self._company)

            try:
                dialogs_list = f_dialogs.result()
            except WebitelError as e:
                dialogs_list = []
                err = str(e)
            try:
                calls_list = f_calls.result()
            except WebitelError as e:
                calls_list = []
                if err is None:
                    err = str(e)
            try:
                all_queues = f_aq.result()
            except WebitelError:
                all_queues = []
            try:
                chat_queues = f_cq.result()
            except WebitelError:
                chat_queues = []
            try:
                pay_map = f_pay.result() or {}
            except Exception:
                pay_map = {}
            try:
                crm_today_count = f_crm.result()
            except Exception:
                crm_today_count = None
        queue_grid = self._build_queue_grid(client, all_queues, chat_queues, tz)
        qid_to_sector: dict[int, str] = {}
        for q in all_queues:
            qid = getattr(q, "id", None)
            if qid is None:
                continue
            if self._is_collection_queue(q):
                qid_to_sector[int(qid)] = "collection"
            elif self._is_cc_queue(q):
                qid_to_sector[int(qid)] = "cc"

        def _call_in_sector(call: dict) -> bool:
            if sector == "all":
                return True
            q = call.get("queue") or {}
            qid = q.get("id") if isinstance(q, dict) else None
            try:
                qid_int = int(qid) if qid is not None else None
            except (TypeError, ValueError):
                qid_int = None
            if qid_int is not None:
                return qid_to_sector.get(qid_int, "") == sector
            # Fallback: name-based heuristic when call has no queue id.
            qname = ""
            if isinstance(q, dict):
                qname = str(q.get("name") or "")
            if sector == "cc":
                return "CC" in qname
            if sector == "collection":
                return bool(qname) and "CC" not in qname
            return True

        def _chat_in_sector(d: dict) -> bool:
            """Sector classifier for chat dialogs:
              * 'all' — keep everything.
              * 'collection' / 'cc' — keep chats whose escalation queue
                belongs to that team. Bot-only chats (no queue) are
                kept regardless — we can't classify them by sector
                without process_name/flow mapping, and excluding them
                would silently kill ~85% of the count."""
            if sector == "all":
                return True
            if not d.get("queued"):
                # Bot-only — keep on every sector view; subtitle
                # explains the breakdown.
                return True
            team = str(d.get("queue_team") or "").lower()
            if not team:
                return True
            if sector == "collection":
                return "collection" in team
            if sector == "cc":
                return "cc" in team or "client" in team
            return True

        tz = self._tz()
        d_counts = [0] * len(buckets)
        d_responded = [0] * len(buckets)
        d_pending = [0] * len(buckets)
        # Hourly buckets 08..20 (13 hours), only for "today" in the
        # company's timezone (independent of the selected period).
        HOURS = list(range(8, 21))
        today_local = datetime.now(tz).date()
        h_d_responded = [0] * len(HOURS)
        h_d_pending = [0] * len(HOURS)
        h_c_inbound = [0] * len(HOURS)
        h_c_outbound = [0] * len(HOURS)
        # Today-only chat counts — feed the "Чатов" counter when the
        # operator switches the chart toggle to "По часам". Counter
        # widget reads them from the snapshot.
        today_dialogs_total = 0
        today_dialogs_responded = 0
        today_dialogs_pending = 0
        sector_filtered_dialogs: list[dict] = []
        for d in dialogs_list:
            if not _chat_in_sector(d):
                continue
            sector_filtered_dialogs.append(d)
            ts = self._to_ms(d.get("started") or d.get("date"))
            idx = self._bucket_index(ts, buckets, tz)
            if 0 <= idx < len(buckets):
                d_counts[idx] += 1
                if _bot_responded(d):
                    d_responded[idx] += 1
                else:
                    d_pending[idx] += 1
            if ts is not None:
                try:
                    dt_local = datetime.fromtimestamp(ts / 1000, tz=tz)
                except Exception:
                    dt_local = None
                if dt_local is not None and dt_local.date() == today_local:
                    today_dialogs_total += 1
                    if _bot_responded(d):
                        today_dialogs_responded += 1
                    else:
                        today_dialogs_pending += 1
                    h = dt_local.hour
                    if h in HOURS:
                        hi = HOURS.index(h)
                        if _bot_responded(d):
                            h_d_responded[hi] += 1
                        else:
                            h_d_pending[hi] += 1
        c_counts = [0] * len(buckets)
        c_inbound = [0] * len(buckets)
        c_outbound = [0] * len(buckets)
        # Per-day outbound funnel (для столбчатого чарта).
        co_amd = [0] * len(buckets)
        co_to_op = [0] * len(buckets)
        co_talk = [0] * len(buckets)
        # Today-only outbound funnel (для верхних карточек).
        co_today_total = 0
        co_today_amd_machine = 0
        co_today_amd_human = 0
        co_today_amd_notsure = 0
        co_today_handled = 0
        co_today_abandoned = 0
        # queue stats: name -> {"attempts": int, "destinations": set[str]}
        co_today_queue_stats: dict[str, dict] = {}
        for c in calls_list:
            if not _call_in_sector(c):
                continue
            ts = self._to_ms(c.get("created_at") or c.get("answered_at"))
            idx = self._bucket_index(ts, buckets, tz)
            direction = str(c.get("direction") or "").lower()
            if ts is not None:
                try:
                    dt_local = datetime.fromtimestamp(ts / 1000, tz=tz)
                except Exception:
                    dt_local = None
                if dt_local is not None and dt_local.date() == today_local:
                    h = dt_local.hour
                    if h in HOURS:
                        hi = HOURS.index(h)
                        if direction == "inbound":
                            h_c_inbound[hi] += 1
                        else:
                            h_c_outbound[hi] += 1
            if 0 <= idx < len(buckets):
                c_counts[idx] += 1
                if direction == "inbound":
                    c_inbound[idx] += 1
                else:
                    c_outbound[idx] += 1
                    amd = str(c.get("amd_result") or "").upper()
                    bridged = c.get("bridged_at") or 0
                    try:
                        bridged_ms = int(bridged) if bridged else 0
                    except (TypeError, ValueError):
                        bridged_ms = 0
                    try:
                        talk = int(c.get("talk_sec") or 0)
                    except (TypeError, ValueError):
                        talk = 0
                    agent_id = c.get("agent_id")
                    if amd == "HUMAN":
                        co_amd[idx] += 1
                    if bridged_ms > 0 or agent_id:
                        co_to_op[idx] += 1
                    handled = (bridged_ms > 0 or agent_id) and talk >= 10
                    if handled:
                        co_talk[idx] += 1
                    # Today-only outbound funnel.
                    if (
                        dt_local is not None
                        and dt_local.date() == today_local
                    ):
                        co_today_total += 1
                        if amd == "MACHINE":
                            co_today_amd_machine += 1
                        elif amd == "HUMAN":
                            co_today_amd_human += 1
                        elif amd in ("NOTSURE", "NOT_SURE"):
                            co_today_amd_notsure += 1
                        if handled:
                            co_today_handled += 1
                        elif amd != "MACHINE" and (
                            bridged_ms > 0 or c.get("answered_at")
                        ):
                            co_today_abandoned += 1
                        q = c.get("queue")
                        qname = ""
                        if isinstance(q, dict):
                            qname = str(q.get("name") or "").strip()
                        elif isinstance(q, str):
                            qname = q.strip()
                        if qname:
                            stats = co_today_queue_stats.setdefault(
                                qname, {
                                    "attempts": 0,
                                    "destinations": set(),
                                    "amd_machine": 0,
                                    "handled": 0,
                                    "abandoned": 0,
                                },
                            )
                            stats["attempts"] += 1
                            dest = str(c.get("destination") or "").strip()
                            if dest:
                                stats["destinations"].add(dest)
                            if amd == "MACHINE":
                                stats["amd_machine"] += 1
                            if handled:
                                stats["handled"] += 1
                            elif amd != "MACHINE" and (
                                bridged_ms > 0 or c.get("answered_at")
                            ):
                                stats["abandoned"] += 1

        # Unique agents across queues (an agent may sit in many queues).
        unique: dict[int, str] = {}
        queues = list(all_queues)
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

        # `pay_map` уже получен параллельно выше.
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
            "dialogs_total": len(sector_filtered_dialogs),
            "dialogs_responded": sum(d_responded),
            "dialogs_pending": sum(d_pending),
            "today_dialogs_total": today_dialogs_total,
            "today_dialogs_responded": today_dialogs_responded,
            "today_dialogs_pending": today_dialogs_pending,
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
            "queue_grid": queue_grid,
            "co_amd": co_amd,
            "co_to_op": co_to_op,
            "co_talk": co_talk,
            "co_today": {
                "total": co_today_total,
                "amd_machine": co_today_amd_machine,
                "amd_human": co_today_amd_human,
                "amd_notsure": co_today_amd_notsure,
                "handled": co_today_handled,
                "abandoned": co_today_abandoned,
                "queues": {
                    name: {
                        "attempts": s["attempts"],
                        "uniq": len(s["destinations"]),
                        "amd_machine": s.get("amd_machine", 0),
                        "handled": s.get("handled", 0),
                        "abandoned": s.get("abandoned", 0),
                    }
                    for name, s in co_today_queue_stats.items()
                },
                "crm_results_today": crm_today_count,
            },
            "h_today": today_local.strftime("%d.%m.%Y"),
            "h_buckets": [f"{h:02d}" for h in HOURS],
            "h_d_responded": h_d_responded,
            "h_d_pending": h_d_pending,
            "h_c_inbound": h_c_inbound,
            "h_c_outbound": h_c_outbound,
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

    # With dedup-by-id pagination protection, hitting more than ~10 pages
    # means Webitel ignored `?page=N` and we already detected the loop.
    MAX_PAGES = 20

    PAGE_SIZE = 500

    GROUPS = ("G1", "G2", "G3")
    SUBS = ("Main", "APTP", "BPTP", "Chat")

    @staticmethod
    def _has_token(name: str, token: str) -> bool:
        import re
        pattern = r"(?:^|[^A-Za-z0-9])" + re.escape(token) + r"(?:$|[^A-Za-z0-9])"
        return re.search(pattern, name or "", re.IGNORECASE) is not None

    def _build_queue_grid(
        self,
        client: WebitelClient,
        agent_queues,
        chat_queues,
        tz: ZoneInfo,
    ) -> list[list[dict]]:
        """Return a 3×4 grid (G1/G2/G3 × Main/APTP/BPTP/Chat). Each cell:
        {"present": bool, "id": int|None, "name": str|None,
         "calendar_id": int|None, "hour_start": int|None, "hour_end": int|None}
        """
        # Map (group, sub) → queue.
        def _pick_voice(group: str, sub: str):
            for q in agent_queues:
                if not q.enabled:
                    continue
                name = q.name or ""
                if not name.lstrip().lower().startswith("collection"):
                    continue
                if self._has_token(name, group) and self._has_token(name, sub):
                    return q
            return None

        def _pick_chat(group: str):
            for q in chat_queues:
                if not q.enabled:
                    continue
                name = q.name or ""
                if "collection" not in name.lower():
                    continue
                if self._has_token(name, group):
                    return q
            return None

        # Cache calendar fetches across worker calls (file-backed, TTL 6h).
        cal_cache: dict[int, tuple[Optional[int], Optional[int]]] = {}
        weekday_today = datetime.now(tz).weekday()  # 0..6 (Mon..Sun)

        def _hours_for(cal_id: Optional[int]):
            if not cal_id:
                return (None, None)
            if cal_id in cal_cache:
                return cal_cache[cal_id]
            accepts = get_calendar_accepts(
                self._company.key, int(cal_id), client.get_calendar
            )
            if accepts is None:
                cal_cache[cal_id] = (None, None)
                return (None, None)
            # Webitel days: 1=Mon..7=Sun (or 0=Sun..6=Sat depending on tenant).
            # Try matching weekday, falling back to first non-disabled entry.
            target = None
            for a in accepts:
                if a.get("disabled"):
                    continue
                day = a.get("day")
                if day is None:
                    continue
                # try: 1..7 with Mon=1
                if int(day) - 1 == weekday_today:
                    target = a
                    break
                # try: 0..6 with Mon=0
                if int(day) == weekday_today:
                    target = a
                    break
            if target is None:
                for a in accepts:
                    if not a.get("disabled"):
                        target = a
                        break
            if target is None:
                cal_cache[cal_id] = (None, None)
                return (None, None)
            s = target.get("start_time_of_day") or 0
            e = target.get("end_time_of_day") or 0
            try:
                s = int(s); e = int(e)
            except (TypeError, ValueError):
                cal_cache[cal_id] = (None, None)
                return (None, None)
            # Detect units: minutes (<= 1440) or seconds.
            if max(s, e) > 1440:
                s //= 60; e //= 60
            res = (s // 60, max(s // 60, (e + 59) // 60))
            cal_cache[cal_id] = res
            return res

        rows: list[list[dict]] = []
        for g in self.GROUPS:
            row: list[dict] = []
            for s in self.SUBS:
                q = _pick_chat(g) if s == "Chat" else _pick_voice(g, s)
                if q is None:
                    row.append({
                        "present": False, "id": None, "name": None,
                        "calendar_id": None,
                        "hour_start": None, "hour_end": None,
                    })
                    continue
                cal_id = getattr(q.calendar, "id", None) if q.calendar else None
                hs, he = _hours_for(cal_id)
                row.append({
                    "present": True,
                    "id": int(q.id),
                    "name": q.name or "",
                    "calendar_id": int(cal_id) if cal_id else None,
                    "hour_start": hs,
                    "hour_end": he,
                })
            rows.append(row)
        return rows

    def _paginate(
        self,
        client: WebitelClient,
        path_for_page,
        items_field: str,
    ) -> list[dict]:
        """Generic paginator with hard duplicate protection.

        Webitel's `?page=N` is sometimes silently ignored — the same page is
        returned over and over. We detect this two ways:
          * Compound de-dup key (id + created_at + destination) — items
            already seen are skipped.
          * If a page brings *zero* new items (everything is a duplicate of
            previous pages) we stop — pagination is clearly broken.
        Also stop on a short page (`len < page_size`) and on `next=False`.
        """
        def _key(it: dict):
            iid = it.get("id")
            if iid is not None:
                # Stringify so a hash mismatch from int/str variants is
                # impossible.
                return f"id:{iid}"
            ca = it.get("created_at") or it.get("date") or ""
            dest = it.get("destination")
            if isinstance(dest, (dict, list)):
                dest = json.dumps(dest, sort_keys=True)
            return f"k:{ca}:{dest}"

        out: list[dict] = []
        seen: set = set()
        for page in range(1, self.MAX_PAGES + 1):
            data = client._get(path_for_page(page))
            items = data.get(items_field) or []
            new_items: list[dict] = []
            for it in items:
                k = _key(it)
                if k in seen:
                    continue
                seen.add(k)
                new_items.append(it)
            if not new_items:
                # Either page is empty, or the API returned the same items
                # we already have. Either way — stop.
                break
            out.extend(new_items)
            if len(items) < self.PAGE_SIZE:
                break
            if data.get("next") is False:
                break
        return out

    def _fetch_dialogs(self, client: WebitelClient, since: int, until: int) -> list[dict]:
        # Prefer Grafana → Postgres path: REST `/chat/dialogs` is filtered
        # by the API user's RBAC (HQ_access usually misses bot-only chats),
        # so on a typical day it returns ~13% of the actual volume. The
        # Postgres view through Grafana sees everything in
        # `chat.conversation` regardless of membership.
        self._last_dialogs_source = "rest"
        self._last_dialogs_error = ""
        try:
            from .. import grafana_pg
        except ImportError:
            grafana_pg = None  # type: ignore[assignment]

        if grafana_pg is not None and grafana_pg.is_configured(self._company.key):
            try:
                # Per-company WA-number filter (otherwise multi-tenant
                # Webitel domains return mixed traffic).
                wa_number = ""
                try:
                    from ..wa_bot_config import load_raw as _wa_load_raw
                    wa_cfg = (
                        ((_wa_load_raw().get(self._company.key) or {})
                         .get("bots") or {})
                        .get("whatsapp") or {}
                    )
                    wa_number = str(wa_cfg.get("bot_phone_number") or "").strip()
                except Exception:
                    wa_number = ""
                rows = grafana_pg.list_chat_conversations(
                    since, until,
                    company_key=self._company.key,
                    channel=None,
                    whatsapp_number=wa_number or None,
                    limit=10000,
                )
                # Convert grafana rows → dict with the fields the rest of
                # the snapshot-builder reads. `_bot_responded` reads
                # `message.sender.id` and checks if it equals dialog id —
                # we synthesise that flag from queued/bridged so:
                #   queued=False OR bridged=True → bot/agent responded
                #   queued=True AND NOT bridged  → still pending in queue
                # That maps to "ответили / ждут ответа" close enough for
                # the dashboard counter while we're missing chat.message
                # data on the bot-only path.
                out: list[dict] = []
                for r in rows:
                    chat_id = str(r.get("id") or "")
                    if not chat_id:
                        continue
                    queued = bool(r.get("queued"))
                    bridged = bool(r.get("bridged"))
                    responded = (not queued) or bridged
                    sender_id = chat_id if responded else "client"
                    started_ms = int(float(r.get("created_at_ms") or 0))
                    closed_ms = int(float(r.get("closed_at_ms") or 0)) or started_ms
                    out.append({
                        "id": chat_id,
                        "started": started_ms,
                        "date": closed_ms,
                        "from": {"name": str(r.get("peer_name") or "")},
                        "message": {
                            "sender": {"id": sender_id},
                            "date": closed_ms,
                        },
                        # Sector classification — only present for chats
                        # that joined a queue. Bot-only chats have
                        # queue_team=None and aren't sector-filtered.
                        "queue_team": r.get("queue_team"),
                        "queued": queued,
                    })
                self._last_dialogs_source = "grafana"
                return out
            except Exception as e:
                # Don't swallow silently — the operator needs to know
                # when REST fallback (with its undercount) kicks in.
                # Persist the reason for the status line to surface.
                self._last_dialogs_source = "rest-fallback"
                self._last_dialogs_error = f"{type(e).__name__}: {e}"
                try:
                    from .._logging import dashboard_log  # type: ignore
                    dashboard_log(self._company.key, "grafana_fetch_failed", str(e))
                except Exception:
                    pass
        return self._paginate(
            client,
            lambda p: (
                f"/chat/dialogs?size={self.PAGE_SIZE}&page={p}"
                f"&date.since={since}&date.until={until}"
            ),
            items_field="data",
        )

    def _fetch_calls(self, client: WebitelClient, since: int, until: int) -> list[dict]:
        return self._paginate(
            client,
            lambda p: (
                f"/calls/history?size={self.PAGE_SIZE}&page={p}"
                f"&created_at.from={since}&created_at.to={until}"
                f"&fields=id&fields=created_at&fields=answered_at"
                f"&fields=direction&fields=amd_result&fields=bridged_at"
                f"&fields=talk_sec&fields=agent_id&fields=cause"
                f"&fields=queue&fields=destination"
            ),
            items_field="items",
        )

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
