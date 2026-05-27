"""Event-trigger dispatch для voice-bot алертов.

В отличие от scheduler-driven шаблонов (queue_checklist, wa_senders_health,
…), эти алерты шлются по эвенту прямо из flow:

  * `dispatch_analysis_alerts(company, sector, payload)` — сразу после
    того, как `voice_bot_analysis.run_analysis` вернул успешный результат
    с предложениями. Шлёт два шаблона раздельно — `voice_analysis_
    suggestions_prompt` и `voice_analysis_suggestions_tool`, если в
    батче есть suggestion'ы соответствующего типа и алерт включён.

  * `dispatch_prompt_pushed_alert(company, sector, agent_id, blocks,
    first_message)` — после успешного PATCH system_prompt из Prompts
    panel.

  * `dispatch_tool_pushed_alert(company, sector, tool_id, tool)` —
    после успешного PATCH save_call_result tool из Results panel.

Алерт «включён» — это запись в `bot_alerts[<company>]["voice"]` с
`template=<slug>` и `enabled=True`. Schedule игнорируется (эвент-триггер).
Sector в alerts.json не разделяется — один alert config работает для
обоих секторов; маркер сектора попадает в `category` и в context_kv.

Никаких исключений наружу — UI не должен падать из-за TG-сбоя. Ошибки
тихо логируются через `print` (попадают в stdout exe).
"""
from __future__ import annotations

from typing import Optional

from .alert_format import render_alert_html
from .alerts import (
    TelegramError,
    ensure_company_topic,
    load_alerts_config,
    send_telegram_message,
    telegram_block_for_alert,
    telegram_topic_for_company,
)
from .data import Company, load_companies
from .voice_bot_config import BLOCK_ORDER, BLOCK_TITLES


# Шаблоны, на которые рассылка ниже завязана. Имена должны совпадать
# с `ALERT_TEMPLATES` в `app/alerts.py`.
TEMPLATE_SUGGESTIONS_PROMPT = "voice_analysis_suggestions_prompt"
TEMPLATE_SUGGESTIONS_TOOL = "voice_analysis_suggestions_tool"
TEMPLATE_APPLIED_PROMPT = "voice_change_applied_prompt"
TEMPLATE_APPLIED_TOOL = "voice_change_applied_tool"


def _alert_enabled(
    cfg: dict, company_key: str, template: str,
) -> Optional[dict]:
    """Найти первую включённую запись alert'а для (company, kind=voice,
    template=<slug>). Возвращает alert-dict или None."""
    bots = cfg.get("bot_alerts") or {}
    co_bucket = bots.get(company_key) or {}
    alerts = co_bucket.get("voice") or []
    for a in alerts:
        if (
            isinstance(a, dict)
            and a.get("template") == template
            and a.get("enabled", True)
        ):
            return a
    return None


def _resolve_company(company_or_key) -> Optional[Company]:
    if isinstance(company_or_key, Company):
        return company_or_key
    if isinstance(company_or_key, str):
        for c in load_companies():
            if c.key == company_or_key:
                return c
    return None


def _send_html(
    cfg: dict, company: Company, template: str, html_body: str,
) -> None:
    """Отправить уже отрендеренный HTML в нужный TG-блок + топик компании.
    Никаких исключений наружу."""
    tg = telegram_block_for_alert(cfg, template)
    bot_token = (tg or {}).get("bot_token") or ""
    chat_id = (tg or {}).get("chat_id") or ""
    if not bot_token or not chat_id:
        print(f"[voice_bot_alerts] {template}: TG-блок не настроен (bot_token/chat_id), skip")
        return
    topic_id = telegram_topic_for_company(tg, company.key)
    if topic_id is None:
        # попытаться создать топик на лету (как делает alerts_panel test-send)
        try:
            topic_id = ensure_company_topic(cfg, company)
        except Exception as exc:  # noqa: BLE001 — TG может вернуть любое
            print(f"[voice_bot_alerts] ensure_company_topic failed: {exc}")
            topic_id = None
    try:
        send_telegram_message(
            bot_token, str(chat_id), html_body,
            parse_mode="HTML",
            message_thread_id=topic_id,
        )
    except TelegramError as exc:
        print(f"[voice_bot_alerts] {template}: TG error: {exc}")


# ---------------------------------------------------------------------------
# Suggestions (after run_analysis)
# ---------------------------------------------------------------------------

def _block_title(block_id: str) -> str:
    return BLOCK_TITLES.get(block_id, block_id)


_SEVERITY_EMOJI = {"low": "🟢", "medium": "🟠", "high": "🔴"}


def _format_suggestion_bullets(suggestions: list[dict], limit: int = 10) -> list[str]:
    bullets: list[str] = []
    for sg in suggestions[:limit]:
        sev = (sg.get("severity") or "low").lower()
        emoji = _SEVERITY_EMOJI.get(sev, "•")
        target = sg.get("target") or ""
        if target == "prompt_block":
            tag = _block_title(sg.get("block_id") or "?")
        elif target == "tool_property":
            tag = (
                f"{sg.get('tool_property') or '?'}"
                f" / {sg.get('tool_field') or '?'}"
            )
        else:
            tag = target or "?"
        title = (sg.get("title") or "—").strip()
        bullets.append(f"{emoji} [{tag}] {title}")
    if len(suggestions) > limit:
        bullets.append(f"… и ещё {len(suggestions) - limit}")
    return bullets


def dispatch_analysis_alerts(
    company_or_key, sector: str, payload: dict,
) -> None:
    """Разослать два эвент-алерта по результатам run_analysis.

    `payload` — это словарь, который `run_analysis` сохраняет в analysis
    state: ожидаются ключи ``ok``, ``result.suggestions``, ``calls_fetched``,
    ``model``, ``params.{since_ts,until_ts}``.
    """
    try:
        if not payload or not payload.get("ok"):
            return
        company = _resolve_company(company_or_key)
        if company is None:
            return
        result = payload.get("result") or {}
        suggestions = result.get("suggestions") or []
        if not suggestions:
            return

        prompt_sg = [
            s for s in suggestions if s.get("target") == "prompt_block"
        ]
        tool_sg = [
            s for s in suggestions if s.get("target") == "tool_property"
        ]

        cfg = load_alerts_config()
        calls_n = result.get("calls_analyzed") or payload.get("calls_fetched") or 0
        params = payload.get("params") or {}
        common = result.get("common_failures") or []
        summary = (result.get("summary") or "").strip()
        model = payload.get("model") or "?"
        code = company.key.rstrip("_")
        period_meta: list[tuple[str, str]] = []
        if params.get("since_ts") and params.get("until_ts"):
            period_meta.append((
                "Период",
                f"{params['since_ts']} → {params['until_ts']} (unix)",
            ))

        def _common_block() -> list[str]:
            return [str(x) for x in common[:5]]

        for tpl_slug, sg_list, label in (
            (TEMPLATE_SUGGESTIONS_PROMPT, prompt_sg, "промт"),
            (TEMPLATE_SUGGESTIONS_TOOL,   tool_sg,   "save_call_result"),
        ):
            if not sg_list:
                continue
            if _alert_enabled(cfg, company.key, tpl_slug) is None:
                continue
            html = render_alert_html(
                severity="info",
                title=f"Анализ звонков · {len(sg_list)} правок в {label}",
                company_code=code,
                company_name=company.name,
                category=f"Voice/{sector}",
                metrics=[
                    ("Звонков", str(calls_n)),
                    ("Модель", str(model)),
                    ("Предложений", str(len(sg_list))),
                ],
                body=summary,
                bullets=_format_suggestion_bullets(sg_list),
                context_kv=[
                    *period_meta,
                    ("common_failures", " | ".join(_common_block()) or "—"),
                ],
                action_hint=(
                    "Открой вкладку «Анализ звонков» в хабе, выбери "
                    "нужные предложения и нажми «Применить выбранные "
                    "локально». Push в ElevenLabs — отдельно на вкладке «Промпты»/«Результаты»."
                ),
            )
            _send_html(cfg, company, tpl_slug, html)
    except Exception as exc:  # noqa: BLE001 — событийный диспетчер не должен валить flow
        print(f"[voice_bot_alerts] dispatch_analysis_alerts failed: {exc}")


# ---------------------------------------------------------------------------
# Applied — prompt push
# ---------------------------------------------------------------------------

def dispatch_prompt_pushed_alert(
    company_or_key,
    sector: str,
    *,
    agent_id: str,
    blocks: dict[str, str],
    first_message: str = "",
    push_user: str = "",
) -> None:
    """Шлётся после успешного PATCH system_prompt из Prompts panel."""
    try:
        company = _resolve_company(company_or_key)
        if company is None:
            return
        cfg = load_alerts_config()
        if _alert_enabled(cfg, company.key, TEMPLATE_APPLIED_PROMPT) is None:
            return

        total_chars = sum(len(blocks.get(bid) or "") for bid in BLOCK_ORDER)
        bullets: list[str] = []
        for bid in BLOCK_ORDER:
            n = len(blocks.get(bid) or "")
            mark = "—" if n == 0 else "✓"
            bullets.append(f"{mark} {_block_title(bid)}: {n} chars")

        code = company.key.rstrip("_")
        html = render_alert_html(
            severity="ok",
            title=f"Прод-промт обновлён в ElevenLabs · {sector}",
            company_code=code,
            company_name=company.name,
            category=f"Voice/{sector}",
            metrics=[
                ("agent_id", agent_id or "—"),
                ("system_prompt", f"{total_chars} chars"),
                ("first_message", f"{len(first_message or '')} chars"),
            ],
            bullets=bullets,
            context_kv=([("оператор", push_user)] if push_user else []),
            footer=(
                "Действие: PATCH /v1/convai/agents/<agent_id> "
                "conversation_config.agent.prompt.prompt"
            ),
        )
        _send_html(cfg, company, TEMPLATE_APPLIED_PROMPT, html)
    except Exception as exc:  # noqa: BLE001
        print(f"[voice_bot_alerts] dispatch_prompt_pushed_alert failed: {exc}")


# ---------------------------------------------------------------------------
# Applied — tool push
# ---------------------------------------------------------------------------

def _tool_summary(tool: dict) -> tuple[str, list[str]]:
    """Вернуть (имя tool, список property-bullets) для шаблона."""
    name = str(tool.get("name") or "—")
    api = (tool.get("api_schema") or {})
    rbs = api.get("request_body_schema") or {}
    props = rbs.get("properties") or []
    bullets: list[str] = []
    if isinstance(props, list):
        iterable = enumerate(props)
    elif isinstance(props, dict):
        iterable = props.items()
    else:
        iterable = []
    for key, p in iterable:
        if not isinstance(p, dict):
            continue
        pid = p.get("id") or p.get("name") or str(key)
        ptype = p.get("type") or "?"
        binding = ""
        dv = p.get("dynamic_variable") or ""
        const = p.get("constant_value")
        if dv:
            binding = f"  dyn={dv}"
        elif const not in (None, ""):
            binding = f"  const={const!r}"
        enum_vals = p.get("enum")
        if isinstance(enum_vals, list) and enum_vals:
            binding += f"  enum=[{len(enum_vals)}]"
        bullets.append(f"{pid} ({ptype}){binding}")
    if len(bullets) > 12:
        rest = len(bullets) - 12
        bullets = bullets[:12] + [f"… и ещё {rest}"]
    return name, bullets


def dispatch_tool_pushed_alert(
    company_or_key,
    sector: str,
    *,
    tool_id: str,
    tool: dict,
    push_user: str = "",
) -> None:
    """Шлётся после успешного PATCH save_call_result tool из Results panel."""
    try:
        company = _resolve_company(company_or_key)
        if company is None:
            return
        cfg = load_alerts_config()
        if _alert_enabled(cfg, company.key, TEMPLATE_APPLIED_TOOL) is None:
            return
        tool_name, bullets = _tool_summary(tool or {})
        code = company.key.rstrip("_")
        html = render_alert_html(
            severity="ok",
            title=f"save_call_result обновлён в ElevenLabs · {sector}",
            company_code=code,
            company_name=company.name,
            category=f"Voice/{sector}",
            metrics=[
                ("tool_id", tool_id or "—"),
                ("tool name", tool_name),
                ("properties", str(len(bullets))),
            ],
            bullets=bullets,
            context_kv=([("оператор", push_user)] if push_user else []),
            footer="Действие: PATCH /v1/convai/tools/<tool_id> tool_config",
        )
        _send_html(cfg, company, TEMPLATE_APPLIED_TOOL, html)
    except Exception as exc:  # noqa: BLE001
        print(f"[voice_bot_alerts] dispatch_tool_pushed_alert failed: {exc}")
