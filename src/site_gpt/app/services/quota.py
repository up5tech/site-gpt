"""Daily per-website chat quota.

The in-memory rate limiter in `ratelimit.py` is keyed by client IP, so it caps a
single visitor and nothing else. One viral embed, or a handful of IPs, can still
spend a customer's whole LLM budget in a day. This module adds the missing
ceiling: a counter per website per UTC day, kept in Redis so every worker shares
it and no schema change is needed.

The counter is consumed **before** the LLM call and is never refunded: a message
that reached the provider costs money whether or not the answer was used.

V4 F4 adds the per-session cap (`consume_session_message`): the same Redis-INCR
pattern keyed by `(website, session)`, with a sliding TTL, checked **before** the
daily counter so a capped session never spends the website's daily budget.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from site_gpt.app.core.logging import log_event, log_exception
from uuid import UUID

from site_gpt.app.core.config import (
    DAILY_MESSAGE_LIMIT,
    SESSION_CAP_TTL_SECONDS,
    SESSION_MESSAGE_LIMIT,
)
from site_gpt.app.services.redis import redis_client

# Shown verbatim to the visitor when the cap is hit. It goes through the normal
# chat response (or SSE stream) so the widget renders it as a normal answer
# instead of an "Error!" bubble.
QUOTA_MESSAGE = (
    "Thanks for your interest! This assistant has reached its daily message "
    "limit, so I can't answer new questions today. Please try again tomorrow, "
    "or contact the team directly and they'll help you right away."
)

# Shown when one session hits its own cap (V4 F4, D6). The daily notice above is
# about the website's spend; this one is about a single conversation, so it asks
# the visitor to start a new chat rather than to come back tomorrow.
SESSION_CAP_MESSAGE = (
    "Thanks for the conversation! This chat has reached its message limit, so I "
    "can't take more questions in this session. Please start a new chat, or "
    "contact the team directly and they'll help you right away."
)


def parse_limit(raw: str | None, *, default: int) -> int:
    """Turn a stored setting into a message limit.

    Missing, empty or unparseable values fall back to `default` (the env
    setting), so a typo can never silently remove the ceiling. Zero is a real
    value and disables the cap; negative numbers are treated as a typo.
    """
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        log_event(
            "quota.invalid_limit",
            level=logging.WARNING,
            setting="daily_message_limit",
            value=raw,
        )
        return default
    if value < 0:
        log_event(
            "quota.invalid_limit",
            level=logging.WARNING,
            setting="daily_message_limit",
            value=value,
        )
        return default
    return value


def quota_key(website_id: UUID | str, now: datetime) -> str:
    """One counter per website per UTC day; tomorrow's date is a new key."""
    return f"quota:messages:{website_id}:{now:%Y-%m-%d}"


def seconds_until_reset(now: datetime) -> int:
    """Seconds from `now` until the next UTC midnight (at least 1)."""
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - now).total_seconds()))


async def usage(
    website_id: UUID | str, *, now: datetime | None = None
) -> int | None:
    """Messages answered for this website today.

    Returns None when Redis cannot be read: the owner's dashboard then shows the
    count as unknown instead of a wrong zero.
    """
    moment = now or datetime.now(UTC)
    try:
        value = await redis_client.get(quota_key(website_id, moment))  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - reporting must not break the request
        log_exception(
            "quota.usage_read_failed",
            e,
            level=logging.WARNING,
            website_id=str(website_id),
        )
        return None
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return None


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
        log_exception(
            "quota.count_failed",
            e,
            level=logging.WARNING,
            website_id=str(website_id),
        )
        return True

    return int(used) <= limit


def session_cap_key(website_id: UUID | str, session_id: str) -> str:
    """One counter per visitor session inside one website (D6)."""
    return f"quota:session:{website_id}:{session_id}"


async def consume_session_message(
    website_id: UUID | str,
    session_id: str,
    *,
    limit: int | None = None,
) -> bool:
    """Count one visitor message against its session's cap (V4 F4, D6).

    `limit=0` (or negative) disables the cap. The TTL is refreshed on every
    message instead of being set once: the cap is an idle window, so a visitor
    who returns after `SESSION_CAP_TTL_SECONDS` starts clean, while one who
    keeps trying never drifts out of the window. A Redis failure fails open with
    a logged error, exactly like the daily cap — chat staying available matters
    more than a temporarily missing ceiling.
    """
    if limit is None:
        limit = SESSION_MESSAGE_LIMIT
    if limit <= 0:
        return True

    key = session_cap_key(website_id, session_id)
    try:
        used = await redis_client.incr(key)  # type: ignore[attr-defined]
        await redis_client.expire(key, SESSION_CAP_TTL_SECONDS)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - any Redis problem must not break chat
        # The session id stays out of the log: it is the visitor's identity here.
        log_exception(
            "quota.session_count_failed",
            e,
            level=logging.WARNING,
            website_id=str(website_id),
        )
        return True

    return int(used) <= limit


async def quota_sse_events(message: str = QUOTA_MESSAGE):
    """SSE body for a capped streaming request, in the widget's normal shape.

    Both caps share it: the caller passes the notice that fits (the daily quota
    or the per-session cap), so the widget always renders a normal answer.
    """
    yield f"data: {json.dumps({'chunk': message})}\n\n"
    yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
