"""Retention purge (F9): delete visitor data older than a company's policy.

Nothing used to delete anything, so every transcript, rating, handoff request,
contact and digest row accumulated for ever — a privacy problem before it is a
storage one. A company sets `retention_days` (0 = keep for ever, the default) and
the worker purges once a day.

The rules this module holds:

* one cutoff, computed once, applied as `created_at < cutoff` — a row created
  exactly at the cutoff survives, so a dry run and the real run agree;
* only the company's own rows, via its websites (or `company_id` for
  `digest_log`), never a global delete;
* `dry_run=True` counts without deleting, so an owner can see what a policy would
  remove before trusting it;
* no cascade surprises: `chat_feedback.message_id` and `handoff_requests.contact_id`
  are `ON DELETE SET NULL`, so purging messages or contacts first is safe.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import false
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.services import company_settings

logger = logging.getLogger(__name__)

# A policy longer than ten years is a typo, not a policy; clamping keeps a bad
# row from making the purge a no-op that looks like it ran.
MAX_RETENTION_DAYS = 3650

# Rows deleted (and committed) per statement. A tenant with millions of old rows
# would otherwise hold one transaction — and its locks — for the whole delete,
# blocking writes and bloating the WAL. Small enough to stay short, large enough
# that a normal purge is one round trip.
RETENTION_BATCH_SIZE = 1000

# Tables scoped through the company's websites.
SCOPED_BY_WEBSITE: tuple[tuple[str, type], ...] = (
    ("chat_messages", models.ChatMessage),
    ("chat_feedback", models.ChatFeedback),
    ("handoff_requests", models.HandoffRequest),
    ("contacts", models.Contact),
)

# Tables that carry `company_id` directly.
SCOPED_BY_COMPANY: tuple[tuple[str, type], ...] = (("digest_log", models.DigestLog),)


def parse_retention_days(raw: str | int | None) -> int:
    """Setting value → days. Anything unusable means "keep for ever" (0)."""
    if raw is None or raw == "":
        return 0
    try:
        days = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    return min(days, MAX_RETENTION_DAYS)


def cutoff_for(days: int, now: datetime | None = None) -> datetime | None:
    """The boundary itself: rows strictly older than this are purged."""
    if days <= 0:
        return None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - timedelta(days=days)


def company_retention_days(db: Session, company_id: UUID) -> int:
    return parse_retention_days(
        company_settings.value(db, company_id, "retention_days", "0")
    )


def _delete_batch(
    db: Session,
    model,
    filters: list,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Count what matches (dry run) or delete it a bounded batch at a time.

    Each batch is selected by id and deleted by id, then committed: a tenant with
    millions of expired rows never holds one long transaction. Postgres has no
    `DELETE ... LIMIT`, so the id round-trip is how a batch is scoped.
    """
    query = db.query(model).filter(*filters)
    if dry_run:
        return query.count()

    deleted = 0
    while True:
        ids = [
            row_id
            for (row_id,) in db.query(model.id)
            .filter(*filters)
            .order_by(model.created_at.asc())
            .limit(batch_size)
            .all()
        ]
        if not ids:
            break
        deleted += (
            db.query(model)
            .filter(model.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        if len(ids) < batch_size:
            break
    return deleted


def purge_company(
    db: Session,
    company_id: UUID,
    days: int | None = None,
    dry_run: bool = True,
    now: datetime | None = None,
    batch_size: int = RETENTION_BATCH_SIZE,
) -> dict:
    """Delete (or count) this company's rows older than `days`.

    Returns `deleted` per table — the count of matching rows in a dry run, and the
    number actually deleted otherwise. A company with no rows or a policy of 0
    returns zeroes rather than an error: this runs unattended every day.
    """
    if days is None:
        days = company_retention_days(db, company_id)
    batch_size = max(1, int(batch_size or 0))
    cutoff = cutoff_for(days, now)
    deleted: dict[str, int] = {name: 0 for name, _ in SCOPED_BY_WEBSITE + SCOPED_BY_COMPANY}

    if cutoff is not None:
        website_ids = [
            website_id
            for (website_id,) in db.query(models.Website.id)
            .filter(models.Website.company_id == company_id)
            .all()
        ]
        for name, model in SCOPED_BY_WEBSITE:
            filters = [model.created_at < cutoff]
            if website_ids:
                filters.append(model.website_id.in_(website_ids))
            else:
                # No websites means no rows in these tables; an empty `IN ()`
                # would still be a query, so short-circuit instead.
                filters.append(false())
            deleted[name] = _delete_batch(db, model, filters, batch_size, dry_run)

        for name, model in SCOPED_BY_COMPANY:
            filters = [model.company_id == company_id, model.created_at < cutoff]
            deleted[name] = _delete_batch(db, model, filters, batch_size, dry_run)

        if not dry_run:
            logger.info(
                "retention purge for company %s: %s (cutoff %s)",
                company_id,
                deleted,
                cutoff.isoformat(),
            )

    return {
        "retention_days": days,
        "cutoff": cutoff,
        "dry_run": dry_run,
        "deleted": deleted,
        "total": sum(deleted.values()),
    }


def companies_with_policy(db: Session) -> list[UUID]:
    """Companies that set `retention_days` above zero (the purge targets)."""
    rows = (
        db.query(models.Setting.company_id, models.Setting.value)
        .filter(models.Setting.key == "retention_days")
        .all()
    )
    return [
        company_id
        for company_id, value in rows
        if parse_retention_days(value) > 0
    ]
