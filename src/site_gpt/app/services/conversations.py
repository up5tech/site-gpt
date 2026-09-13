"""Conversation history helpers.

Conversations are NOT a separate table — they are groups of `chat_messages`
rows sharing the same `session_id` (see models.ChatMessage). These helpers
aggregate those rows into a browsable list and into per-session message feeds
so the admin panel and the embeddable widget can retrieve past chats.
"""

from uuid import UUID

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from site_gpt.app import models

# How long a conversation title may be before we truncate it for display.
TITLE_MAX_LEN = 80


def list_conversations(
    db: Session, website_id: UUID, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    """Return (summaries, total) for a website's conversations.

    Each summary is one `session_id`: message count, first/last activity, and
    the first user message as a display title.
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

    # First user message per session becomes the conversation title.
    titles: dict[str, str] = {}
    if session_ids:
        first_msgs = (
            db.query(
                models.ChatMessage.session_id,
                models.ChatMessage.message,
            )
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

    summaries: list[dict] = []
    for row in agg:
        title = titles.get(row.session_id)
        if title and len(title) > TITLE_MAX_LEN:
            title = title[:TITLE_MAX_LEN] + "…"
        summaries.append(
            {
                "session_id": row.session_id,
                "website_id": website_id,
                "title": title,
                "message_count": row.message_count,
                "created_at": row.created_at,
                "last_message_at": row.last_message_at,
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


def delete_conversation(db: Session, website_id: UUID, session_id: str) -> int:
    """Delete every message of a session. Returns number of rows removed."""
    deleted = (
        db.query(models.ChatMessage)
        .filter_by(website_id=website_id, session_id=session_id)
        .delete()
    )
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
