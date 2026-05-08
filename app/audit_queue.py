"""Persistent, panel-independent queue for chat-audit runs.

Why this exists
---------------
Manual audits used to be spawned from `ChatAuditPanel._run` in a daemon
thread tied to the panel widget. Two problems with that:

  1. **Tab/company switch destroys the panel.** The thread keeps running
     in the background but its `self.after(...)` result-delivery dies
     with the widget — the user comes back to a panel with nothing,
     even though tokens were spent and a result is in `audit_history`.

  2. **App close loses in-flight requests.** Daemon threads die when
     the main thread exits, so an audit that was waiting for Anthropic
     when the operator quit is gone — and on next start there's no
     trace it ever happened.

This module owns audit jobs end-to-end, persisting their state to disk
so the UI is just a viewer. Panels read from `latest_active_job(co)`
and poll job status; results land in `audit_history` exactly as
before.

Layout
------

`data/audit_jobs/<company_key>/<request_id>.json`:

    {
      "request_id":      "<16-hex>",
      "company_key":     "CO_",
      "status":          "queued|running|done|failed|interrupted",
      "started_at_ms":   ...,
      "ended_at_ms":     ...,
      "params":          {model_kind, chat_limit, period_days,
                          since_ms, until_ms, lang, send_to_tg},
      "result_audit_id": "<id>" | null,    // set on done; full result
                                           // lives in audit_history
      "error":           "..." | null,
      "elapsed_s":       float | null,
      "tg_err":          "..." | null,
    }

Lifecycle hooks
---------------

- `reconcile_orphans()` on hub start — any job left in `queued|running`
  is by definition stale (no worker is alive), mark it `interrupted`
  with a clear error.

- `get_queue()` returns the singleton `AuditQueue`. The pool is shared
  across the whole hub: scheduler-fired audits go through the same
  pool, so the operator sees one place for "who's running what".

- `shutdown()` is called from `app.main` on real exit. Running jobs
  will be marked interrupted on next start (their thread dies with
  the process; we don't try to drain — UX is "tray-hide" for keep-
  alive, "Quit" for full stop).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .data import Company
from .paths import data_dir


# Status values are plain strings (not Enum) so they round-trip cleanly
# through JSON without custom encoders.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)
TERMINAL_STATUSES = (STATUS_DONE, STATUS_FAILED, STATUS_INTERRUPTED)


@dataclass
class AuditJob:
    request_id: str
    company_key: str
    status: str
    started_at_ms: int = 0
    ended_at_ms: int = 0
    params: dict = field(default_factory=dict)
    result_audit_id: Optional[str] = None
    error: Optional[str] = None
    elapsed_s: Optional[float] = None
    tg_err: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


# --- File-backed storage ----------------------------------------------------

def _jobs_root() -> Path:
    return data_dir() / "audit_jobs"


def _job_path(company_key: str, request_id: str) -> Path:
    return _jobs_root() / company_key / f"{request_id}.json"


def save_job(job: AuditJob) -> None:
    p = _job_path(job.company_key, job.request_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(
            json.dumps(asdict(job), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load_job(company_key: str, request_id: str) -> Optional[AuditJob]:
    p = _job_path(company_key, request_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return AuditJob(**d)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def list_jobs(company_key: str, limit: int = 20) -> list[AuditJob]:
    folder = _jobs_root() / company_key
    if not folder.exists():
        return []
    out: list[AuditJob] = []
    for f in folder.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append(AuditJob(**d))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    out.sort(key=lambda j: -int(j.started_at_ms or 0))
    return out[:limit]


def latest_active_job(company_key: str) -> Optional[AuditJob]:
    """Most recent job in queued/running state for this company.
    Used by the panel to reattach after a tab/company switch."""
    for j in list_jobs(company_key, limit=10):
        if j.is_active:
            return j
    return None


def latest_terminal_job(company_key: str) -> Optional[AuditJob]:
    """Most recent finished job (done/failed/interrupted) — for showing
    "last result" when no active run is in flight."""
    for j in list_jobs(company_key, limit=10):
        if j.is_terminal:
            return j
    return None


def reconcile_orphans() -> int:
    """Called once on hub start. Any job still in queued/running can't
    actually be running — its thread died with the previous process.
    Mark them as `interrupted` so the UI can surface them."""
    if not _jobs_root().exists():
        return 0
    n = 0
    now_ms = int(time.time() * 1000)
    for co_dir in _jobs_root().iterdir():
        if not co_dir.is_dir():
            continue
        for f in co_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if d.get("status") not in ACTIVE_STATUSES:
                continue
            d["status"] = STATUS_INTERRUPTED
            d["ended_at_ms"] = now_ms
            if not d.get("error"):
                d["error"] = (
                    "interrupted: hub was closed before the audit finished. "
                    "Re-run from the panel."
                )
            try:
                f.write_text(
                    json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                n += 1
            except OSError:
                pass
    return n


# --- Queue ------------------------------------------------------------------

class AuditQueue:
    """Owns the worker pool. One singleton per process; do not instantiate
    directly — use `get_queue()`.

    Thread-safe. The `_inflight` map is for cancellation/observability;
    persistence-of-truth is the on-disk job file.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="audit-job",
        )
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}

    def enqueue(
        self,
        company: Company,
        params: dict,
        on_complete: Optional[Callable[[AuditJob, Optional[dict]], None]] = None,
    ) -> AuditJob:
        """Persist a fresh job and submit it to the worker pool. Returns
        the persisted job (status=queued). The on_complete callback runs
        in the worker thread once the job reaches a terminal state — use
        sparingly; UI panels should poll instead."""
        rid = secrets.token_hex(8)
        job = AuditJob(
            request_id=rid,
            company_key=company.key,
            status=STATUS_QUEUED,
            started_at_ms=int(time.time() * 1000),
            params=dict(params),
        )
        save_job(job)
        with self._lock:
            self._inflight[rid] = threading.Event()
        self._pool.submit(self._run_job, company, rid, on_complete)
        return job

    def _run_job(
        self,
        company: Company,
        request_id: str,
        on_complete: Optional[Callable[[AuditJob, Optional[dict]], None]],
    ) -> None:
        # Lazy imports — heavy modules.
        from .audit_scheduler import send_audit_to_telegram
        from .calibration_cycle import run_cycle as _run_cycle
        from .chat_audit import run_audit

        job = load_job(company.key, request_id)
        if job is None:
            return
        job.status = STATUS_RUNNING
        save_job(job)

        result: Optional[dict] = None
        try:
            params = job.params or {}
            t0 = time.time()
            result = run_audit(
                company,
                int(params.get("since_ms") or 0),
                int(params.get("until_ms") or 0),
                model_kind=str(params.get("model_kind") or "sonnet"),
                chat_limit=int(params.get("chat_limit") or 200),
                lang=str(params.get("lang") or "ENG"),
                elapsed_for_save=None,
            )
            job.elapsed_s = time.time() - t0
            audit_id = (result.get("_meta") or {}).get("audit_id")
            job.result_audit_id = audit_id

            # Optional Telegram delivery + cycle hook (matches the
            # scheduled-audit flow so manual runs feel the same).
            if params.get("send_to_tg"):
                try:
                    job.tg_err = send_audit_to_telegram(
                        company, result,
                        int(params.get("period_days") or 1),
                        str(params.get("model_kind") or "sonnet"),
                        job.elapsed_s,
                    )
                except Exception as exc:  # noqa: BLE001
                    job.tg_err = f"{type(exc).__name__}: {exc}"
            if params.get("run_cycle_after"):
                try:
                    _run_cycle(
                        company.key, result,
                        audit_meta={
                            "audit_id": audit_id or "",
                            "ts_ms": (result.get("_meta") or {}).get("ts_ms") or 0,
                            "model_kind": str(params.get("model_kind") or "sonnet"),
                        },
                    )
                except Exception:
                    pass

            job.status = STATUS_DONE
        except Exception as exc:  # noqa: BLE001
            job.status = STATUS_FAILED
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.ended_at_ms = int(time.time() * 1000)
            save_job(job)
            with self._lock:
                ev = self._inflight.pop(request_id, None)
            if ev is not None:
                ev.set()
            if on_complete is not None:
                try:
                    on_complete(job, result)
                except Exception:
                    pass

    def shutdown(self) -> None:
        """Soft-stop. Queued jobs are cancelled; running jobs continue
        as daemon threads and die with the process — they'll show up as
        `interrupted` on next start via `reconcile_orphans()`."""
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


# Singleton ------------------------------------------------------------------

_queue_singleton: Optional[AuditQueue] = None
_singleton_lock = threading.Lock()


def get_queue() -> AuditQueue:
    global _queue_singleton
    with _singleton_lock:
        if _queue_singleton is None:
            _queue_singleton = AuditQueue()
        return _queue_singleton
