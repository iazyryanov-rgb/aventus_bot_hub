"""Per-company testers list (universal across bot kinds).

Lives on `CompanyPanel`. Reads/writes `data/testers/<COMPANY_KEY>.json` via
`app.testers`. CRUD on the testers list, plus a checkbox-equivalent button
to mark one tester as the company default.
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..alerts import (
    ensure_company_topic,
    load_alerts_config,
    save_alerts_config,
    send_telegram_message,
    TelegramError,
)
from ..crm_lookup import find_client_phone_by_criteria
from ..data import Company
from ..i18n import t
from ..loan_statuses import get_sector, get_statuses
from ..router_testers import RouterTester, save_testers as save_router_testers
from ..testers import (
    ENVIRONMENTS,
    delete_tester,
    load_testers,
    make_tester_id,
    set_default_tester,
    upsert_tester,
)
from ..webitel import WebitelError
from .colors import META_FG


CLIENT_TYPES = ("NEW", "REP")


def _mask_digits(s: str, head: int = 3, tail: int = 3, ch: str = "*") -> str:
    """Mask the middle of a phone-like string: keep `head` leading and
    `tail` trailing characters, replace the rest with `ch`. Short strings
    (<=head+tail) are returned untouched so we never reveal a 1:1 string."""
    s = str(s or "")
    if not s:
        return ""
    if len(s) <= head + tail:
        return s
    return s[:head] + ch * (len(s) - head - tail) + s[-tail:]


class TestersPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, company: Company) -> None:
        super().__init__(master)
        self._company = company

        ttk.Label(
            self,
            text=t("testers_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))
        ttk.Label(
            self,
            text=t("testers_help"),
            foreground=META_FG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Button(toolbar, text=t("btn_add"), command=self._add).pack(side="left")
        self._edit_btn = ttk.Button(
            toolbar, text=t("btn_edit"), command=self._edit, state="disabled"
        )
        self._edit_btn.pack(side="left", padx=(8, 0))
        self._del_btn = ttk.Button(
            toolbar, text=t("btn_delete"), command=self._delete, state="disabled"
        )
        self._del_btn.pack(side="left", padx=(8, 0))
        self._default_btn = ttk.Button(
            toolbar,
            text=t("testers_make_default"),
            command=self._make_default,
            state="disabled",
        )
        self._default_btn.pack(side="left", padx=(8, 0))
        # Sync local testers.json → router schema (testers customModule) +
        # post a status alert to the company's TG topic.
        self._sync_btn = ttk.Button(
            toolbar,
            text=t("testers_sync_wa_bot"),
            command=self._sync_to_wa_bot,
        )
        self._sync_btn.pack(side="left", padx=(8, 0))
        self._sync_status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._sync_status.pack(side="left", padx=(10, 0))

        cols = (
            "name", "phone", "destination", "environment",
            "owner", "default", "notes",
        )
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="browse",
        )
        self.tree.heading("name", text=t("col_name"))
        self.tree.heading("phone", text=t("testers_col_phone"))
        self.tree.heading("destination", text=t("testers_col_destination"))
        self.tree.heading("environment", text=t("testers_col_env"))
        self.tree.heading("owner", text=t("testers_col_owner"))
        self.tree.heading("default", text=t("testers_col_default"))
        self.tree.heading("notes", text=t("testers_col_notes"))
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("phone", width=140, anchor="w", stretch=False)
        self.tree.column("destination", width=140, anchor="w", stretch=False)
        self.tree.column("environment", width=90, anchor="w", stretch=False)
        self.tree.column("owner", width=180, anchor="w")
        self.tree.column("default", width=80, anchor="center", stretch=False)
        self.tree.column("notes", width=300, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scl = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scl.set)
        scl.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_buttons())
        self.tree.bind("<Double-Button-1>", lambda _e: self._edit())

        self._row_to_tester: dict[str, dict] = {}
        self._reload()

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        data = load_testers(self._company.key)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_tester.clear()
        default_id = data.get("default_tester_id") or ""
        for tester in data.get("testers") or []:
            tid = tester.get("id", "")
            iid = self.tree.insert(
                "", "end",
                values=(
                    tester.get("display_name", ""),
                    tester.get("phone_e164", ""),
                    tester.get("destination", ""),
                    tester.get("environment", ""),
                    tester.get("test_owner_key", ""),
                    t("testers_default_marker") if tid and tid == default_id else "",
                    tester.get("notes", ""),
                ),
            )
            self._row_to_tester[iid] = tester
        self._update_buttons()

    def _selected(self) -> Optional[dict]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._row_to_tester.get(sel[0])

    def _update_buttons(self) -> None:
        st = "normal" if self._selected() else "disabled"
        self._edit_btn.configure(state=st)
        self._del_btn.configure(state=st)
        self._default_btn.configure(state=st)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add(self) -> None:
        TesterEditDialog(self, self._company, None, on_saved=self._on_saved)

    def _edit(self) -> None:
        tester = self._selected()
        if not tester:
            return
        TesterEditDialog(self, self._company, tester, on_saved=self._on_saved)

    def _delete(self) -> None:
        tester = self._selected()
        if not tester:
            return
        name = tester.get("display_name") or tester.get("id", "")
        if not messagebox.askyesno(
            t("testers_confirm_delete"),
            f"{t('testers_confirm_delete')}\n\n{name}",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            delete_tester(self._company.key, tester.get("id", ""))
        except OSError as exc:
            messagebox.showerror(
                "Error", str(exc), parent=self.winfo_toplevel(),
            )
            return
        self._reload()

    def _make_default(self) -> None:
        tester = self._selected()
        if not tester:
            return
        try:
            set_default_tester(self._company.key, tester.get("id", ""))
        except OSError as exc:
            messagebox.showerror(
                "Error", str(exc), parent=self.winfo_toplevel(),
            )
            return
        self._reload()

    def _on_saved(self, _tester: dict) -> None:
        self._reload()

    # ------------------------------------------------------------------
    # Sync local testers.json → router schema (testers customModule)
    # ------------------------------------------------------------------

    def _sync_to_wa_bot(self) -> None:
        """Push the current testers list to the company's router schema and
        post a TG status alert. Runs in a background thread so the UI
        stays responsive — the router rebuild + Webitel PUT can take a
        few seconds."""
        data = load_testers(self._company.key)
        testers = data.get("testers") or []
        if not testers:
            messagebox.showinfo(
                t("testers_sync_wa_bot"),
                t("testers_sync_empty"),
                parent=self.winfo_toplevel(),
            )
            return
        self._sync_btn.configure(state="disabled")
        self._sync_status.configure(
            text=t("testers_sync_running"), foreground=META_FG,
        )
        threading.Thread(
            target=self._sync_worker, args=(list(testers),), daemon=True,
        ).start()

    def _sync_worker(self, testers: list[dict]) -> None:
        # Map local tester format (testers.json) -> RouterTester for the
        # router-schema rebuild.
        # `phone` (= router switch case) MUST come from `phone_e164` — that's
        # what the operator writes the bot from. `destination` is a separate
        # override for downstream CRM lookup: when destination differs from
        # phone, the tester's set node rewrites ${user}=destination so the
        # bot fetches the loan attached to a chosen test number, while still
        # being routed by their real handset phone.
        router_testers: list[RouterTester] = []
        for tt in testers:
            phone = "".join(
                ch for ch in str(tt.get("phone_e164") or "") if ch.isdigit()
            )
            if not phone:
                phone = "".join(
                    ch for ch in str(tt.get("destination") or "") if ch.isdigit()
                )
            if not phone:
                continue
            destination = "".join(
                ch for ch in str(tt.get("destination") or "") if ch.isdigit()
            ) or phone
            env = (tt.get("environment") or "").lower()
            area = "bot_candidate" if env == "staging" else "bot_prod"
            router_testers.append(RouterTester(
                phone=phone,
                test_owner=str(tt.get("display_name") or "").strip() or phone,
                test_area=area,
                destination=destination,
            ))

        try:
            result = save_router_testers(
                self._company.key, router_testers,
                snapshot_label="testers-ui-sync",
            )
        except KeyError as e:
            self._after_sync(False, str(e), router_testers)
            return
        except WebitelError as e:
            self._after_sync(False, str(e), router_testers)
            return
        except Exception as e:  # noqa: BLE001 — surface any unexpected error
            self._after_sync(False, f"{type(e).__name__}: {e}", router_testers)
            return

        if not result.get("ok"):
            self._after_sync(
                False, result.get("error", "sync failed"), router_testers,
            )
            return

        tg_err = self._post_tg_alert(testers, router_testers, result)
        msg = (
            t("testers_sync_done").format(n=len(router_testers))
            + (f" · TG: {tg_err}" if tg_err else "")
        )
        self._after_sync(True, msg, router_testers)

    def _post_tg_alert(
        self,
        testers_json: list[dict],
        router_testers: list[RouterTester],
        result: dict,
    ) -> Optional[str]:
        """Best-effort post to the company's TG topic. Returns None on
        success, or an error string to surface in the status line."""
        cfg = load_alerts_config()
        tg = cfg.get("telegram") or {}
        token = tg.get("bot_token") or ""
        chat_id = tg.get("chat_id") or ""
        if not token or not chat_id:
            return "TG not configured"
        topic_id = ensure_company_topic(cfg, self._company)
        try:
            save_alerts_config(cfg)
        except OSError:
            pass

        code = self._company.key.rstrip("_")
        lines = [
            f"🧪 <b>Testers synced to WhatsApp bot — {self._html_esc(code)} "
            f"({self._html_esc(self._company.name)})</b>",
            f"Router schema: <code>{result.get('router_schema_id')}</code> · "
            f"updated_at: <code>{result.get('new_updated_at')}</code>",
            "",
        ]
        # Pair testers.json entries with router_testers by phone for the
        # masked phone/destination view.
        by_phone = {rt.phone: rt for rt in router_testers}
        for i, tt in enumerate(testers_json, start=1):
            phone_raw = str(tt.get("phone_e164") or "").strip()
            dest_raw = "".join(
                ch for ch in str(tt.get("destination") or "") if ch.isdigit()
            )
            rt = by_phone.get(dest_raw) if dest_raw else None
            name = self._html_esc(
                tt.get("display_name") or rt.test_owner if rt else "?"
            )
            phone_m = self._html_esc(_mask_digits(phone_raw, head=4, tail=3))
            dest_m = self._html_esc(_mask_digits(dest_raw, head=3, tail=3))
            area = self._html_esc(rt.test_area if rt else "—")
            lines.append(
                f"{i}. <b>{name}</b> · phone <code>{phone_m}</code> · "
                f"dest <code>{dest_m}</code> · area <code>{area}</code>"
            )
        text = "\n".join(lines)

        try:
            send_telegram_message(
                token, chat_id, text,
                parse_mode="HTML",
                message_thread_id=topic_id,
            )
        except TelegramError as exc:
            return str(exc)
        return None

    @staticmethod
    def _html_esc(s: str) -> str:
        return (
            str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _after_sync(
        self, ok: bool, msg: str, router_testers: list[RouterTester],
    ) -> None:
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_sync_result(ok, msg))

    def _render_sync_result(self, ok: bool, msg: str) -> None:
        if not self.winfo_exists():
            return
        self._sync_btn.configure(state="normal")
        self._sync_status.configure(
            text=msg,
            foreground=("#16a34a" if ok else "#dc2626"),
        )


class TesterEditDialog(tk.Toplevel):
    """Modal-ish edit dialog. Single column form, autoderives `destination`
    from `phone_e164` when destination is empty on save."""

    def __init__(
        self,
        master: tk.Misc,
        company: Company,
        tester: Optional[dict],
        on_saved=None,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._tester = dict(tester) if tester else {}
        self._on_saved = on_saved

        self.title(
            t("testers_dialog_edit") if tester else t("testers_dialog_add")
        )
        try:
            self.transient(master.winfo_toplevel())
        except tk.TclError:
            pass
        self.resizable(False, False)

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        row = 0
        self._name_var = self._add_entry(frm, row, t("testers_field_name"), self._tester.get("display_name", ""))
        row += 1
        self._phone_var = self._add_entry(frm, row, t("testers_field_phone"), self._tester.get("phone_e164", ""))
        row += 1
        self._dest_var = self._add_entry(frm, row, t("testers_field_destination"), self._tester.get("destination", ""))
        row += 1

        ttk.Label(frm, text=t("testers_field_env") + ":").grid(
            row=row, column=0, sticky="w", pady=2,
        )
        self._env_var = tk.StringVar(value=self._tester.get("environment") or "prod")
        ttk.Combobox(
            frm,
            textvariable=self._env_var,
            values=ENVIRONMENTS,
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        self._owner_var = self._add_entry(frm, row, t("testers_field_owner"), self._tester.get("test_owner_key", ""))
        row += 1

        # --- CRM-search criteria (also persisted on the tester record) ---
        self._dpd_var = self._add_entry(
            frm, row, t("testers_field_dpd"),
            str(self._tester.get("dpd", "0") or "0"),
        )
        row += 1

        # Loan status combo — only statuses with a non-empty sector for this
        # company (the operator already curated those in the loan-statuses
        # panel). Codes without a sector are hidden to keep the picker short.
        # All loan statuses for this company — without the sector filter,
        # so the operator can pick any state (CO_ has many statuses with
        # no sector tag yet). Keeps the combobox writable so any custom
        # value can be typed.
        statuses = get_statuses(company.key) or {}
        sorted_codes = sorted(
            statuses.items(),
            key=lambda kv: int(kv[0]) if kv[0].lstrip("-").isdigit() else 0,
        )
        self._loan_status_labels: dict[str, str] = {"": "—"}
        for code, name in sorted_codes:
            sector = get_sector(company.key, code) or ""
            suffix = f" ({sector})" if sector else ""
            self._loan_status_labels[code] = f"{code} — {name}{suffix}"
        self._loan_status_code_by_label = {
            lbl: code for code, lbl in self._loan_status_labels.items()
        }
        ttk.Label(frm, text=t("testers_field_loan_status") + ":").grid(
            row=row, column=0, sticky="w", pady=2,
        )
        cur_status = str(self._tester.get("loan_status") or "")
        self._loan_status_var = tk.StringVar(
            value=self._loan_status_labels.get(cur_status, "—"),
        )
        ttk.Combobox(
            frm,
            textvariable=self._loan_status_var,
            values=list(self._loan_status_labels.values()),
            width=40,
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        ttk.Label(frm, text=t("testers_field_client_type") + ":").grid(
            row=row, column=0, sticky="w", pady=2,
        )
        self._client_type_var = tk.StringVar(
            value=str(self._tester.get("client_type") or "NEW"),
        )
        ttk.Combobox(
            frm,
            textvariable=self._client_type_var,
            values=list(CLIENT_TYPES),
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        # --- CRM lookup button ---
        crm_row = ttk.Frame(frm)
        crm_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        self._find_btn = ttk.Button(
            crm_row,
            text=t("testers_find_client"),
            command=self._find_client_in_crm,
        )
        self._find_btn.pack(side="left")
        self._find_status = ttk.Label(crm_row, text="", foreground=META_FG)
        self._find_status.pack(side="left", padx=(10, 0))
        row += 1

        ttk.Label(frm, text=t("testers_field_notes") + ":").grid(
            row=row, column=0, sticky="nw", pady=2,
        )
        self._notes_text = tk.Text(frm, width=44, height=4, wrap="word")
        self._notes_text.grid(row=row, column=1, sticky="ew", pady=2)
        self._notes_text.insert("1.0", self._tester.get("notes", "") or "")
        row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text=t("btn_save"), command=self._save).pack(
            side="left", padx=(0, 6),
        )
        ttk.Button(btns, text=t("btn_cancel"), command=self.destroy).pack(
            side="left",
        )

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())

    @staticmethod
    def _add_entry(parent: ttk.Frame, row: int, label: str, value: str) -> tk.StringVar:
        ttk.Label(parent, text=label + ":").grid(
            row=row, column=0, sticky="w", pady=2,
        )
        var = tk.StringVar(value=value or "")
        ttk.Entry(parent, textvariable=var, width=44).grid(
            row=row, column=1, sticky="ew", pady=2,
        )
        return var

    def _save(self) -> None:
        name = self._name_var.get().strip()
        phone = self._phone_var.get().strip()
        dest = self._dest_var.get().strip()
        if not name or (not phone and not dest):
            messagebox.showwarning(
                self.title() or "—",
                t("testers_required_fields"),
                parent=self,
            )
            return
        if not dest and phone:
            dest = re.sub(r"\D", "", phone)
        notes = self._notes_text.get("1.0", "end").rstrip()
        # CRM-search fields (also used by the «Найти клиента» button).
        dpd_raw = self._dpd_var.get().strip() or "0"
        try:
            dpd_val: int = int(dpd_raw)
        except ValueError:
            dpd_val = 0
        loan_status_code = self._loan_status_code_by_label.get(
            self._loan_status_var.get(), "",
        )
        client_type = (self._client_type_var.get() or "NEW").strip().upper()
        if client_type not in CLIENT_TYPES:
            client_type = "NEW"
        record = {
            **self._tester,
            "display_name": name,
            "phone_e164": phone,
            "destination": dest,
            "environment": self._env_var.get().strip() or "prod",
            "test_owner_key": self._owner_var.get().strip(),
            "company": self._company.name,
            "notes": notes,
            "dpd": dpd_val,
            "loan_status": loan_status_code,
            "client_type": client_type,
        }
        if not record.get("id"):
            record["id"] = make_tester_id(name, dest)
        try:
            upsert_tester(self._company.key, record)
        except OSError as exc:
            messagebox.showerror(self.title() or "—", str(exc), parent=self)
            return
        if self._on_saved:
            self._on_saved(record)
        self.destroy()

    # ------------------------------------------------------------------
    # CRM search (manual)
    # ------------------------------------------------------------------

    def _find_client_in_crm(self) -> None:
        """Query the company's CRM DB for a client matching the current
        dpd / loan_status / client_type form values. On hit, ask the
        operator to substitute the found phone into the destination field.
        Runs in a background thread so the dialog stays responsive."""
        dpd_raw = self._dpd_var.get().strip()
        try:
            dpd_val: Optional[int] = int(dpd_raw) if dpd_raw else 0
        except ValueError:
            self._find_status.configure(
                text=t("testers_dpd_must_be_int"), foreground="#dc2626",
            )
            return
        loan_status_code = self._loan_status_code_by_label.get(
            self._loan_status_var.get(), "",
        )
        loan_status_int: Optional[int] = None
        if loan_status_code:
            try:
                loan_status_int = int(loan_status_code)
            except ValueError:
                loan_status_int = None
        client_type = (self._client_type_var.get() or "NEW").strip().upper()
        if client_type not in CLIENT_TYPES:
            client_type = None

        self._find_btn.configure(state="disabled")
        self._find_status.configure(
            text=t("testers_finding"), foreground=META_FG,
        )
        threading.Thread(
            target=self._find_worker,
            args=(dpd_val, loan_status_int, client_type),
            daemon=True,
        ).start()

    def _find_worker(
        self,
        dpd: Optional[int],
        loan_status: Optional[int],
        client_type: Optional[str],
    ) -> None:
        phone, err = find_client_phone_by_criteria(
            self._company,
            dpd=dpd,
            loan_status=loan_status,
            client_type=client_type,
        )
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._after_find(phone, err))

    def _after_find(self, phone: Optional[str], err: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._find_btn.configure(state="normal")
        if err or not phone:
            self._find_status.configure(
                text=err or t("testers_not_found"), foreground="#dc2626",
            )
            return
        # Hit — propose substitution. We don't auto-overwrite so the
        # operator stays in control of the destination value.
        masked = _mask_digits(phone, head=3, tail=3)
        if messagebox.askyesno(
            t("testers_find_client"),
            t("testers_found_phone").format(phone=masked),
            parent=self,
        ):
            self._dest_var.set(phone)
            self._find_status.configure(
                text=t("testers_dest_updated"), foreground="#16a34a",
            )
        else:
            self._find_status.configure(
                text=t("testers_found_phone_short").format(phone=masked),
                foreground=META_FG,
            )
