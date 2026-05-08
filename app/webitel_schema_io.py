"""Read/write helpers for Webitel routing schema payloads.

Phase 0 of the calibration ↔ Webitel integration. See
`docs/skill_calibration_integration_plan.md` for the broader plan.

These helpers wrap `WebitelClient.get_schema` / `update_schema` with two
extras the calibration flow needs:

  * **Snapshots.** Every push is preceded by a full-object dump to
    `data/webitel_schema_snapshots/<company_key>/<id>_<ts>_<label>.json`.
    That file is the rollback target — it captures exactly what Webitel
    had before we touched it (`schema` compiled string included), so the
    operator can always restore byte-perfect state via `update_schema`.

  * **Conflict guard.** If the caller supplies `expected_updated_at`, we
    re-fetch the schema right before PUT and compare. If a UI-side edit
    landed in between (Webitel's `updated_at` moved), we abort with
    `WebitelConflict` rather than overwrite someone else's work.

Smoke test (manual, run once after auth is confirmed):
    >>> from app.data import load_companies
    >>> from app.webitel import WebitelClient
    >>> from app.webitel_schema_io import fetch_payload, push_payload, make_snapshot
    >>> co = next(c for c in load_companies() if c.key == "CO_")
    >>> client = WebitelClient(co.webitel_host, co.webitel_access_token)
    >>> full, payload = fetch_payload(client, 110)
    >>> snap = make_snapshot("CO_", 110, full, label="smoke-test")
    >>> # No-op round-trip: push the SAME payload back.
    >>> push_payload(client, 110, payload, expected_updated_at=full["updated_at"], base_object=full)
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import data_dir
from .webitel import WebitelClient, WebitelConflict


SNAPSHOT_DIR_NAME = "webitel_schema_snapshots"


def snapshots_root() -> Path:
    return data_dir() / SNAPSHOT_DIR_NAME


def _safe_label(label: str) -> str:
    out = []
    for ch in (label or "").strip().lower():
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip("_")
    return s or "patch"


def _safe_co_dir(company_key: str) -> str:
    s = (company_key or "").strip().strip("/\\")
    return s or "_unknown"


def fetch_full(client: WebitelClient, schema_id: int) -> dict:
    """Read the full routing/schema/{id} object."""
    return client.get_schema(schema_id)


def fetch_payload(client: WebitelClient, schema_id: int) -> tuple[dict, dict]:
    """Returns (full_object, payload_view).

    `payload_view` is a deep copy of `full_object['payload']`, so callers
    can mutate it freely without aliasing the snapshot we'll dump from
    `full_object`.
    """
    full = client.get_schema(schema_id)
    payload = copy.deepcopy(full.get("payload") or {})
    return full, payload


def make_snapshot(
    company_key: str,
    schema_id: int,
    full_object: dict,
    *,
    label: str = "before-patch",
) -> Path:
    """Dump `full_object` to a per-company snapshot file. Returns the path.

    Snapshots are append-only — we never overwrite an existing file because
    each filename includes a UTC timestamp."""
    out_dir = snapshots_root() / _safe_co_dir(company_key)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"{int(schema_id)}_{ts}_{_safe_label(label)}.json"
    path = out_dir / fname
    path.write_text(
        json.dumps(full_object, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def clone_schema(
    client: WebitelClient,
    source_id: int,
    new_name: str,
    *,
    company_key: Optional[str] = None,
    snapshot_label: str = "clone-source",
) -> dict:
    """Create a brand-new schema whose `payload` is a deep copy of `source_id`.

    Strips server-managed fields (`id`, `created_at`, `created_by`,
    `updated_at`, `updated_by`) before POST so Webitel mints fresh ones.
    Keeps `type`, `editor`, `tags`, `schema` (Webitel will recompile the
    `schema` string from `payload` on save anyway).

    If `company_key` is set, dumps a snapshot of the source schema first —
    useful as the starting point of a candidate's history.

    Returns the created object (with its new `id`).
    """
    source = client.get_schema(source_id)
    if company_key:
        make_snapshot(company_key, source_id, source, label=snapshot_label)

    body = dict(source)
    for k in ("id", "created_at", "created_by", "updated_at", "updated_by"):
        body.pop(k, None)
    body["name"] = new_name

    return client.create_schema(body)


def push_payload(
    client: WebitelClient,
    schema_id: int,
    new_payload: dict,
    *,
    expected_updated_at: Optional[str] = None,
    base_object: Optional[dict] = None,
) -> dict:
    """Update the routing schema's `payload` field, leaving everything else
    on the server-side object intact.

    Args:
        client: configured WebitelClient.
        schema_id: routing schema id (int or numeric str).
        new_payload: the mutated payload to write.
        expected_updated_at: if provided, we re-fetch right before PUT and
            abort with `WebitelConflict` if the timestamp changed (someone
            edited via UI in the meantime).
        base_object: optional, the full object previously fetched. Used as
            the body skeleton; only `payload` is replaced. If omitted, we
            re-fetch.

    Returns:
        Webitel's response body (typically the updated schema object).
    """
    if base_object is None:
        base_object = client.get_schema(schema_id)

    if expected_updated_at is not None:
        fresh = client.get_schema(schema_id)
        fresh_at = str(fresh.get("updated_at") or "")
        if fresh_at and fresh_at != str(expected_updated_at):
            raise WebitelConflict(
                f"Schema {schema_id} was modified externally "
                f"(expected updated_at={expected_updated_at}, "
                f"server has {fresh_at}). Re-fetch and re-apply."
            )
        # Use the re-fetch as the skeleton so server-derived fields stay
        # current; we only replace `payload` with what the caller computed.
        base_object = fresh

    body = dict(base_object)
    body["payload"] = new_payload
    return client.update_schema(schema_id, body)
