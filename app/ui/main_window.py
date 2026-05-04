import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..paths import icon_path
from .companies_tree import CompaniesTree


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Aventus Bot Hub")
        self.configure(bg="#f3f4f6")

        ico = icon_path()
        if ico.exists():
            try:
                self._icon_img = tk.PhotoImage(file=str(ico))
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

        self.state("zoomed")
        self.bind("<Escape>", lambda _e: self.destroy())

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, width=420)
        left.pack_propagate(False)
        paned.add(left, weight=0)

        self.right = ttk.Frame(paned)
        paned.add(self.right, weight=1)
        self._right_content: Optional[tk.Widget] = None

        self.companies = CompaniesTree(left, on_open_panel=self.show_panel)
        self.companies.pack(fill="both", expand=True)

    def show_panel(self, factory: Callable[[tk.Misc], tk.Widget]) -> None:
        if self._right_content is not None:
            self._right_content.destroy()
        self._right_content = factory(self.right)
        self._right_content.pack(fill="both", expand=True)
