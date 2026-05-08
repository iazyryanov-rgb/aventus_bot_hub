import threading
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Optional

from ..data import Company
from ..tree_tester import run_test


META_FG = "#6b7280"
OK_FG = "#16a34a"
ERR_FG = "#dc2626"
TEXT_FG = "#111827"
LINK_FG = "#1d4ed8"


class ActionTreeTestDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        company: Company,
        bot_kind: str,
        bot_kind_label: str,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._bot_kind = bot_kind
        self.title(f"Тест дерева — {bot_kind_label}")
        self.geometry("960x600")
        self.transient(master.winfo_toplevel())

        head = ttk.Frame(self)
        head.pack(fill="x", padx=14, pady=(14, 6))
        ttk.Label(
            head,
            text=f"Тестирование действий для {bot_kind_label}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        self._status = ttk.Label(
            head,
            text="Поиск клиента (90+ DPD), запрос CRM, отправка результатов…",
            foreground=META_FG,
        )
        self._status.pack(anchor="w", pady=(2, 0))
        self._loan_link: Optional[ttk.Label] = None

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(8, 14))

        cols = ("status", "label", "detail")
        self.tree = ttk.Treeview(body, columns=cols, show="headings")
        self.tree.heading("status", text="")
        self.tree.heading("label", text="Путь по дереву")
        self.tree.heading("detail", text="Результат")
        self.tree.column("status", width=40, anchor="center", stretch=False)
        self.tree.column("label", width=320, anchor="w")
        self.tree.column("detail", width=540, anchor="w")
        self.tree.tag_configure("ok", foreground=OK_FG)
        self.tree.tag_configure("err", foreground=ERR_FG)
        scl = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scl.pack(side="right", fill="y")

        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            data = run_test(self._company, self._bot_kind)
        except Exception as exc:
            data = {"fatal": f"{type(exc).__name__}: {exc}",
                    "phone": None, "loan_url": None, "results": []}
        self.after(0, lambda: self._render(data))

    def _render(self, data: dict) -> None:
        if data.get("fatal"):
            self._status.configure(
                text=f"Ошибка: {data['fatal']}", foreground=ERR_FG
            )
            return
        phone = data.get("phone") or "?"
        results = data.get("results") or []
        ok_count = sum(1 for r in results if r.get("ok"))
        self._status.configure(
            text=(
                f"Клиент: {phone}  ·  отправлено путей: {len(results)}  ·  "
                f"OK: {ok_count}  ·  ошибок: {len(results) - ok_count}"
            ),
            foreground=META_FG,
        )

        loan_url = data.get("loan_url")
        if loan_url:
            link = ttk.Label(
                self._status.master,
                text=f"Открыть в CRM: {loan_url}",
                foreground=LINK_FG,
                cursor="hand2",
            )
            link.pack(anchor="w", pady=(2, 0))
            link.bind(
                "<Button-1>", lambda _e, u=loan_url: webbrowser.open(u)
            )
            self._loan_link = link

        for r in results:
            label = r.get("label") or "(без меток)"
            if r.get("ok"):
                glyph = "OK"
                tag = "ok"
                detail = f"HTTP {r.get('status')}"
                if r.get("warnings"):
                    detail += "  ·  предупреждения: " + "; ".join(r["warnings"])
            else:
                glyph = "ERR"
                tag = "err"
                err = r.get("error") or "ошибка"
                resp = (r.get("response") or "").strip().replace("\n", " ")
                if resp:
                    if len(resp) > 240:
                        resp = resp[:240] + "…"
                    detail = f"{err}  ·  {resp}"
                else:
                    detail = err
                if r.get("warnings"):
                    detail += "  ·  предупреждения: " + "; ".join(r["warnings"])
            self.tree.insert("", "end", values=(glyph, label, detail), tags=(tag,))
