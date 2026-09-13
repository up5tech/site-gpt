"""Lightweight in-memory fixed-window rate limiter.

Sufficient for a single-process API. If you run multiple uvicorn workers, swap
this for a Redis-backed counter (the interface stays the same).
"""

import asyncio
import time
from collections import defaultdict
from collections import deque

from fastapi import HTTPException, Request

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


def _client_ip(request: Request) -> str:
    # Honour X-Forwarded-For when behind a proxy, fall back to socket IP.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
