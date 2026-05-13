import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..i18n import LANGUAGES, current_language, set_language, t
from ..paths import icon_path
from .companies_tree import CompaniesTree
from .theme import WIN_BG, apply_modern_theme


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Aventus Bot Hub")
        # Apply Win11-flavoured theme before any widgets are created so they
        # pick up styles / option-DB defaults straight away.
        apply_modern_theme(self)
        self.configure(bg=WIN_BG)
        self._install_clipboard_bindings()

        # Window/title-bar icon. The .exe icon (taskbar / Explorer) is baked
        # into the binary by PyInstaller's --icon flag at build time. Inside
        # the running Tk window we use iconphoto(default=True, ...) so all
        # Toplevel dialogs inherit the same icon. Mixing iconbitmap +
        # iconphoto on Windows tends to leave the title-bar empty, so we
        # stick with iconphoto only.
        png = icon_path()
        if png.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

        self.state("zoomed")

        self._right_content: Optional[tk.Widget] = None
        self._build_ui()

    def _build_ui(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        self._right_content = None

        topbar = ttk.Frame(self)
        topbar.pack(fill="x", padx=12, pady=(8, 6))
        ttk.Label(
            topbar, text="Aventus Bot Hub", style="Title.TLabel",
        ).pack(side="left")
        lang_box = ttk.Combobox(
            topbar,
            textvariable=getattr(self, "_lang_var", None) or self._make_lang_var(),
            values=list(LANGUAGES),
            state="readonly",
            width=8,
        )
        lang_box.pack(side="right")
        lang_box.bind("<<ComboboxSelected>>", self._on_lang_change)
        ttk.Label(topbar, text=t("label_language"), style="Meta.TLabel").pack(
            side="right", padx=(0, 8),
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=14)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(8, 10))

        left = ttk.Frame(paned, width=420)
        left.pack_propagate(False)
        paned.add(left, weight=0)

        self.right = ttk.Frame(paned)
        paned.add(self.right, weight=1)

        self.companies = CompaniesTree(
            left,
            on_open_panel=self.show_panel,
            on_company_check=self._on_company_check,
        )
        self.companies.pack(fill="both", expand=True)
        self._init_background_refresher()

    def _make_lang_var(self) -> tk.StringVar:
        self._lang_var = tk.StringVar(value=current_language())
        return self._lang_var

    def _on_lang_change(self, _e: tk.Event) -> None:
        chosen = self._lang_var.get()
        if chosen == current_language():
            return
        set_language(chosen)
        self._build_ui()

    def _install_clipboard_bindings(self) -> None:
        """Make Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A работать на любой раскладке.

        В Tkinter биндинги вида `<Control-c>` срабатывают по keysym — а на
        русской раскладке Ctrl+C даёт keysym `Cyrillic_es`, и стандартные
        ярлыки молчат. Биндимся на `<Control-KeyPress>` и проверяем
        `event.keycode` (Win32 virtual-key, не зависит от раскладки).
        """

        def handler(event: tk.Event) -> Optional[str]:
            code = event.keycode
            if code == 67:  # C
                try:
                    event.widget.event_generate("<<Copy>>")
                except tk.TclError:
                    return None
                return "break"
            if code == 86:  # V
                try:
                    event.widget.event_generate("<<Paste>>")
                except tk.TclError:
                    return None
                return "break"
            if code == 88:  # X
                try:
                    event.widget.event_generate("<<Cut>>")
                except tk.TclError:
                    return None
                return "break"
            if code == 65:  # A
                w = event.widget
                try:
                    cls = w.winfo_class()
                    if cls in ("Entry", "TEntry"):
                        w.selection_range(0, "end")
                        w.icursor("end")
                    elif cls == "TCombobox":
                        w.select_range(0, "end")
                        w.icursor("end")
                    elif cls == "Text":
                        w.tag_add("sel", "1.0", "end-1c")
                        w.mark_set("insert", "end-1c")
                except (tk.TclError, AttributeError):
                    pass
                return "break"
            return None

        for cls in ("Entry", "TEntry", "TCombobox", "Text"):
            self.bind_class(cls, "<Control-KeyPress>", handler, add="+")

    def _init_background_refresher(self) -> None:
        """Hidden DashboardPanel instances per checked company. Their own
        auto-refresh timers keep the per-company cache up to date even when
        the panel isn't currently shown on screen. Toggling the company
        checkbox creates / destroys the hidden panel."""
        self._bg_frame = tk.Frame(self)  # never packed → invisible
        self._bg_panels: dict[str, "tk.Widget"] = {}
        self.after(200, self._sync_background_refresher)

    def _sync_background_refresher(self) -> None:
        try:
            from ..data import load_companies
            from .dashboard_panel import DashboardPanel
        except Exception:
            return
        try:
            companies = {c.key: c for c in load_companies()}
        except Exception:
            companies = {}
        checked = set(self.companies.checked_company_keys())
        # spawn for newly checked
        for key in checked:
            if key in self._bg_panels:
                continue
            company = companies.get(key)
            if not company:
                continue
            try:
                self._bg_panels[key] = DashboardPanel(
                    self._bg_frame, company, background=True
                )
            except Exception:
                continue
        # tear down for unchecked
        for key in list(self._bg_panels.keys()):
            if key not in checked:
                w = self._bg_panels.pop(key, None)
                if w is not None:
                    try:
                        w.destroy()
                    except Exception:
                        pass

    def _on_company_check(self, _company_key: str, _checked: bool) -> None:
        self._sync_background_refresher()

    def show_panel(self, factory: Callable[[tk.Misc], tk.Widget]) -> None:
        if self._right_content is not None:
            self._right_content.destroy()
        self._right_content = factory(self.right)
        self._right_content.pack(fill="both", expand=True)
