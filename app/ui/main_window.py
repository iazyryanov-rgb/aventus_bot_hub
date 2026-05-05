import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..i18n import LANGUAGES, current_language, set_language, t
from ..paths import icon_path
from .companies_tree import CompaniesTree


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Aventus Bot Hub")
        self.configure(bg="#f3f4f6")
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
        self.bind("<Escape>", lambda _e: self.destroy())

        self._right_content: Optional[tk.Widget] = None
        self._build_ui()

    def _build_ui(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        self._right_content = None

        topbar = ttk.Frame(self)
        topbar.pack(fill="x", padx=10, pady=(6, 4))
        ttk.Label(topbar, text=f"{t('label_language')}:").pack(side="right", padx=(0, 6))
        self._lang_var = tk.StringVar(value=current_language())
        lang_box = ttk.Combobox(
            topbar,
            textvariable=self._lang_var,
            values=list(LANGUAGES),
            state="readonly",
            width=6,
        )
        lang_box.pack(side="right")
        lang_box.bind("<<ComboboxSelected>>", self._on_lang_change)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, width=420)
        left.pack_propagate(False)
        paned.add(left, weight=0)

        self.right = ttk.Frame(paned)
        paned.add(self.right, weight=1)

        self.companies = CompaniesTree(left, on_open_panel=self.show_panel)
        self.companies.pack(fill="both", expand=True)

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

    def show_panel(self, factory: Callable[[tk.Misc], tk.Widget]) -> None:
        if self._right_content is not None:
            self._right_content.destroy()
        self._right_content = factory(self.right)
        self._right_content.pack(fill="both", expand=True)
