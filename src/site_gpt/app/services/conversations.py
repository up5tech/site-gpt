"""Conversation history helpers.

A conversation has two layers. The messages (`chat_messages`, grouped by
`session_id`) are the transcript and exist for every session ever recorded; the
`conversations` row (M9) is the inbox state — who owns the session, whether an
agent is answering, when it was last touched. The row is created **lazily**, the
first time a session writes a message, so nothing is backfilled and every helper
here still works for a session that has no row.

The state machine is deliberately small and lives in one place:

* `bot → waiting`   — the visitor asks for a human (`api/handoff.py`).
* `waiting → human` — an agent claims it (V3-41).
* `human → waiting` — the agent releases it; it goes back to the queue.
* `human → closed`  — the agent closes it.
* `closed → bot`    — a later visitor message starts a new exchange, so a closed
  session is not permanently silenced.
* `closed → waiting` — the visitor asks for a human again.

Keeping creation here (and not in a route) is what stops a second copy of the
"get or create" race: the unique `(website_id, session_id)` is the real lock, and
this module is the only place that knows how to lose it gracefully.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import distinct, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from site_gpt.app import models

# How long a conversation title may be before we truncate it for display.
TITLE_MAX_LEN = 80

# Inbox states, in the order a session moves through them.
STATE_BOT = "bot"
STATE_WAITING = "waiting"
STATE_HUMAN = "human"
STATE_CLOSED = "closed"
STATES = (STATE_BOT, STATE_WAITING, STATE_HUMAN, STATE_CLOSED)

# Which state a message may move a conversation out of. Anything not listed is
# an invalid transition and raises rather than silently corrupting the queue.
TRANSITIONS: dict[str, set[str]] = {
    STATE_BOT: {STATE_WAITING},
    STATE_WAITING: {STATE_HUMAN, STATE_CLOSED},
    STATE_HUMAN: {STATE_WAITING, STATE_CLOSED},
    # A closed session is reopened by the visitor, not by an agent.
    STATE_CLOSED: {STATE_BOT, STATE_WAITING},
}


class ConversationStateError(ValueError):
    """An inbox transition that the state machine does not allow."""


def _now(when: datetime | None = None) -> datetime:
    moment = when or datetime.now(UTC)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def conversation_for(
    db: Session, website_id: UUID, session_id: str
) -> models.Conversation | None:
    """The inbox row of one session, or None when it was never created."""
    return (
        db.query(models.Conversation)
        .filter(
            models.Conversation.website_id == website_id,
            models.Conversation.session_id == session_id,
        )
        .first()
    )


def ensure_conversation(
    db: Session,
    website_id: UUID,
    session_id: str,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """Get or lazily create the session's inbox row. Never raises on a race.

    Two tabs writing their first message at the same moment both pass the
    "no row yet" read. The insert runs in a SAVEPOINT, so losing that race costs
    only the savepoint — the caller's pending message is untouched — and the
    winner's row is returned.
    """
    row = conversation_for(db, website_id, session_id)
    if row is not None:
        return row

    moment = _now(when)
    row = models.Conversation(
        website_id=website_id,
        session_id=session_id,
        state=STATE_BOT,
        last_message_at=moment,
        created_at=moment,
        updated_at=moment,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        row = conversation_for(db, website_id, session_id)
        if row is None:
            raise
    return row


def set_state(
    db: Session,
    conversation: models.Conversation,
    state: str,
    *,
    user_id: UUID | None = None,
    when: datetime | None = None,
) -> models.Conversation:
    """Move a conversation to `state`, enforcing the transition table.

    `user_id` is the agent taking ownership; it is cleared automatically when the
    session leaves `human`, so a released or closed session never keeps a stale
    assignee. Callers commit.
    """
    if state not in STATES:
        raise ConversationStateError(f"unknown conversation state: {state}")
    if state == conversation.state:
        return conversation
    if state not in TRANSITIONS.get(conversation.state, set()):
        raise ConversationStateError(
            f"cannot move a conversation from {conversation.state} to {state}"
        )

    moment = _now(when)
    conversation.state = state
    if state == STATE_HUMAN:
        conversation.assigned_user_id = user_id
        conversation.claimed_at = moment
        conversation.closed_at = None
    else:
        conversation.assigned_user_id = None
        conversation.claimed_at = None
        if state == STATE_CLOSED:
            conversation.closed_at = moment
        else:
            conversation.closed_at = None
    conversation.updated_at = moment
    db.flush()
    return conversation


def mark_waiting(
    db: Session,
    website_id: UUID,
    session_id: str,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """The visitor asked for a human: bot → waiting (idempotent while queued).

    A session already queued or already answered by an agent is left alone — a
    second click must not push a claimed conversation back into the queue.
    """
    conversation = ensure_conversation(db, website_id, session_id, when=when)
    if conversation.state in (STATE_WAITING, STATE_HUMAN):
        return conversation
    return set_state(db, conversation, STATE_WAITING, when=when)


def claim(
    db: Session,
    conversation: models.Conversation,
    user_id: UUID,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """An agent takes the session: waiting → human."""
    return set_state(db, conversation, STATE_HUMAN, user_id=user_id, when=when)


def release(
    db: Session,
    conversation: models.Conversation,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """The agent gives the session back to the queue: human → waiting."""
    return set_state(db, conversation, STATE_WAITING, when=when)


def close(
    db: Session,
    conversation: models.Conversation,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """The agent finishes with the session: human → closed."""
    return set_state(db, conversation, STATE_CLOSED, when=when)


def note_message(
    db: Session,
    website_id: UUID,
    session_id: str,
    role: str,
    *,
    when: datetime | None = None,
) -> models.Conversation:
    """Record that a message was written in this session. Callers commit.

    Touches `last_message_at` (the retention and queue clock) and reopens a
    closed session when the visitor speaks again, because the bot should answer a
    new question instead of staying silent for ever. An agent message never
    changes the state on its own: ownership moves through `claim`/`release`/`close`.
    """
    conversation = ensure_conversation(db, website_id, session_id, when=when)
    moment = _now(when)
    conversation.last_message_at = moment
    conversation.updated_at = moment
    if role == "user" and conversation.state == STATE_CLOSED:
        set_state(db, conversation, STATE_BOT, when=moment)
    db.flush()
    return conversation


def _titles(db: Session, website_id: UUID, session_ids: list[str]) -> dict[str, str]:
    """First user message per session, used as the display title."""
    titles: dict[str, str] = {}
    if not session_ids:
        return titles
    first_msgs = (
        db.query(models.ChatMessage.session_id, models.ChatMessage.message)
        .filter(
            models.ChatMessage.website_id == website_id,
            models.ChatMessage.session_id.in_(session_ids),
            models.ChatMessage.role == "user",
        )
        .order_by(
            models.ChatMessage.session_id,
            models.ChatMessage.created_at.asc(),
        )
        .all()
    )
    for sid, msg in first_msgs:
        if sid not in titles:
            titles[sid] = msg
    return titles


def _inbox_rows(
    db: Session, website_id: UUID, session_ids: list[str]
) -> dict[str, models.Conversation]:
    """The inbox rows that happen to exist for these sessions (no creation)."""
    if not session_ids:
        return {}
    rows = (
        db.query(models.Conversation)
        .filter(
            models.Conversation.website_id == website_id,
            models.Conversation.session_id.in_(session_ids),
        )
        .all()
    )
    return {row.session_id: row for row in rows}


def list_conversations(
    db: Session, website_id: UUID, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    """Return (summaries, total) for a website's conversations.

    Each summary is one `session_id`: message count, first/last activity, and
    the first user message as a display title. The inbox fields are filled in
    from the `conversations` row when it exists and are `None` otherwise, so a
    session that predates M9 keeps listing exactly as it did.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    agg = (
        db.query(
            models.ChatMessage.session_id,
            func.count(models.ChatMessage.id).label("message_count"),
            func.min(models.ChatMessage.created_at).label("created_at"),
            func.max(models.ChatMessage.created_at).label("last_message_at"),
        )
        .filter(models.ChatMessage.website_id == website_id)
        .group_by(models.ChatMessage.session_id)
        .order_by(func.max(models.ChatMessage.created_at).desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    total = (
        db.query(func.count(distinct(models.ChatMessage.session_id)))
        .filter(models.ChatMessage.website_id == website_id)
        .scalar()
        or 0
    )

    session_ids = [row.session_id for row in agg]
    titles = _titles(db, website_id, session_ids)
    inbox = _inbox_rows(db, website_id, session_ids)

    summaries: list[dict] = []
    for row in agg:
        title = titles.get(row.session_id)
        if title and len(title) > TITLE_MAX_LEN:
            title = title[:TITLE_MAX_LEN] + "…"
        conversation = inbox.get(row.session_id)
        summaries.append(
            {
                "session_id": row.session_id,
                "website_id": website_id,
                "title": title,
                "message_count": row.message_count,
                "created_at": row.created_at,
                "last_message_at": row.last_message_at,
                "conversation_id": conversation.id if conversation else None,
                "state": conversation.state if conversation else None,
            }
        )

    return summaries, total


def get_conversation_messages(
    db: Session, website_id: UUID, session_id: str
) -> list[models.ChatMessage]:
    """All messages of one session, oldest first."""
    return (
        db.query(models.ChatMessage)
        .filter_by(website_id=website_id, session_id=session_id)
        .order_by(models.ChatMessage.created_at.asc())
        .all()
    )


def human_handling(db: Session, website_id: UUID, session_id: str) -> bool:
    """True while a teammate owns the session, so the bot must stay quiet.

    Only `human` silences the bot: a `waiting` session is queued but still
    unattended, so it keeps getting answers until an agent claims it. A closed
    session is reopened by the visitor's next message (`note_message`), which is
    how the bot takes over again after the agent is done.
    """
    row = conversation_for(db, website_id, session_id)
    return row is not None and row.state == STATE_HUMAN


def question_for_answer(
    db: Session, website_id: UUID, session_id: str, answer: models.ChatMessage
) -> models.ChatMessage | None:
    """The user message that prompted `answer` (F4).

    Resolved from stored rows, never from the client, so a rating can only ever
    train the question that was actually asked in that session.
    """
    return (
        db.query(models.ChatMessage)
        .filter(
            models.ChatMessage.website_id == website_id,
            models.ChatMessage.session_id == session_id,
            models.ChatMessage.role == "user",
            models.ChatMessage.created_at <= answer.created_at,
            models.ChatMessage.id != answer.id,
        )
        .order_by(models.ChatMessage.created_at.desc())
        .limit(1)
        .first()
    )


def delete_conversation(db: Session, website_id: UUID, session_id: str) -> int:
    """Delete every message of a session and its inbox row (one transaction).

    Returns the number of messages removed. The conversation row goes too: an
    inbox entry without a transcript would be a queue item an agent cannot read.
    """
    deleted = (
        db.query(models.ChatMessage)
        .filter_by(website_id=website_id, session_id=session_id)
        .delete()
    )
    db.query(models.Conversation).filter_by(
        website_id=website_id, session_id=session_id
    ).delete()
    db.commit()
    return deleted


def erase_session(db: Session, website_id: UUID, session_id: str) -> dict[str, int]:
    """Erase one session completely, in a single transaction (F9, D2).

    Everything the session left behind is deleted together — messages, the inbox
    row, feedback, handoff requests and the K4 session token — so an erasure can
    never half-succeed and leave a readable remainder. The caller (the privacy
    route) drops derived cluster windows separately, because those are keyed by
    company and week rather than by session.
    """
    filters = {
        "website_id": website_id,
        "session_id": session_id,
    }
    deleted = {
        "chat_messages": db.query(models.ChatMessage).filter_by(**filters).delete(),
        "chat_feedback": db.query(models.ChatFeedback).filter_by(**filters).delete(),
        "handoff_requests": db.query(models.HandoffRequest)
        .filter_by(**filters)
        .delete(),
        "session_tokens": db.query(models.SessionToken).filter_by(**filters).delete(),
        "conversations": db.query(models.Conversation).filter_by(**filters).delete(),
    }
    db.commit()
    return deleted


def list_recent_conversations(
    db: Session, company_id: UUID, limit: int = 10
) -> list[dict]:
    """Latest conversations across all of a company's websites.

    Aggregates `chat_messages` grouped by session_id (joined to the owning
    website for the name), newest activity first. Used by the Dashboard.
    """
    limit = max(1, min(limit, 50))

    sub = (
        db.query(
            models.ChatMessage.session_id,
            models.ChatMessage.website_id,
            func.count(models.ChatMessage.id).label("message_count"),
            func.max(models.ChatMessage.created_at).label("last_message_at"),
        )
        .join(models.Website, models.Website.id == models.ChatMessage.website_id)
        .filter(models.Website.company_id == company_id)
        .group_by(
            models.ChatMessage.session_id,
            models.ChatMessage.website_id,
        )
        .subquery()
    )

    rows = (
        db.query(
            sub.c.session_id,
            sub.c.website_id,
            models.Website.name.label("website_name"),
            sub.c.message_count,
            sub.c.last_message_at,
        )
        .join(models.Website, models.Website.id == sub.c.website_id)
        .order_by(sub.c.last_message_at.desc())
        .limit(limit)
        .all()
    )

    session_ids = [r.session_id for r in rows]

    # First user message per session becomes the title.
    titles: dict[str, str] = {}
    if session_ids:
        first_msgs = (
            db.query(
                models.ChatMessage.session_id,
                models.ChatMessage.message,
            )
            .join(
                models.Website,
                models.Website.id == models.ChatMessage.website_id,
            )
            .filter(
                models.Website.company_id == company_id,
                models.ChatMessage.session_id.in_(session_ids),
                models.ChatMessage.role == "user",
            )
            .order_by(
                models.ChatMessage.session_id,
                models.ChatMessage.created_at.asc(),
            )
            .all()
        )
        for sid, msg in first_msgs:
            if sid not in titles:
                titles[sid] = msg

    result: list[dict] = []
    for r in rows:
        title = titles.get(r.session_id)
        if title and len(title) > TITLE_MAX_LEN:
            title = title[:TITLE_MAX_LEN] + "…"
        result.append(
            {
                "session_id": r.session_id,
                "website_id": r.website_id,
                "website_name": r.website_name,
                "title": title,
                "message_count": r.message_count,
                "last_message_at": r.last_message_at,
            }
        )

    return result
