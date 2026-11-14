"""Lightweight in-memory fixed-window rate limiter.

Sufficient for a single-process API. If you run multiple uvicorn workers, swap
this for a Redis-backed counter (the interface stays the same).
"""

import asyncio
import ipaddress
import time
from collections import defaultdict
from collections import deque

from fastapi import HTTPException, Request

from site_gpt.app.core.config import TRUSTED_PROXY_IPS

_lock = asyncio.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


async def allow(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    async with _lock:
        dq = _hits[key]
        while dq and now - dq[0] >= window_seconds:
            dq.popleft()
        if len(dq) >= max_requests:
            return False
        dq.append(now)
        return True


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
            )

    return dependency
