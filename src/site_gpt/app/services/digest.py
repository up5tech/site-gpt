"""Weekly digest and analytics (F6).

Every number is company-scoped through `Website` and computed with plain SQL
plus `collections.Counter`: no LLM call and no new dependency, so the same week
always produces the same report and a preview is cheap enough to render on
demand.

Delivery is at-most-once. The `digest_log` row is inserted *before* the email is
sent (with `sent_at` NULL); a crash, a retry or a second worker therefore finds
the claim and sends nothing, and only the claiming worker stamps `sent_at`. A
claim that is still unsent after the stale window belongs to a dead worker and
can be taken over.

Named topic groups (V3 F2) are read back from `topic_clusters`, never computed
here: the worker already spent the embedding and naming calls, so rendering a
digest stays a pure database read. They are only reported when the requested
interval is exactly a whole number of digest weeks whose runs all completed;
otherwise the term counts stay the answer. See `_topic_groups`.
"""

import html
import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.config import FRONTEND_URL
from site_gpt.app.services import company_settings
from site_gpt.app.services.integrations import emit_event_async
from site_gpt.app.services.mail import send_email_async

logger = logging.getLogger(__name__)

TOPIC_LIMIT = 10
UNANSWERED_LIMIT = 10
TOPIC_MIN_LENGTH = 3

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Short English function words carry no topic signal. The list is deliberately
# small: a longer one would start hiding real terms, and this is not a search
# index.
STOPWORDS = frozenset(
    """
    a about after again all also am an and any are as at be been before being
    both but by can could did do does doing done down each few for from further
    get got had has have having he her here hers him his how i if in into is it
    its just me more most my no nor not now of off on once only or other our out
    over own same she should so some such than that the their them then there
    these they this those through to too under until up us very was we were what
    when where which while who whom why will with would you your yours
    """.split()
)

WORD_RE = re.compile(r"\w+", re.UNICODE)


def normalize_period(
    now: datetime, digest_day: str = "monday"
) -> tuple[datetime, datetime]:
    """The current digest week as `[start, end)` in UTC (D3).

    `start` is `digest_day` 00:00 UTC of the week containing `now`. Both the
    scheduler and `send-now` normalise through this function, so the same week
    always yields the same `period_start` — `digest_log`'s unique constraint
    depends on it, and a rolling `now - 7 days` would never match twice.
    """
    day = str(digest_day or "monday").strip().lower()
    target = WEEKDAYS.index(day) if day in WEEKDAYS else 0
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    midnight = current.astimezone(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = midnight - timedelta(days=(midnight.weekday() - target) % 7)
    return start, start + timedelta(days=7)


def previous_period(
    now: datetime, digest_day: str = "monday"
) -> tuple[datetime, datetime]:
    """The last complete digest week before the one containing `now`.

    A digest describes a week that is over. The topic worker clusters exactly this
    window (`topics.previous_window` delegates here), so the report and the named
    groups it shows never describe different weeks. The week still in progress is
    not a digest period: `digest_log` marks a period sent once, so mailing a
    half-finished week would leave the rest of it permanently unreported — and the
    window could not have a completed clustering run either.
    """
    current_start, _ = normalize_period(now, digest_day)
    return current_start - timedelta(days=7), current_start


def company_name(db: Session, company_id: UUID) -> str:
    """The company's display name, used in the subject and heading."""
    company = (
        db.query(models.Company).filter(models.Company.id == company_id).first()
    )
    return company.name if company is not None else ""


def _period_messages(
    db: Session, company_id: UUID, start: datetime, end: datetime
) -> list[models.ChatMessage]:
    """Every message of the period, oldest first, company-scoped."""
    return (
        db.query(models.ChatMessage)
        .join(models.Website, models.Website.id == models.ChatMessage.website_id)
        .filter(
            models.Website.company_id == company_id,
            models.ChatMessage.created_at >= start,
            models.ChatMessage.created_at < end,
        )
        .order_by(models.ChatMessage.created_at.asc())
        .all()
    )


def _count_feedback(
    db: Session, company_id: UUID, rating: str, start: datetime, end: datetime
) -> int:
    return (
        db.query(models.ChatFeedback)
        .join(models.Website, models.Website.id == models.ChatFeedback.website_id)
        .filter(
            models.Website.company_id == company_id,
            models.ChatFeedback.rating == rating,
            models.ChatFeedback.created_at >= start,
            models.ChatFeedback.created_at < end,
        )
        .count()
    )


def _topics(messages: list[models.ChatMessage]) -> list[dict]:
    """Most frequent words across the period's visitor questions."""
    counter: Counter[str] = Counter()
    for message in messages:
        if message.role != "user":
            continue
        for word in WORD_RE.findall((message.message or "").lower()):
            if len(word) < TOPIC_MIN_LENGTH or word.isdigit():
                continue
            if word in STOPWORDS:
                continue
            counter[word] += 1
    return [
        {"term": term, "count": count}
        for term, count in counter.most_common(TOPIC_LIMIT)
    ]


def _topic_groups(
    db: Session, company_id: UUID, start: datetime, end: datetime
) -> list[dict] | None:
    """Named clusters for `[start, end)`, or None when it is not exactly covered.

    `topics.completed_windows` is the whole gate: it returns None unless the
    interval is a whole number of digest-aligned weeks and every window has a
    `completed` run, which is also what keeps a rolling `/analytics` window on the
    term-count fallback instead of presenting a partly-built period as whole. The
    feature is opt-in per company, so the flag is checked before any cluster read.
    """
    if not company_settings.flag(db, company_id, "topic_clustering_enabled"):
        return None
    # Imported here because `topics` reads this module (stopwords, normalize_period).
    from site_gpt.app.services import topics

    windows = topics.completed_windows(db, company_id, start, end)
    if windows is None:
        return None
    return [
        {
            "label": cluster.label,
            "summary": cluster.summary,
            "period_start": window_start.isoformat(),
            # Window-level counts, repeated on every row by the writer: they say
            # how much of the week's questions the groups were built from.
            "sampled_messages": cluster.sampled_messages,
            "eligible_messages": cluster.eligible_messages,
        }
        for window_start, clusters in windows
        for cluster in clusters
    ]


def _unanswered(
    messages: list[models.ChatMessage], websites: dict[str, str]
) -> list[dict]:
    """Questions whose answer was tagged `answered = False`, newest first."""
    by_session: dict[str, list[models.ChatMessage]] = {}
    for message in messages:
        by_session.setdefault(message.session_id, []).append(message)

    found: list[dict] = []
    for message in messages:
        if message.role != "assistant" or message.answered is not False:
            continue
        question = None
        for candidate in reversed(by_session.get(message.session_id, [])):
            if candidate.role == "user" and candidate.created_at <= message.created_at:
                question = candidate.message
                break
        website_id = str(message.website_id)
        found.append(
            {
                "question": question,
                "website_id": website_id,
                "website_name": websites.get(website_id),
                "session_id": message.session_id,
                "asked_at": message.created_at.isoformat(),
                # Deep link straight into the transcript (D1/D2 of the plan).
                "link": f"{FRONTEND_URL}?website={website_id}&focus={message.session_id}",
            }
        )
    return list(reversed(found[-UNANSWERED_LIMIT:]))


def build_digest(
    db: Session, company_id: UUID, start: datetime, end: datetime
) -> dict:
    """The digest payload for one company and one period."""
    websites = {
        str(website_id): name
        for website_id, name in db.query(
            models.Website.id, models.Website.name
        )
        .filter(models.Website.company_id == company_id)
        .all()
    }

    messages = _period_messages(db, company_id, start, end)
    new_contacts = (
        db.query(models.Contact)
        .join(models.Website, models.Website.id == models.Contact.website_id)
        .filter(
            models.Website.company_id == company_id,
            models.Contact.created_at >= start,
            models.Contact.created_at < end,
        )
        .count()
    )

    payload = {
        "company_id": str(company_id),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "conversation_volume": len({m.session_id for m in messages}),
        "message_count": len(messages),
        "new_contacts": new_contacts,
        "feedback_up": _count_feedback(db, company_id, "up", start, end),
        "feedback_down": _count_feedback(db, company_id, "down", start, end),
        "top_topics": _topics(messages),
        "unanswered_questions": _unanswered(messages, websites),
    }

    # Added only for an exactly covered interval, so with the feature off (its
    # default) the payload is the V2.1 one key for key. `top_topics` stays either
    # way: `/api/v1` clients keep reading the fields they already know.
    groups = _topic_groups(db, company_id, start, end)
    if groups is not None:
        payload["topic_groups"] = groups
    return payload


def render_digest_html(data: dict, company_name: str = "") -> str:
    """Plain f-string HTML: no templating dependency, previewable in a browser."""
    title = html.escape(company_name or "Weekly digest")
    start = str(data["period_start"])[:10]
    end = str(data["period_end"])[:10]

    terms = "".join(
        f"<li>{html.escape(str(topic['term']))} — {topic['count']}</li>"
        for topic in data["top_topics"]
    ) or "<li>No topics yet</li>"

    groups = data.get("topic_groups") or []
    if groups:
        # Window-level counts, so a truncated sample is disclosed rather than
        # presented as the week's total.
        sampled = max(int(group["sampled_messages"]) for group in groups)
        eligible = max(int(group["eligible_messages"]) for group in groups)
        topics_block = (
            "<h3>Topic groups</h3><ul>"
            + "".join(
                f"<li><strong>{html.escape(str(group['label']))}</strong>"
                + (
                    f" — {html.escape(str(group['summary']))}"
                    if group.get("summary")
                    else ""
                )
                + "</li>"
                for group in groups
            )
            + "</ul>"
            f'<p style="color:#555">Named from {sampled} of {eligible} '
            "visitor questions.</p>"
        )
    else:
        topics_block = "<h3>Top topics</h3><ul>" + terms + "</ul>"

    unanswered = "".join(
        "<li>"
        f"<a href=\"{html.escape(str(item['link']))}\">"
        f"{html.escape(str(item['question'] or item['session_id']))}</a>"
        f" <small>({html.escape(str(item['website_name'] or ''))})</small>"
        "</li>"
        for item in data["unanswered_questions"]
    ) or "<li>Every question was answered from your content</li>"

    return (
        "<!doctype html><html><body "
        'style="font-family:Arial,sans-serif;color:#111">'
        f"<h2>{title} — weekly digest</h2>"
        f'<p style="color:#555">{start} → {end}</p>'
        "<ul>"
        f"<li>Conversations: <strong>{data['conversation_volume']}</strong></li>"
        f"<li>Messages: <strong>{data['message_count']}</strong></li>"
        f"<li>New contacts: <strong>{data['new_contacts']}</strong></li>"
        f"<li>Feedback: 👍 {data['feedback_up']} / 👎 {data['feedback_down']}</li>"
        "</ul>"
        + topics_block
        + "<h3>Questions your content could not answer</h3><ul>"
        + unanswered
        + "</ul></body></html>"
    )


def recipients_for(db: Session, company_id: UUID) -> list[str]:
    """`digest_recipients`, or the company's active admins/managers."""
    return company_settings.emails(
        db, company_id, company_settings.value(db, company_id, "digest_recipients")
    ) or company_settings.team_emails(db, company_id)


def period_settled(
    db: Session, company_id: UUID, period_start: datetime, stale_before: datetime
) -> bool:
    """True when this period was sent, or is claimed by a live worker.

    The scheduler asks before enqueueing: a settled period needs no job, while a
    claim from a dead worker (no heartbeat since `stale_before`) does.
    """
    existing = (
        db.query(models.DigestLog)
        .filter(
            models.DigestLog.company_id == company_id,
            models.DigestLog.period_start == period_start,
        )
        .first()
    )
    if existing is None:
        return False
    if existing.sent_at is not None:
        return True
    heartbeat = existing.updated_at or existing.created_at
    if heartbeat is not None and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    return heartbeat is not None and heartbeat >= stale_before


def claim_period(
    db: Session,
    company_id: UUID,
    period_start: datetime,
    period_end: datetime,
    stale_before: datetime,
) -> models.DigestLog | None:
    """Claim this period for sending; None when someone else owns it.

    A claim is taken before the email goes out. The row already sent is a hard
    "no"; an unsent claim younger than `stale_before` belongs to a live worker;
    an older one belongs to a worker that died mid-send and is taken over here.
    """
    now = datetime.now(UTC)
    existing = (
        db.query(models.DigestLog)
        .filter(
            models.DigestLog.company_id == company_id,
            models.DigestLog.period_start == period_start,
        )
        .first()
    )
    if existing is None:
        row = models.DigestLog(
            company_id=company_id,
            period_start=period_start,
            period_end=period_end,
            sent_at=None,
            recipient_count=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    if existing.sent_at is not None:
        return None
    heartbeat = existing.updated_at or existing.created_at
    if heartbeat is not None and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    if heartbeat is not None and heartbeat >= stale_before:
        return None
    # Dead worker's claim: take it over rather than leaving the week unsent.
    existing.updated_at = now
    db.commit()
    db.refresh(existing)
    return existing


async def send_period(
    db: Session,
    company_id: UUID,
    period_start: datetime,
    period_end: datetime,
    stale_before: datetime,
) -> dict:
    """Claim, build, render and email one digest period.

    Returns `{"status": "sent" | "skipped" | "empty" | "failed", ...}`. A
    company with no activity releases its claim and sends nothing, so a quiet
    week never leaves a permanently-stuck row.
    """
    claim = claim_period(db, company_id, period_start, period_end, stale_before)
    if claim is None:
        return {
            "status": "skipped",
            "reason": "period already claimed or sent",
            "period_start": period_start.isoformat(),
        }

    data = build_digest(db, company_id, period_start, period_end)
    if (
        data["message_count"] == 0
        and data["new_contacts"] == 0
        and data["conversation_volume"] == 0
    ):
        db.delete(claim)
        db.commit()
        return {
            "status": "empty",
            "reason": "no activity in this period",
            "period_start": period_start.isoformat(),
        }

    recipients = recipients_for(db, company_id)
    if not recipients:
        db.delete(claim)
        db.commit()
        return {
            "status": "skipped",
            "reason": "no recipients configured",
            "period_start": period_start.isoformat(),
        }

    name = company_name(db, company_id)
    subject = (
        f"{name or 'Your'} weekly digest "
        f"({period_start.date().isoformat()})"
    )
    body = render_digest_html(data, name)

    sent = 0
    for recipient in recipients:
        try:
            await send_email_async(recipient, subject, body)
            sent += 1
        except Exception:
            logger.exception(
                "digest for company %s could not be sent to one recipient",
                company_id,
            )

    if sent == 0:
        # Nothing delivered: release the claim so the next tick can retry.
        db.delete(claim)
        db.commit()
        return {
            "status": "failed",
            "reason": "every send failed",
            "period_start": period_start.isoformat(),
        }

    claim.sent_at = datetime.now(UTC)
    claim.recipient_count = sent
    db.commit()

    # Integration hook (F7): the digest really went out, so the owner's tools can
    # announce it. Delivered after the claim is stamped, so a failure here can
    # neither resend nor break the send that already happened.
    await emit_event_async(
        db,
        company_id,
        "digest.generated",
        {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "recipients": sent,
            "conversation_volume": data["conversation_volume"],
            "message_count": data["message_count"],
            "new_contacts": data["new_contacts"],
        },
    )
    return {
        "status": "sent",
        "recipients": sent,
        "period_start": period_start.isoformat(),
    }
