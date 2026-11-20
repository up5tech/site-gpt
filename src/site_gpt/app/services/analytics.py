"""Advanced analytics (V4 F1): daily trend, engagement funnel, top questions.

All three read data that already exists and share the weekly digest's
definitions, so the admin page, the upcoming CSV export and the email can never
disagree about the same window:

- the window's messages come from `digest._period_messages`, the same query (and
  the same `idx_chat_messages_website_id_created_at` range scan) `build_digest`
  runs;
- a conversation is one `session_id`, exactly what `build_digest` counts in
  `conversation_volume`;
- an answer is unanswered when it is a `role='assistant'` row with
  `answered is False` (`digest._unanswered`'s rule). `answered` is NULL for rows
  written before V2 and for a partial answer saved after a stream failure, and
  NULL is never "unanswered";
- a funnel session counts as `human` when its inbox row is `human` right now or
  was closed after being claimed — `closed_at` is only ever set from `human`. A
  released session goes back to `waiting` and leaves no marker, so it is no
  longer counted.

Nothing here calls a model, adds an index or edits `build_digest`: these are
plain company-scoped reads returning dicts, so the digest payload is untouched
and stays byte-identical (invariant 15).
"""

import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.services import digest

# D4: the top questions are an exact-match grouping, top 10, no embeddings.
TOP_QUESTION_LIMIT = 10

# D4/D7 funnel stages, in the order the chart draws them. Each is a count of
# distinct sessions, and the stages overlap rather than nest: a session can be a
# lead without a handoff, and a handoff without ever reaching a human.
FUNNEL_STAGES = ("started", "answered", "lead", "handoff", "human")
REPLY_ROLES = ("assistant", "agent")

WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)
# Trailing punctuation only: an apostrophe or `?` inside a question is part of it.
TRAILING_PUNCTUATION_RE = re.compile(
    r"[\s?!.,;:…\-–—\"'”’)\]}>»]+$", re.UNICODE
)


def normalize_question(text: str | None) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation (D4).

    Grouping then treats "How much does it cost?" and "how much does it cost"
    as one question without an embedding or an LLM call. A question that is
    only punctuation normalizes to "", which callers skip.
    """
    collapsed = WHITESPACE_RE.sub(" ", (text or "").strip().lower())
    return TRAILING_PUNCTUATION_RE.sub("", collapsed).strip()


def is_unanswered(message: models.ChatMessage) -> bool:
    """The digest's unanswered rule, spelled once for per-day counting.

    `digest._unanswered` selects `role='assistant'` rows whose `answered` is
    exactly `False`. `tests/test_analytics.py` pins this to the same messages the
    digest reports, so a change on one side cannot drift from the other.
    """
    return message.role == "assistant" and message.answered is False


def _utc_day(moment: datetime) -> date:
    """The UTC day of a stored timestamp (NULL timezone means UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).date()


def _created(
    db: Session,
    model,
    company_id: UUID,
    start: datetime,
    end: datetime,
    *columns,
):
    """`created_at` (plus extra columns) of one company's rows in `[start, end)`.

    One query per table, company-scoped through the `websites` join, so a foreign
    company id reads nothing of ours.
    """
    return (
        db.query(model.created_at, *columns)
        .join(models.Website, models.Website.id == model.website_id)
        .filter(
            models.Website.company_id == company_id,
            model.created_at >= start,
            model.created_at < end,
        )
        .all()
    )


def _sessions(
    db: Session, model, company_id: UUID, start: datetime, end: datetime
) -> set[str]:
    """Distinct sessions with one `model` row of this company in the window."""
    return {
        session_id
        for (session_id,) in db.query(model.session_id)
        .join(models.Website, models.Website.id == model.website_id)
        .filter(
            models.Website.company_id == company_id,
            model.created_at >= start,
            model.created_at < end,
        )
        .all()
    }


def daily_trend(
    db: Session, company_id: UUID, start: datetime, end: datetime
) -> list[dict]:
    """One row per UTC day in `[start, end)`, zeros included.

    `conversations` is the distinct-session count for that day, so a session that
    spans midnight counts on both days and the daily rows do not sum to the
    window's `conversation_volume` — the digest owns that number, this one shows
    activity. `unanswered` counts answers tagged `answered = False` that day (see
    `is_unanswered`); the last day is partial when `end` is "now".
    """
    start_day = _utc_day(start)
    # `end` is exclusive, so the last day with any second in the window is the
    # day before `end` — unless `end` is exactly midnight of the start day.
    last_day = _utc_day(end - timedelta(microseconds=1))

    days: dict[date, dict] = {}
    day = start_day
    while day <= last_day:
        days[day] = {
            "date": day.isoformat(),
            "conversations": set(),
            "messages": 0,
            "visitor_messages": 0,
            "new_contacts": 0,
            "feedback_up": 0,
            "feedback_down": 0,
            "unanswered": 0,
        }
        day += timedelta(days=1)

    for message in digest._period_messages(db, company_id, start, end):
        bucket = days.get(_utc_day(message.created_at))
        if bucket is None:
            continue
        bucket["messages"] += 1
        bucket["conversations"].add(message.session_id)
        if message.role == "user":
            bucket["visitor_messages"] += 1
        if is_unanswered(message):
            bucket["unanswered"] += 1

    for (created_at,) in _created(db, models.Contact, company_id, start, end):
        bucket = days.get(_utc_day(created_at))
        if bucket is not None:
            bucket["new_contacts"] += 1

    for created_at, rating in _created(
        db,
        models.ChatFeedback,
        company_id,
        start,
        end,
        models.ChatFeedback.rating,
    ):
        bucket = days.get(_utc_day(created_at))
        if bucket is not None and rating in ("up", "down"):
            bucket[f"feedback_{rating}"] += 1

    return [
        {**bucket, "conversations": len(bucket["conversations"])}
        for bucket in days.values()
    ]


def engagement_funnel(
    db: Session, company_id: UUID, start: datetime, end: datetime
) -> list[dict]:
    """The five D4 stages, each a count of distinct sessions in the window.

    `started` is the digest's `conversation_volume` rule applied to the window;
    `answered` adds every session with at least one bot **or** human reply, so an
    agent-answered conversation is not counted as unanswered traffic; `lead` is a
    contact created in the window; `handoff` a handoff request; `human` a
    conversation that reached the inbox's `human` state.
    """
    messages = digest._period_messages(db, company_id, start, end)

    human = {
        session_id
        for (session_id,) in db.query(models.Conversation.session_id)
        .join(models.Website, models.Website.id == models.Conversation.website_id)
        .filter(
            models.Website.company_id == company_id,
            models.Conversation.last_message_at >= start,
            models.Conversation.last_message_at < end,
            or_(
                models.Conversation.state == "human",
                models.Conversation.closed_at.isnot(None),
            ),
        )
        .all()
    }

    counts = {
        "started": {message.session_id for message in messages},
        "answered": {
            message.session_id
            for message in messages
            if message.role in REPLY_ROLES
        },
        "lead": _sessions(db, models.Contact, company_id, start, end),
        "handoff": _sessions(db, models.HandoffRequest, company_id, start, end),
        "human": human,
    }
    return [
        {"stage": stage, "sessions": len(counts[stage])} for stage in FUNNEL_STAGES
    ]


def top_questions(
    db: Session,
    company_id: UUID,
    start: datetime,
    end: datetime,
    limit: int = TOP_QUESTION_LIMIT,
) -> list[dict]:
    """The visitor questions asked most often, exact-match on `normalize_question`.

    Ordered by count, ties by first appearance (the window's messages come back
    oldest first), truncated to `limit` — deterministic for the same rows, with
    no embeddings and no LLM call.
    """
    counter: Counter[str] = Counter()
    for message in digest._period_messages(db, company_id, start, end):
        if message.role != "user":
            continue
        question = normalize_question(message.message)
        if not question:
            continue
        counter[question] += 1
    return [
        {"question": question, "count": count}
        for question, count in counter.most_common(max(0, int(limit)))
    ]
