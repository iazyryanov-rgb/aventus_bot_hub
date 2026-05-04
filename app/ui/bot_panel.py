import tkinter as tk
from tkinter import ttk

from ..data import Company
from .alerts_panel import AlertsPanel


class BotPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company, kind: str) -> None:
        super().__init__(master)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 10))

        if kind == "agents":
            from .queues_panel import QueuesPanel
            queues = QueuesPanel(self.notebook, company)
            self.notebook.add(queues, text="Контроль очередей")

            from .conversations_panel import ConversationsPanel
            conversations = ConversationsPanel(self.notebook, company)
            self.notebook.add(conversations, text="Чаты")

        alerts = AlertsPanel(self.notebook, company, kind)
        self.notebook.add(alerts, text="Алерты")

        self.notebook.select(0)
