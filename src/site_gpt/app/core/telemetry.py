"""Operational telemetry and the D8 alert set (V6-21).

There is no metrics vendor, so the numbers an operator needs come from three
places that already exist:

* this API process's own request counters (`record_request`, fed by the access
  middleware V6-22 installed) — the 5xx rate D8 alerts on;
* the worker's heartbeat, queue-pop time and job-failure counter in Redis —
  written by `worker.heartbeat_loop` and the job loop, read here;
* the queue itself (`LLEN queue:jobs`), which is the backlog depth.

`build_snapshot` combines them and `evaluate` turns them into alerts. The
snapshot is served by `GET /api/ops/status` (api/ops.py) and by
`scripts/ops_status.py`, and both use this module so the external check and the
endpoint cannot disagree about a threshold.

Everything here is per process, not aggregate: the counters live in this API
process's memory and the snapshot is answered by whichever instance the caller
reaches, while the worker keys are one document overwritten by every worker. A
fleet-wide view needs an external collector (V6-23/V6-40); the docs record the
limit and what the external check therefore proves.

Redis is passed in rather than imported: this module must stay importable from
`core.logging` (which counts requests) without a cycle through
`services.redis`. Every function here is best-effort — a telemetry failure is
reported as missing data, never raised at the caller.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from site_gpt.app.core.config import (
    API_ERROR_RATE_ALERT,
    API_ERROR_RATE_MIN_REQUESTS,
    API_ERROR_RATE_WINDOW_SECONDS,
    JOB_FAILURE_ALERT_COUNT,
    JOB_FAILURE_WINDOW_SECONDS,
    QUEUE_AGE_ALERT_SECONDS,
    QUEUE_DEPTH_ALERT,
    WORKER_HEARTBEAT_INTERVAL_SECONDS,
    WORKER_HEARTBEAT_STALE_SECONDS,
)

#: One JSON document per key, each written by the worker and read by the API.
HEARTBEAT_KEY = "ops:worker:heartbeat"
LAST_POP_KEY = "ops:queue:last_pop"
JOB_FAILURES_KEY = "ops:worker:job_failures"

#: A heartbeat older than three intervals is gone: the process stops refreshing
#: the key when it dies, and the TTL removes it, so both a crash and a hang look
#: the same to the reader.
HEARTBEAT_TTL_SECONDS = 3 * WORKER_HEARTBEAT_INTERVAL_SECONDS

#: (monotonic timestamp, is_5xx) for requests inside the alert window.
_recent: deque[tuple[float, bool]] = deque()
_recent_lock = threading.Lock()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(value: Any) -> datetime | None:
    """An aware UTC datetime from an ISO string, or None when unusable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(value: Any, now: datetime) -> float | None:
    moment = _parse(value)
    if moment is None:
        return None
    return max(0.0, (now - moment).total_seconds())


# -- request counters -------------------------------------------------------


def record_request(status_code: int, *, now: float | None = None) -> None:
    """Count one request for the in-process error-rate window.

    Called by `RequestContextMiddleware` for every HTTP response; cheap and
    never raises, so the access path never depends on telemetry.
    """
    try:
        seen = time.monotonic() if now is None else now
        with _recent_lock:
            _recent.append((seen, int(status_code) >= 500))
            _prune(seen)
    except Exception:  # noqa: BLE001 - never break a response to count it
        return


def _prune(now: float) -> None:
    cutoff = now - API_ERROR_RATE_WINDOW_SECONDS
    while _recent and _recent[0][0] < cutoff:
        _recent.popleft()


def request_window(*, now: float | None = None) -> dict[str, Any]:
    """Requests and 5xx inside the alert window, plus the rate."""
    seen = time.monotonic() if now is None else now
    with _recent_lock:
        _prune(seen)
        requests = len(_recent)
        errors = sum(1 for _, failed in _recent if failed)
    return {
        "window_seconds": API_ERROR_RATE_WINDOW_SECONDS,
        "requests": requests,
        "errors_5xx": errors,
        "error_rate": (errors / requests) if requests else 0.0,
    }


def reset_request_window() -> None:
    """Clear the counters (tests, and a process that wants a fresh window)."""
    with _recent_lock:
        _recent.clear()


# -- worker-written Redis keys ---------------------------------------------


async def write_heartbeat(client: Any, *, loops: list[str]) -> bool:
    """Publish one heartbeat; False when Redis is unreachable."""
    payload = {
        "at": _iso(datetime.now(UTC)),
        "pid": os.getpid(),
        "loops": list(loops),
    }
    try:
        await client.set(
            HEARTBEAT_KEY, json.dumps(payload), ex=HEARTBEAT_TTL_SECONDS
        )
    except Exception:  # noqa: BLE001 - a failed heartbeat is visible as one
        return False
    return True


async def note_queue_pop(client: Any, *, now: datetime | None = None) -> bool:
    """Record the last time a job left the queue.

    Queue age is measured from this moment while the queue is non-empty: a list
    entry carries no timestamp of its own, and what the alert needs to know is
    whether work is still being taken off the queue at all. A worker that keeps
    popping keeps this fresh even while a long job runs, and a stopped worker
    lets it age.
    """
    moment = _iso(now or datetime.now(UTC))
    try:
        await client.set(LAST_POP_KEY, moment)
    except Exception:  # noqa: BLE001 - missing age is reported, not raised
        return False
    return True


async def note_job_failure(client: Any) -> int | None:
    """Count one failed job inside the alert window; None when Redis is down."""
    try:
        count = await client.incr(JOB_FAILURES_KEY)
        if int(count) == 1:
            await client.expire(JOB_FAILURES_KEY, JOB_FAILURE_WINDOW_SECONDS)
    except Exception:  # noqa: BLE001 - a failure is already logged by the worker
        return None
    return int(count)


async def redis_snapshot(client: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Read the worker heartbeat, queue depth and counters. Never raises."""
    moment = now or datetime.now(UTC)
    snapshot: dict[str, Any] = {
        "ok": False,
        "heartbeat_age_seconds": None,
        "heartbeat_loops": [],
        "queue_depth": None,
        "queue_age_seconds": None,
        "job_failures": 0,
    }
    try:
        raw_heartbeat = await client.get(HEARTBEAT_KEY)
        raw_pop = await client.get(LAST_POP_KEY)
        raw_failures = await client.get(JOB_FAILURES_KEY)
        depth = int(await client.llen("queue:jobs"))
    except Exception:  # noqa: BLE001 - the snapshot reports redis: false instead
        return snapshot

    snapshot["ok"] = True
    snapshot["queue_depth"] = max(0, depth)
    try:
        snapshot["job_failures"] = int(raw_failures or 0)
    except (TypeError, ValueError):
        snapshot["job_failures"] = 0

    heartbeat = None
    if raw_heartbeat:
        try:
            heartbeat = json.loads(raw_heartbeat)
        except (TypeError, ValueError):
            heartbeat = None
    if isinstance(heartbeat, dict):
        snapshot["heartbeat_age_seconds"] = _age_seconds(heartbeat.get("at"), moment)
        loops = heartbeat.get("loops")
        snapshot["heartbeat_loops"] = (
            [str(name) for name in loops] if isinstance(loops, list) else []
        )

    # Age only means something while there is something waiting.
    if snapshot["queue_depth"]:
        snapshot["queue_age_seconds"] = _age_seconds(raw_pop, moment)
    return snapshot


# -- the alert set ----------------------------------------------------------


def _alert(code: str, severity: str, summary: str, **evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "summary": summary,
        "evidence": {key: value for key, value in evidence.items() if value is not None},
    }


def evaluate(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one snapshot into the D8 alert set.

    Thresholds are environment configuration; a value *above* a threshold
    alerts (so the configured number is still acceptable). Each alert carries a
    stable `code` and a small `evidence` mapping — never a token, a path or a
    tenant's data — so an external check can route it without parsing prose.
    """
    alerts: list[dict[str, Any]] = []

    if not snapshot.get("db"):
        alerts.append(
            _alert(
                "api.database_unreachable",
                "critical",
                "The API cannot reach its database; requests cannot be served.",
            )
        )

    if not snapshot.get("redis", {}).get("ok"):
        alerts.append(
            _alert(
                "api.redis_unreachable",
                "critical",
                "Redis is unreachable: the queue, shared rate limits, presence "
                "and session limits are degraded.",
            )
        )
    else:
        heartbeat_age = snapshot["redis"].get("heartbeat_age_seconds")
        depth = snapshot["redis"].get("queue_depth")
        queue_age = snapshot["redis"].get("queue_age_seconds")
        failures = snapshot["redis"].get("job_failures") or 0

        if heartbeat_age is None:
            alerts.append(
                _alert(
                    "worker.heartbeat_missing",
                    "critical",
                    "No worker heartbeat: background jobs are not being consumed.",
                )
            )
        elif heartbeat_age > WORKER_HEARTBEAT_STALE_SECONDS:
            alerts.append(
                _alert(
                    "worker.heartbeat_stale",
                    "critical",
                    "The worker heartbeat is stale: the process may be stopped "
                    "or hung.",
                    age_seconds=round(heartbeat_age, 1),
                    threshold_seconds=WORKER_HEARTBEAT_STALE_SECONDS,
                )
            )

        if depth is not None and depth > QUEUE_DEPTH_ALERT:
            alerts.append(
                _alert(
                    "queue.depth_high",
                    "warning",
                    "The job queue is deeper than its threshold.",
                    depth=depth,
                    threshold=QUEUE_DEPTH_ALERT,
                )
            )
        if queue_age is not None and queue_age > QUEUE_AGE_ALERT_SECONDS:
            alerts.append(
                _alert(
                    "queue.age_high",
                    "critical",
                    "Queued work is not being taken off the queue: the backlog "
                    "is older than its threshold.",
                    age_seconds=round(queue_age, 1),
                    threshold_seconds=QUEUE_AGE_ALERT_SECONDS,
                )
            )
        if failures >= JOB_FAILURE_ALERT_COUNT:
            alerts.append(
                _alert(
                    "worker.job_failures",
                    "warning",
                    "Jobs are failing repeatedly inside the alert window.",
                    failures=failures,
                    threshold=JOB_FAILURE_ALERT_COUNT,
                )
            )

    api = snapshot.get("api") or {}
    requests = api.get("requests") or 0
    if requests >= API_ERROR_RATE_MIN_REQUESTS:
        rate = api.get("error_rate") or 0.0
        if rate >= API_ERROR_RATE_ALERT:
            alerts.append(
                _alert(
                    "api.error_rate",
                    "critical" if rate >= 2 * API_ERROR_RATE_ALERT else "warning",
                    "The API 5xx rate is above its threshold.",
                    error_rate=round(rate, 4),
                    requests=requests,
                    errors_5xx=api.get("errors_5xx"),
                    threshold=API_ERROR_RATE_ALERT,
                )
            )
    return alerts


def build_snapshot(
    *,
    db_ok: bool,
    redis: dict[str, Any],
    api: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The operator snapshot: inputs, thresholds and the alerts they raise."""
    moment = now or datetime.now(UTC)
    snapshot = {
        "generated_at": _iso(moment),
        "db": bool(db_ok),
        "redis": redis,
        "api": api or request_window(),
    }
    snapshot["alerts"] = evaluate(snapshot)
    snapshot["thresholds"] = {
        "worker_heartbeat_stale_seconds": WORKER_HEARTBEAT_STALE_SECONDS,
        "worker_heartbeat_interval_seconds": WORKER_HEARTBEAT_INTERVAL_SECONDS,
        "queue_depth": QUEUE_DEPTH_ALERT,
        "queue_age_seconds": QUEUE_AGE_ALERT_SECONDS,
        "job_failures": JOB_FAILURE_ALERT_COUNT,
        "job_failure_window_seconds": JOB_FAILURE_WINDOW_SECONDS,
        "api_error_rate": API_ERROR_RATE_ALERT,
        "api_error_rate_min_requests": API_ERROR_RATE_MIN_REQUESTS,
        "api_error_rate_window_seconds": API_ERROR_RATE_WINDOW_SECONDS,
    }
    return snapshot


__all__ = [
    "HEARTBEAT_KEY",
    "HEARTBEAT_TTL_SECONDS",
    "JOB_FAILURES_KEY",
    "LAST_POP_KEY",
    "build_snapshot",
    "evaluate",
    "note_job_failure",
    "note_queue_pop",
    "record_request",
    "redis_snapshot",
    "request_window",
    "reset_request_window",
    "write_heartbeat",
]
