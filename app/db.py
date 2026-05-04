"""CRM DB connectivity helpers.

The CRM DB lives on `localhost` for every project; only the port differs per
company (`crm_db_port` in `companies.json`). User `viewer`, engine `mysql`.
Password (and host/user override, if needed) is read from `data/db.json`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .paths import data_dir

DEFAULT_DB_CONFIG = {
    "host": "localhost",
    "user": "viewer",
    "password": "",
    "engine": "mysql",
    "connect_timeout": 5,
}


def db_config_path() -> Path:
    return data_dir() / "db.json"


def load_db_config() -> dict:
    path = db_config_path()
    if not path.exists():
        return dict(DEFAULT_DB_CONFIG)
    try:
        with open(path, encoding="utf-8") as f:
            user_cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        user_cfg = {}
    merged = dict(DEFAULT_DB_CONFIG)
    merged.update(user_cfg or {})
    return merged


def test_connection(port: int) -> Optional[str]:
    """Try a SELECT 1 against the CRM DB. Returns None on success, error
    message on failure."""
    try:
        import pymysql
    except ImportError:
        return (
            "Драйвер pymysql не установлен. Выполни "
            "`pip install pymysql` и пересобери exe."
        )

    cfg = load_db_config()
    try:
        conn = pymysql.connect(
            host=cfg.get("host", "localhost"),
            port=int(port),
            user=cfg.get("user", "viewer"),
            password=cfg.get("password", "") or "",
            connect_timeout=int(cfg.get("connect_timeout", 5) or 5),
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return f"{type(exc).__name__}: {exc}"
    try:
        conn.close()
    except Exception:
        pass
    return None
