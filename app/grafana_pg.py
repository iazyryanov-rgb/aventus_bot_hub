"""Run raw SQL against Webitel's Postgres via Grafana's `/api/ds/query`.

Why this exists
---------------
The hub's Webitel REST client only sees chat dialogs that pass an
opaque (probably team/membership-based) RBAC filter. Bot-only dialogs
that never join a queue are invisible. Grafana, on the other hand, has
direct read-access to Webitel's internal Postgres — every conversation
is in `chat.conversation` regardless of membership. Empirical: REST
returns ~200 dialogs/day for CO_, the same window via Postgres returns
~1500.

Rather than open up Postgres directly (would need infra work on the
Webitel host), we use Grafana itself as a thin SQL proxy via its
`/api/ds/query` endpoint. Grafana already has the right datasource
configured and exposes it over HTTPS that's already publicly reachable.

Credentials
-----------
Stored in `data/api_keys.json` under the `grafana` key:

    {
      "anthropic": "sk-ant-...",
      "grafana": {
        "base_url": "https://aventus.us-east.webitel.com/grafana",
        "user":     "supervisor@grafana.aventus.us-east",
        "password": "<...>"
      }
    }

Public API
----------
- `GrafanaPgClient(base_url, user, password)` — explicit instance.
- `get_client()` — singleton built from `api_keys.json`. Lazy-login.
- `client.query(sql, params=None)` → `list[dict]` (one dict per row).
- `client.execute_query(payload)` — raw payload passthrough for advanced
  cases (e.g. multiple queries in one request, custom datasource).

Convenience helpers (all use domain_id from kwarg/default = 1):
- `chat_count(since_ms, until_ms, domain_id=1) -> dict` — total +
  queue + bot_only counts.
- `list_chat_conversations(since_ms, until_ms, only_bot_only=False,
  limit=200, domain_id=1) -> list[dict]` — id, peer, started_at, etc.

The default Postgres datasource UID is auto-discovered on first call
(picks the one named "PostgreSQL"). Override via
`GrafanaPgClient(datasource_uid=...)`.
"""
from __future__ import annotations

import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from .ai_client import _api_keys_path  # reuse the same json file

DEFAULT_DOMAIN_ID = 1


class GrafanaError(Exception):
    pass


class _HttpError(Exception):
    """Internal HTTP-error carrier — keeps status code + body so the
    request-retry layer can inspect and decide whether to relogin."""
    def __init__(self, code: int, body: str) -> None:
        super().__init__(f"HTTP {code}: {body[:200]}")
        self.code = code
        self.body = body


class GrafanaPgClient:
    """Thin wrapper around Grafana's `/api/ds/query` endpoint, scoped
    to one Postgres datasource. Login is lazy + sticky (cookie jar)."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        datasource_uid: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        if not base_url:
            raise GrafanaError("base_url is empty")
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._timeout = timeout_s
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj),
        )
        self._logged_in = False
        self._login_lock = threading.Lock()
        # Serialise transport too: urllib opener + cookiejar are NOT
        # thread-safe. Concurrent _request calls on the same client
        # corrupt the cookie state and produce intermittent 401s.
        self._req_lock = threading.Lock()
        self._ds_uid: Optional[str] = datasource_uid

    # --- low-level transport ---------------------------------------------

    def _raw_request(
        self, path: str, *,
        method: str = "GET",
        body: Optional[dict] = None,
    ) -> tuple[int, dict]:
        """Single HTTP round-trip without auto-relogin. Used by _login
        itself + by `_request` (which may retry once after re-login)."""
        url = f"{self._base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with self._req_lock:
            try:
                with self._opener.open(req, timeout=self._timeout) as r:
                    raw = r.read().decode("utf-8")
                    try:
                        parsed = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        parsed = {"raw": raw}
                    return r.status, parsed
            except urllib.error.HTTPError as e:
                # Re-raise with body — caller decides whether to retry.
                try:
                    err_body = e.read().decode("utf-8", "replace")
                except Exception:
                    err_body = ""
                raise _HttpError(e.code, err_body) from e
            except urllib.error.URLError as e:
                raise GrafanaError(f"network: {e}") from e

    def _request(
        self, path: str, *,
        method: str = "GET",
        body: Optional[dict] = None,
    ) -> tuple[int, dict]:
        try:
            return self._raw_request(path, method=method, body=body)
        except _HttpError as e:
            # 401 → session likely expired. Re-login once and retry.
            if e.code == 401 and path != "/login":
                with self._login_lock:
                    self._logged_in = False
                self._login()
                try:
                    return self._raw_request(path, method=method, body=body)
                except _HttpError as e2:
                    raise GrafanaError(
                        f"HTTP {e2.code} on {path}: {e2.body[:300]}"
                    ) from e2
            raise GrafanaError(f"HTTP {e.code} on {path}: {e.body[:300]}") from e

    def _login(self) -> None:
        with self._login_lock:
            if self._logged_in:
                return
            try:
                status, resp = self._raw_request(
                    "/login", method="POST",
                    body={"user": self._user, "password": self._password},
                )
            except _HttpError as e:
                raise GrafanaError(
                    f"login failed: HTTP {e.code} {e.body[:300]}"
                ) from e
            if status != 200:
                raise GrafanaError(f"login failed: HTTP {status} {resp}")
            self._logged_in = True

    def _ensure_datasource_uid(self) -> str:
        if self._ds_uid:
            return self._ds_uid
        self._login()
        _, resp = self._request("/api/datasources")
        if not isinstance(resp, list):
            raise GrafanaError(f"datasources: unexpected shape {type(resp).__name__}")
        # Prefer one named "PostgreSQL", fall back to first postgresql type.
        candidates = [
            d for d in resp
            if str(d.get("type", "")).startswith("grafana-postgresql")
            or str(d.get("type", "")) == "postgres"
        ]
        if not candidates:
            raise GrafanaError("no PostgreSQL datasource found in Grafana")
        named = next(
            (d for d in candidates if d.get("name") == "PostgreSQL"),
            candidates[0],
        )
        self._ds_uid = str(named.get("uid") or "")
        if not self._ds_uid:
            raise GrafanaError("datasource has no uid")
        return self._ds_uid

    # --- public API -------------------------------------------------------

    def query(
        self,
        sql: str,
        *,
        from_ms: Optional[int] = None,
        to_ms: Optional[int] = None,
        format: str = "table",
    ) -> list[dict]:
        """Run a single SQL string. `from_ms`/`to_ms` are the dashboard
        time-range that Grafana injects into `$__timeFilter(...)` macros
        in the query — pass them only if your SQL uses those macros.
        Returns a list of row-dicts."""
        self._login()
        ds_uid = self._ensure_datasource_uid()
        if from_ms is None:
            from_ms = int(time.time() * 1000) - 24 * 3600 * 1000
        if to_ms is None:
            to_ms = int(time.time() * 1000)
        body = {
            "queries": [{
                "refId": "A",
                "rawSql": sql,
                "format": format,
                "datasource": {"uid": ds_uid, "type": "grafana-postgresql-datasource"},
            }],
            "from": str(int(from_ms)),
            "to": str(int(to_ms)),
        }
        status, resp = self._request(
            "/api/ds/query", method="POST", body=body,
        )
        if status != 200:
            raise GrafanaError(f"query: HTTP {status}: {resp}")
        return _parse_frames(resp, "A")


def _parse_frames(resp: dict, ref_id: str) -> list[dict]:
    """Convert Grafana's column-oriented response to row dicts."""
    results = (resp or {}).get("results") or {}
    block = results.get(ref_id) or {}
    status = block.get("status")
    if status and status != 200:
        err = block.get("error") or block.get("frames") or block
        raise GrafanaError(f"query refId={ref_id} status={status}: {str(err)[:300]}")
    frames = block.get("frames") or []
    if not frames:
        return []
    frame = frames[0]
    schema = frame.get("schema") or {}
    fields = schema.get("fields") or []
    data = (frame.get("data") or {}).get("values") or []
    if not fields or not data:
        return []
    names = [f.get("name") or f"col{i}" for i, f in enumerate(fields)]
    out: list[dict] = []
    n_rows = max((len(col) for col in data), default=0)
    for i in range(n_rows):
        row = {}
        for j, name in enumerate(names):
            col = data[j] if j < len(data) else []
            row[name] = col[i] if i < len(col) else None
        out.append(row)
    return out


# --- Per-company client cache ----------------------------------------------
#
# Each company has its own Webitel installation with its own Grafana,
# so creds are stored per-company in companies.json under a
# `grafana: {base_url, user, password}` block. We cache one
# GrafanaPgClient per company key; cookie sessions stay sticky between
# calls within a process.

_clients: dict[str, GrafanaPgClient] = {}
_clients_lock = threading.Lock()


def _load_grafana_creds_for(company_key: str) -> dict:
    """Return the `grafana` block from companies.json for `company_key`,
    or {} if absent / invalid. Falls back to api_keys.json `grafana`
    block — useful during the migration window."""
    # Lazy import: avoid circulars; data module is light.
    try:
        from .data import load_raw
        info = (load_raw() or {}).get(company_key) or {}
        g = info.get("grafana") if isinstance(info, dict) else None
        if isinstance(g, dict) and g.get("base_url") and g.get("user") and g.get("password"):
            return g
    except Exception:
        pass
    # Legacy fallback: shared block in api_keys.json.
    p = _api_keys_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    legacy = d.get("grafana")
    return legacy if isinstance(legacy, dict) else {}


def is_configured(company_key: Optional[str] = None) -> bool:
    """True if the given company has Grafana creds configured (or, when
    `company_key` is None, if the legacy global creds are present)."""
    if company_key is None:
        # Legacy check — only api_keys.json.
        p = _api_keys_path()
        if not p.exists():
            return False
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        g = d.get("grafana") or {}
        return bool(g.get("base_url") and g.get("user") and g.get("password"))
    g = _load_grafana_creds_for(company_key)
    return bool(g.get("base_url") and g.get("user") and g.get("password"))


def get_client(company_key: Optional[str] = None) -> GrafanaPgClient:
    """Return a per-company Grafana client. `company_key=None` returns
    the legacy global-creds client (api_keys.json) — kept for transitional
    callers that haven't been updated yet.
    """
    cache_key = company_key or "__legacy_global__"
    with _clients_lock:
        existing = _clients.get(cache_key)
        if existing is not None:
            return existing

        if company_key is None:
            p = _api_keys_path()
            d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            g = d.get("grafana") if isinstance(d, dict) else None
            g = g if isinstance(g, dict) else {}
        else:
            g = _load_grafana_creds_for(company_key)
        if not g.get("base_url") or not g.get("user") or not g.get("password"):
            raise GrafanaError(
                f"Grafana not configured"
                f"{' for ' + company_key if company_key else ''}. "
                "Open the company edit dialog and fill in the Grafana "
                "host/login/password."
            )
        client = GrafanaPgClient(
            base_url=str(g["base_url"]),
            user=str(g["user"]),
            password=str(g["password"]),
            datasource_uid=g.get("datasource_uid") or None,
        )
        _clients[cache_key] = client
        return client


# --- Convenience helpers ---------------------------------------------------

def chat_count(
    since_ms: int, until_ms: int,
    *, company_key: Optional[str] = None,
    domain_id: int = DEFAULT_DOMAIN_ID,
) -> dict:
    """Total / queued / bot-only counts in `chat.conversation` in the
    given time window. Returns:

        {"total": int, "queued": int, "bot_only": int}

    `bot_only` = total - queued (chats with no `cc_member_attempt(_history)`
    join — i.e. never escalated to a queue)."""
    sql = f"""
    select
      count(distinct cconv.id)                                  as total,
      count(distinct cconv.id) filter (where cmah.id notnull)   as queued
    from chat.conversation cconv
      left join lateral (
        select id, member_call_id, joined_at
        from call_center.cc_member_attempt_history
        where domain_id = {int(domain_id)}
          and joined_at >= to_timestamp({int(since_ms)} / 1000.0)
          and joined_at <= to_timestamp({int(until_ms)} / 1000.0)
        union all
        select id, member_call_id, joined_at
        from call_center.cc_member_attempt
        where domain_id = {int(domain_id)}
          and joined_at >= to_timestamp({int(since_ms)} / 1000.0)
          and joined_at <= to_timestamp({int(until_ms)} / 1000.0)
      ) cmah on cmah.member_call_id::uuid = cconv.id
    where cconv.created_at::timestamptz >= to_timestamp({int(since_ms)} / 1000.0)
      and cconv.created_at::timestamptz <= to_timestamp({int(until_ms)} / 1000.0)
      and cconv.domain_id = {int(domain_id)}
    """
    rows = get_client(company_key).query(sql, from_ms=since_ms, to_ms=until_ms)
    if not rows:
        return {"total": 0, "queued": 0, "bot_only": 0}
    total = int(rows[0].get("total") or 0)
    queued = int(rows[0].get("queued") or 0)
    return {
        "total": total,
        "queued": queued,
        "bot_only": max(0, total - queued),
    }


def _esc_sql(s: str) -> str:
    return str(s).replace("'", "''")


def list_chat_conversations(
    since_ms: int, until_ms: int,
    *, company_key: Optional[str] = None,
    only_bot_only: bool = False,
    channel: Optional[str] = None,
    whatsapp_number: Optional[str] = None,
    limit: int = 500,
    domain_id: int = DEFAULT_DOMAIN_ID,
) -> list[dict]:
    """List `chat.conversation` rows in the period. Each row carries:

        id, created_at_ms, closed_at_ms, channel, queued,
        from_phone (props->>'user'),
        whatsapp_number (props->>'whatsapp.number') — bot's WA gateway,
                                                      use for per-company filter,
        loan_id (props->>'loan_id'),
        client_id (props->>'client_id'),
        link (props->>'link') — URL into the company's CRM,
        flow (props->>'flow').

    `queued=True` iff a row in `cc_member_attempt(_history)` exists.
    Filters: `channel` ('whatsapp', 'telegram', ...), `whatsapp_number`
    ('+57 315 1586256' for CO_), `only_bot_only=True`.

    Performance: pulls inner LIMIT first (cheap with index on
    created_at), then resolves queued-status with a left join. If
    `only_bot_only=True` we 5x the inner limit and post-filter.
    """
    filters = []
    if channel:
        filters.append(f" and cconv.props ->> 'chat' = '{_esc_sql(channel)}'")
    if whatsapp_number:
        filters.append(
            f" and cconv.props ->> 'whatsapp.number' = '{_esc_sql(whatsapp_number)}'"
        )
    chan_filter = "".join(filters)
    inner_limit = max(int(limit), 200)
    if only_bot_only:
        inner_limit = max(inner_limit, int(limit) * 5)

    sql = f"""
    with recent_chats as (
      select cconv.id, cconv.created_at, cconv.closed_at, cconv.props
      from chat.conversation cconv
      where cconv.created_at::timestamptz >= to_timestamp({int(since_ms)} / 1000.0)
        and cconv.created_at::timestamptz <= to_timestamp({int(until_ms)} / 1000.0)
        and cconv.domain_id = {int(domain_id)}
        {chan_filter}
      order by cconv.created_at desc
      limit {inner_limit}
    ),
    -- All attempts that touched any of `recent_chats`. Carries
    -- agent_id and queue_id (with team_name resolved) so the hub
    -- can label rows AND filter them by sector (Collection / CC).
    chat_attempts as (
      select mah.member_call_id::uuid as conv_id,
             mah.agent_id, mah.queue_id, mah.bridged_at,
             cq.team_id
      from call_center.cc_member_attempt_history mah
      left join call_center.cc_queue cq on cq.id = mah.queue_id
      where mah.domain_id = {int(domain_id)}
        and mah.member_call_id::uuid in (select id from recent_chats)
      union all
      select ma.member_call_id::uuid,
             ma.agent_id, ma.queue_id, ma.bridged_at,
             cq.team_id
      from call_center.cc_member_attempt ma
      left join call_center.cc_queue cq on cq.id = ma.queue_id
      where ma.domain_id = {int(domain_id)}
        and ma.member_call_id::uuid in (select id from recent_chats)
    ),
    chat_attempts_named as (
      select ca.*, t.name as team_name
      from chat_attempts ca
      left join call_center.cc_team t on t.id = ca.team_id
    ),
    queued_agg as (
      select conv_id,
             max(agent_id) filter (where bridged_at is not null) as agent_id_picked,
             max(agent_id)                                       as agent_id_any,
             bool_or(bridged_at is not null)                     as bridged,
             -- Pick the team name from the most-bridged attempt;
             -- fall back to any team for queued-but-not-bridged.
             max(team_name) filter (where bridged_at is not null) as team_picked,
             max(team_name)                                       as team_any
      from chat_attempts_named
      group by conv_id
    )
    select
      rc.id::text                                as id,
      extract(epoch from rc.created_at) * 1000   as created_at_ms,
      extract(epoch from rc.closed_at)  * 1000   as closed_at_ms,
      rc.props ->> 'chat'                        as channel,
      rc.props ->> 'user'                        as from_phone,
      rc.props ->> 'client_name'                 as peer_name,
      rc.props ->> 'whatsapp.number'             as whatsapp_number,
      rc.props ->> 'loan_id'                     as loan_id,
      rc.props ->> 'client_id'                   as client_id,
      rc.props ->> 'link'                        as link,
      rc.props ->> 'flow'                        as flow,
      (q.conv_id is not null)                    as queued,
      coalesce(q.bridged, false)                 as bridged,
      coalesce(q.agent_id_picked, q.agent_id_any) as agent_id,
      coalesce(q.team_picked, q.team_any)         as queue_team
    from recent_chats rc
      left join queued_agg q on q.conv_id = rc.id
    order by rc.created_at desc
    """
    rows = get_client(company_key).query(sql, from_ms=since_ms, to_ms=until_ms)
    if only_bot_only:
        rows = [r for r in rows if not r.get("queued")]
    return rows[:int(limit)]
