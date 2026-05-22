import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..data import (
    Company,
    is_bot_complete,
    is_company_complete,
    latest_build_date,
    load_bot,
    load_companies,
    now_in_timezone,
    save_bot,
)
from ..i18n import t
from ..sectors import DEFAULT_SECTOR, SECTORS, sector_label_key
from ..webitel import WebitelClient, WebitelError, find_whatsapp_infobip_prod

BG = "#ffffff"
HOVER_BG = "#f3f4f6"
TEXT = "#111827"
HEADER = "#6b7280"
CHECK_ON_FILL = "#2563eb"
CHECK_OFF_BORDER = "#9ca3af"
STATUS_WARN = "#dc2626"
STATUS_OK = "#16a34a"
STATUS_ERROR = "#ea580c"


class Checkbox(tk.Canvas):
    SIZE = 18

    def __init__(
        self,
        master: tk.Misc,
        checked: bool = False,
        command: Optional[Callable[[bool], None]] = None,
        bg: str = BG,
    ) -> None:
        super().__init__(
            master,
            width=self.SIZE,
            height=self.SIZE,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._checked = checked
        self._command = command
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, value: bool) -> None:
        if self._checked == value:
            return
        self._checked = value
        self._draw()

    def set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._draw()

    def _on_click(self, _e: tk.Event) -> None:
        self._checked = not self._checked
        self._draw()
        if self._command:
            self._command(self._checked)

    def _draw(self) -> None:
        self.delete("all")
        s = self.SIZE
        r = 4
        if self._checked:
            self._rounded(1, 1, s - 1, s - 1, r, fill=CHECK_ON_FILL, outline=CHECK_ON_FILL)
            self.create_line(
                4, 9, 8, 13, 14, 5,
                fill="#ffffff", width=2,
                capstyle="round", joinstyle="round",
            )
        else:
            self._rounded(1, 1, s - 1, s - 1, r, fill="#ffffff", outline=CHECK_OFF_BORDER)

    def _rounded(self, x1: int, y1: int, x2: int, y2: int, r: int, **kw) -> int:
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)


class StatusIcon(tk.Canvas):
    SIZE = 16

    def __init__(self, master: tk.Misc, state: str, bg: str = BG) -> None:
        super().__init__(
            master,
            width=self.SIZE,
            height=self.SIZE,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self._state = state
        self._draw()

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._draw()

    def set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        s = self.SIZE
        if self._state == "warn":
            self.create_oval(1, 1, s - 1, s - 1, fill=STATUS_WARN, outline=STATUS_WARN)
            self.create_line(s / 2, 4, s / 2, s - 6, fill="#ffffff", width=2, capstyle="round")
            self.create_oval(s / 2 - 1, s - 5, s / 2 + 1, s - 3, fill="#ffffff", outline="#ffffff")
        elif self._state == "ok":
            self.create_oval(1, 1, s - 1, s - 1, fill=STATUS_OK, outline=STATUS_OK)
            self.create_line(
                4, 9, 7, 12, 12, 5,
                fill="#ffffff", width=2,
                capstyle="round", joinstyle="round",
            )
        elif self._state == "error":
            self.create_oval(1, 1, s - 1, s - 1, fill=STATUS_ERROR, outline=STATUS_ERROR)
            self.create_line(5, 5, s - 5, s - 5, fill="#ffffff", width=2, capstyle="round")
            self.create_line(s - 5, 5, 5, s - 5, fill="#ffffff", width=2, capstyle="round")


class Row(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        label: str,
        indent: int = 0,
        on_menu: Optional[Callable[[tk.Event], None]] = None,
        on_click: Optional[Callable[[], None]] = None,
        on_check: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(master, bg=BG, highlightthickness=0)
        self._on_menu = on_menu
        self._on_click = on_click
        self._on_check = on_check
        self._bg_widgets: list[tk.Widget] = [self]

        if indent:
            spacer = tk.Frame(self, width=indent, bg=BG)
            spacer.pack(side="left")
            self._bg_widgets.append(spacer)

        self.checkbox = Checkbox(
            self, checked=True, command=self._on_checkbox_change
        )
        self.checkbox.pack(side="left", padx=(10, 10), pady=5)

        self._status: Optional[StatusIcon] = None

        self.label = tk.Label(
            self,
            text=label,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 10),
            anchor="w",
        )
        self.label.pack(side="left", fill="x", expand=True, pady=5)
        self._bg_widgets.append(self.label)

        for w in (self, self.label):
            w.bind("<Enter>", self._hover_on, add="+")
            w.bind("<Leave>", self._hover_off, add="+")
            w.bind("<Button-3>", self._right_click, add="+")
            if on_click is not None:
                w.bind("<Button-1>", self._left_click, add="+")
                w.configure(cursor="hand2")
                self.label.configure(cursor="hand2")

    def set_label(self, text: str) -> None:
        self.label.configure(text=text)

    def _on_checkbox_change(self, value: bool) -> None:
        if self._on_check:
            self._on_check(value)

    def set_status(self, state: Optional[str]) -> None:
        if state is None:
            if self._status is not None:
                self._bg_widgets.remove(self._status)
                self._status.destroy()
                self._status = None
            return
        if self._status is None:
            self._status = StatusIcon(self, state=state, bg=self.label.cget("bg"))
            self._status.pack(side="left", padx=(0, 6), before=self.label)
            self._bg_widgets.append(self._status)
            self._status.bind("<Enter>", self._hover_on, add="+")
            self._status.bind("<Leave>", self._hover_off, add="+")
            self._status.bind("<Button-3>", self._right_click, add="+")
        else:
            self._status.set_state(state)

    def is_checked(self) -> bool:
        return self.checkbox.is_checked()

    def _hover_on(self, _e: tk.Event) -> None:
        self._set_bg(HOVER_BG)

    def _hover_off(self, _e: tk.Event) -> None:
        self._set_bg(BG)

    def _set_bg(self, color: str) -> None:
        for w in self._bg_widgets:
            w.configure(bg=color)
        self.checkbox.set_bg(color)
        if self._status is not None:
            self._status.set_bg(color)

    def _right_click(self, event: tk.Event) -> None:
        if self._on_menu:
            self._on_menu(event)

    def _left_click(self, _event: tk.Event) -> None:
        if self._on_click:
            self._on_click()


class CompaniesTree(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        on_open_panel: Optional[Callable[[Callable[[tk.Misc], tk.Widget]], None]] = None,
        on_company_check: Optional[Callable[[str, bool], None]] = None,
    ) -> None:
        super().__init__(master)
        self._on_open_panel = on_open_panel
        self._on_company_check = on_company_check
        self.configure(style="Companies.TFrame")

        style = ttk.Style(self)
        style.configure("Companies.TFrame", background=BG)

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=14, pady=(14, 10))
        tk.Label(
            head,
            text=t("header_companies"),
            font=("Segoe UI", 9, "bold"),
            fg=HEADER,
            bg=BG,
        ).pack(side="left")

        self._list = tk.Frame(self, bg=BG)
        self._list.pack(fill="both", expand=True, padx=6, pady=(0, 12))

        self._companies = load_companies()
        self._co_rows: dict[str, Row] = {}
        self._bot_rows: dict[tuple[str, str, str], Row] = {}
        self._bot_errors: dict[tuple[str, str], bool] = {}
        self._populate()

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=14)

        actions = ttk.Frame(self, style="Companies.TFrame")
        actions.pack(fill="x", padx=14, pady=(10, 14))
        self._add_btn = ttk.Button(
            actions,
            text=t("btn_add_company"),
            command=self._open_add_company,
            style="Accent.TButton",
        )
        self._add_btn.pack(side="left")
        self._analytics_btn = ttk.Button(
            actions,
            text=t("btn_analytics"),
            command=self._open_analytics,
            state="disabled",
        )
        self._analytics_btn.pack(side="left", padx=(8, 0))
        self._sync_btn = ttk.Button(
            actions, text=t("btn_sync_webitel"), command=self._sync_webitel
        )
        self._sync_btn.pack(side="right")

        self._tick()

    def _co_label(self, c: Company) -> str:
        return f"{c.code}  —  {c.name} ({c.country})   {now_in_timezone(c.timezone)}"

    def _bot_label(self, c: Company, kind: str) -> str:
        if kind == "voice":
            return "Voice Bot"
        if kind == "whatsapp":
            label = "WhatsApp Infobip bot"
            build = latest_build_date(c.key)
            if build:
                label += f" (build {build.strftime('%d.%m.%Y')})"
            return label
        if kind == "agents":
            return "Agents"
        return kind

    def _populate(self) -> None:
        for c in self._companies:
            co_row = Row(
                self._list,
                label=self._co_label(c),
                on_menu=lambda e, key=c.key: self._show_company_menu(e, key),
                on_click=lambda key=c.key: self._open_dashboard(key),
                on_check=lambda v, key=c.key: self._handle_company_check(key, v),
            )
            co_row.pack(fill="x")
            co_row.set_status("warn" if not is_company_complete(c.key) else None)
            self._co_rows[c.key] = co_row

            for sector in SECTORS:
                sector_row = Row(
                    self._list,
                    label=t(sector_label_key(sector)),
                    indent=28,
                    on_menu=lambda _e: None,
                    on_click=lambda _v=None: None,
                    on_check=lambda _v: self._refresh_analytics(),
                )
                sector_row.pack(fill="x")
                for kind in ("voice", "whatsapp", "agents"):
                    on_click = (
                        lambda key=c.key, k=kind, sec=sector:
                            self._open_bot_panel(key, k, sec)
                    )
                    bot_row = Row(
                        self._list,
                        label=self._bot_label(c, kind),
                        indent=56,
                        on_menu=lambda e, key=c.key, k=kind, sec=sector:
                            self._show_bot_menu(e, key, k, sec),
                        on_click=on_click,
                        on_check=lambda _v: self._refresh_analytics(),
                    )
                    bot_row.pack(fill="x")
                    self._bot_rows[(c.key, sector, kind)] = bot_row
                    self._refresh_bot_status(c.key, kind, sector)

    def _reload_companies(self) -> None:
        for w in list(self._list.winfo_children()):
            w.destroy()
        self._co_rows.clear()
        self._bot_rows.clear()
        self._companies = load_companies()
        self._populate()
        self._refresh_analytics()

    def _tick(self) -> None:
        for c in self._companies:
            row = self._co_rows.get(c.key)
            if row:
                row.set_label(self._co_label(c))
        self.after(1000, self._tick)

    def _show_company_menu(self, event: tk.Event, key: str) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Изменить", command=lambda: self._edit_company(key))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_bot_menu(
        self, event: tk.Event, company_key: str, kind: str,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        menu = tk.Menu(self, tearoff=0)
        if kind == "whatsapp":
            menu.add_command(
                label="Изменить",
                command=lambda: self._edit_whatsapp_bot(company_key),
            )
        else:
            menu.add_command(label="Изменить", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _handle_company_check(self, company_key: str, checked: bool) -> None:
        self._refresh_analytics()
        if self._on_company_check:
            try:
                self._on_company_check(company_key, checked)
            except Exception:
                pass

    def checked_company_keys(self) -> list[str]:
        return [k for k, row in self._co_rows.items() if row.is_checked()]

    def _open_dashboard(self, company_key: str) -> None:
        company = next((c for c in self._companies if c.key == company_key), None)
        if not company or not self._on_open_panel:
            return
        from .company_panel import CompanyPanel
        self._on_open_panel(lambda parent: CompanyPanel(parent, company))

    def _open_add_company(self) -> None:
        from .company_edit_dialog import CompanyEditDialog
        CompanyEditDialog(
            self, company_key=None, on_saved=lambda _k: self._reload_companies()
        )

    def _collect_selection(self) -> tuple[list[str], list[tuple[str, str]]]:
        companies_checked: list[str] = []
        bots_checked: list[tuple[str, str]] = []
        for c in self._companies:
            row = self._co_rows.get(c.key)
            if row and row.is_checked():
                companies_checked.append(c.key)
            for sector in SECTORS:
                for kind in ("voice", "whatsapp", "agents"):
                    br = self._bot_rows.get((c.key, sector, kind))
                    if br and br.is_checked():
                        bots_checked.append((c.key, kind))
        return companies_checked, bots_checked

    def _analytics_eligible(
        self, companies: list[str], bots: list[tuple[str, str]]
    ) -> bool:
        if companies and bots:
            return False
        if companies and not bots:
            return len(companies) >= 1
        if bots and not companies:
            kinds = {kind for _, kind in bots}
            return len(kinds) == 1
        return False

    def _refresh_analytics(self) -> None:
        companies, bots = self._collect_selection()
        state = "normal" if self._analytics_eligible(companies, bots) else "disabled"
        self._analytics_btn.configure(state=state)

    def _open_analytics(self) -> None:
        if not self._on_open_panel:
            return
        companies, bots = self._collect_selection()
        if not self._analytics_eligible(companies, bots):
            return
        if companies and not bots:
            keys = companies
            kind: Optional[str] = None
        else:
            keys = sorted({k for k, _ in bots})
            kind = next(iter({k for _, k in bots}))
        objs = [c for c in self._companies if c.key in keys]
        from .analytics_panel import AnalyticsPanel
        self._on_open_panel(lambda parent: AnalyticsPanel(parent, objs, kind))

    def _open_bot_panel(
        self, company_key: str, kind: str,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        company = next((c for c in self._companies if c.key == company_key), None)
        if not company or not self._on_open_panel:
            return
        from .bot_panel import BotPanel
        self._on_open_panel(
            lambda parent: BotPanel(parent, company, kind, sector)
        )

    def _edit_whatsapp_bot(self, company_key: str) -> None:
        company = next((c for c in self._companies if c.key == company_key), None)
        if not company:
            return
        from .whatsapp_bot_dialog import WhatsAppBotDialog
        WhatsAppBotDialog(
            self,
            company,
            on_saved=lambda c: self._refresh_bot_status(c.key, "whatsapp"),
        )

    def _refresh_bot_status(
        self, company_key: str, kind: str,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        row = self._bot_rows.get((company_key, sector, kind))
        if not row:
            return
        if self._bot_errors.get((company_key, kind)):
            row.set_status("error")
        elif is_bot_complete(company_key, kind):
            row.set_status("ok")
        else:
            row.set_status("warn")

    def set_bot_error(self, company_key: str, kind: str, has_error: bool) -> None:
        self._bot_errors[(company_key, kind)] = has_error
        self._refresh_bot_status(company_key, kind)

    def _sync_webitel(self) -> None:
        self._sync_btn.configure(state="disabled", text="…")
        companies = list(self._companies)
        threading.Thread(
            target=self._sync_worker, args=(companies,), daemon=True
        ).start()

    def _sync_worker(self, companies: list[Company]) -> None:
        results: list[tuple[str, str, str]] = []
        for c in companies:
            if not c.webitel_host or not c.webitel_access_token:
                results.append((c.key, "skip", "нет webitel_host/token"))
                continue
            try:
                client = WebitelClient(c.webitel_host, c.webitel_access_token)
                schemas = client.list_chat_schemas()
            except WebitelError as exc:
                results.append((c.key, "error", str(exc)))
                continue
            pick = find_whatsapp_infobip_prod(schemas, c.name)
            if pick is None:
                results.append((c.key, "missing", "схема не найдена"))
                continue
            existing = load_bot(c.key, "whatsapp")
            existing["prod_schema_id"] = pick.id
            existing["prod_schema_name"] = pick.name
            try:
                save_bot(c.key, "whatsapp", existing)
            except OSError as exc:
                results.append((c.key, "error", f"save: {exc}"))
                continue
            results.append((c.key, "ok", f"{pick.id} — {pick.name}"))
        self.after(0, lambda: self._sync_done(results))

    def _sync_done(self, results: list[tuple[str, str, str]]) -> None:
        for key, status, _info in results:
            self._bot_errors[(key, "whatsapp")] = status == "error"
            self._refresh_bot_status(key, "whatsapp")
        self._sync_btn.configure(state="normal", text=t("btn_sync_webitel"))
        ok = sum(1 for _, s, _ in results if s == "ok")
        problems = [
            f"  {k} — {s}: {info}"
            for k, s, info in results
            if s != "ok"
        ]
        from tkinter import messagebox
        if problems:
            messagebox.showwarning(
                "Sync с Webitel",
                f"Готово. OK: {ok} из {len(results)}.\n\nПроблемы:\n" + "\n".join(problems),
                parent=self.winfo_toplevel(),
            )
        else:
            messagebox.showinfo(
                "Sync с Webitel",
                f"Готово. Обновлены все {ok} компаний.",
                parent=self.winfo_toplevel(),
            )

    def _edit_company(self, key: str) -> None:
        from .company_edit_dialog import CompanyEditDialog
        CompanyEditDialog(self, key, on_saved=self._on_company_saved)

    def _on_company_saved(self, key: str) -> None:
        new_companies = load_companies()
        new_map = {c.key: c for c in new_companies}
        if key not in new_map:
            return
        for i, c in enumerate(self._companies):
            if c.key == key:
                self._companies[i] = new_map[key]
                break
        row = self._co_rows.get(key)
        if row:
            row.set_label(self._co_label(new_map[key]))
            row.set_status("warn" if not is_company_complete(key) else None)
