"""Per-company Voice bot configuration panel (ElevenLabs Conversational AI).

Сейчас единственная вкладка — Prompts: редактор system prompt + first
message с возможностью Pull/Push в ElevenLabs по agent_id. Анналог
`WaBotPromptsPanel`, только без functions-tree и builder — у 11labs
агента это всё хранится на их стороне, нас интересует только промт.
"""
from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from ..action_trees import get_tree
from ..data import Company
from ..elevenlabs import (
    ElevenLabsError,
    extract_prompt,
    get_agent,
    get_elevenlabs_key,
    list_agents,
    set_elevenlabs_key,
    update_agent_prompt,
)
from ..i18n import t
from ..paths import data_dir
from ..sectors import DEFAULT_SECTOR, SECTORS
from ..voice_bot_config import (
    BLOCK_HELPS,
    BLOCK_ORDER,
    BLOCK_TITLES,
    SIP_DYNAMIC_VARS,
    block_vars_for,
    enum_sets_from_tree,
    get_tool_id,
    join_blocks,
    load_config,
    save_config,
    split_blocks,
)
from .colors import ERR_FG, META_FG, OK_FG, TBD_FG, TEXT_FG


def _block_title(block_id: str) -> str:
    """i18n заголовка блока. Дефолт — английский из BLOCK_TITLES."""
    key = f"voice_bot_block_{block_id}"
    val = t(key)
    return val if val and val != key else BLOCK_TITLES.get(block_id, block_id)


def _block_help(block_id: str) -> str:
    key = f"voice_bot_block_{block_id}_help"
    val = t(key)
    return val if val and val != key else BLOCK_HELPS.get(block_id, "")


_SIP_PLACEHOLDER_RE = re.compile(r"\{\{\s*(sip_[A-Za-z0-9_]+)\s*\}\}")


def _placeholders_in_text(text: str) -> set[str]:
    return set(_SIP_PLACEHOLDER_RE.findall(text or ""))


def _load_voice_tool_snapshot(
    company_key: str, sector: str,
) -> Optional[dict]:
    """Читаем `data/voice_bot_tools/<COMPANY>/<sector>/save_call_result.json`,
    если он есть — нужен валидатору, чтобы понять какие dynamic_variable
    биндит tool и какие enum-значения у property."""
    p = (
        data_dir() / "voice_bot_tools" / company_key / sector
        / "save_call_result.json"
    )
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _expected_agent_prefix(company_key: str) -> str:
    """Конвенция именования голосовых агентов в ElevenLabs: company key без
    trailing ``_``, плюс ``1`` если последний символ не цифра. Примеры:

      * ``CO_``  → ``CO1``
      * ``CO2_`` → ``CO2``
      * ``PE_``  → ``PE1``
      * ``AR_``  → ``AR1``

    Используется как префикс фильтра агентов в picker'е (агент должен
    называться ``<prefix>_<что-то>``).
    """
    base = (company_key or "").rstrip("_")
    if not base:
        return ""
    return base if base[-1].isdigit() else base + "1"


class VoiceBotOverviewPanel(ttk.Frame):
    """Voice-bot summary card grid for this company.

    Pulls recent ElevenLabs conversations for the agent registered in
    voice_bot_config (``elevenlabs_agent_id``), filters by selected
    period (today / 7d / 30d), and aggregates basic operational metrics:
    total calls, successful vs failed, duration, and ElevenLabs cost
    (credits). The cost requires a per-conversation detail fetch, so a
    parallel thread pool drives the second pass."""

    PERIODS = (
        ("voice_bot_overview_period_today", 1),
        ("voice_bot_overview_period_7d", 7),
        ("voice_bot_overview_period_30d", 30),
    )

    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        self._cfg: dict = load_config(company.key, self._sector)
        self._agent_id: str = str(self._cfg.get("elevenlabs_agent_id") or "").strip()

        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})  ·  {t('sector_' + self._sector)}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        if not self._agent_id:
            ttk.Label(
                self,
                text=t("voice_bot_conv_no_agent"),
                foreground=TBD_FG, wraplength=900, justify="left",
            ).pack(anchor="w", padx=14, pady=12)
            return

        # ---- Toolbar: period selector + refresh + status ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(
            toolbar,
            text=t("voice_bot_overview_period_label") + ":",
            foreground=META_FG,
        ).pack(side="left")
        self._period_var = tk.StringVar(value=t(self.PERIODS[0][0]))
        period_box = ttk.Combobox(
            toolbar,
            textvariable=self._period_var,
            values=[t(k) for k, _ in self.PERIODS],
            state="readonly",
            width=16,
        )
        period_box.pack(side="left", padx=(6, 12))
        period_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
        self._refresh_btn = ttk.Button(
            toolbar,
            text=t("voice_bot_conv_refresh"),
            command=self._refresh,
            style="Accent.TButton",
        )
        self._refresh_btn.pack(side="left")
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        # ---- Cards grid ----
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=12, pady=(0, 12))
        self._cards: dict[str, ttk.Label] = {}
        defs = [
            ("total", t("voice_bot_overview_card_total"), 0, 0),
            ("successful", t("voice_bot_overview_card_successful"), 0, 1),
            ("failed", t("voice_bot_overview_card_failed"), 0, 2),
            ("duration_total", t("voice_bot_overview_card_duration_total"), 1, 0),
            ("duration_avg", t("voice_bot_overview_card_duration_avg"), 1, 1),
            ("duration_max", t("voice_bot_overview_card_duration_max"), 1, 2),
            ("llm_usd_total", t("voice_bot_overview_card_llm_usd_total"), 2, 0),
            ("llm_usd_avg", t("voice_bot_overview_card_llm_usd_avg"), 2, 1),
            ("success_rate", t("voice_bot_overview_card_success_rate"), 2, 2),
        ]
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform="card")
        for key, label, row, col in defs:
            box = ttk.LabelFrame(cards, text=label, padding=10)
            box.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            big = ttk.Label(
                box, text="—",
                font=("Segoe UI", 18, "bold"),
                foreground=TEXT_FG,
            )
            big.pack(anchor="w")
            self._cards[key] = big

        # Auto-load on open
        self.after(50, self._refresh)

    # ------------------------------------------------------------------
    # Refresh / aggregation
    # ------------------------------------------------------------------

    def _period_days(self) -> int:
        current = self._period_var.get()
        for key, days in self.PERIODS:
            if t(key) == current:
                return days
        return 7

    def _refresh(self) -> None:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        days = self._period_days()
        self._refresh_btn.configure(state="disabled")
        self._status.configure(
            text=t("voice_bot_overview_loading"), foreground=META_FG,
        )
        threading.Thread(
            target=self._refresh_worker, args=(days,), daemon=True,
        ).start()

    def _refresh_worker(self, days: int) -> None:
        """Incremental refresh: подсасываем только новые conversations.

        Алгоритм:
          1. Загружаем кэш `data/voice_bot_overview_cache/<COMPANY>/<sector>.json`
             (привязан к agent_id; при смене агента стартуем с пустого).
          2. Идём по pages списка conversations с самой свежей. Для каждой
             страницы:
               - добавляем в `new_to_detail` те, чьего id ещё нет в кэше
                 и чей `start_time_unix_secs >= cutoff`;
               - если все id страницы уже в кэше — выходим (вся история
                 ниже уже у нас);
               - если самая старая запись страницы старше `cutoff` —
                 выходим (вне выбранного периода).
          3. Параллельно вытягиваем `get_conversation` только для
             `new_to_detail` (метаданные с cost/llm_price); сохраняем в кэш.
          4. Записываем кэш на диск, агрегируем метрики из кэша,
             отфильтрованного по `start_time_unix_secs >= cutoff`.

        Это даёт O(новые) вместо O(всё в окне) HTTP-вызовов после первой
        загрузки, и переживает закрытие хаба (история на диске).
        """
        import time as _time
        from concurrent.futures import ThreadPoolExecutor
        try:
            from ..elevenlabs import list_conversations, get_conversation
            api_key = get_elevenlabs_key(self._company.key)
            cutoff = int(_time.time()) - days * 86400

            cache = _load_overview_cache(
                self._company.key, self._sector, self._agent_id,
            )
            cached_convs: dict = cache.get("conversations") or {}
            cached_ids = set(cached_convs.keys())

            new_to_detail: list[dict] = []
            cursor = ""
            for _ in range(20):  # hard pagination cap
                r = list_conversations(
                    agent_id=self._agent_id, page_size=100,
                    cursor=cursor, api_key=api_key,
                )
                page = r.get("conversations") or []
                if not page:
                    break

                page_ids: set[str] = set()
                for c in page:
                    cid = c.get("conversation_id")
                    ts = c.get("start_time_unix_secs") or 0
                    if not cid:
                        continue
                    page_ids.add(cid)
                    if ts < cutoff:
                        continue
                    if cid in cached_ids:
                        continue
                    new_to_detail.append(c)

                page_oldest = min(
                    (c.get("start_time_unix_secs") or 0) for c in page
                )
                # Stopping rules. Любое из условий = вся «свежая» история
                # с этого момента и далее уже у нас.
                if page_oldest < cutoff:
                    break
                if page_ids and page_ids.issubset(cached_ids):
                    break
                if not r.get("has_more"):
                    break
                cursor = r.get("next_cursor") or ""
                if not cursor:
                    break

            details_total = len(new_to_detail)
            if self.winfo_exists():
                self.after(
                    0,
                    lambda: self._status.configure(
                        text=t("voice_bot_overview_loading_details").format(
                            done=0, total=details_total,
                        ),
                        foreground=META_FG,
                    ),
                )

            def fetch_entry(conv: dict) -> dict:
                """Возвращает кэш-запись для одной conversation: базовые поля
                списка + cost/llm_usd из metadata get_conversation."""
                cid = conv.get("conversation_id")
                base = {
                    "conversation_id": cid,
                    "start_time_unix_secs": conv.get("start_time_unix_secs"),
                    "call_successful": conv.get("call_successful"),
                    "call_duration_secs": conv.get("call_duration_secs"),
                }
                try:
                    det = get_conversation(cid, api_key=api_key)
                    md = det.get("metadata") or {}
                    charging = md.get("charging") or {}
                    base["cost_credits"] = int(md.get("cost") or 0)
                    base["llm_usd"] = float(charging.get("llm_price") or 0.0)
                except Exception:  # noqa: BLE001 — single-call error не валит всё
                    base["cost_credits"] = 0
                    base["llm_usd"] = 0.0
                return base

            new_entries: list[dict] = []
            if new_to_detail:
                with ThreadPoolExecutor(max_workers=8) as ex:
                    for i, entry in enumerate(ex.map(fetch_entry, new_to_detail)):
                        new_entries.append(entry)
                        if self.winfo_exists() and (i + 1) % 5 == 0:
                            done = i + 1
                            self.after(
                                0,
                                lambda d=done, t_=details_total:
                                    self._status.configure(
                                        text=t("voice_bot_overview_loading_details").format(
                                            done=d, total=t_,
                                        ),
                                        foreground=META_FG,
                                    ),
                            )

            # Merge new entries into cache and persist.
            for entry in new_entries:
                cid = entry.get("conversation_id")
                if cid:
                    cached_convs[cid] = entry
            cache["agent_id"] = self._agent_id
            cache["company_key"] = self._company.key
            cache["sector"] = self._sector
            cache["conversations"] = cached_convs
            cache["last_updated_unix"] = int(_time.time())
            _save_overview_cache(self._company.key, self._sector, cache)

            # Aggregate from cache, filtered to selected period.
            in_period = [
                c for c in cached_convs.values()
                if (c.get("start_time_unix_secs") or 0) >= cutoff
            ]
            cost_total = sum(int(c.get("cost_credits") or 0) for c in in_period)
            llm_usd_total = sum(float(c.get("llm_usd") or 0.0) for c in in_period)
            stats = _aggregate_conversations(
                in_period, cost_total, llm_usd_total,
            )
            stats["new_fetched"] = len(new_entries)
            stats["cache_total"] = len(cached_convs)
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001
            stats, err = None, str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_stats(stats, err))

    def _render_stats(
        self, stats: Optional[dict], err: Optional[str],
    ) -> None:
        self._refresh_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            return
        if not stats:
            self._status.configure(
                text=t("voice_bot_overview_no_data"),
                foreground=TBD_FG,
            )
            for lbl in self._cards.values():
                lbl.configure(text="—")
            return

        total = stats["total"]
        successful = stats["successful"]
        failed = stats["failed"]
        rate = (
            f"{(successful * 100 / total):.0f}%" if total else "—"
        )
        self._cards["total"].configure(text=str(total))
        self._cards["successful"].configure(text=str(successful))
        self._cards["failed"].configure(text=str(failed))
        self._cards["duration_total"].configure(
            text=_fmt_hms(stats["duration_total"]),
        )
        self._cards["duration_avg"].configure(
            text=_fmt_hms(stats["duration_avg"]),
        )
        self._cards["duration_max"].configure(
            text=_fmt_hms(stats["duration_max"]),
        )
        self._cards["llm_usd_total"].configure(
            text=f"${stats['llm_usd_total']:.2f}",
        )
        self._cards["llm_usd_avg"].configure(
            text=(
                f"${stats['llm_usd_avg']:.4f}" if total else "—"
            ),
        )
        self._cards["success_rate"].configure(text=rate)
        new_fetched = int(stats.get("new_fetched") or 0)
        cache_total = int(stats.get("cache_total") or 0)
        if new_fetched > 0 or cache_total > 0:
            self._status.configure(
                text=t("voice_bot_overview_loaded_incremental").format(
                    n=total, days=self._period_days(),
                    new_fetched=new_fetched, cache_total=cache_total,
                ),
                foreground=OK_FG,
            )
        else:
            self._status.configure(
                text=t("voice_bot_overview_loaded").format(
                    n=total, days=self._period_days(),
                ),
                foreground=OK_FG,
            )


def _overview_cache_path(company_key: str, sector: str):
    return (
        data_dir() / "voice_bot_overview_cache" / company_key / f"{sector}.json"
    )


def _load_overview_cache(
    company_key: str, sector: str, agent_id: str,
) -> dict:
    """Возвращает локальный кэш ElevenLabs conversations для (company, sector).

    Структура файла:
        {
          "company_key": "CO_",
          "sector": "collection",
          "agent_id": "agent_...",
          "conversations": {
            "<conversation_id>": {
              "conversation_id": ...,
              "start_time_unix_secs": ...,
              "call_successful": "success" | "failure" | "unknown",
              "call_duration_secs": ...,
              "cost_credits": <int from metadata.cost>,
              "llm_usd": <float from metadata.charging.llm_price>
            }, ...
          },
          "last_updated_unix": ...
        }

    Кэш привязан к ``agent_id``: если оператор переcвязал агента, старый
    кэш отбрасываем (стартуем с пустого), чтобы не смешивать историю двух
    разных агентов.
    """
    empty = {
        "company_key": company_key,
        "sector": sector,
        "agent_id": agent_id,
        "conversations": {},
        "last_updated_unix": 0,
    }
    p = _overview_cache_path(company_key, sector)
    if not p.exists():
        return empty
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("agent_id") != agent_id:
        return empty
    convs = data.get("conversations")
    if not isinstance(convs, dict):
        data["conversations"] = {}
    return data


def _save_overview_cache(
    company_key: str, sector: str, cache: dict,
) -> None:
    p = _overview_cache_path(company_key, sector)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _aggregate_conversations(
    convs: list[dict], cost_total: int, llm_usd_total: float,
) -> dict:
    total = len(convs)
    successful = sum(1 for c in convs if c.get("call_successful") == "success")
    failed = sum(1 for c in convs if c.get("call_successful") == "failure")
    durations = [int(c.get("call_duration_secs") or 0) for c in convs]
    dur_total = sum(durations)
    dur_avg = (dur_total / total) if total else 0
    dur_max = max(durations) if durations else 0
    llm_usd_avg = (llm_usd_total / total) if total else 0.0
    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "duration_total": dur_total,
        "duration_avg": int(dur_avg),
        "duration_max": dur_max,
        "cost_total_credits": cost_total,
        "llm_usd_total": llm_usd_total,
        "llm_usd_avg": llm_usd_avg,
    }


def _fmt_hms(secs: int) -> str:
    s = int(secs or 0)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m:02d}m"


def _normalize_sip_header_to_dyn_var(name: str) -> str:
    """Convert a Webitel SIP-header (``sip_h_X-<a>-<b>-<c>``) to the
    ElevenLabs dynamic-variable form (``sip_<a>_<b>_<c>``). Mirrors how
    ElevenLabs auto-normalizes incoming custom SIP headers."""
    n = name or ""
    if n.lower().startswith("sip_h_x-"):
        n = n[len("sip_h_X-"):]
    return "sip_" + n.lower().replace("-", "_")


def _extract_bridge_endpoints(node: dict) -> list[dict]:
    sch = node.get("schema") or {}
    eps = sch.get("endpoints") or []
    return [e for e in eps if isinstance(e, dict)]


def _bridge_is_test(node: dict) -> bool:
    """True если хотя бы у одного endpoint'а gateway содержит ``test`` в
    имени. Соглашение Webitel-схем Aventus: production-gateway называется
    ``11labs_collection_voice_bot`` / ``11labs_cc_voice_bot`` / т.п., а
    sandbox-bridge с hardcoded JJ Abrams / 22222 / etc. — на gateway
    ``11labs_test``. Такие bridge-ноды в Mapping не показываем."""
    for ep in _extract_bridge_endpoints(node):
        gw_name = ((ep.get("gateway") or {}).get("name") or "").lower()
        if "test" in gw_name:
            return True
    return False


def _extract_httprequest_exports(node: dict) -> list[dict]:
    sch = node.get("schema") or {}
    out = sch.get("exportVariables") or sch.get("exports") or []
    return [v for v in out if isinstance(v, dict)]


def _extract_set_vars(node: dict) -> list[dict]:
    sch = node.get("schema") or {}
    out = sch.get("set") or []
    return [v for v in out if isinstance(v, dict)]


class VoiceBotMappingPanel(ttk.Frame):
    """Viewer of the Webitel voice routing schema for this company.

    Pulls the schema from Webitel (``GET /routing/schema/<id>``) using
    the company's host + token, then renders the structurally important
    bits: bridge endpoints (gateway, dialString, SIP headers →
    normalized ElevenLabs dynamic_variables), httpRequest nodes (CRM
    lookup URL + exported variables), and ``set`` test-data nodes.
    Read-only; edits to the schema happen in Webitel UI.
    """

    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        self._cfg: dict = load_config(company.key, self._sector)
        self._schema: Optional[dict] = None

        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})  ·  {t('sector_' + self._sector)}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        schema_id = self._cfg.get("webitel_schema_id") or 0
        schema_name = self._cfg.get("webitel_schema_name") or ""
        gateway_id = self._cfg.get("webitel_gateway_id") or ""
        gateway_name = self._cfg.get("webitel_gateway_name") or ""

        meta = ttk.LabelFrame(
            self, text=t("voice_bot_mapping_section_schema"), padding=10,
        )
        meta.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(
            meta, foreground=META_FG,
            text=t("voice_bot_mapping_schema_label") + ":",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        self._schema_label = ttk.Label(
            meta, text=f"{schema_name or '—'}  (id={schema_id or '—'})",
            foreground=TEXT_FG,
        )
        self._schema_label.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(
            meta, foreground=META_FG,
            text=t("voice_bot_mapping_gateway_label") + ":",
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        self._gateway_label = ttk.Label(
            meta, text=f"{gateway_name or '—'}  (id={gateway_id or '—'})",
            foreground=TEXT_FG,
        )
        self._gateway_label.grid(row=1, column=1, sticky="w", pady=2)
        # Bridge dialString — заполняется после Pull из первого endpoint'а
        # production bridge'а (test-bridges отфильтрованы).
        ttk.Label(
            meta, foreground=META_FG,
            text=t("voice_bot_mapping_dial_label") + ":",
        ).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        self._dial_label = ttk.Label(
            meta, text="—", foreground=TEXT_FG, font=("Consolas", 9),
        )
        self._dial_label.grid(row=2, column=1, sticky="w", pady=2)
        # Agent phone (ElevenLabs) — фоновый воркер тянет
        # `/v1/convai/phone-numbers` после рендера схемы; если у выбранного
        # agent_id есть привязанные номера, показываем их + ✓/⚠ по
        # совпадению с dialString по суффиксу.
        ttk.Label(
            meta, foreground=META_FG,
            text=t("voice_bot_mapping_agent_phone_label") + ":",
        ).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=2)
        self._agent_phone_label = ttk.Label(
            meta, text="—", foreground=TEXT_FG, font=("Consolas", 9),
        )
        self._agent_phone_label.grid(row=3, column=1, sticky="w", pady=2)
        # Pick button — всегда видим (даже если schema_id ещё не задан, что
        # типично для AR / новой компании без SEED).
        ttk.Button(
            meta, text=t("voice_bot_mapping_pick_schema"),
            command=self._pick_schema_dialog,
        ).grid(row=0, column=2, padx=(20, 0), sticky="w")
        if schema_id:
            ttk.Button(
                meta, text=t("voice_bot_mapping_open_in_webitel"),
                command=self._open_in_webitel,
            ).grid(row=1, column=2, padx=(20, 0), sticky="w")
        self._pull_btn = ttk.Button(
            meta, text=t("voice_bot_mapping_pull"),
            command=self._pull, style="Accent.TButton",
        )
        self._pull_btn.grid(row=0, column=3, rowspan=2, padx=(6, 0), sticky="w")
        if not schema_id:
            self._pull_btn.configure(state="disabled")
        self._status = ttk.Label(meta, text="", foreground=META_FG)
        self._status.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # Hint показываем только когда schema_id ещё не привязан. Ссылку
        # храним, чтобы убрать после успешного Pick.
        self._no_schema_hint: Optional[ttk.Label] = None
        if not schema_id:
            self._no_schema_hint = ttk.Label(
                self, text=t("voice_bot_mapping_no_schema_id"),
                foreground=TBD_FG, wraplength=900, justify="left",
            )
            self._no_schema_hint.pack(anchor="w", padx=14, pady=12)

        # Scrollable body строим всегда — даже без schema_id, чтобы после
        # Pick'a можно было сразу запустить Pull без переоткрытия таба.
        self._build_scrollable_body()
        if schema_id:
            self.after(50, self._pull)

    def _build_scrollable_body(self) -> None:
        body_wrap = ttk.Frame(self)
        body_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        canvas = tk.Canvas(body_wrap, highlightthickness=0)
        vscroll = ttk.Scrollbar(
            body_wrap, orient="vertical", command=canvas.yview,
        )
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        self._body = ttk.Frame(canvas)
        self._body_window = canvas.create_window(
            (0, 0), window=self._body, anchor="nw",
        )
        self._body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._body_window, width=e.width),
        )

    # ------------------------------------------------------------------
    # Webitel pull
    # ------------------------------------------------------------------

    def _open_in_webitel(self) -> None:
        import webbrowser
        host = (self._company.webitel_host or "").rstrip("/")
        sid = self._cfg.get("webitel_schema_id") or 0
        if not host or not sid:
            return
        webbrowser.open(f"{host}/flow/{sid}/voice")

    def _pull(self) -> None:
        self._pull_btn.configure(state="disabled")
        self._status.configure(
            text=t("voice_bot_mapping_loading"), foreground=META_FG,
        )
        threading.Thread(target=self._pull_worker, daemon=True).start()

    def _pull_worker(self) -> None:
        try:
            from ..webitel import WebitelClient
            sid = int(self._cfg.get("webitel_schema_id") or 0)
            client = WebitelClient(
                self._company.webitel_host,
                self._company.webitel_access_token,
            )
            schema = client.get_schema(sid)
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001 — webitel client can raise many things
            schema, err = None, str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render(schema, err))

    # ------------------------------------------------------------------
    # Agent phone (ElevenLabs) ↔ bridge dialString match
    # ------------------------------------------------------------------

    @staticmethod
    def _digits_suffix(value: str, n: int = 9) -> str:
        """Удаляет всё не-цифровое и возвращает суффикс длины n. Используется
        для fuzzy-сравнения форматов телефона: dialString ``00098123126``
        vs E.164 ``+541112345678`` — берём последние 9 цифр и сравниваем."""
        digits = "".join(c for c in (value or "") if c.isdigit())
        return digits[-n:] if len(digits) >= n else digits

    def _refresh_agent_phone(self, dial_string: str) -> None:
        """Async: тянем все phone-numbers ElevenLabs workspace'a, фильтруем
        по cfg.agent_id, сравниваем суффиксы с bridge dialString. Только
        если есть agent_id и ElevenLabs API key для компании."""
        agent_id = (self._cfg.get("elevenlabs_agent_id") or "").strip()
        if not agent_id:
            self._agent_phone_label.configure(
                text=t("voice_bot_mapping_agent_phone_no_agent"),
                foreground=TBD_FG,
            )
            return
        api_key = get_elevenlabs_key(self._company.key)
        if not api_key:
            self._agent_phone_label.configure(
                text=t("voice_bot_mapping_agent_phone_no_key"),
                foreground=TBD_FG,
            )
            return
        self._agent_phone_label.configure(
            text=t("voice_bot_mapping_agent_phone_loading"), foreground=META_FG,
        )
        threading.Thread(
            target=self._agent_phone_worker,
            args=(agent_id, dial_string, api_key),
            daemon=True,
        ).start()

    def _agent_phone_worker(
        self, agent_id: str, dial_string: str, api_key: str,
    ) -> None:
        try:
            from ..elevenlabs import list_phone_numbers
            numbers = list_phone_numbers(api_key=api_key)
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001
            numbers, err = [], str(exc)
        if not self.winfo_exists():
            return
        self.after(
            0, lambda: self._apply_agent_phone(agent_id, dial_string, numbers, err),
        )

    def _apply_agent_phone(
        self, agent_id: str, dial_string: str,
        numbers: list, err: Optional[str],
    ) -> None:
        if err:
            self._agent_phone_label.configure(text=err, foreground=ERR_FG)
            return
        # Найти phone-numbers, привязанные к нашему agent_id.
        assigned: list[dict] = []
        for n in (numbers or []):
            if not isinstance(n, dict):
                continue
            aa = n.get("assigned_agent") or {}
            aid = (aa.get("agent_id") if isinstance(aa, dict) else None) or n.get("agent_id")
            if aid and str(aid) == agent_id:
                assigned.append(n)
        if not assigned:
            self._agent_phone_label.configure(
                text=t("voice_bot_mapping_agent_phone_none"), foreground=TBD_FG,
            )
            return
        dial_suffix = self._digits_suffix(dial_string)
        # Сравниваем суффиксы цифр (последние 9). Маркируем каждое
        # назначение ✓/⚠ по совпадению с dialString.
        parts: list[str] = []
        any_match = False
        for n in assigned:
            phone = str(n.get("phone_number") or "—")
            ph_suffix = self._digits_suffix(phone)
            if dial_suffix and ph_suffix and dial_suffix == ph_suffix:
                parts.append(f"✓ {phone}")
                any_match = True
            else:
                parts.append(f"⚠ {phone}")
        self._agent_phone_label.configure(
            text="  ·  ".join(parts),
            foreground=OK_FG if any_match else ERR_FG,
        )

    def _render(self, schema: Optional[dict], err: Optional[str]) -> None:
        self._pull_btn.configure(state="normal")
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            return
        self._schema = schema or {}
        for child in self._body.winfo_children():
            child.destroy()
        nodes = (self._schema.get("payload") or {}).get("nodes") or []
        nodes = [n for n in nodes if isinstance(n, dict)]
        bridges_all = [n for n in nodes if n.get("label") == "bridge"]
        # Sandbox bridges (gateway name содержит ``test``) скрываем — там
        # hardcoded test-данные и они только захламляют сверку.
        bridges = [n for n in bridges_all if not _bridge_is_test(n)]
        https = [n for n in nodes if n.get("label") == "httpRequest"]
        sets = [n for n in nodes if n.get("label") == "set"]
        others = [
            n for n in nodes
            if n.get("label") not in ("bridge", "httpRequest", "set")
        ]

        # Detect gateway + dialString из первой production bridge (test-
        # bridges уже отфильтрованы). Всегда переписываем cfg.gateway —
        # это снимает stale gateway, который мог остаться после первой
        # привязки схемы (когда auto-detect случайно подхватил test-bridge).
        bridge_dial = ""
        for n in bridges:
            picked = False
            for ep in _extract_bridge_endpoints(n):
                gw = ep.get("gateway") or {}
                gid = gw.get("id")
                gname = gw.get("name") or ""
                dial = ep.get("dialString") or ""
                if gid:
                    if (
                        self._cfg.get("webitel_gateway_id") != gid
                        or self._cfg.get("webitel_gateway_name") != gname
                    ):
                        self._cfg["webitel_gateway_id"] = gid
                        self._cfg["webitel_gateway_name"] = gname
                        save_config(
                            self._company.key, self._cfg, self._sector,
                        )
                    self._gateway_label.configure(
                        text=f"{gname or '—'}  (id={gid})",
                    )
                    bridge_dial = str(dial)
                    picked = True
                    break
            if picked:
                break
        # Обновляем подпись dialString в meta-блоке.
        self._dial_label.configure(
            text=bridge_dial or "—",
        )
        # Async: подтягиваем агентские phone numbers из ElevenLabs и
        # сравниваем с dialString по цифровому суффиксу.
        self._refresh_agent_phone(bridge_dial)

        # Auto-extract `dynamic_variables` из bridge-ноды (единственной по
        # дизайну voice-схемы). Имена SIP-headers нормализуются как это
        # делает ElevenLabs (`sip_h_X-foo-bar` → `sip_foo_bar`), и список
        # уходит в cfg как source of truth для валидатора на Prompts-табе
        # — той же ролью, что PE_SIP_DYNAMIC_VARS / CO_SIP_DYNAMIC_VARS у
        # SEEDS-привязанных тенантов.
        extracted: list[str] = []
        if bridges:
            seen: set[str] = set()
            for ep in _extract_bridge_endpoints(bridges[0]):
                for p in (ep.get("parameters") or []):
                    if not isinstance(p, dict):
                        continue
                    k = (p.get("key") or "").strip()
                    if not k.lower().startswith("sip_h_x-"):
                        continue
                    var = _normalize_sip_header_to_dyn_var(k)
                    if var and var not in seen:
                        seen.add(var)
                        extracted.append(var)
            current = list(self._cfg.get("dynamic_variables") or [])
            if extracted and extracted != current:
                self._cfg["dynamic_variables"] = extracted
                save_config(
                    self._company.key, self._cfg, self._sector,
                )
        self._extracted_vars_count = len(extracted)

        # Map channel-var → откуда у него значение. У AR/CO/PE-схем источников
        # обычно два:
        #   1) единственный httpRequest с exportVariables — извлечение из
        #      JSON-ответа CRM по номеру; pair = ("crm", json_path).
        #   2) set-ноды (constants / channel-var references) — pair = ("set",
        #      value). Сюда часто кладут collector_id (literal), loan_id (из
        #      ${destination}) и т.д., которые не приходят из CRM напрямую.
        var_source_map: dict[str, tuple[str, str]] = {}
        # Set-нодами заполняем первыми, чтобы httpRequest exports их
        # переписали (если та же переменная и там, и там — приоритет CRM-
        # пути, т.к. он семантически точнее).
        for sn in sets:
            for v in _extract_set_vars(sn):
                k = (v.get("key") or "").strip()
                val = v.get("value")
                if k:
                    var_source_map[k] = ("set", "" if val is None else str(val))
        if len(https) == 1:
            for e in _extract_httprequest_exports(https[0]):
                k = (e.get("key") or "").strip()
                val = (e.get("value") or "").strip()
                if k:
                    var_source_map[k] = ("crm", val)
        self._var_source_map = var_source_map

        for n in bridges:
            self._render_bridge(n)
        for n in https:
            self._render_httprequest(n)
        for n in sets:
            self._render_set(n)
        if others:
            others_box = ttk.LabelFrame(
                self._body,
                text=t("voice_bot_mapping_section_other_nodes"),
                padding=8,
            )
            others_box.pack(fill="x", pady=(0, 8))
            for n in others:
                ttk.Label(
                    others_box,
                    text=f"• {n.get('label','?')}  id={n.get('id','')}",
                    foreground=TEXT_FG,
                ).pack(anchor="w")

        self._status.configure(
            text=t("voice_bot_mapping_loaded").format(
                bridges=len(bridges), https=len(https),
                sets=len(sets), others=len(others),
                vars=self._extracted_vars_count,
            ),
            foreground=OK_FG,
        )

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _render_bridge(self, node: dict) -> None:
        nid = node.get("id", "")
        eps = _extract_bridge_endpoints(node)
        title = t("voice_bot_mapping_bridge_title").format(id=nid)
        box = ttk.LabelFrame(self._body, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        var_source_map: dict[str, tuple[str, str]] = getattr(
            self, "_var_source_map", {},
        ) or {}
        for i, ep in enumerate(eps):
            gw = ep.get("gateway") or {}
            gw_name = gw.get("name") or "—"
            gw_id = gw.get("id") or "—"
            dial = ep.get("dialString") or "—"
            ttk.Label(
                box,
                text=t("voice_bot_mapping_endpoint_header").format(
                    n=i + 1, gw=gw_name, gw_id=gw_id, dial=dial,
                ),
                foreground=TEXT_FG, font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(0, 4))
            params = [p for p in (ep.get("parameters") or []) if isinstance(p, dict)]
            sip_params = [p for p in params if (p.get("key") or "").lower().startswith("sip_h_x-")]
            if not sip_params:
                ttk.Label(
                    box, text=t("voice_bot_mapping_no_sip_headers"),
                    foreground=TBD_FG,
                ).pack(anchor="w", pady=(0, 2))
                continue
            # Колонки по новому порядку:
            #   1) crm_var   — что приходит из CRM-ответа (JSON path)
            #   2) schema_var — channel-var, как мы его называем в exports
            #   3) bridge    — нормализованное имя из bridge (ElevenLabs sees)
            #   4) value     — значение из bridge (`${var}` или literal)
            #   5) prompt    — placeholder в промте бота (`{{var}}`)
            tv = ttk.Treeview(
                box,
                columns=("crm_var", "schema_var", "bridge", "value", "prompt"),
                show="headings",
                height=min(15, max(3, len(sip_params))),
            )
            tv.heading("crm_var", text=t("voice_bot_mapping_col_crm_var"))
            tv.heading("schema_var", text=t("voice_bot_mapping_col_schema_var"))
            tv.heading("bridge", text=t("voice_bot_mapping_col_bridge_name"))
            tv.heading("value", text=t("voice_bot_mapping_col_bridge_value"))
            tv.heading("prompt", text=t("voice_bot_mapping_col_prompt_name"))
            tv.column("crm_var", width=240, anchor="w")
            tv.column("schema_var", width=200, anchor="w")
            tv.column("bridge", width=200, anchor="w")
            tv.column("value", width=200, anchor="w")
            tv.column("prompt", width=220, anchor="w")
            # Per-row tagging: green когда bridge name (без `sip_`) == имени
            # channel-var в Source (`${var}`). Это «правильный» mapping.
            # Красный — рассинхрон (опечатка / подмена / пропуск). Литералы
            # без `${...}` — нейтральные (сознательный hardcode).
            tv.tag_configure("match", background="#dcfce7")
            tv.tag_configure("mismatch", background="#fee2e2")
            for p in sip_params:
                k = p.get("key") or ""
                v = p.get("value")
                if v is None:
                    v = ""
                source_text = str(v)
                norm = _normalize_sip_header_to_dyn_var(k)
                # Parse `${channel_var}` из source.
                channel_var = ""
                stripped = source_text.strip()
                if stripped.startswith("${") and stripped.endswith("}"):
                    channel_var = stripped[2:-1].strip()
                # Tag.
                tag = ""
                if channel_var:
                    expected = norm[len("sip_"):] if norm.startswith("sip_") else norm
                    tag = "match" if expected == channel_var else "mismatch"
                # Cross-reference channel-var с источником из httpRequest /
                # set-нод. CRM-экспорт показывается как JSON path; set-
                # литералы — с префиксом `set: ` чтобы оператор видел, что
                # источник — нода в schema, не CRM-ответ.
                source_display = "—"
                if channel_var and channel_var in var_source_map:
                    src_type, src_val = var_source_map[channel_var]
                    if src_type == "crm":
                        source_display = src_val or channel_var
                    else:
                        source_display = f"set: {src_val}" if src_val else "set"
                prompt_name = "{{ " + norm + " }}" if norm else ""
                tv.insert(
                    "", "end",
                    values=(
                        source_display,
                        channel_var or "—",
                        norm or "—",
                        source_text,
                        prompt_name,
                    ),
                    tags=((tag,) if tag else ()),
                )
            tv.pack(fill="x", pady=(0, 6))

    def _render_httprequest(self, node: dict) -> None:
        """Минимальный показ: URL (с методом) в заголовке секции +
        body, если он непустой. Список exports не дублируется отдельной
        таблицей — переменные оттуда уже отражены в bridge-таблице через
        колонку «Источник» (CRM path / set). Это убирает шум на скрине."""
        nid = node.get("id", "")
        sch = node.get("schema") or {}
        url = sch.get("url") or sch.get("requestUrl") or "—"
        method = sch.get("method") or sch.get("requestMethod") or "POST"
        body_data = sch.get("data") or ""
        title = t("voice_bot_mapping_httprequest_title_with_url").format(
            id=nid, method=method, url=url,
        )
        box = ttk.LabelFrame(self._body, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        if body_data and body_data != "{}":
            ttk.Label(
                box, text=f"body: {body_data}",
                foreground=META_FG, font=("Consolas", 9),
                wraplength=900, justify="left",
            ).pack(anchor="w", pady=(0, 4))
        else:
            ttk.Label(
                box, text=t("voice_bot_mapping_httprequest_no_body"),
                foreground=META_FG,
            ).pack(anchor="w", pady=(0, 2))

    def _render_set(self, node: dict) -> None:
        nid = node.get("id", "")
        rows = _extract_set_vars(node)
        title = t("voice_bot_mapping_set_title").format(id=nid, n=len(rows))
        box = ttk.LabelFrame(self._body, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        if not rows:
            ttk.Label(
                box, text=t("voice_bot_mapping_set_empty"),
                foreground=TBD_FG,
            ).pack(anchor="w")
            return
        tv = ttk.Treeview(
            box,
            columns=("var", "val"),
            show="headings",
            height=min(20, max(3, len(rows))),
        )
        tv.heading("var", text=t("voice_bot_mapping_col_var"))
        tv.heading("val", text=t("voice_bot_mapping_col_value"))
        tv.column("var", width=220, anchor="w")
        tv.column("val", width=540, anchor="w")
        for r in rows:
            tv.insert(
                "", "end",
                values=(r.get("key") or "", str(r.get("value", ""))),
            )
        tv.pack(fill="x")

    # ------------------------------------------------------------------
    # Voice schema picker (Webitel)
    # ------------------------------------------------------------------

    def _pick_schema_dialog(self) -> None:
        """Список voice-схем Webitel → выбор → сохранение в voice_bot_config.

        Применим к компаниям без SEED'a (AR / новые тенанты) и к перевязке
        на другую схему. После сохранения просим переоткрыть таб, чтобы
        Mapping заново отрисовал тело с новой схемой."""
        if not (self._company.webitel_host or "").strip():
            messagebox.showwarning(
                t("voice_bot_mapping_pick_schema"),
                t("voice_bot_mapping_no_webitel_host"),
                parent=self.winfo_toplevel(),
            )
            return
        self._status.configure(
            text=t("voice_bot_mapping_listing_schemas"), foreground=META_FG,
        )
        threading.Thread(target=self._list_schemas_worker, daemon=True).start()

    def _list_schemas_worker(self) -> None:
        try:
            from ..webitel import WebitelClient
            client = WebitelClient(
                self._company.webitel_host,
                self._company.webitel_access_token,
            )
            schemas = client.list_voice_schemas()
            err: Optional[str] = None
        except Exception as exc:  # noqa: BLE001
            schemas, err = [], str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_schema_picker(schemas, err))

    def _render_schema_picker(
        self, schemas: list, err: Optional[str],
    ) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_mapping_pick_schema"), err,
                parent=self.winfo_toplevel(),
            )
            return
        if not schemas:
            self._status.configure(
                text=t("voice_bot_mapping_no_schemas"), foreground=META_FG,
            )
            messagebox.showinfo(
                t("voice_bot_mapping_pick_schema"),
                t("voice_bot_mapping_no_schemas_long"),
                parent=self.winfo_toplevel(),
            )
            return

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(t("voice_bot_mapping_pick_schema"))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        tree = ttk.Treeview(
            dialog, columns=("name", "id"),
            show="headings", height=min(20, max(5, len(schemas))),
        )
        tree.heading("name", text=t("voice_bot_mapping_schema_name"))
        tree.heading("id", text=t("voice_bot_mapping_schema_id"))
        tree.column("name", width=420, anchor="w")
        tree.column("id", width=120, anchor="w")
        # Подсветим текущую привязку, если есть.
        current_id = int(self._cfg.get("webitel_schema_id") or 0)
        focused = None
        for s in schemas:
            iid = tree.insert("", "end", values=(s.name or "—", s.id))
            if s.id == current_id:
                focused = iid
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        if focused:
            tree.selection_set(focused)
            tree.see(focused)

        def use_selected() -> None:
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            picked_name = str(vals[0]) if vals[0] != "—" else ""
            try:
                picked_id = int(vals[1])
            except (TypeError, ValueError):
                return
            if not picked_id:
                return
            if not messagebox.askyesno(
                t("voice_bot_mapping_pick_schema"),
                t("voice_bot_mapping_pick_confirm").format(
                    name=picked_name or "—", schema_id=picked_id,
                ),
                parent=dialog,
            ):
                return
            # Save new schema_id + name; clear gateway чтобы _render
            # авто-задетектил его из bridge-ноды при следующем Pull.
            self._cfg["webitel_schema_id"] = picked_id
            self._cfg["webitel_schema_name"] = picked_name
            self._cfg["webitel_gateway_id"] = None
            self._cfg["webitel_gateway_name"] = ""
            save_config(
                self._company.key, self._cfg, self._sector,
            )
            self._schema_label.configure(
                text=f"{picked_name or '—'}  (id={picked_id})",
            )
            self._gateway_label.configure(text="—  (id=—)")
            dialog.destroy()
            self._status.configure(
                text=t("voice_bot_mapping_pick_done").format(
                    name=picked_name or "—", schema_id=picked_id,
                ),
                foreground=OK_FG,
            )
            # Если был hint «нет схемы» — убираем, тело уже построено
            # в __init__ и готово принять отрисовку. Pull стартует
            # auto-detect gateway + dynamic_variables.
            if self._no_schema_hint is not None:
                self._no_schema_hint.destroy()
                self._no_schema_hint = None
            self._pull_btn.configure(state="normal")
            self._pull()

        btns = ttk.Frame(dialog)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text=t("btn_cancel"), command=dialog.destroy).pack(
            side="right",
        )
        ttk.Button(
            btns, text=t("voice_bot_mapping_use_schema"),
            command=use_selected, style="Accent.TButton",
        ).pack(side="right", padx=(0, 6))
        tree.bind("<Double-1>", lambda _e: use_selected())


class VoiceBotPromptsPanel(ttk.Frame):
    """Prompts editor for the company's ElevenLabs voice agent.

    Layout (top → bottom):
      * Header — компания, agent_id, кнопка задать API key.
      * Тулбар Pull / Push / Save / List agents — между ElevenLabs и
        локальным конфигом.
      * Баннер «структура не распознана» — поднимается при Pull, если
        промт ElevenLabs пришёл без block-anchors.
      * Notebook с 8 вкладками для блоков system prompt.
      * First message — короткое текстовое поле.
      * Подсказка по dynamic_variables (SIP-headers из bridge-ноды).
      * Валидатор: сверка SIP-vars и enum action_trees с tool snapshot.
    """

    def __init__(
        self, master: tk.Misc, company: Company,
        sector: str = DEFAULT_SECTOR,
    ) -> None:
        super().__init__(master)
        self._company = company
        self._sector = sector if sector in SECTORS else DEFAULT_SECTOR
        self._cfg: dict = load_config(company.key, self._sector)
        # block_id → tk.Text. Заполняется в loop'е ниже.
        self._block_texts: dict[str, tk.Text] = {}

        # ---- Заголовок + agent_id + API key dialog ----
        ttk.Label(
            self,
            text=t("voice_bot_header"),
            font=("Segoe UI", 9, "bold"),
            foreground=META_FG,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        code = company.key.rstrip("_")
        ttk.Label(
            self,
            text=f"{code} — {company.name} ({company.country})  ·  {t('sector_' + self._sector)}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        meta = ttk.LabelFrame(self, text=t("voice_bot_section_meta"), padding=10)
        meta.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(meta, text=t("voice_bot_agent_id") + ":", foreground=META_FG).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=2,
        )
        self._agent_id_var = tk.StringVar(
            value=str(self._cfg.get("elevenlabs_agent_id") or ""),
        )
        ttk.Entry(
            meta, textvariable=self._agent_id_var, width=40,
        ).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Button(
            meta, text=t("voice_bot_list_agents"), command=self._pick_agent_dialog,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0), pady=2)
        ttk.Button(
            meta, text=t("voice_bot_set_key"), command=self._set_api_key,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0), pady=2)

        sname = self._cfg.get("webitel_schema_name") or "—"
        sid = self._cfg.get("webitel_schema_id")
        gname = self._cfg.get("webitel_gateway_name") or "—"
        ttk.Label(
            meta,
            text=t("voice_bot_webitel_schema") + ":", foreground=META_FG,
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(
            meta, text=f"{sname} (id={sid})  →  gateway {gname}",
            foreground=TEXT_FG,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=2)

        # ---- Тулбар Pull / Push / Save ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(0, 8))
        self._pull_btn = ttk.Button(
            toolbar, text=t("voice_bot_pull"), command=self._pull_from_elevenlabs,
        )
        self._pull_btn.pack(side="left")
        self._push_btn = ttk.Button(
            toolbar, text=t("voice_bot_push"), command=self._push_to_elevenlabs,
            style="Accent.TButton",
        )
        self._push_btn.pack(side="left", padx=(6, 0))
        ttk.Button(
            toolbar, text=t("btn_save"), command=self._save_local,
        ).pack(side="left", padx=(6, 0))
        self._status = ttk.Label(toolbar, text="", foreground=META_FG)
        self._status.pack(side="left", padx=(12, 0))

        # ---- Баннер «структура не распознана» (по умолчанию скрыт) ----
        self._unparsed_banner = ttk.Label(
            self,
            text=t("voice_bot_unparsed_banner"),
            foreground=ERR_FG,
            wraplength=900,
            justify="left",
        )
        # pack-ится по требованию через _show_unparsed_banner.

        # ---- Notebook со вкладками-блоками system prompt ----
        ttk.Label(
            self, text=t("voice_bot_prompt_main"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(8, 2))
        ttk.Label(
            self, text=t("voice_bot_blocks_help"),
            foreground=META_FG, wraplength=900, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 4))

        dyn_vars_for_blocks = list(
            self._cfg.get("dynamic_variables") or SIP_DYNAMIC_VARS
        )
        block_vars_map = block_vars_for(dyn_vars_for_blocks)

        blocks_nb = ttk.Notebook(self)
        blocks_nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        cfg_blocks = self._cfg.get("main_prompt_blocks") or {}
        for bid in BLOCK_ORDER:
            tab = ttk.Frame(blocks_nb, padding=8)
            blocks_nb.add(tab, text=_block_title(bid))

            ttk.Label(
                tab, text=_block_help(bid),
                foreground=META_FG, wraplength=900, justify="left",
            ).pack(anchor="w", pady=(0, 4))

            relevant_vars = block_vars_map.get(bid) or ()
            if relevant_vars:
                ttk.Label(
                    tab,
                    text=t("voice_bot_block_vars_label") + ":  "
                    + "  ".join(f"{{{{ {v} }}}}" for v in relevant_vars),
                    foreground=TEXT_FG, font=("Consolas", 9),
                    wraplength=900, justify="left",
                ).pack(anchor="w", pady=(0, 4))

            txt = tk.Text(tab, wrap="word")
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", str(cfg_blocks.get(bid) or ""))
            self._block_texts[bid] = txt

        # ---- First message ----
        ttk.Label(
            self, text=t("voice_bot_first_message"), font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        self._first_message = tk.Text(self, height=3, wrap="word")
        self._first_message.pack(fill="x", padx=12, pady=(0, 8))
        self._first_message.insert("1.0", str(self._cfg.get("first_message") or ""))

        # ---- SIP dynamic_variables (только список placeholder'ов, per-company) ----
        vars_box = ttk.LabelFrame(
            self, text=t("voice_bot_section_dynamic_vars"), padding=8,
        )
        vars_box.pack(fill="x", padx=12, pady=(0, 12))
        dyn_vars = list(self._cfg.get("dynamic_variables") or SIP_DYNAMIC_VARS)
        ttk.Label(
            vars_box,
            text="  ".join(f"{{{{ {v} }}}}" for v in dyn_vars),
            foreground=TEXT_FG, font=("Consolas", 9),
            wraplength=900, justify="left",
        ).pack(anchor="w")

        # ---- Сверка с tool и action_trees -----------------------------
        self._dyn_vars_for_validation: list[str] = dyn_vars
        self._validator_pending: Optional[str] = None  # after-id для debounce
        val_box = ttk.LabelFrame(
            self, text=t("voice_bot_validator_section"), padding=8,
        )
        val_box.pack(fill="both", expand=False, padx=12, pady=(0, 12))
        header_row = ttk.Frame(val_box)
        header_row.pack(fill="x", pady=(0, 4))
        ttk.Label(
            header_row, text=t("voice_bot_validator_help"),
            foreground=META_FG, wraplength=820, justify="left",
        ).pack(side="left", anchor="w")
        ttk.Button(
            header_row, text=t("voice_bot_validator_refresh"),
            command=self._refresh_validator,
        ).pack(side="right")

        ttk.Label(
            val_box, text=t("voice_bot_validator_subtitle_vars"),
            foreground=META_FG, font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(4, 2))
        self._vars_tree = ttk.Treeview(
            val_box,
            columns=("var", "prompt", "tool", "note"),
            show="headings",
            height=min(8, max(3, len(dyn_vars) + 1)),
        )
        for col, key, width, anchor in (
            ("var", "voice_bot_validator_col_var", 220, "w"),
            ("prompt", "voice_bot_validator_col_prompt", 90, "center"),
            ("tool", "voice_bot_validator_col_tool", 90, "center"),
            ("note", "voice_bot_validator_col_note", 380, "w"),
        ):
            self._vars_tree.heading(col, text=t(key))
            self._vars_tree.column(col, width=width, anchor=anchor)
        self._vars_tree.pack(fill="x", pady=(0, 6))

        ttk.Label(
            val_box, text=t("voice_bot_validator_subtitle_enums"),
            foreground=META_FG, font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(4, 2))
        self._enums_tree = ttk.Treeview(
            val_box,
            columns=("var", "prompt", "tool", "note"),
            show="headings", height=10,
        )
        for col, key, width, anchor in (
            ("var", "voice_bot_validator_col_var", 360, "w"),
            ("prompt", "voice_bot_validator_col_prompt", 90, "center"),
            ("tool", "voice_bot_validator_col_tool", 90, "center"),
            ("note", "voice_bot_validator_col_note", 240, "w"),
        ):
            self._enums_tree.heading(col, text=t(key))
            self._enums_tree.column(col, width=width, anchor=anchor)
        self._enums_tree.pack(fill="x", pady=(0, 4))
        self._validator_status = ttk.Label(
            val_box, text="", foreground=META_FG,
        )
        self._validator_status.pack(anchor="w")

        # Debounced refresh on prompt edit (300ms after last keystroke).
        for txt in self._block_texts.values():
            txt.bind(
                "<KeyRelease>", lambda _e: self._schedule_validator_refresh(),
            )
        self._first_message.bind(
            "<KeyRelease>", lambda _e: self._schedule_validator_refresh(),
        )
        self._refresh_validator()

    # ------------------------------------------------------------------
    # Block helpers
    # ------------------------------------------------------------------

    def _collect_blocks(self) -> dict[str, str]:
        return {
            bid: self._block_texts[bid].get("1.0", "end").rstrip()
            for bid in BLOCK_ORDER
        }

    def _joined_prompt_text(self) -> str:
        """Полный system prompt = склейка всех 8 блоков (без anchors —
        для валидатора, который ищет {{placeholders}} и enum-значения)."""
        return "\n\n".join(
            self._block_texts[bid].get("1.0", "end") for bid in BLOCK_ORDER
        )

    def _show_unparsed_banner(self, show: bool) -> None:
        if show:
            self._unparsed_banner.pack(fill="x", padx=12, pady=(0, 6))
        else:
            self._unparsed_banner.pack_forget()

    # ------------------------------------------------------------------
    # Validator
    # ------------------------------------------------------------------

    def _schedule_validator_refresh(self) -> None:
        if self._validator_pending is not None:
            try:
                self.after_cancel(self._validator_pending)
            except Exception:  # noqa: BLE001 — after_cancel can raise after destroy
                pass
            self._validator_pending = None
        self._validator_pending = self.after(300, self._refresh_validator)

    def _refresh_validator(self) -> None:
        self._validator_pending = None
        if not hasattr(self, "_vars_tree"):
            return
        self._vars_tree.delete(*self._vars_tree.get_children())
        self._enums_tree.delete(*self._enums_tree.get_children())

        prompt_text = (
            self._joined_prompt_text()
            + "\n"
            + self._first_message.get("1.0", "end")
        )
        used_in_prompt = _placeholders_in_text(prompt_text)

        tool = _load_voice_tool_snapshot(self._company.key, self._sector)
        tool_dv: dict[str, list[str]] = {}
        tool_enums: dict[str, list[str]] = {}
        if isinstance(tool, dict):
            schema = (tool.get("api_schema") or {}).get("request_body_schema") or {}
            props = schema.get("properties")
            if isinstance(props, list):
                for p in props:
                    if not isinstance(p, dict):
                        continue
                    pid = p.get("id") or p.get("name") or ""
                    dv = (p.get("dynamic_variable") or "").strip()
                    if dv:
                        tool_dv.setdefault(dv, []).append(pid)
                    enum_vals = p.get("enum")
                    if isinstance(enum_vals, list) and pid:
                        tool_enums[pid] = [str(x) for x in enum_vals]
            elif isinstance(props, dict):
                for pid, p in props.items():
                    if not isinstance(p, dict):
                        continue
                    dv = (p.get("dynamic_variable") or "").strip()
                    if dv:
                        tool_dv.setdefault(dv, []).append(pid)
                    enum_vals = p.get("enum")
                    if isinstance(enum_vals, list):
                        tool_enums[pid] = [str(x) for x in enum_vals]

        yes = t("voice_bot_validator_yes")
        no = t("voice_bot_validator_no")

        for v in self._dyn_vars_for_validation:
            in_prompt = v in used_in_prompt
            bound = tool_dv.get(v, [])
            self._vars_tree.insert(
                "", "end",
                values=(
                    v,
                    yes if in_prompt else no,
                    yes if bound else no,
                    ", ".join(bound) if bound else "",
                ),
            )

        tree = get_tree(self._company.key)
        if not tree:
            self._enums_tree.insert(
                "", "end",
                values=("", "", "", t("voice_bot_validator_empty_tree")),
            )
            self._validator_status.configure(
                text="" if tool else t("voice_bot_validator_empty_tool"),
                foreground=META_FG,
            )
            return

        enum_sets = enum_sets_from_tree(tree)
        if not tool:
            self._validator_status.configure(
                text=t("voice_bot_validator_empty_tool"), foreground=META_FG,
            )
        else:
            tool_id = get_tool_id(
                self._company.key, self._sector, "save_call_result",
            )
            self._validator_status.configure(
                text=t("voice_bot_validator_using_tool").format(
                    tool_id=tool_id or "—",
                ),
                foreground=META_FG,
            )

        for produces, values in enum_sets.items():
            tool_vals = tool_enums.get(produces, [])
            tool_vals_set = set(tool_vals)
            tree_set = set(values)
            extra = sorted(tool_vals_set - tree_set)
            missing = sorted(tree_set - tool_vals_set)
            note = ""
            if produces not in tool_enums and tool:
                note = t("voice_bot_validator_no_tool_prop")
            elif missing or extra:
                note = (
                    f"−{len(missing)} missing / +{len(extra)} extra"
                )
            parent_id = self._enums_tree.insert(
                "", "end",
                values=(
                    f"{produces}  ({len(values)})",
                    yes if any(v in prompt_text for v in values) else no,
                    yes if tool_vals else no,
                    note,
                ),
                open=False,
            )
            for v in values:
                in_p = v in prompt_text
                in_t = v in tool_vals_set
                self._enums_tree.insert(
                    parent_id, "end",
                    values=(
                        f"   {v}",
                        yes if in_p else no,
                        yes if in_t else no,
                        "" if in_t else (
                            t("voice_bot_validator_no_in_tool_enum")
                            if produces in tool_enums else ""
                        ),
                    ),
                )
            for ex in extra:
                self._enums_tree.insert(
                    parent_id, "end",
                    values=(
                        f"   {ex} (extra)",
                        yes if ex in prompt_text else no,
                        yes,
                        t("voice_bot_validator_no_in_tree"),
                    ),
                )

    # ------------------------------------------------------------------
    # Local persistence
    # ------------------------------------------------------------------

    def _sync_into_cfg(self) -> None:
        self._cfg["main_prompt_blocks"] = self._collect_blocks()
        self._cfg.pop("main_prompt", None)  # старое поле больше не пишем
        self._cfg["first_message"] = self._first_message.get("1.0", "end").rstrip()
        self._cfg["elevenlabs_agent_id"] = self._agent_id_var.get().strip()

    def _save_local(self) -> None:
        self._sync_into_cfg()
        save_config(self._company.key, self._cfg, self._sector)
        self._status.configure(text=t("voice_bot_saved_local"), foreground=OK_FG)

    # ------------------------------------------------------------------
    # ElevenLabs API actions
    # ------------------------------------------------------------------

    def _set_api_key(self) -> None:
        current = get_elevenlabs_key()
        hint = (
            f"{t('voice_bot_key_dialog_help')}\n\n"
            f"{t('voice_bot_key_current')}: "
            + (current[:8] + "…" + current[-4:] if current else "—")
        )
        new = simpledialog.askstring(
            t("voice_bot_key_dialog_title"), hint,
            parent=self.winfo_toplevel(),
            initialvalue=current,
            show="*",
        )
        if new is None:
            return
        set_elevenlabs_key(new.strip())
        self._status.configure(
            text=t("voice_bot_key_saved") if new.strip() else t("voice_bot_key_cleared"),
            foreground=OK_FG,
        )

    def _pick_agent_dialog(self) -> None:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return
        self._status.configure(
            text=t("voice_bot_listing_agents"), foreground=META_FG,
        )
        threading.Thread(target=self._list_agents_worker, daemon=True).start()

    def _list_agents_worker(self) -> None:
        try:
            agents = list_agents(
                api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            agents, err = [], str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._render_agent_picker(agents, err))

    def _render_agent_picker(
        self, agents: list[dict], err: Optional[str],
    ) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_section_meta"), err,
                parent=self.winfo_toplevel(),
            )
            return
        if not agents:
            self._status.configure(
                text=t("voice_bot_no_agents"), foreground=META_FG,
            )
            messagebox.showinfo(
                t("voice_bot_section_meta"),
                t("voice_bot_no_agents_long"),
                parent=self.winfo_toplevel(),
            )
            return

        prefix = _expected_agent_prefix(self._company.key)
        total = len(agents)

        def _matches(a: dict) -> bool:
            if not prefix:
                return True
            n = (a.get("name") or "").strip()
            return n == prefix or n.startswith(prefix + "_")

        filtered = [a for a in agents if _matches(a)] if prefix else list(agents)
        show_all_fallback = bool(prefix) and not filtered
        visible_agents = agents if show_all_fallback else filtered

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(t("voice_bot_list_agents"))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        if prefix:
            if show_all_fallback:
                label_text = t("voice_bot_agent_filter_none").format(
                    prefix=prefix, total=total,
                )
                label_color = TBD_FG
            else:
                label_text = t("voice_bot_agent_filter_match").format(
                    prefix=prefix, n=len(filtered), total=total,
                )
                label_color = META_FG
            ttk.Label(
                dialog, text=label_text, foreground=label_color,
                wraplength=600, justify="left",
            ).pack(anchor="w", padx=10, pady=(10, 4))

        tree = ttk.Treeview(
            dialog, columns=("name", "agent_id"),
            show="headings", height=min(15, max(5, len(visible_agents))),
        )
        tree.heading("name", text=t("voice_bot_agent_name"))
        tree.heading("agent_id", text=t("voice_bot_agent_id"))
        tree.column("name", width=320, anchor="w")
        tree.column("agent_id", width=320, anchor="w")
        for a in visible_agents:
            tree.insert("", "end", values=(a.get("name") or "—", a.get("agent_id") or ""))
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def use_selected() -> None:
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            self._agent_id_var.set(vals[1])
            dialog.destroy()
            self._status.configure(
                text=t("voice_bot_agent_selected"), foreground=OK_FG,
            )

        btns = ttk.Frame(dialog)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text=t("btn_cancel"), command=dialog.destroy).pack(side="right")
        ttk.Button(
            btns, text=t("voice_bot_use_agent"), command=use_selected,
            style="Accent.TButton",
        ).pack(side="right", padx=(0, 6))
        tree.bind("<Double-1>", lambda _e: use_selected())

    def _pull_from_elevenlabs(self) -> None:
        if not self._require_key_and_id():
            return
        self._status.configure(text=t("voice_bot_pulling"), foreground=META_FG)
        agent_id = self._agent_id_var.get().strip()
        threading.Thread(
            target=self._pull_worker, args=(agent_id,), daemon=True,
        ).start()

    def _pull_worker(self, agent_id: str) -> None:
        try:
            agent = get_agent(
                agent_id, api_key=get_elevenlabs_key(self._company.key),
            )
            prompt, first_msg = extract_prompt(agent)
            err: Optional[str] = None
        except ElevenLabsError as exc:
            agent, prompt, first_msg, err = {}, "", "", str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._apply_pulled(agent, prompt, first_msg, err))

    def _apply_pulled(
        self, agent: dict, prompt: str, first_msg: str, err: Optional[str],
    ) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_pull"), err, parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            t("voice_bot_pull"),
            t("voice_bot_pull_confirm").format(
                name=agent.get("name") or "—",
                prompt_len=len(prompt),
                first_msg_len=len(first_msg),
            ),
            parent=self.winfo_toplevel(),
        ):
            self._status.configure(text=t("voice_bot_pull_cancelled"), foreground=META_FG)
            return
        blocks, recognized = split_blocks(prompt)
        for bid in BLOCK_ORDER:
            txt = self._block_texts[bid]
            txt.delete("1.0", "end")
            txt.insert("1.0", blocks.get(bid, ""))
        self._first_message.delete("1.0", "end")
        self._first_message.insert("1.0", first_msg)
        self._show_unparsed_banner(not recognized)
        if recognized:
            self._status.configure(text=t("voice_bot_pulled"), foreground=OK_FG)
        else:
            self._status.configure(
                text=t("voice_bot_pulled_unparsed"), foreground=ERR_FG,
            )
        self._refresh_validator()

    def _push_to_elevenlabs(self) -> None:
        if not self._require_key_and_id():
            return
        self._sync_into_cfg()
        prompt = join_blocks(self._cfg.get("main_prompt_blocks") or {})
        first_msg = self._cfg.get("first_message") or ""
        if not prompt and not first_msg:
            messagebox.showwarning(
                t("voice_bot_push"),
                t("voice_bot_push_empty"),
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            t("voice_bot_push"),
            t("voice_bot_push_confirm").format(
                agent_id=self._cfg.get("elevenlabs_agent_id") or "",
                prompt_len=len(prompt),
                first_msg_len=len(first_msg),
            ),
            parent=self.winfo_toplevel(),
        ):
            return
        self._status.configure(text=t("voice_bot_pushing"), foreground=META_FG)
        agent_id = self._cfg["elevenlabs_agent_id"]
        threading.Thread(
            target=self._push_worker,
            args=(agent_id, prompt, first_msg),
            daemon=True,
        ).start()

    def _push_worker(
        self, agent_id: str, prompt: str, first_msg: str,
    ) -> None:
        try:
            update_agent_prompt(
                agent_id,
                system_prompt=prompt,
                first_message=first_msg,
                api_key=get_elevenlabs_key(self._company.key),
            )
            err: Optional[str] = None
        except ElevenLabsError as exc:
            err = str(exc)
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._apply_pushed(err))

    def _apply_pushed(self, err: Optional[str]) -> None:
        if err:
            self._status.configure(text=err, foreground=ERR_FG)
            messagebox.showerror(
                t("voice_bot_push"), err, parent=self.winfo_toplevel(),
            )
            return
        # Локальный save после успешного push — фиксируем как «деплой».
        save_config(self._company.key, self._cfg, self._sector)
        self._status.configure(text=t("voice_bot_pushed"), foreground=OK_FG)
        # Event-trigger: алерт о применённой правке в проде.
        try:
            from ..voice_bot_alerts import dispatch_prompt_pushed_alert
            dispatch_prompt_pushed_alert(
                self._company, self._sector,
                agent_id=self._cfg.get("elevenlabs_agent_id") or "",
                blocks=self._cfg.get("main_prompt_blocks") or {},
                first_message=self._cfg.get("first_message") or "",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[voice_bot_panel] prompt-pushed alert failed: {exc}")

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _require_key_and_id(self) -> bool:
        if not get_elevenlabs_key(self._company.key):
            messagebox.showwarning(
                t("voice_bot_key_dialog_title"),
                t("voice_bot_key_missing"),
                parent=self.winfo_toplevel(),
            )
            return False
        if not self._agent_id_var.get().strip():
            messagebox.showwarning(
                t("voice_bot_agent_id"),
                t("voice_bot_agent_id_missing"),
                parent=self.winfo_toplevel(),
            )
            return False
        return True
