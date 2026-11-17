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

import json
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
