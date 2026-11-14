"""Daily per-website chat quota.

The in-memory rate limiter in `ratelimit.py` is keyed by client IP, so it caps a
single visitor and nothing else. One viral embed, or a handful of IPs, can still
spend a customer's whole LLM budget in a day. This module adds the missing
ceiling: a counter per website per UTC day, kept in Redis so every worker shares
it and no schema change is needed.

The counter is consumed **before** the LLM call and is never refunded: a message
that reached the provider costs money whether or not the answer was used.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from site_gpt.app.core.config import DAILY_MESSAGE_LIMIT
from site_gpt.app.services.redis import redis_client

# Shown verbatim to the visitor when the cap is hit. It goes through the normal
# chat response (or SSE stream) so the widget renders it as a normal answer
# instead of an "Error!" bubble.
QUOTA_MESSAGE = (
    "Thanks for your interest! This assistant has reached its daily message "
    "limit, so I can't answer new questions today. Please try again tomorrow, "
    "or contact the team directly and they'll help you right away."
)


def quota_key(website_id: UUID | str, now: datetime) -> str:
    """One counter per website per UTC day; tomorrow's date is a new key."""
    return f"quota:messages:{website_id}:{now:%Y-%m-%d}"


def seconds_until_reset(now: datetime) -> int:
    """Seconds from `now` until the next UTC midnight (at least 1)."""
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - now).total_seconds()))


async def consume_message(
    website_id: UUID | str,
    *,
    limit: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Count one message against today's cap. Returns whether it may be answered.

    `limit=0` (or negative) disables the cap. A Redis failure fails open: chat
    staying available matters more than a temporary missing ceiling, and the
    event is logged so the outage is visible.
    """
    if limit is None:
        limit = DAILY_MESSAGE_LIMIT
    if limit <= 0:
        return True

    moment = now or datetime.now(UTC)
    key = quota_key(website_id, moment)

    try:
        used = await redis_client.incr(key)  # type: ignore[attr-defined]
        if used == 1:
            # Expire with the day so stale counters cannot pile up; a crash
            # between INCR and EXPIRE only leaves an orphan key for a day.
            await redis_client.expire(key, seconds_until_reset(moment))  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - any Redis problem must not break chat
        print(f"[quota] could not count message for website {website_id}: {e}")
        return True

    return int(used) <= limit


async def quota_sse_events():
    """SSE body for a capped streaming request, in the widget's normal shape."""
    yield f"data: {json.dumps({'chunk': QUOTA_MESSAGE})}\n\n"
    yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
