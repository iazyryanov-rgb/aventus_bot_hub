"""Lightweight i18n. Lookups happen at widget-construction time, so changing
the language requires rebuilding the UI tree (handled by MainWindow)."""
from __future__ import annotations

from .settings import load_settings, save_settings

LANGUAGES = ("RU", "ENG", "ES")
DEFAULT_LANGUAGE = "RU"

# Translation table. Missing keys for non-RU fall back to RU.
TRANSLATIONS: dict[str, dict[str, str]] = {
    # main shell
    "label_language":          {"RU": "Язык",                  "ENG": "Language",       "ES": "Idioma"},
    # left tree
    "header_companies":        {"RU": "КОМПАНИИ И БОТЫ",       "ENG": "COMPANIES & BOTS","ES": "EMPRESAS Y BOTS"},
    "btn_add_company":         {"RU": "+ Добавить компанию",   "ENG": "+ Add company",  "ES": "+ Agregar empresa"},
    "btn_analytics":           {"RU": "📊 Аналитика",          "ENG": "📊 Analytics",   "ES": "📊 Analítica"},
    "btn_sync_webitel":        {"RU": "Sync с Webitel",        "ENG": "Sync with Webitel","ES": "Sincronizar con Webitel"},
    # bot panel tabs
    "tab_queues":              {"RU": "Контроль очередей",     "ENG": "Queue control",  "ES": "Control de colas"},
    "tab_chats":               {"RU": "Чаты",                  "ENG": "Chats",          "ES": "Chats"},
    "tab_alerts":              {"RU": "Алерты",                "ENG": "Alerts",         "ES": "Alertas"},
    "tab_crm_data":            {"RU": "Данные из CRM",         "ENG": "CRM data",       "ES": "Datos de CRM"},
    "tab_action_tree":         {"RU": "Дерево действий",       "ENG": "Action tree",    "ES": "Árbol de acciones"},
    # section headers
    "header_queues":           {"RU": "КОНТРОЛЬ ОЧЕРЕДЕЙ",     "ENG": "QUEUE CONTROL",  "ES": "CONTROL DE COLAS"},
    "header_chats":            {"RU": "ЧАТЫ",                  "ENG": "CHATS",          "ES": "CHATS"},
    "header_alerts":           {"RU": "АЛЕРТЫ",                "ENG": "ALERTS",         "ES": "ALERTAS"},
    "header_analytics":        {"RU": "АНАЛИТИКА",             "ENG": "ANALYTICS",      "ES": "ANALÍTICA"},
    # generic
    "btn_refresh":             {"RU": "Обновить",              "ENG": "Refresh",        "ES": "Actualizar"},
    "btn_save":                {"RU": "Сохранить",             "ENG": "Save",           "ES": "Guardar"},
    "btn_cancel":              {"RU": "Отмена",                "ENG": "Cancel",         "ES": "Cancelar"},
}


def current_language() -> str:
    lang = load_settings().get("language", DEFAULT_LANGUAGE)
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def set_language(lang: str) -> None:
    if lang not in LANGUAGES:
        return
    s = load_settings()
    s["language"] = lang
    save_settings(s)


def t(key: str) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(current_language()) or entry.get(DEFAULT_LANGUAGE) or key
