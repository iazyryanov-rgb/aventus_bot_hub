"""Cross-company analytics overview.

Two views in one panel:

  1. **Companies overview** — one row per company with green/orange flags
     for: required settings filled, Webitel host+token, CRM host+token,
     ElevenLabs voice agent linked.

  2. **Alerts breakdown** — hierarchical tree:
     `company → bot kind → configured alerts`. Shows which alerts are
     enabled and which are configured-but-disabled (`enabled=False` /
     `schedule="Не запускать"`). Defaults that haven't been added yet
     show as "available, not configured" so the operator sees gaps.

All data is read locally from `companies.json`, `alerts.json` and
`data/voice_bot_config/<co>.json`. No network calls — the panel opens
instantly and is safe to refresh from a hot path.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from ..alerts import (
    ALERT_TEMPLATES,
    DEFAULT_AGENT_ALERTS,
    DEFAULT_AI_AUDIT_ALERTS,
    DEFAULT_HEALTH_ALERTS,
    DEFAULT_WA_SEND_TIME_ALERTS,
    get_bot_alerts,
)
from ..data import (
    Company,
    REQUIRED_COMPANY_FIELDS,
    is_company_complete,
    load_companies,
    load_raw,
)
from ..i18n import t
from .colors import ERR_FG, META_FG, OK_FG, TEXT_FG


KIND_LABELS = {
    "voice":    "Voice Bot",
    "whatsapp": "WhatsApp Infobip bot",
    "agents":   "Agents",
}


# Per-kind defaults — used to highlight templates that *could* be turned
# on but aren't configured yet for a given company/bot combo.
DEFAULTS_BY_KIND: dict[str, list[dict]] = {
    "whatsapp": (
        DEFAULT_HEALTH_ALERTS
        + DEFAULT_AI_AUDIT_ALERTS
        + DEFAULT_WA_SEND_TIME_ALERTS
    ),
    "agents":   list(DEFAULT_AGENT_ALERTS),
    "voice":    [],
}


# Treeview tag → (foreground colour, label text). Tags are also used as
# the "status" column value so the table reads cleanly even without
# colour (e.g. when the user copies a row).
TAG_OK         = "ok"
TAG_WARN       = "warn"
TAG_ERR        = "err"
TAG_MUTED      = "muted"


def _company_feature_flags(c: Company) -> dict[str, tuple[str, str]]:
    """Returns the per-company status cells:
        { settings, webitel, crm, elevenlabs } → (status_text, tag).
    """
    raw = load_raw().get(c.key, {}) or {}
    flags: dict[str, tuple[str, str]] = {}

    missing = [
        f for f in REQUIRED_COMPANY_FIELDS
        if not str(raw.get(f) or "").strip()
    ]
    if not missing:
        flags["settings"] = ("✓ OK", TAG_OK)
    else:
        flags["settings"] = (f"⚠ нет: {', '.join(missing)}", TAG_WARN)

    if c.webitel_host and c.webitel_access_token:
        flags["webitel"] = ("✓ host+token", TAG_OK)
    else:
        flags["webitel"] = ("⚠ нет host/token", TAG_WARN)

    crm_host = str(raw.get("crm_host") or "").strip()
    crm_token = str(raw.get("crm_access_token") or "").strip()
    if crm_host and crm_token:
        flags["crm"] = ("✓ host+token", TAG_OK)
    else:
        miss = []
        if not crm_host:
            miss.append("host")
        if not crm_token:
            miss.append("token")
        flags["crm"] = (f"⚠ нет {'/'.join(miss)}", TAG_WARN)

    flags["elevenlabs"] = _elevenlabs_status(c.key)
    return flags


def _elevenlabs_status(company_key: str) -> tuple[str, str]:
    """Cheap probe of voice bot config: returns (text, tag).

    Imported lazily so the panel still loads even if the voice config
    module fails to read (e.g. malformed json on disk).
    """
    try:
        from .. import voice_bot_config as vbc
        cfg = vbc.load_config(company_key)
    except Exception:
        return ("⚠ конфиг не читается", TAG_WARN)
    agent_id = str(cfg.get("elevenlabs_agent_id") or "").strip()
    schema_id = cfg.get("webitel_schema_id")
    if not agent_id and not schema_id:
        return ("— не настроен", TAG_MUTED)
    if agent_id and schema_id:
        return (f"✓ agent {agent_id[:8]}… · schema {schema_id}", TAG_OK)
    if agent_id:
        return (f"⚠ agent ok, нет schema_id", TAG_WARN)
    return ("⚠ нет agent_id", TAG_WARN)


def _wa_bot_status(company_key: str) -> tuple[str, str]:
    """WA-bot's prod schema linkage (the closest thing to «WA sync»)."""
    raw = load_raw().get(company_key, {}) or {}
    wa = ((raw.get("bots") or {}).get("whatsapp") or {})
    sid = wa.get("prod_schema_id")
    name = wa.get("prod_schema_name") or ""
    if sid:
        return (f"✓ schema {sid} · {name}", TAG_OK)
    return ("⚠ нет prod_schema_id", TAG_WARN)


def _alert_status(alert: dict) -> tuple[str, str]:
    """Map a configured alert to (status text, tag)."""
    enabled = bool(alert.get("enabled"))
    schedule = str(alert.get("schedule") or "").strip()
    if not enabled or schedule == "Не запускать":
        return ("✕ выключен", TAG_ERR)
    if schedule:
        return (f"✓ {schedule}", TAG_OK)
    return ("✓ enabled", TAG_OK)


class AnalyticsPanel(ttk.Frame):
    """Global view — no company / kind args. Re-reads everything from
    disk on construction so the panel always shows current state.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._companies: list[Company] = load_companies()

        ttk.Label(
            self,
            text=t("header_analytics"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))

        ttk.Label(
            self,
            text=t("analytics_subtitle"),
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 12))

        # Refresh button on top — re-loads data without losing the tab.
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Button(
            bar, text=t("btn_refresh"), command=self._on_refresh,
        ).pack(side="left")

        # Section 1 — companies overview ---------------------------------
        ttk.Label(
            self,
            text=t("analytics_section_overview"),
            font=("Segoe UI", 10, "bold"),
            foreground=TEXT_FG,
        ).pack(anchor="w", padx=14, pady=(8, 4))

        ov_wrap = ttk.Frame(self)
        ov_wrap.pack(fill="x", padx=14, pady=(0, 14))
        self._overview = self._build_overview_tree(ov_wrap)

        # Section 2 — alerts breakdown -----------------------------------
        ttk.Label(
            self,
            text=t("analytics_section_alerts"),
            font=("Segoe UI", 10, "bold"),
            foreground=TEXT_FG,
        ).pack(anchor="w", padx=14, pady=(2, 4))

        al_wrap = ttk.Frame(self)
        al_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._alerts_tree = self._build_alerts_tree(al_wrap)

        self._populate()

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_overview_tree(self, parent: tk.Misc) -> ttk.Treeview:
        cols = ("code", "name", "country", "settings", "webitel", "crm", "elevenlabs")
        tree = ttk.Treeview(
            parent, columns=cols, show="headings",
            selectmode="browse", height=6,
        )
        tree.heading("code", text=t("analytics_col_code"))
        tree.heading("name", text=t("analytics_col_name"))
        tree.heading("country", text=t("analytics_col_country"))
        tree.heading("settings", text=t("analytics_col_settings"))
        tree.heading("webitel", text=t("analytics_col_webitel"))
        tree.heading("crm", text=t("analytics_col_crm"))
        tree.heading("elevenlabs", text=t("analytics_col_elevenlabs"))
        tree.column("code", width=60, anchor="w", stretch=False)
        tree.column("name", width=200, anchor="w")
        tree.column("country", width=110, anchor="w", stretch=False)
        tree.column("settings", width=220, anchor="w")
        tree.column("webitel", width=170, anchor="w")
        tree.column("crm", width=170, anchor="w")
        tree.column("elevenlabs", width=240, anchor="w")
        self._apply_status_tags(tree)
        tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        return tree

    def _build_alerts_tree(self, parent: tk.Misc) -> ttk.Treeview:
        tree = ttk.Treeview(
            parent, columns=("status",), show="tree headings",
            selectmode="browse",
        )
        tree.heading("#0", text=t("analytics_col_alerts_target"))
        tree.heading("status", text=t("analytics_col_status"))
        tree.column("#0", width=520, anchor="w")
        tree.column("status", width=240, anchor="w")
        self._apply_status_tags(tree)
        tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        return tree

    @staticmethod
    def _apply_status_tags(tree: ttk.Treeview) -> None:
        tree.tag_configure(TAG_OK,    foreground=OK_FG)
        tree.tag_configure(TAG_WARN,  foreground="#ea580c")
        tree.tag_configure(TAG_ERR,   foreground=ERR_FG)
        tree.tag_configure(TAG_MUTED, foreground=META_FG)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        for iid in self._overview.get_children():
            self._overview.delete(iid)
        for iid in self._alerts_tree.get_children():
            self._alerts_tree.delete(iid)

        for c in self._companies:
            flags = _company_feature_flags(c)
            # Worst-of-3 tag colours the row name; settings/webitel/crm/
            # 11labs each carry their own tag in their column already.
            worst = TAG_OK
            for cell_tag in (flags[k][1] for k in flags):
                if cell_tag == TAG_WARN:
                    worst = TAG_WARN
            self._overview.insert(
                "", "end",
                values=(
                    c.code, c.name, c.country,
                    flags["settings"][0],
                    flags["webitel"][0],
                    flags["crm"][0],
                    flags["elevenlabs"][0],
                ),
                tags=(worst,),
            )

            co_iid = self._alerts_tree.insert(
                "", "end",
                text=f"{c.code} — {c.name}",
                values=("",),
            )
            for kind in ("voice", "whatsapp", "agents"):
                self._populate_bot_kind(co_iid, c, kind)
            # auto-expand company nodes — there are at most 4 companies
            # so the tree fits without scrolling.
            self._alerts_tree.item(co_iid, open=True)

    def _populate_bot_kind(
        self, parent_iid: str, c: Company, kind: str,
    ) -> None:
        configured = get_bot_alerts(c.key, kind)
        defaults = DEFAULTS_BY_KIND.get(kind) or []

        if kind == "whatsapp":
            bot_status = _wa_bot_status(c.key)
        elif kind == "voice":
            bot_status = _elevenlabs_status(c.key)
        else:
            bot_status = ("", TAG_MUTED)

        on_count = sum(
            1 for a in configured
            if bool(a.get("enabled"))
            and (a.get("schedule") or "").strip() != "Не запускать"
        )
        off_count = len(configured) - on_count
        summary = f"{on_count} вкл · {off_count} выкл · {len(configured)} всего"
        if bot_status[0]:
            summary = f"{bot_status[0]}  ·  {summary}"

        kind_iid = self._alerts_tree.insert(
            parent_iid, "end",
            text=KIND_LABELS.get(kind, kind),
            values=(summary,),
            tags=(bot_status[1] if bot_status[1] != TAG_MUTED else TAG_MUTED,),
        )

        configured_templates = {
            str(a.get("template") or "") for a in configured
        }

        for alert in configured:
            tmpl = str(alert.get("template") or "")
            label = self._format_alert_label(alert, tmpl)
            status_text, tag = _alert_status(alert)
            self._alerts_tree.insert(
                kind_iid, "end",
                text=label,
                values=(status_text,),
                tags=(tag,),
            )

        for d in defaults:
            tmpl = str(d.get("template") or "")
            if tmpl in configured_templates:
                continue
            label = self._format_alert_label(d, tmpl, available_only=True)
            self._alerts_tree.insert(
                kind_iid, "end",
                text=label,
                values=(t("analytics_alert_available"),),
                tags=(TAG_MUTED,),
            )

        # auto-expand kind so the alert rows are visible without
        # extra clicks — defaults are read-only context, no point
        # hiding them.
        self._alerts_tree.item(kind_iid, open=True)

    @staticmethod
    def _format_alert_label(
        alert: dict, template: str, *, available_only: bool = False,
    ) -> str:
        title = ""
        for slug, head, _desc in ALERT_TEMPLATES:
            if slug == template:
                title = head
                break
        name = str(alert.get("name") or "").strip()
        bits = []
        if title:
            bits.append(title)
        elif template:
            bits.append(template)
        if name and (not title or name not in title):
            bits.append(f"« {name} »")
        if available_only:
            bits.append("[default, не добавлен]")
        return "  ·  ".join(bits) or template or "?"

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self._companies = load_companies()
        self._populate()
