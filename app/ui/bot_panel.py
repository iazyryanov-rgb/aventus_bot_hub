import tkinter as tk
from tkinter import ttk

from ..data import Company
from ..i18n import t
from .alerts_panel import AlertsPanel


class BotPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company, kind: str) -> None:
        super().__init__(master)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 10))

        if kind == "agents":
            from .queues_panel import QueuesPanel
            queues = QueuesPanel(self.notebook, company)
            self.notebook.add(queues, text=t("tab_queues"))

            from .conversations_panel import ConversationsPanel
            conversations = ConversationsPanel(self.notebook, company)
            self.notebook.add(conversations, text=t("tab_chats"))

        alerts = AlertsPanel(self.notebook, company, kind)
        self.notebook.add(alerts, text=t("tab_alerts"))

        from .crm_data_panel import CrmDataPanel
        crm_data = CrmDataPanel(self.notebook, company, kind)
        self.notebook.add(crm_data, text=t("tab_crm_data"))

        from .action_tree_panel import ActionTreePanel
        action_tree = ActionTreePanel(self.notebook, company, kind)
        self.notebook.add(action_tree, text=t("tab_action_tree"))

        self.notebook.select(0)
