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

The 5xx rate has two views. The in-process window above is this process's own
detail: it dies with the process and says nothing about its peers. The bucketed
Redis counters (`record_request_shared`, `fleet_window`, V6-23) are the fleet's
— every replica writes the same keys, so behind the ingress the alert is the
replicas' sum rather than whichever instance the caller reached, and it
survives a restart because the buckets do. With Redis down there is no fleet
view, so the alert falls back to the instance window and its evidence says
which one it read. The worker keys are still one document overwritten by every
worker, so the worker view is still not per process; V6-23's per-worker keys
are the fix, and the docs record what the external check therefore proves.

Redis is passed in rather than imported: this module must stay importable from
`core.logging` (which counts requests) without a cycle through
`services.redis`. Every function here is best-effort — a telemetry failure is
reported as missing data, never raised at the caller.
"""

from __future__ import annotations

import json
import os
import socket
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
    OPS_EXPECTED_WORKERS,
    QUEUE_AGE_ALERT_SECONDS,
    QUEUE_DEPTH_ALERT,
    WORKER_HEARTBEAT_INTERVAL_SECONDS,
    WORKER_HEARTBEAT_STALE_SECONDS,
)

#: One JSON document per key, each written by the worker and read by the API.
#: The legacy key is still written for one release; the per-worker keys below
#: are what a worker can be judged by (V6-23).
HEARTBEAT_KEY = "ops:worker:heartbeat"
#: One key per worker, so a dead process' key expires instead of being
#: overwritten by a live peer.
WORKER_HEARTBEAT_PREFIX = "ops:worker:heartbeat:"
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


# -- the fleet-wide 5xx window (V6-23) --------------------------------------
#
# The window above lives in one process, so behind the ingress the alert was
# that instance's rate. These counters are the fleet's: the access middleware
# writes one pair of buckets per replica into the shared Redis, and the reader
# sums the buckets that cover `API_ERROR_RATE_WINDOW_SECONDS`. Bucketing keeps
# the read bounded — six keys, not one key per second — at the cost of at most
# one bucket of slack at each edge of the window.

REQUESTS_BUCKET_PREFIX = "ops:api:requests:"
ERRORS_BUCKET_PREFIX = "ops:api:errors:"

#: A sixth of the window per bucket, so six buckets cover it; the reader takes
#: one more so a request exactly one window old is still inside the sum.
BUCKET_SECONDS = max(1, API_ERROR_RATE_WINDOW_SECONDS // 6)
BUCKET_COUNT = 6
BUCKET_READ_COUNT = BUCKET_COUNT + 1
#: Keep a bucket until it can no longer fall inside a window.
BUCKET_TTL_SECONDS = API_ERROR_RATE_WINDOW_SECONDS + BUCKET_SECONDS


def _bucket_of(epoch: float) -> int:
    return int(epoch // BUCKET_SECONDS)


async def record_request_shared(
    client: Any, status_code: int, *, now: float | None = None
) -> bool:
    """Count one response into the fleet buckets; False when Redis is unusable.

    Called by `RequestContextMiddleware` beside `record_request`, so every
    replica feeds the same keys. One pipeline keeps it to a single round trip;
    only a 5xx touches the error bucket, so the request count cannot be
    double-counted as an error. A hung Redis is bounded by the client's socket
    timeouts (V6-23 owns them) and no failure here may reach the response.
    """
    try:
        moment = time.time() if now is None else float(now)
        bucket = _bucket_of(moment)
        requests_key = f"{REQUESTS_BUCKET_PREFIX}{bucket}"
        pipe = client.pipeline()
        pipe.incr(requests_key)
        pipe.expire(requests_key, BUCKET_TTL_SECONDS)
        if int(status_code) >= 500:
            errors_key = f"{ERRORS_BUCKET_PREFIX}{bucket}"
            pipe.incr(errors_key)
            pipe.expire(errors_key, BUCKET_TTL_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001 - counting must never break a response
        return False
    return True


async def fleet_window(client: Any, *, now: float | None = None) -> dict[str, Any]:
    """The fleet's requests/5xx over the alert window; `ok: False` on failure.

    Counts are None when the buckets cannot be read, which `evaluate` treats as
    "no fleet view" rather than "no errors" — a failed read must not silence
    the alert.
    """
    moment = time.time() if now is None else float(now)
    current = _bucket_of(moment)
    buckets = [current - offset for offset in range(BUCKET_READ_COUNT)]
    snapshot: dict[str, Any] = {
        "ok": False,
        "window_seconds": API_ERROR_RATE_WINDOW_SECONDS,
        "bucket_seconds": BUCKET_SECONDS,
        "requests": None,
        "errors_5xx": None,
        "error_rate": None,
    }
    try:
        raw = await client.mget(
            [f"{REQUESTS_BUCKET_PREFIX}{bucket}" for bucket in buckets]
            + [f"{ERRORS_BUCKET_PREFIX}{bucket}" for bucket in buckets]
        )
    except Exception:  # noqa: BLE001 - reported as missing data
        return snapshot

    raw = list(raw or [])

    def _count(values: list[Any]) -> int:
        total = 0
        for value in values:
            try:
                total += int(value or 0)
            except (TypeError, ValueError):
                continue
        return total

    requests = _count(raw[:BUCKET_READ_COUNT])
    errors = _count(raw[BUCKET_READ_COUNT:])
    snapshot.update(
        ok=True,
        requests=requests,
        errors_5xx=errors,
        error_rate=(errors / requests) if requests else 0.0,
    )
    return snapshot


# -- worker-written Redis keys ---------------------------------------------


def worker_key(*, host: str | None = None, pid: int | None = None) -> str:
    """The key one worker owns: the host names the container, the pid the process.

    Two workers on one host (a supervisor running two processes, or a test)
    stay distinct, and a container's hostname is what the deployment already
    uses to tell replicas apart.
    """
    name = host if host is not None else socket.gethostname()
    process = pid if pid is not None else os.getpid()
    return f"{WORKER_HEARTBEAT_PREFIX}{name}:{process}"


async def write_heartbeat(client: Any, *, loops: list[str]) -> bool:
    """Publish one heartbeat; False when Redis is unreachable.

    Written twice (V6-23): under the worker's own key so a dead peer cannot be
    hidden by a live one, and under the legacy key so a reader that predates
    the per-worker keys still sees that *a* worker is alive.
    """
    identity = f"{socket.gethostname()}:{os.getpid()}"
    payload = {
        "at": _iso(datetime.now(UTC)),
        "pid": os.getpid(),
        "loops": list(loops),
        "worker": identity,
    }
    encoded = json.dumps(payload)
    try:
        await client.set(HEARTBEAT_KEY, encoded, ex=HEARTBEAT_TTL_SECONDS)
        await client.set(
            f"{WORKER_HEARTBEAT_PREFIX}{identity}",
            encoded,
            ex=HEARTBEAT_TTL_SECONDS,
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


async def _worker_snapshots(client: Any, moment: datetime) -> list[dict[str, Any]]:
    """Every per-worker heartbeat key, with its identity and age.

    `SCAN`, never `KEYS`, and a read failure leaves the list empty rather than
    failing the snapshot: the legacy key still proves that *a* worker is alive,
    it just cannot say which or how many.
    """
    workers: list[dict[str, Any]] = []
    try:
        keys = [
            key
            async for key in client.scan_iter(match=f"{WORKER_HEARTBEAT_PREFIX}*")
        ]
    except Exception:  # noqa: BLE001 - the legacy view is still readable
        return workers

    for key in keys:
        try:
            raw = await client.get(key)
        except Exception:  # noqa: BLE001 - one unreadable key is not the fleet
            continue
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        identity = payload.get("worker")
        if not isinstance(identity, str) or not identity:
            identity = str(key)[len(WORKER_HEARTBEAT_PREFIX) :]
        loops = payload.get("loops")
        workers.append(
            {
                "worker": identity,
                "age_seconds": _age_seconds(payload.get("at"), moment),
                "loops": (
                    [str(name) for name in loops] if isinstance(loops, list) else []
                ),
            }
        )
    return sorted(workers, key=lambda worker: worker["worker"])


def fresh_worker_count(workers: list[dict[str, Any]] | None) -> int:
    """How many workers are inside the stale window (V6-23).

    A per-worker key's TTL (three intervals) outlives the stale threshold, so a
    stopped worker can still have a key that is present and too old: counting
    every key would let a corpse satisfy the deployment's expected count. A key
    with no usable timestamp is not fresh either. This is the number
    `OPS_EXPECTED_WORKERS` is compared with, so it lives next to the snapshot's
    own `workers` list and both numbers are computed one way.
    """
    fresh = 0
    for worker in workers or []:
        if not isinstance(worker, dict):
            continue
        age = worker.get("age_seconds")
        if age is not None and age <= WORKER_HEARTBEAT_STALE_SECONDS:
            fresh += 1
    return fresh


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
        "workers": [],
        "workers_live": 0,
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

    # V6-23: per-worker keys beside the legacy document, worst-first detection.
    snapshot["workers"] = await _worker_snapshots(client, moment)
    snapshot["workers_live"] = fresh_worker_count(snapshot["workers"])

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

        # V6-23: each worker's own key, so a dead worker is named even while a
        # peer keeps the legacy document fresh.
        for worker in snapshot["redis"].get("workers") or []:
            if not isinstance(worker, dict):
                continue
            identity = str(worker.get("worker") or "unknown")
            age = worker.get("age_seconds")
            if age is None:
                alerts.append(
                    _alert(
                        "worker.heartbeat_missing",
                        "critical",
                        "A worker's heartbeat key carries no usable timestamp.",
                        worker=identity,
                    )
                )
            elif age > WORKER_HEARTBEAT_STALE_SECONDS:
                alerts.append(
                    _alert(
                        "worker.heartbeat_stale",
                        "critical",
                        "A worker's heartbeat is stale: that process may be "
                        "stopped or hung.",
                        worker=identity,
                        age_seconds=round(age, 1),
                        threshold_seconds=WORKER_HEARTBEAT_STALE_SECONDS,
                    )
                )

        # V6-23: the deployment's roster. Per-worker alerts can only name a key
        # that exists; a worker that never started, or whose key already expired,
        # leaves nothing behind, so only a deployment-fed count sees it. 0 means
        # the roster is not configured and never alerts.
        if OPS_EXPECTED_WORKERS:
            live = snapshot["redis"].get("workers_live")
            if live is None:
                # An older producer's snapshot has no count; derive it from the
                # same definition rather than assume zero.
                live = fresh_worker_count(snapshot["redis"].get("workers"))
            if live < OPS_EXPECTED_WORKERS:
                alerts.append(
                    _alert(
                        "worker.count_low",
                        "critical",
                        "Fewer workers are heartbeating than the deployment "
                        "expects: a worker is stopped or never started.",
                        expected=OPS_EXPECTED_WORKERS,
                        live=live,
                        missing=OPS_EXPECTED_WORKERS - live,
                    )
                )

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

        # V6-23: an eviction policy or a restart without persistence can delete
        # `queue:jobs`, which has no copy anywhere else. Unreadable settings are
        # not alerted (managed Redis often refuses CONFIG); a *read* settings set
        # with a known-bad value is, because no later signal would show the loss.
        durability = snapshot["redis"].get("durability") or {}
        durably_bad = [
            str(name) for name in (durability.get("problems") or []) if name
        ]
        if durability.get("ok") and durably_bad:
            alerts.append(
                _alert(
                    "redis.durability_unsafe",
                    "critical",
                    "Redis can drop queued jobs: an eviction policy other than "
                    "noeviction, or no persistence across a restart.",
                    problems=durably_bad,
                )
            )

    api = snapshot.get("api") or {}
    fleet = api.get("fleet") or {}
    # V6-23: the fleet's sum when the buckets could be read, this instance's
    # window otherwise — and the evidence names which one was read, so a fallback
    # is never mistaken for a fleet-wide rate.
    if fleet.get("ok"):
        counts, source = fleet, "fleet"
    else:
        counts, source = api, "instance"
    requests = counts.get("requests") or 0
    if requests >= API_ERROR_RATE_MIN_REQUESTS:
        rate = counts.get("error_rate") or 0.0
        if rate >= API_ERROR_RATE_ALERT:
            alerts.append(
                _alert(
                    "api.error_rate",
                    "critical" if rate >= 2 * API_ERROR_RATE_ALERT else "warning",
                    "The API 5xx rate is above its threshold.",
                    source=source,
                    error_rate=round(rate, 4),
                    requests=requests,
                    errors_5xx=counts.get("errors_5xx"),
                    threshold=API_ERROR_RATE_ALERT,
                )
            )
    return alerts


def build_snapshot(
    *,
    db_ok: bool,
    redis: dict[str, Any],
    api: dict[str, Any] | None = None,
    fleet: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The operator snapshot: inputs, thresholds and the alerts they raise.

    `api` is this process's window; `fleet` (V6-23) is the replicas' sum and
    rides inside it, so a reader sees the detail and the number the alert used
    side by side.
    """
    moment = now or datetime.now(UTC)
    local_api = dict(api or request_window())
    if fleet is not None:
        local_api["fleet"] = fleet
    snapshot = {
        "generated_at": _iso(moment),
        "db": bool(db_ok),
        "redis": redis,
        "api": local_api,
    }
    snapshot["alerts"] = evaluate(snapshot)
    snapshot["thresholds"] = {
        "worker_heartbeat_stale_seconds": WORKER_HEARTBEAT_STALE_SECONDS,
        "worker_heartbeat_interval_seconds": WORKER_HEARTBEAT_INTERVAL_SECONDS,
        "expected_workers": OPS_EXPECTED_WORKERS,
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
    "BUCKET_COUNT",
    "BUCKET_READ_COUNT",
    "BUCKET_SECONDS",
    "BUCKET_TTL_SECONDS",
    "ERRORS_BUCKET_PREFIX",
    "HEARTBEAT_KEY",
    "HEARTBEAT_TTL_SECONDS",
    "JOB_FAILURES_KEY",
    "LAST_POP_KEY",
    "REQUESTS_BUCKET_PREFIX",
    "WORKER_HEARTBEAT_PREFIX",
    "build_snapshot",
    "evaluate",
    "fleet_window",
    "fresh_worker_count",
    "note_job_failure",
    "note_queue_pop",
    "record_request",
    "record_request_shared",
    "redis_snapshot",
    "request_window",
    "reset_request_window",
    "worker_key",
    "write_heartbeat",
]
