"""Per-IP rate limiter with a shared Redis backend (V3, F1).

Two backends, selected by `RATE_LIMIT_BACKEND` (env, default `memory`):

- `memory` — the V2.1 in-process sliding window (deque per key). Per
  process: restarts reset it and workers do not share it.
- `redis` — a sliding window over a Redis sorted set, pruned/counted/
  conditionally-added by one atomic Lua script, so concurrent requests
  against multiple API processes cannot exceed one shared budget and a
  restart does not reset a live window.

If Redis is unreachable while the `redis` backend is configured, the
limiter falls back to the in-process deque (D5) and reports itself
degraded via `limiter_degraded()` (surfaced in `/health`). That fallback
is per-process only: during an outage, combined traffic across processes
may exceed one shared budget up to the per-process allowance. It is a
weaker local cap, not a global guarantee.

Public surface is unchanged from V2.1: `allow(key, max_requests,
window_seconds)` and the `rate_limit(...)` dependency factory.
"""

import asyncio
import ipaddress
import logging
import time
import uuid
from collections import defaultdict
from collections import deque

from fastapi import HTTPException, Request

from site_gpt.app.core.config import RATE_LIMIT_BACKEND, TRUSTED_PROXY_IPS

log = logging.getLogger(__name__)

_lock = asyncio.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)

# Degraded-limiter state: set when the redis backend falls back to memory,
# cleared on the next successful Redis call. Read by `/health`.
_redis_degraded = False
_last_degraded_log = 0.0

# Atomic sliding-window check-and-add. Prune entries older than the window,
# count what remains, and add the caller only when under the cap; the key
# expires with the window so an idle bucket disappears on its own. The
# member is a unique token per call so two hits in the same instant cannot
# collapse into one sorted-set entry (which would under-count).
_LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCOUNT', key, now - window, now)
if count >= max then
    redis.call('PEXPIRE', key, window * 1000)
    return 0
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window * 1000)
return 1
"""

# One policy table for every public limit (V3-11). Values are
# (scope, max_requests, window_seconds) and match the pre-V3 literals
# exactly, so migrating a route to `rate_limit_policy` changes nothing.
# `v1` is reserved: /api/v1 is authenticated by API key and has no
# per-IP limiter today; per-key limiting is deferred (see V3-12) and
# this row is not wired to any route.
RATE_LIMIT_POLICIES: dict[str, tuple[str, int, int]] = {
    "chat": ("chat", 20, 60),
    "stream": ("chat", 20, 60),  # shares the `chat` bucket, as before
    "feedback": ("chat", 40, 60),
    "contacts": ("chat", 40, 60),
    "handoff": ("chat", 10, 60),
    "session-token": ("session", 30, 60),
    "ingest": ("ingest", 10, 60),
    "register": ("register", 3, 3600),
    "login": ("login", 10, 60),
    "reset": ("reset", 3, 3600),
    "reset-confirm": ("reset-confirm", 10, 300),
    "v1": ("v1", 60, 60),  # reserved, not wired — see V3-12
}


def limiter_backend() -> str:
    return RATE_LIMIT_BACKEND


def limiter_degraded() -> bool:
    """True while the redis backend is actively falling back to memory."""
    return _redis_degraded


async def _allow_memory(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    async with _lock:
        dq = _hits[key]
        while dq and now - dq[0] >= window_seconds:
            dq.popleft()
        if len(dq) >= max_requests:
            return False
        dq.append(now)
        return True


async def _allow_redis(key: str, max_requests: int, window_seconds: int) -> bool | None:
    """Sliding-window check against Redis. None on any Redis error."""
    global _redis_degraded, _last_degraded_log
    # Imported lazily: the module must stay importable with Redis down.
    from site_gpt.app.services.redis import redis_client

    now = time.time()
    try:
        allowed = await redis_client.eval(  # type: ignore[attr-defined]
            _LUA_SLIDING_WINDOW,
            1,
            f"ratelimit:{key}",
            now,
            window_seconds,
            max_requests,
            f"{now}:{uuid.uuid4().hex}",
        )
    except Exception as e:  # noqa: BLE001 - fall back to the local cap
        _redis_degraded = True
        if now - _last_degraded_log > 60:
            _last_degraded_log = now
            log.warning(
                "rate limiter: Redis unreachable, falling back to per-process "
                "memory cap (weaker than a shared budget): %s",
                e,
            )
        return None
    _redis_degraded = False
    return bool(int(allowed))


async def allow(key: str, max_requests: int, window_seconds: int) -> bool:
    if RATE_LIMIT_BACKEND == "redis":
        result = await _allow_redis(key, max_requests, window_seconds)
        if result is not None:
            return result
        # Redis error: fall through to the per-process cap (D5).
    return await _allow_memory(key, max_requests, window_seconds)


def _parse_ip(value: str):
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _trusted_networks(entries) -> list:
    """Parse `TRUSTED_PROXY_IPS` entries into networks, skipping rubbish."""
    networks = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return networks


# Configured allowlist (empty when TRUSTED_PROXY_IPS is unset).
_TRUSTED_PROXIES = _trusted_networks(TRUSTED_PROXY_IPS)


def _is_trusted_peer(value: str) -> bool:
    """Whether the direct peer may be a reverse proxy worth trusting.

    Loopback/private addresses are trusted implicitly (proxy on the same host,
    Docker network or VPC). A public-address proxy — a cloud load balancer —
    has to be listed in `TRUSTED_PROXY_IPS`, otherwise every visitor would be
    keyed by the LB's address and share a single rate-limit bucket.
    """
    addr = _parse_ip(value)
    if addr is None:
        return False
    if addr.is_loopback or addr.is_private:
        return True
    return any(addr in network for network in _TRUSTED_PROXIES)


def _client_ip(request: Request) -> str:
    """Resolve the client IP without letting callers spoof it.

    `X-Forwarded-For` is attacker-controlled, so it is only honoured when the
    direct peer is loopback or a private address — i.e. a reverse proxy on the
    same host or VPC. A direct internet connection always uses the socket
    address, otherwise rotating the header would bypass every rate limit.
    """
    if request.client is None:
        return "unknown"

    peer = request.client.host
    if not _is_trusted_peer(peer):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    candidate = forwarded.split(",")[0].strip()
    if _parse_ip(candidate) is None:
        # Malformed/forged header entry: fall back to the socket address.
        return peer
    return candidate


def rate_limit(scope: str, max_requests: int = 20, window_seconds: int = 60):
    """FastAPI dependency factory. Key = `{scope}:{client_ip}`."""

    async def dependency(request: Request):
        ip = _client_ip(request)
        ok = await allow(f"{scope}:{ip}", max_requests, window_seconds)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Limit is {max_requests} per "
                f"{window_seconds}s. Please slow down.",
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency


def rate_limit_policy(name: str):
    """Dependency for a named policy from `RATE_LIMIT_POLICIES` (V3-11)."""
    scope, max_requests, window_seconds = RATE_LIMIT_POLICIES[name]
    return rate_limit(scope, max_requests=max_requests, window_seconds=window_seconds)
