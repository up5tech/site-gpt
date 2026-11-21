"""Agent-facing inbox service (V3-41).

The agent console addresses a conversation by its **UUID**, never by
`session_id`: a session id is unique per website only, so the same string can
exist on two websites of one company, and on another tenant's website it means
nothing at all. Every helper here therefore takes `(company_id,
conversation_id)` and resolves the website through a join, which is also what
turns a foreign UUID into a plain "not found" instead of a cross-tenant read.

State changes belong to `services/conversations.py`; this module is the only
place an agent action is translated into one of its transitions. Routes call
these helpers and never touch a row themselves.

The claim is the concurrency boundary:
`SELECT … FOR UPDATE SKIP LOCKED` locks one waiting row, so two agents pressing
Claim at the same moment produce one winner and one `InboxConflict` (the loser
is answered with a 409). The lock is held until this module commits, which is when the state change becomes visible to everyone else — exactly the window in
which the session must not be handed to a second agent.

The console learns about a change through a pub/sub notification (V3-42), never
instead of the database: `conversation_event` is published by the route **after**
the service committed, it carries a stable id so a reconnect can drop duplicates,
and the console still re-reads the row. Pub/sub is not durable and not exactly
once, so a missed notification costs a poll, not a wrong screen. Presence is a
lease per connection with a TTL, so a crashed tab ages out and a second tab's
presence cannot be cleared by the first one leaving.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.config import (
    INBOX_PRESENCE_TTL_SECONDS,
    INBOX_STREAM_HEARTBEAT_SECONDS,
)
from site_gpt.app.services import company_settings, conversations, rag
from site_gpt.app.services import redis as redis_service

# The per-company switch (V3-03 registry key). Off means the whole agent surface
# answers 404, so an installation that does not run an agent console does not
# advertise one.
INBOX_FLAG = "live_inbox_enabled"

# Who may hold a conversation: whatever `get_manager_user` already allows.
AGENT_ROLES = ("admin", "manager")


class InboxNotFound(LookupError):
    """No conversation with that UUID in the caller's company (route: 404)."""


class InboxConflict(ValueError):
    """The action is refused: held by someone else, or the state forbids it (409)."""


def enabled(db: Session, company_id: UUID) -> bool:
    """Whether this company has the live inbox turned on."""
    return company_settings.flag(db, company_id, INBOX_FLAG)


def assignable_user(
    db: Session, company_id: UUID, user_id: UUID
) -> models.User | None:
    """A teammate who can hold a conversation, or None.

    Active managers/admins of the **caller's** company only: assigning to a
    foreign id would otherwise be a way to point at another tenant's user.
    """
    return (
        db.query(models.User)
        .filter(
            models.User.id == user_id,
            models.User.company_id == company_id,
            models.User.status == "active",
            models.User.role.in_(AGENT_ROLES),
        )
        .first()
    )


def _scoped(
    db: Session, company_id: UUID, conversation_id: UUID
) -> models.Conversation | None:
    """The conversation, only if its website belongs to `company_id`."""
    return (
        db.query(models.Conversation)
        .join(models.Website, models.Website.id == models.Conversation.website_id)
        .filter(
            models.Conversation.id == conversation_id,
            models.Website.company_id == company_id,
        )
        .first()
    )


def _require(
    db: Session, company_id: UUID, conversation_id: UUID
) -> models.Conversation:
    row = _scoped(db, company_id, conversation_id)
    if row is None:
        raise InboxNotFound("Conversation not found")
    return row


def locked_query(
    db: Session, company_id: UUID, conversation_id: UUID, states: tuple[str, ...]
):
    """The claim/lock select: one company-scoped row in an allowed state.

    `FOR UPDATE OF conversations SKIP LOCKED` is the whole point. A plain select
    leaves the same row visible to both agents; locking the row without
    `SKIP LOCKED` would make the loser wait and then claim a session that is
    already taken. Skipping it makes the loser see nothing, and nothing is what
    the route reports as a 409. The lock is released by the caller's commit.

    SQLite ignores `FOR UPDATE` (and has no `SKIP LOCKED`), which is why the
    concurrency behaviour is verified against Postgres; the statement shape is
    pinned against the Postgres dialect instead.
    """
    return (
        db.query(models.Conversation)
        .join(models.Website, models.Website.id == models.Conversation.website_id)
        .filter(
            models.Conversation.id == conversation_id,
            models.Website.company_id == company_id,
            models.Conversation.state.in_(states),
        )
        .with_for_update(of=models.Conversation, skip_locked=True)
    )


def waiting_claim_query(db: Session, company_id: UUID, conversation_id: UUID):
    """The waiting-row claim select used by `claim` and `assign`."""
    return locked_query(
        db, company_id, conversation_id, (conversations.STATE_WAITING,)
    )


def _lock(
    db: Session, company_id: UUID, conversation_id: UUID, states: tuple[str, ...]
) -> models.Conversation | None:
    """Take the row lock, or None when someone else already holds it."""
    return locked_query(db, company_id, conversation_id, states).first()


def _ensure_holder(conversation: models.Conversation, user: models.User) -> None:
    """Only the assignee (or an admin overriding) may release or close."""
    assignee = conversation.assigned_user_id
    if assignee is not None and assignee != user.id and user.role != "admin":
        raise InboxConflict("Another agent is handling this conversation")


def _take(
    db: Session,
    company_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
    *,
    action: str,
    when: datetime | None = None,
) -> models.Conversation:
    """Give a waiting conversation to `user_id`: waiting → human, exactly once.

    Claim and assign differ only in whose id ends up as the assignee — the row
    lock, the idempotent retry and the conflict are the same, so they live here
    rather than in two copies that could drift apart.

    A retry by the agent who already holds it returns the same row (acting twice
    is not an error); anyone else gets `InboxConflict` because the row is no
    longer `waiting`, either because it was taken or because it never queued.
    If the locked select returns nothing, another transaction holds the row:
    `SKIP LOCKED` skipped it, and the caller must not claim it anyway.
    """
    row = _require(db, company_id, conversation_id)
    if row.state == conversations.STATE_HUMAN and row.assigned_user_id == user_id:
        return row
    if row.state != conversations.STATE_WAITING:
        raise InboxConflict(
            f"Conversation is {row.state}, not waiting to be {action}"
        )

    locked = waiting_claim_query(db, company_id, conversation_id).first()
    if locked is None:
        raise InboxConflict("Another agent is claiming this conversation")
    conversations.claim(db, locked, user_id, when=when)
    # The visitor is being served now, so the V2.1 callback row is `accepted`.
    _sync_handoff(db, locked, "accepted")
    db.commit()
    return locked


def _sync_handoff(
    db: Session, conversation: models.Conversation, status: str
) -> None:
    """Mirror a queue move onto the session's handoff request (V3-45).

    The `handoff_requests` row is the same request seen on `/handoffs`: leaving
    it `pending` after an agent claimed the session, or after it was closed,
    would tell the team to call back a visitor who is already being served. It
    touches only values — a company without the inbox never gets a row created —
    and runs inside the transition's own transaction. Callers commit.
    """
    db.query(models.HandoffRequest).filter(
        models.HandoffRequest.website_id == conversation.website_id,
        models.HandoffRequest.session_id == conversation.session_id,
    ).update({"status": status}, synchronize_session=False)


def claim(
    db: Session,
    company_id: UUID,
    conversation_id: UUID,
    user: models.User,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """An agent takes a waiting conversation for themselves."""
    return _take(
        db, company_id, conversation_id, user.id, action="claimed", when=when
    )


def assign(
    db: Session,
    company_id: UUID,
    conversation_id: UUID,
    target: models.User,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """Give a waiting conversation to a specific teammate.

    Used by a manager pushing a queue item to an agent instead of taking it
    themselves. The target is resolved by `assignable_user` before this call, so
    a foreign/non-agent id never reaches a state change.
    """
    return _take(
        db, company_id, conversation_id, target.id, action="assigned", when=when
    )


def reply(
    db: Session,
    company_id: UUID,
    conversation_id: UUID,
    user: models.User,
    message: str,
) -> tuple[models.Conversation, models.ChatMessage]:
    """An agent answers the visitor: store a `role='agent'` row, then return it.

    Only the holder (or an admin) may write, and only while the session is
    `human` — a queued or bot-run conversation has nobody to answer as. The row
    carries `author_user_id`, so the transcript, the inbox detail and the
    privacy export all name the teammate who wrote it. `rag.save_message`
    commits (and refreshes the conversation's `last_message_at`), so callers
    publish the notifications afterwards, never before.
    """
    row = _require(db, company_id, conversation_id)
    if row.state != conversations.STATE_HUMAN:
        raise InboxConflict(f"Conversation is {row.state}, not with an agent")
    _ensure_holder(row, user)
    saved = rag.save_message(
        db,
        row.website_id,
        row.session_id,
        rag.AGENT_ROLE,
        message,
        author_user_id=user.id,
    )
    return row, saved


def release(
    db: Session,
    company_id: UUID,
    conversation_id: UUID,
    user: models.User,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """The holder gives the conversation back to the queue: human → waiting."""
    row = _require(db, company_id, conversation_id)
    if row.state != conversations.STATE_HUMAN:
        raise InboxConflict(f"Conversation is {row.state}, not with an agent")
    _ensure_holder(row, user)

    locked = _lock(db, company_id, conversation_id, (conversations.STATE_HUMAN,))
    if locked is None:
        raise InboxConflict("Another request is changing this conversation")
    conversations.release(db, locked, when=when)
    # Back in the queue: the callback request is pending again.
    _sync_handoff(db, locked, "pending")
    db.commit()
    return locked


def close(
    db: Session,
    company_id: UUID,
    conversation_id: UUID,
    user: models.User,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """Finish with the conversation: human (or waiting) → closed.

    `bot` is refused: a session nobody asked to escalate has nothing to close,
    and silencing it would hide the visitor from the agent who picks it up next.
    Closing twice is idempotent.
    """
    row = _require(db, company_id, conversation_id)
    if row.state == conversations.STATE_CLOSED:
        return row
    if row.state == conversations.STATE_BOT:
        raise InboxConflict(
            "The bot is answering this conversation; there is nothing to close"
        )
    if row.state == conversations.STATE_HUMAN:
        _ensure_holder(row, user)

    locked = _lock(
        db,
        company_id,
        conversation_id,
        (conversations.STATE_WAITING, conversations.STATE_HUMAN),
    )
    if locked is None:
        raise InboxConflict("Another request is changing this conversation")
    conversations.close(db, locked, when=when)
    # Done with the visitor, and the email queue agrees.
    _sync_handoff(db, locked, "closed")
    db.commit()
    return locked


def _user_names(db: Session, user_ids: set[UUID]) -> dict[UUID, str | None]:
    """Display names for assignees/authors, in one query."""
    if not user_ids:
        return {}
    rows = (
        db.query(models.User.id, models.User.first_name, models.User.last_name)
        .filter(models.User.id.in_(user_ids))
        .all()
    )
    return {
        user_id: f"{first or ''} {last or ''}".strip() or None
        for user_id, first, last in rows
    }


def _message_stats(
    db: Session, pairs: list[tuple[UUID, str]]
) -> tuple[dict[tuple[UUID, str], int], dict[tuple[UUID, str], str]]:
    """Message counts and first-question titles for a page of conversations."""
    counts: dict[tuple[UUID, str], int] = {}
    titles: dict[tuple[UUID, str], str] = {}
    if not pairs:
        return counts, titles

    scope = tuple_(
        models.ChatMessage.website_id, models.ChatMessage.session_id
    ).in_(pairs)

    for website_id, session_id, count in (
        db.query(
            models.ChatMessage.website_id,
            models.ChatMessage.session_id,
            func.count(models.ChatMessage.id),
        )
        .filter(scope)
        .group_by(models.ChatMessage.website_id, models.ChatMessage.session_id)
        .all()
    ):
        counts[(website_id, session_id)] = count

    # Oldest first, so the first row seen for a session is its first question.
    for website_id, session_id, message in (
        db.query(
            models.ChatMessage.website_id,
            models.ChatMessage.session_id,
            models.ChatMessage.message,
        )
        .filter(scope, models.ChatMessage.role == "user")
        .order_by(models.ChatMessage.created_at.asc())
        .all()
    ):
        key = (website_id, session_id)
        if key not in titles and message:
            titles[key] = message
    return counts, titles


def _contacts(
    db: Session, pairs: list[tuple[UUID, str]]
) -> dict[tuple[UUID, str], models.Contact]:
    """The lead rows of a page of conversations, when the visitor left one."""
    if not pairs:
        return {}
    rows = (
        db.query(models.Contact)
        .filter(
            tuple_(
                models.Contact.website_id, models.Contact.session_id
            ).in_(pairs)
        )
        .all()
    )
    return {(row.website_id, row.session_id): row for row in rows}


def _insights(
    db: Session, conversation_ids: list[UUID]
) -> dict[UUID, models.ConversationInsight]:
    """The insight row of each conversation on a page, when one exists.

    A read-only join beside the queue, not a second endpoint: the badge belongs
    on the row an agent is already looking at, and a company that never opted in
    simply has no rows here, so its items carry null labels (V4 F2).
    """
    if not conversation_ids:
        return {}
    rows = (
        db.query(models.ConversationInsight)
        .filter(models.ConversationInsight.conversation_id.in_(conversation_ids))
        .all()
    )
    return {row.conversation_id: row for row in rows}


def _person_name(contact: models.Contact) -> str | None:
    return f"{contact.first_name} {contact.last_name}".strip() or None


def _truncate(title: str | None) -> str | None:
    if title and len(title) > conversations.TITLE_MAX_LEN:
        return title[: conversations.TITLE_MAX_LEN] + "…"
    return title


def _describe(
    db: Session, rows: list[tuple[models.Conversation, str]]
) -> list[dict]:
    """Turn page rows into list items, in three extra queries."""
    pairs = [(row.website_id, row.session_id) for row, _ in rows]
    counts, titles = _message_stats(db, pairs)
    contacts = _contacts(db, pairs)
    insights = _insights(db, [row.id for row, _ in rows])
    names = _user_names(
        db, {row.assigned_user_id for row, _ in rows if row.assigned_user_id}
    )

    items: list[dict] = []
    for row, website_name in rows:
        key = (row.website_id, row.session_id)
        contact = contacts.get(key)
        insight = insights.get(row.id)
        items.append(
            {
                "id": row.id,
                "website_id": row.website_id,
                "website_name": website_name,
                "session_id": row.session_id,
                "state": row.state,
                "assigned_user_id": row.assigned_user_id,
                "assigned_user_name": names.get(row.assigned_user_id),
                "claimed_at": row.claimed_at,
                "closed_at": row.closed_at,
                "last_message_at": row.last_message_at,
                "created_at": row.created_at,
                "message_count": counts.get(key, 0),
                "title": _truncate(titles.get(key)),
                "contact_name": (
                    _person_name(contact) if contact is not None else None
                ),
                "contact_email": contact.email if contact is not None else None,
                "sentiment": insight.sentiment if insight is not None else None,
                "resolution": insight.resolution if insight is not None else None,
                "summary": insight.summary if insight is not None else None,
            }
        )
    return items


def list_conversations(
    db: Session,
    company_id: UUID,
    *,
    state: str | None = None,
    website_id: UUID | None = None,
    assigned_user_id: UUID | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[dict], int]:
    """One page of the company's inbox queue plus the matching total.

    `website_id` is checked against the caller's company first, so filtering by
    another tenant's website is a 404 rather than an empty page that confirms
    the id exists.
    """
    limit = max(1, min(limit, 100))
    page = max(1, page)

    query = (
        db.query(models.Conversation, models.Website.name)
        .join(models.Website, models.Website.id == models.Conversation.website_id)
        .filter(models.Website.company_id == company_id)
    )
    if state is not None:
        query = query.filter(models.Conversation.state == state)
    if website_id is not None:
        website = (
            db.query(models.Website)
            .filter(
                models.Website.id == website_id,
                models.Website.company_id == company_id,
            )
            .first()
        )
        if website is None:
            raise InboxNotFound("Website not found")
        query = query.filter(models.Conversation.website_id == website_id)
    if assigned_user_id is not None:
        query = query.filter(models.Conversation.assigned_user_id == assigned_user_id)

    total = query.count()
    rows = (
        query.order_by(
            models.Conversation.last_message_at.desc(),
            models.Conversation.id,
        )
        .limit(limit)
        .offset((page - 1) * limit)
        .all()
    )
    return _describe(db, rows), total


def transcript(db: Session, conversation: models.Conversation) -> list[dict]:
    """Every message of the conversation, oldest first, with author names."""
    rows = conversations.get_conversation_messages(
        db, conversation.website_id, conversation.session_id
    )
    names = _user_names(
        db, {row.author_user_id for row in rows if row.author_user_id}
    )
    return [
        {
            "id": row.id,
            "role": row.role,
            "message": row.message,
            "author_user_id": row.author_user_id,
            "author_name": names.get(row.author_user_id),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def contact_for(
    db: Session, conversation: models.Conversation
) -> models.Contact | None:
    """The lead the visitor left in this session, if any."""
    return (
        db.query(models.Contact)
        .filter(
            models.Contact.website_id == conversation.website_id,
            models.Contact.session_id == conversation.session_id,
        )
        .first()
    )


def detail(db: Session, company_id: UUID, conversation_id: UUID) -> dict:
    """One conversation: the list item plus its transcript and contact."""
    row = _require(db, company_id, conversation_id)
    website = (
        db.query(models.Website)
        .filter(models.Website.id == row.website_id)
        .first()
    )
    item = _describe(db, [(row, website.name if website is not None else None)])[0]
    contact = contact_for(db, row)
    item["messages"] = transcript(db, row)
    item["contact"] = (
        {
            "id": contact.id,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "email": contact.email,
            "consent_at": contact.consent_at,
            "created_at": contact.created_at,
        }
        if contact is not None
        else None
    )
    return item


def item_for(
    db: Session, company_id: UUID, conversation: models.Conversation
) -> dict:
    """The list item of one conversation (used as the action response)."""
    website = (
        db.query(models.Website)
        .filter(models.Website.id == conversation.website_id)
        .first()
    )
    if website is None or website.company_id != company_id:
        raise InboxNotFound("Conversation not found")
    return _describe(db, [(conversation, website.name)])[0]


# -- notifications, the event stream and presence (V3-42) -------------------
#
# One channel per company: an agent console only ever subscribes to its own
# company's notifications, so a conversation id from another tenant cannot leak
# through a broadcast. The SSE body is generated here rather than in the route
# so the framing, the heartbeat and the lease can be tested without HTTP.


def channel(company_id: UUID) -> str:
    """The pub/sub channel carrying one company's inbox notifications."""
    return f"inbox:{company_id}"


def _stamp(moment: datetime | None) -> str:
    """An ISO timestamp with a timezone, even for a naive SQLite value."""
    moment = moment or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def conversation_event(
    conversation: models.Conversation, event: str
) -> dict:
    """One notification for a state change that is already committed.

    The id comes from the row (`<uuid>:<updated_at>`), not from a fresh random
    value: publishing the same transition twice — a retry, or a client that
    reconnects — produces the same id, so the console can drop the duplicate.
    The rest of the payload is only a hint; the console re-reads the
    authoritative row, because a published notification can be lost or delayed.
    """
    stamp = _stamp(conversation.updated_at)
    return {
        "id": f"{conversation.id}:{stamp}",
        "type": "conversation",
        "event": event,
        "conversation_id": str(conversation.id),
        "website_id": str(conversation.website_id),
        "session_id": conversation.session_id,
        "state": conversation.state,
        "assigned_user_id": (
            str(conversation.assigned_user_id)
            if conversation.assigned_user_id is not None
            else None
        ),
        "at": stamp,
    }


def presence_event(user_id: UUID, event: str) -> dict:
    """An agent came online or went away (one of their tabs, anyway)."""
    stamp = _stamp(None)
    return {
        "id": f"presence:{user_id}:{stamp}",
        "type": "presence",
        "event": event,
        "user_id": str(user_id),
        "at": stamp,
    }


def sse(event: str, payload: dict) -> str:
    """One SSE frame. The `id:` line is what makes dedupe after reconnect work."""
    return (
        f"id: {payload.get('id', '')}\n"
        f"event: {event}\n"
        f"data: {json.dumps(payload)}\n\n"
    )


def forwarded(message: dict) -> str:
    """A published message as an SSE frame, falling back to raw data."""
    data = message.get("data")
    try:
        payload = json.loads(data)
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return f"event: conversation\ndata: {data}\n\n"
    return sse(payload.get("type") or "conversation", payload)


async def publish(company_id: UUID, payload: dict) -> bool:
    """Send one notification from async code (the stream's presence events).

    `redis.publish_event` reports failure instead of raising, so a Redis outage
    never turns a committed claim into a 500: the console's next poll shows the
    new state instead.
    """
    return await redis_service.publish_event(channel(company_id), payload)


def publish_after_commit(company_id: UUID, payload: dict) -> None:
    """Queue one notification for this company and return immediately.

    Call this **after** the service committed: the event describes a state the
    database already holds, and the console re-reads that state anyway. The
    action routes are sync because a claim runs a `FOR UPDATE` transaction,
    which must not hold the event loop (and every open SSE stream) while the
    database answers; `redis.enqueue_publish` drains the queue on its own
    thread, so a slow or dead Redis cannot delay or fail a claim.
    """
    redis_service.enqueue_publish(channel(company_id), payload)


def presence_key(company_id: UUID, user_id: UUID, lease_id: str) -> str:
    """One lease per connection — the lease id is what keeps two tabs apart."""
    return f"inbox:presence:{company_id}:{user_id}:{lease_id}"


def presence_pattern(company_id: UUID) -> str:
    """Every live lease of one company."""
    return f"inbox:presence:{company_id}:*"


def _presence_user(key: str) -> UUID | None:
    """The user id out of `inbox:presence:<company>:<user>:<lease>`."""
    parts = key.split(":")
    if len(parts) != 5 or parts[0] != "inbox" or parts[1] != "presence":
        return None
    try:
        return UUID(parts[3])
    except ValueError:
        return None


async def presence(db: Session, company_id: UUID) -> list[dict]:
    """Who is watching this inbox right now, one entry per agent.

    Leases are counted, not de-duplicated: two tabs are two connections, which
    is what the console shows beside the name. Because each connection owns its
    own key, one tab leaving only removes its own lease — the agent stays online
    while any other tab's lease survives. A Redis outage reads as "nobody
    online" rather than failing the console: presence is decoration, the queue
    is not.
    """
    keys = await redis_service.lease_keys(presence_pattern(company_id))
    counts: dict[UUID, int] = {}
    # `SCAN` can hand the same key back twice while the keyspace changes, and a
    # repeated key would count one tab as two connections.
    for key in set(keys):
        user_id = _presence_user(key)
        if user_id is not None:
            counts[user_id] = counts.get(user_id, 0) + 1
    names = _user_names(db, set(counts))
    return [
        {"user_id": user_id, "name": names.get(user_id), "connections": count}
        for user_id, count in sorted(counts.items(), key=lambda item: str(item[0]))
    ]


async def event_stream(
    company_id: UUID,
    user_id: UUID,
    *,
    disconnect: Callable[[], Awaitable[bool]] | None = None,
    heartbeat_seconds: int | None = None,
    lease_ttl_seconds: int | None = None,
    lease_id: str | None = None,
) -> AsyncIterator[str]:
    """The SSE body of `GET /api/inbox/events`.

    A `fetch()` stream, not `EventSource`: the console authenticates with the
    same `Authorization` header as every other admin call, and `EventSource`
    cannot send one. The route has already checked the flag and that Redis
    answers; this generator starts with a `retry:` hint and a `ready` event that
    tells the client to reconcile from the database, then forwards notifications
    as they are published.

    The socket read is one long-lived task raced against a sleep, instead of a
    read timeout: a timeout can leave the pub/sub parser mid-frame, while a
    pending read keeps the connection intact and a heartbeat comment goes out on
    every quiet tick. A dying Redis ends the stream with an `error` frame so the
    browser falls back to polling instead of waiting forever, and the lease is
    renewed on each tick and deleted when the connection ends (the TTL covers a
    connection that ends without running its cleanup).
    """
    heartbeat = max(1, heartbeat_seconds or INBOX_STREAM_HEARTBEAT_SECONDS)
    ttl = max(heartbeat * 2, lease_ttl_seconds or INBOX_PRESENCE_TTL_SECONDS)
    lease = lease_id or uuid4().hex
    key = presence_key(company_id, user_id, lease)

    if not await redis_service.set_lease(
        key, {"user_id": str(user_id), "connected_at": _stamp(None)}, ttl
    ):
        # Redis went away between the route's ping and this lease. Do not hang
        # the browser on a stream that cannot receive anything.
        yield sse(
            "error",
            {
                "id": f"error:{uuid4().hex}",
                "type": "error",
                "event": "redis_unavailable",
                "at": _stamp(None),
            },
        )
        return

    # Everything after the lease lives inside the `try`: a client that
    # disconnects right after connecting must still have its own lease removed.
    # The TTL covers the process dying mid-stream, not the ordinary close.
    try:
        # Subscribe **before** the first frame: `ready` tells the client it is
        # attached, so anything published after it is delivered here instead of
        # falling into the gap between the handshake and the subscription (the
        # client still reconciles from the database, but a closed gap is fewer
        # refreshes).
        async with redis_service.subscribe(channel(company_id)) as pubsub:
            await publish(company_id, presence_event(user_id, "online"))
            yield "retry: 3000\n\n"
            yield sse(
                "ready",
                {
                    "id": f"ready:{lease}",
                    "type": "ready",
                    "event": "ready",
                    "resync": True,
                    "heartbeat_seconds": heartbeat,
                    "at": _stamp(None),
                },
            )

            reader = asyncio.ensure_future(
                pubsub.get_message(ignore_subscribe_messages=True)
            )
            try:
                while True:
                    done, _ = await asyncio.wait({reader}, timeout=heartbeat)
                    if disconnect is not None and await disconnect():
                        break
                    await redis_service.renew_lease(key, ttl)
                    if not done:
                        yield f": heartbeat {_stamp(None)}\n\n"
                        continue
                    try:
                        message = reader.result()
                    except Exception as e:  # noqa: BLE001 - end, client reconnects
                        yield sse(
                            "error",
                            {
                                "id": f"error:{uuid4().hex}",
                                "type": "error",
                                "event": "stream_interrupted",
                                "detail": str(e),
                                "at": _stamp(None),
                            },
                        )
                        break
                    reader = asyncio.ensure_future(
                        pubsub.get_message(ignore_subscribe_messages=True)
                    )
                    if message:
                        yield forwarded(message)
            finally:
                reader.cancel()
    finally:
        await redis_service.delete_lease(key)
        await publish(company_id, presence_event(user_id, "offline"))
