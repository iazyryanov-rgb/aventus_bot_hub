"""Infobip API client — just enough to enumerate WhatsApp senders and
their health for one of our per-company Infobip subaccounts.

Why this exists
---------------
Each company has its own Infobip subaccount with a personalised
`{prefix}.api-{region}.infobip.com` base URL and API key. Both live
inside the Webitel chat-bot's `metadata` (provider=`infobip_whatsapp`),
so the hub discovers them automatically — operators never copy creds
into companies.json by hand. This module is a thin wrapper around the
Infobip endpoints we actually use:

  * `GET /whatsapp/2/senders` — list ALL senders attached to the API
    key with their current quality / connection / messaging-limit /
    registration state. This is the v2 endpoint (the public Java SDK
    only ships v1, which lacks `registrationStatus`).
  * `GET /whatsapp/1/senders/quality` (kept as fallback) — accepts an
    explicit list of senders, returns the same quality fields.
    Required senders param to be digits-only (no `+`, no spaces).

The senders endpoint covers our two needs:
  1. enumerate "наши" WhatsApp numbers — we use this to scope the AI
     chat audit to our gateway only;
  2. monitor sender health (quality drops, status flips to
     BANNED/RESTRICTED/RATE_LIMITED, messaging-limit downgrades) —
     consumed by `wa_senders_state` for diff-and-alert.

Auth: Infobip uses `Authorization: App <api_key>` (per their docs).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


DEFAULT_BASE_URL = "https://api.infobip.com"
PAGE_SIZE = 200
CACHE_TTL_S = 30 * 60


class InfobipError(Exception):
    pass


def _request(
    base_url: str,
    api_key: str,
    path: str,
    *,
    query: Optional[dict] = None,
    timeout_s: float = 30.0,
) -> dict:
    base = base_url.rstrip("/")
    qs = ("?" + urllib.parse.urlencode(query, doseq=True)) if query else ""
    url = f"{base}{path}{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"App {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read().decode("utf-8")
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError as e:
                raise InfobipError(f"bad JSON from {path}: {e}") from e
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        raise InfobipError(f"HTTP {e.code} on {path}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise InfobipError(f"network: {e}") from e


def list_senders(
    api_key: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> list[dict]:
    """Pull every WhatsApp sender attached to the API key with full
    health state via `GET /whatsapp/2/senders`. Returns a list of dicts
    with these stable keys:

        sender              digits-only phone, e.g. "573114947740"
        displayName         Meta-side display name
        qualityRating       HIGH | MEDIUM | LOW | UNKNOWN
        limit               LIMIT_NA | LIMIT_250 | LIMIT_2K |
                            LIMIT_10K | LIMIT_100K | UNLIMITED
        connectionStatus    CONNECTED | BANNED | FLAGGED | RESTRICTED |
                            RATE_LIMITED | DELETED | DISCONNECTED |
                            PENDING | UNVERIFIED | MIGRATED | UNKNOWN
        registrationStatus  FINISHED | SUBMITTED_FOR_REGISTRATION |
                            OTP_REQUESTED | …
        numberKey           Infobip-internal id (stable across renames)
        testSender          bool

    The `logo.base64file` field that Infobip returns is stripped — it
    is several KB per sender and we never need it.
    """
    if not api_key:
        raise InfobipError("api_key is empty")
    resp = _request(base_url, api_key, "/whatsapp/2/senders",
                    query={"limit": PAGE_SIZE})
    items = resp.get("results")
    if items is None:
        # v2 returns {results, paging}; if `results` missing the response
        # is malformed for our purposes.
        raise InfobipError(
            f"unexpected response shape: keys={list(resp)[:5]}"
        )
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        # Drop the heavy logo blob; we just want the routable fields.
        slim = {k: v for k, v in it.items() if k != "logo"}
        out.append(slim)
    return out


def list_owned_whatsapp_numbers(
    api_key: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> list[str]:
    """Convenience wrapper: just the digits-only sender numbers."""
    return [
        str(s.get("sender") or "").strip()
        for s in list_senders(api_key, base_url=base_url)
        if s.get("sender")
    ]


# --- Process-local cache ---------------------------------------------------
#
# Numbers don't churn often — once Infobip provisions a number it sticks
# around for months. Caching for 30 min cuts panel-load latency and
# keeps us under Infobip's rate limits with multiple companies.

_cache_lock = threading.Lock()
_senders_cache: dict[str, tuple[float, list[dict]]] = {}


def cached_senders(
    cache_key: str, api_key: str,
    *, base_url: str = DEFAULT_BASE_URL,
    ttl_s: float = CACHE_TTL_S,
) -> list[dict]:
    """Cached wrapper around `list_senders`. Returns last-good on transient
    errors so a flaky Infobip doesn't spam the UI with empties."""
    if not api_key:
        return []
    full_key = f"{cache_key}:{api_key[:8]}"
    now = time.time()
    with _cache_lock:
        existing = _senders_cache.get(full_key)
    if existing is not None and (now - existing[0]) < ttl_s:
        return [dict(s) for s in existing[1]]
    try:
        senders = list_senders(api_key, base_url=base_url)
    except InfobipError:
        if existing is not None:
            return [dict(s) for s in existing[1]]
        return []
    with _cache_lock:
        _senders_cache[full_key] = (now, [dict(s) for s in senders])
    return [dict(s) for s in senders]


def cached_owned_whatsapp_numbers(
    cache_key: str, api_key: str,
    *, base_url: str = DEFAULT_BASE_URL,
    ttl_s: float = CACHE_TTL_S,
) -> list[str]:
    """Cached digits-only sender list — feeds `wa_bot_config.get_owned_
    whatsapp_numbers` and the audit gateway-name resolver."""
    return [
        str(s.get("sender") or "").strip()
        for s in cached_senders(
            cache_key, api_key, base_url=base_url, ttl_s=ttl_s
        )
        if s.get("sender")
    ]


def invalidate_cache(cache_key: Optional[str] = None) -> None:
    """Drop cached entries — for the given company key, or all of them
    when `cache_key` is None. Used after the operator edits the API
    key or the operator hits the manual-refresh button in the panel."""
    with _cache_lock:
        if cache_key is None:
            _senders_cache.clear()
            return
        prefix = f"{cache_key}:"
        for k in [k for k in _senders_cache if k.startswith(prefix)]:
            _senders_cache.pop(k, None)
