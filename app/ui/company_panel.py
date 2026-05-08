import tkinter as tk
from tkinter import ttk

from ..data import Company
from ..i18n import t
from .action_tree_panel import ActionTreePanel
from .alerts_panel import AlertsPanel
from .crm_data_panel import CrmDataPanel
from .dashboard_panel import DashboardPanel
from .loan_statuses_panel import LoanStatusesPanel
from .modern_notebook import ModernNotebook
from .testers_panel import TestersPanel


class CompanyPanel(ttk.Frame):
    """Top-level panel shown when a company row is clicked. Holds tabs that
    are properties of the company itself (not of any specific bot kind):
    Dashboard, CRM data, Action tree."""

    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self.notebook = ModernNotebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        dashboard = DashboardPanel(self.notebook, company)
        self.notebook.add(dashboard, text=t("tab_dashboard"))

        alerts = AlertsPanel(self.notebook, company, "company")
        self.notebook.add(alerts, text=t("tab_alerts"))

        crm_data = CrmDataPanel(self.notebook, company, "")
        self.notebook.add(crm_data, text=t("tab_crm_data"))

        action_tree = ActionTreePanel(self.notebook, company, "")
        self.notebook.add(action_tree, text=t("tab_action_tree"))

        loan_statuses = LoanStatusesPanel(self.notebook, company)
        self.notebook.add(loan_statuses, text=t("tab_loan_statuses"))

        testers = TestersPanel(self.notebook, company)
        self.notebook.add(testers, text=t("tab_testers"))

        self.notebook.select(0)
