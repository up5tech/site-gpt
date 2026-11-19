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
import queue
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from site_gpt.app.core.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB

QUEUE_KEY = "queue:jobs"


def create_client() -> aioredis.Redis:
    """Build a client. Construction is lazy — no I/O happens here."""
    return aioredis.Redis(
        host=REDIS_HOST,
        port=int(REDIS_PORT),
        password=REDIS_PASSWORD,
        db=int(REDIS_DB),
        decode_responses=True,
    )


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
        print(f"[redis] publish to {channel} failed: {e}")
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
        print(f"[redis] lease {key} failed: {e}")
        return False
    return True


async def renew_lease(key: str, ttl_seconds: int) -> bool:
    """Push a lease's expiry out while its connection is still alive."""
    try:
        renewed = await get_client().expire(key, ttl_seconds)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - the next tick can retry
        print(f"[redis] renew {key} failed: {e}")
        return False
    return bool(renewed)


async def delete_lease(key: str) -> bool:
    """Drop one lease on a clean disconnect; False when Redis is unreachable."""
    try:
        await get_client().delete(key)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - the TTL removes it instead
        print(f"[redis] delete {key} failed: {e}")
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
        print(f"[redis] scan {pattern} failed: {e}")
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
            print(f"[redis] notification on {channel} lost: {e}")


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
        print(f"[redis] could not queue a notification: {e}")


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
        print(f"[redis] increment {key} failed: {e}")
        return None
    return int(used)
