import tkinter as tk
from tkinter import ttk
from typing import Optional

from ..alerts import get_bot_alerts
from ..data import Company, is_bot_complete, is_company_complete
from ..i18n import t

KIND_LABELS = {
    None: "Сравнение по компаниям",
    "voice": "Voice Bot · сравнение по компаниям",
    "whatsapp": "WhatsApp Infobip bot · сравнение по компаниям",
    "agents": "Agents · сравнение по компаниям",
}


def _bot_summary(c: Company, kind: str) -> str:
    """Compact summary string per (company, bot kind) for the analytics row."""
    from ..data import load_bot
    if kind == "whatsapp":
        info = load_bot(c.key, "whatsapp")
        sid = info.get("prod_schema_id")
        sname = info.get("prod_schema_name") or ""
        return f"schema {sid} · {sname}" if sid else "—"
    return ""


class AnalyticsPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        companies: list[Company],
        kind: Optional[str],
    ) -> None:
        super().__init__(master)
        self._companies = companies
        self._kind = kind

        ttk.Label(
            self,
            text=t("header_analytics"),
            font=("Segoe UI", 9, "bold"),
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(14, 6))

        ttk.Label(
            self,
            text=KIND_LABELS.get(kind, KIND_LABELS[None]),
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        if kind is None:
            self._render_company_table(body)
        elif kind == "agents":
            self._render_agents_table(body)
        elif kind == "whatsapp":
            self._render_whatsapp_table(body)
        else:
            self._render_voice_table(body)

    def _make_tree(self, parent: tk.Misc, columns: list[tuple[str, str, int]]):
        cols = tuple(c[0] for c in columns)
        tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for col, head, width in columns:
            tree.heading(col, text=head)
            anchor = "center" if col != "name" else "w"
            tree.column(col, width=width, anchor=anchor)
        scl = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scl.set)
        tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")
        return tree

    def _render_company_table(self, parent: tk.Misc) -> None:
        tree = self._make_tree(
            parent,
            [
                ("name", "Компания", 220),
                ("country", "Страна", 110),
                ("tz", "Таймзона", 180),
                ("complete", "Полнота полей", 140),
                ("alerts", "Алертов настроено", 160),
                ("host", "Webitel host", 280),
            ],
        )
        for c in self._companies:
            alerts = sum(
                len(get_bot_alerts(c.key, k))
                for k in ("voice", "whatsapp", "agents")
            )
            complete = "OK" if is_company_complete(c.key) else "не заполнено"
            tree.insert(
                "",
                "end",
                values=(
                    f"{c.code} — {c.name}",
                    c.country,
                    c.timezone,
                    complete,
                    alerts,
                    c.webitel_host,
                ),
            )

    def _render_agents_table(self, parent: tk.Misc) -> None:
        tree = self._make_tree(
            parent,
            [
                ("name", "Компания", 220),
                ("country", "Страна", 110),
                ("alerts", "Алертов агентов", 140),
                ("host", "Webitel host", 320),
            ],
        )
        for c in self._companies:
            alerts = len(get_bot_alerts(c.key, "agents"))
            tree.insert(
                "",
                "end",
                values=(
                    f"{c.code} — {c.name}",
                    c.country,
                    alerts,
                    c.webitel_host,
                ),
            )
        ttk.Label(
            self,
            text="Дальше: тут появится сводка по очередям, агентам онлайн, чек-листу Collection и истории алертов.",
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(0, 12))

    def _render_whatsapp_table(self, parent: tk.Misc) -> None:
        tree = self._make_tree(
            parent,
            [
                ("name", "Компания", 200),
                ("country", "Страна", 100),
                ("schema", "Prod schema", 320),
                ("alerts", "Алертов WhatsApp", 140),
                ("status", "Статус", 110),
            ],
        )
        for c in self._companies:
            alerts = len(get_bot_alerts(c.key, "whatsapp"))
            schema = _bot_summary(c, "whatsapp")
            status = "OK" if is_bot_complete(c.key, "whatsapp") else "warn"
            tree.insert(
                "",
                "end",
                values=(
                    f"{c.code} — {c.name}",
                    c.country,
                    schema,
                    alerts,
                    status,
                ),
            )

    def _render_voice_table(self, parent: tk.Misc) -> None:
        tree = self._make_tree(
            parent,
            [
                ("name", "Компания", 220),
                ("country", "Страна", 110),
                ("alerts", "Алертов Voice", 140),
                ("host", "Webitel host", 320),
            ],
        )
        for c in self._companies:
            alerts = len(get_bot_alerts(c.key, "voice"))
            tree.insert(
                "",
                "end",
                values=(
                    f"{c.code} — {c.name}",
                    c.country,
                    alerts,
                    c.webitel_host,
                ),
            )
        ttk.Label(
            self,
            text="Дальше: тут появятся метрики по голосовому боту — расписание, длина диалога, success rate.",
            foreground="#6b7280",
        ).pack(anchor="w", padx=14, pady=(0, 12))
