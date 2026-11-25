"""Single Redis access point.

Every other module should go through here instead of building its own
client: one construction point keeps host/port/db/decode settings in one
place, and the lazy import-time client never connects until the first
command, so importing this module works with Redis down.

Helpers are best-effort where the caller must not break on an outage:
``ping``/``publish_event`` report failure instead of raising, and
``increment`` returns ``None`` so the caller can fall back (the rate
limiter's in-process fallback, V3-10). Pub/sub notifications are
best-effort — persist first, publish after commit, reconcile from DB.
"""

import asyncio
import json
import logging
import queue
import threading
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from site_gpt.app.core.logging import log_exception

import redis.asyncio as aioredis

from site_gpt.app.core.config import (
    REDIS_DB,
    REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
)

QUEUE_KEY = "queue:jobs"

#: The only `maxmemory-policy` that cannot evict `queue:jobs`. `queue:jobs` is a
#: plain list with no second copy: an OOM that evicts it deletes pending work, and
#: a restart without persistence (`appendonly no` and an empty `save`) loses it
#: the same way. Neither is visible from inside the app afterwards, so the settings
#: are read and reported (V6-23) instead of assumed.
DURABLE_MAXMEMORY_POLICY = "noeviction"


def create_client(**overrides: Any) -> aioredis.Redis:
    """Build a client. Construction is lazy — no I/O happens here.

    V6-23: the timeouts and the health check are applied here, so every caller —
    the API's shared client, the publisher thread's own client, `scripts/` — gets
    the same bounds from one place.
"""
    options: dict[str, Any] = {
        "host": REDIS_HOST,
        "port": int(REDIS_PORT),
        "password": REDIS_PASSWORD,
        "db": int(REDIS_DB),
        "decode_responses": True,
        "socket_connect_timeout": REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": REDIS_SOCKET_TIMEOUT_SECONDS,
        "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
    }
    options.update(overrides)
    return aioredis.Redis(**options)


# Module-level shared client. `redis.Redis()` does not connect at
# construction, so import works with Redis down; the first command
# establishes the connection on the caller's event loop.
redis_client = create_client()


def get_client() -> aioredis.Redis:
    return redis_client


async def ping() -> bool:
    """True if Redis answers; False on any error (never raises)."""
    try:
        return bool(await get_client().ping())
    except Exception:
        return False


async def close_client() -> bool:
    """Release the shared client's pooled connections; never raises.

    Used by the API's shutdown (V6-23): uvicorn stops accepting after the
    lifespan yields, and a connection left in the pool holds a file descriptor
    (and, on a managed Redis, one of its client slots) until the process exits.
    Closing is best-effort — the process is going away either way — and the pool
    reconnects lazily if anything still uses this client afterwards, which is
    what makes the call safe in tests that reuse the module-level client.
    """
    try:
        await get_client().aclose()
    except Exception as e:  # noqa: BLE001 - shutdown must not fail on Redis
        log_exception("redis.close_failed", e, level=logging.WARNING)
        return False
    return True


def durability_problems(values: Mapping[str, Any]) -> list[str]:
    """The names of Redis settings that let an outage drop queued jobs (V6-23).

    Two ways, both silent from inside the app: an eviction policy other than
    `noeviction` frees `queue:jobs` when the instance reaches `maxmemory`, and a
    restart without persistence (`appendonly no` and no `save` schedule) loses
    the list outright. `noeviction` is not a guarantee of durability, it only
    means a full instance refuses writes instead of deleting queued work.

    A missing key is not a problem: managed Redis commonly restricts `CONFIG`,
    so absent settings are reported as unreadable by `durability()` rather than
    guessed here.
    """
    problems: list[str] = []
    policy = values.get("maxmemory-policy")
    if policy is not None and str(policy).strip().lower() != DURABLE_MAXMEMORY_POLICY:
        problems.append("maxmemory-policy")
    appendonly = str(values.get("appendonly") or "").strip().lower()
    if appendonly not in {"yes", "true", "1"}:
        if not str(values.get("save") or "").strip():
            problems.append("appendonly")
    return problems


async def durability() -> dict[str, Any]:
    """Read the durability-relevant Redis settings (V6-23). Never raises.

    `ok: False` means the settings could not be read — Redis is down, or a
    managed instance refuses `CONFIG GET`. That is reported as unknown, never as
    safe: an empty `problems` list only means "nothing wrong was *seen*", and
    the operator runbook has to say what a deployment with `ok: False` must be
    verified against by hand. `queue:jobs` has no copy elsewhere, so the check is
    about refusing to lose pending work, not about cache warmth.
    """
    report: dict[str, Any] = {"ok": False, "problems": [], "settings": {}}
    try:
        raw = await get_client().config_get(  # type: ignore[attr-defined]
            "maxmemory-policy", "appendonly", "save"
        )
    except Exception as e:  # noqa: BLE001 - reported as unknown, not raised
        log_exception("redis.durability_unreadable", e, level=logging.WARNING)
        return report
    settings = {str(key): value for key, value in dict(raw or {}).items()}
    report.update(ok=True, settings=settings, problems=durability_problems(settings))
    return report


async def enqueue_job(data: dict):
    await redis_client.lpush(QUEUE_KEY, json.dumps(data))  # type: ignore


async def publish_event(channel: str, payload: dict | str) -> bool:
    """Publish one notification; True on success, False on any error.

    Best-effort: callers persist first and treat a False as "the
    subscriber will reconcile from the database on its next poll".
    """
    message = payload if isinstance(payload, str) else json.dumps(payload)
    try:
        await get_client().publish(channel, message)
    except Exception as e:  # noqa: BLE001 - notification must not break the request
        log_exception(
            "redis.publish_failed", e, level=logging.WARNING, channel=channel
        )
        return False
    return True


@asynccontextmanager
async def subscribe(channel: str) -> AsyncIterator[object]:
    """Yield a PubSub subscribed to `channel`; always cleaned up.

    Unsubscribe + close run in `finally`, so a disconnected SSE/websocket
    consumer cannot leak a subscription. Kept on the caller's event loop —
    do not wrap this in a private loop (see the /health note in routes.py).
    """
    pubsub = get_client().pubsub()
    try:
        await pubsub.subscribe(channel)
        yield pubsub
    finally:
        try:
            await pubsub.unsubscribe(channel)
        finally:
            await pubsub.aclose()


async def set_lease(key: str, value: dict, ttl_seconds: int) -> bool:
    """Write a self-expiring presence lease; False when Redis is unreachable.

    The TTL is the whole safety net: a tab that crashes (or a worker that dies)
    never runs its cleanup, so the key has to disappear on its own. Renewal is
    `renew_lease`, and each connection owns its own key, which is why one tab
    closing cannot clear another tab's presence.
    """
    try:
        await get_client().set(key, json.dumps(value), ex=ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - presence is best-effort
        log_exception("redis.lease_failed", e, level=logging.WARNING, key=key)
        return False
    return True


async def renew_lease(key: str, ttl_seconds: int) -> bool:
    """Push a lease's expiry out while its connection is still alive."""
    try:
        renewed = await get_client().expire(key, ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - the next tick can retry
        log_exception("redis.renew_failed", e, level=logging.WARNING, key=key)
        return False
    return bool(renewed)


async def delete_lease(key: str) -> bool:
    """Drop one lease on a clean disconnect; False when Redis is unreachable."""
    try:
        await get_client().delete(key)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - the TTL removes it instead
        log_exception("redis.delete_failed", e, level=logging.WARNING, key=key)
        return False
    return True


async def lease_keys(pattern: str) -> list[str]:
    """Every key matching `pattern`, or [] when Redis is unreachable.

    `SCAN` in batches, never `KEYS`: `KEYS` walks the entire keyspace while
    holding the server, so one presence read would stall every other command on
    a shared Redis. `SCAN` asks for a cursor at a time and is safe to run
    against a live server, which is the whole reason presence can be a scan.

    The trade-off is that `SCAN` may return the same key twice if the keyspace
    changes underneath it, so callers count distinct keys, not list entries.
    """
    keys: list[str] = []
    try:
        async for key in get_client().scan_iter(match=pattern):  # type: ignore[attr-defined]
            keys.append(key)
    except Exception as e:  # noqa: BLE001 - callers treat [] as "nobody online"
        log_exception("redis.scan_failed", e, level=logging.WARNING, pattern=pattern)
        return []
    return keys


# -- notifications from sync code -------------------------------------------
# A sync route (a claim, an agent reply) must not wait on Redis: the publish is
# a hint the console can miss and recover from the database, so it belongs off
# the request thread. One daemon thread owns a private loop and client, so a
# publish from a worker thread neither blocks the response nor borrows the
# server loop's connection pool (redis-py binds a connection to its loop).
_outbox: "queue.SimpleQueue[tuple[str, dict]]" = queue.SimpleQueue()
_outbox_started = False
_outbox_lock = threading.Lock()


async def _publish_queued(channel: str, payload: dict) -> None:
    client = create_client()
    try:
        await client.publish(channel, json.dumps(payload))
    finally:
        await client.aclose()


def _drain_outbox() -> None:
    """Drain the outbox forever; a failure loses a hint, never a request."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        channel, payload = _outbox.get()
        try:
            loop.run_until_complete(_publish_queued(channel, payload))
        except Exception as e:  # noqa: BLE001 - callers already committed
            log_exception(
                "redis.notification_lost", e, level=logging.WARNING, channel=channel
            )


def enqueue_publish(channel: str, payload: dict) -> None:
    """Queue one notification and return immediately. Never raises.

    The publisher thread is started on first use. Call this **after** the
    transaction committed; the subscriber re-reads the database anyway, so a
    lost notification costs a poll, not a wrong screen.
    """
    global _outbox_started
    try:
        if not _outbox_started:
            with _outbox_lock:
                if not _outbox_started:
                    threading.Thread(
                        target=_drain_outbox,
                        name="redis-publisher",
                        daemon=True,
                    ).start()
                    _outbox_started = True
        _outbox.put((channel, payload))
    except Exception as e:  # noqa: BLE001 - the next poll recovers
        log_exception("redis.notification_queue_failed", e, level=logging.WARNING)


async def increment(key: str, ttl_seconds: int | None = None) -> int | None:
    """Atomically increment `key`, setting its TTL on first use.

    Returns the new value, or None when Redis is unreachable so the
    caller can fall back. Fixed-window primitive; the sliding-window
    limiter (V3-10) builds its own Lua script on top of this keyspace.
    """
    try:
        client = get_client()
        used = await client.incr(key)  # type: ignore[attr-defined]
        if used == 1 and ttl_seconds:
            await client.expire(key, ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - caller falls back
        log_exception("redis.increment_failed", e, level=logging.WARNING, key=key)
        return None
    return int(used)
