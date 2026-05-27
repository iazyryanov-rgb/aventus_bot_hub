import tkinter as tk
from tkinter import ttk

from ..data import Company
from ..i18n import t
from ..sectors import DEFAULT_SECTOR, SECTORS
from .alerts_panel import AlertsPanel
from .modern_notebook import ModernNotebook


class BotPanel(ttk.Frame):
    def __init__(
        self, master: tk.Misc, company: Company, kind: str,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        self.notebook = ModernNotebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 10))

        if kind == "agents":
            from .queues_panel import QueuesPanel
            queues = QueuesPanel(self.notebook, company, self._sector)
            self.notebook.add(queues, text=t("tab_queues"))

            from .conversations_panel import ConversationsPanel
            conversations = ConversationsPanel(self.notebook, company)
            self.notebook.add(conversations, text=t("tab_chats"))

        if kind == "voice":
            from .voice_bot_panel import (
                VoiceBotMappingPanel,
                VoiceBotOverviewPanel,
                VoiceBotPromptsPanel,
            )
            from .voice_bot_results_panel import VoiceBotResultsPanel
            from .voice_bot_conversations_panel import VoiceBotConversationsPanel
            from .voice_bot_call_analysis_panel import (
                VoiceBotCallAnalysisPanel,
            )
            self.notebook.add(
                VoiceBotOverviewPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_overview"),
            )
            self.notebook.add(
                VoiceBotMappingPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_mapping"),
            )
            self.notebook.add(
                VoiceBotPromptsPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_prompts"),
            )
            self.notebook.add(
                VoiceBotResultsPanel(self.notebook, company, self._sector),
                text=t("voice_bot_tab_results"),
            )
            self.notebook.add(
                VoiceBotConversationsPanel(self.notebook, company, self._sector),
                text=t("voice_bot_tab_conversations"),
            )
            self.notebook.add(
                VoiceBotCallAnalysisPanel(self.notebook, company, self._sector),
                text=t("voice_bot_tab_call_analysis"),
            )

        if kind == "whatsapp":
            from .wa_bot_panel import (
                WaBotBuilderPanel,
                WaBotFunctionsPanel,
                WaBotMappingPanel,
                WaBotOverviewPanel,
                WaBotPromptsPanel,
                WaBotSendersPanel,
            )
            from .chat_audit_panel import ChatAuditPanel
            from .calibration_panel import CalibrationPanel
            self.notebook.add(
                WaBotOverviewPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_overview"),
            )
            self.notebook.add(
                WaBotMappingPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_mapping"),
            )
            self.notebook.add(
                WaBotSendersPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_senders"),
            )
            self.notebook.add(
                WaBotFunctionsPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_functions"),
            )
            self.notebook.add(
                WaBotPromptsPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_prompts"),
            )
            self.notebook.add(
                WaBotBuilderPanel(self.notebook, company, self._sector),
                text=t("wa_bot_tab_builder"),
            )
            self.notebook.add(
                ChatAuditPanel(self.notebook, company),
                text=t("wa_bot_tab_audit"),
            )
            self.notebook.add(
                CalibrationPanel(self.notebook, company),
                text=t("wa_bot_tab_calibration"),
            )

        alerts = AlertsPanel(self.notebook, company, kind)
        self.notebook.add(alerts, text=t("tab_alerts"))

        self.notebook.select(0)
