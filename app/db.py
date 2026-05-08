"""CRM DB connectivity helpers — supports MySQL (CO/CO2) and PostgreSQL
(AR/PE) per company.

Per-company settings live in `data/companies.json`:
  * `crm_db_engine`   — "mysql" | "postgres"  (default: mysql for legacy)
  * `crm_db_port`     — local port (SSH tunnel target)
  * `crm_db_name`     — Postgres database name (required for engine=postgres)

Common credentials live in `data/db.json` (host=localhost, user=viewer, password).
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


def _connect_mysql(host: str, port: int, user: str, password: str, timeout: int):
    import pymysql

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password or "",
        connect_timeout=timeout,
    )


def _connect_postgres(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    timeout: int,
):
    import pg8000.dbapi

    return pg8000.dbapi.connect(
        host=host,
        port=port,
        user=user,
        password=(password or None),
        database=database or "template1",
        timeout=timeout,
        ssl_context=None,
    )


def connect(
    engine: str,
    port: int,
    *,
    database: Optional[str] = None,
):
    """Open a connection using shared creds from db.json + per-call engine/port.
    Caller is responsible for closing it."""
    cfg = load_db_config()
    host = cfg.get("host", "localhost")
    user = cfg.get("user", "viewer")
    password = cfg.get("password", "") or ""
    timeout = int(cfg.get("connect_timeout", 5) or 5)
    eng = (engine or "mysql").lower()
    if eng == "postgres":
        return _connect_postgres(host, port, user, password, database or "", timeout)
    return _connect_mysql(host, port, user, password, timeout)


def connect_for_company(company):
    """Open a CRM-DB connection using the company's `crm_db_*` settings."""
    from .data import load_raw
    info = load_raw().get(company.key, {})
    engine = (info.get("crm_db_engine") or "mysql").lower()
    port_str = str(info.get("crm_db_port") or "").strip()
    if not port_str:
        raise ValueError("crm_db_port не задан")
    port = int(port_str)
    db_name = str(info.get("crm_db_name") or "").strip() or None
    return connect(engine, port, database=db_name)


def test_connection(
    port: int,
    engine: str = "mysql",
    database: Optional[str] = None,
) -> Optional[str]:
    """Try a simple `SELECT 1` against the CRM DB. Returns None on success,
    a short error string on failure. Picks driver by `engine`."""
    eng = (engine or "mysql").lower()
    if eng == "postgres":
        try:
            import pg8000.dbapi  # noqa: F401
        except ImportError:
            return "Драйвер pg8000 не установлен."
    else:
        try:
            import pymysql  # noqa: F401
        except ImportError:
            return "Драйвер pymysql не установлен."

    try:
        conn = connect(eng, int(port), database=database)
    except Exception as exc:
        return f"{type(exc).__name__}: {str(exc)[:200]}"
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1")
            cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return f"{type(exc).__name__}: {str(exc)[:200]}"
    try:
        conn.close()
    except Exception:
        pass
    return None
