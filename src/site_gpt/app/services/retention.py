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
* an imported document goes as a whole. Deleting only its `attachments` row would
  leave `extra_documents.content` and the `embeddings` built from it, so the
  assistant would keep answering from a file the policy says is gone — the exact
  failure this part exists to prevent. The document row, its embeddings and any
  remaining attachments are deleted with it, and the files unlinked after the
  commit.
* uploaded files go with their rows: an `attachments` row is the pointer to a file
  under `uploads/`, so deleting the row without the bytes would leave personal data
  on disk with nothing tracking it. The file is removed after the batch commits, and
  a missing or unremovable file never stops the purge.
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, false, or_, select
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

# Tables scoped through the company's websites. `conversations` is deliberately
# not here: it expires on `last_message_at` rather than `created_at`, because the
# metadata must not outlive the messages that make the session readable (see
# `purge_company`).
SCOPED_BY_WEBSITE: tuple[tuple[str, type], ...] = (
    ("chat_messages", models.ChatMessage),
    ("chat_feedback", models.ChatFeedback),
    ("handoff_requests", models.HandoffRequest),
    ("contacts", models.Contact),
)

# Tables that carry `company_id` directly.
SCOPED_BY_COMPANY: tuple[tuple[str, type], ...] = (
    ("digest_log", models.DigestLog),
    # Topic clusters are derived from messages in the same windows, so they expire
    # on the same clock. Keeping the labels of deleted questions would keep a
    # trace of text the policy removed; the run row goes with them so the worker
    # can rebuild the window instead of treating it as done.
    ("topic_clusters", models.TopicCluster),
    ("topic_cluster_runs", models.TopicClusterRun),
)

# Where uploaded bytes live. Matches `api/upload.py` and `worker.py`, which both
# build `uploads/<attachment.file_url>`: one constant here stays honest because the
# other two would have to change together anyway.
UPLOAD_ROOT = "uploads"


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


def batch_ids(db: Session, model, filters: list, batch_size: int) -> list:
    """The next batch of ids, oldest first. Postgres has no `DELETE ... LIMIT`."""
    return [
        row_id
        for (row_id,) in db.query(model.id)
        .filter(*filters)
        .order_by(model.created_at.asc())
        .limit(batch_size)
        .all()
    ]


def delete_in_batches(
    db: Session,
    model,
    filters: list,
    batch_size: int,
    dry_run: bool = False,
) -> int:
    """Count what matches (dry run) or delete it a bounded batch at a time.

    Each batch is selected by id and deleted by id, then committed: a table with
    millions of expired rows never holds one long transaction. Shared with the
    delivery retention pass, so the two purges cannot drift into one unbounded
    statement each.
    """
    query = db.query(model).filter(*filters)
    if dry_run:
        return query.count()

    deleted = 0
    while True:
        ids = batch_ids(db, model, filters, batch_size)
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


def _attachment_scope(db: Session, company_id: UUID, cutoff: datetime):
    """This company's attachments older than the cutoff.

    An attachment has no tenant of its own: it belongs to an `extra_documents` row
    (the normal case) or, for an upload that was never attached, to the user who
    uploaded it. Both paths are company-scoped here; a row with neither is left
    alone rather than guessed at.

    Uploads belong to their document, not to their own timestamp: a document kept
    alive by a file attached today keeps the files it already had, because deleting
    half of a document the owner is still using leaves the text of the deleted
    files behind with nothing pointing at them. Standalone uploads (no document)
    still expire by their own `created_at`.

    The tenant is a semijoin, not an outer join plus a filter. With the outer join
    the tenant predicate cannot be applied on the index and the hash of the whole
    `extra_documents` table is built before the `LIMIT` can stop anything (measured
    on 120k documents: a 120k-row hash, 13k buffers, 19 ms); as a semijoin the
    planner walks the tenant's own ids through the indexes (12k buffers, 3.3 ms).
    """
    expired, _ = document_expiry(db, cutoff)
    # One semijoin carries both the tenant and the document's fate: an attachment is
    # in scope when it belongs to an *expired* document of this company. Keeping the
    # expiry out of the outer filter matters — as a per-row EXISTS over the joined
    # document the planner materialises the whole table before it can apply the
    # `LIMIT`, and a hash of every document and upload is exactly the cost this
    # shape exists to avoid.
    company_documents = select(models.ExtraDocument.id).where(
        models.ExtraDocument.company_id == company_id, expired
    )
    company_users = select(models.User.id).where(
        models.User.company_id == company_id
    )
    return db.query(models.Attachment).filter(
        models.Attachment.created_at < cutoff,
        # Belongs to this company, through the document or through the uploader.
        or_(
            models.Attachment.extra_document_id.in_(company_documents),
            models.Attachment.user_id.in_(company_users),
        ),
    )


def document_expiry(
    db: Session,
    cutoff: datetime,
    document=models.ExtraDocument,
    attachment=models.Attachment,
):
    """The two SQL conditions that decide a document's fate, in one place.

    ``expired`` is what the document purge deletes; ``live`` is the opposite, and the
    attachment purge uses it to leave a live document's files to that document.
    Computing them together is the point: "a document is in use" must mean the same
    thing on both paths, or one would delete files the other considers current.

    A document is live when it was created inside the window, or when something was
    attached to it inside the window — re-using an old document today is current
    use. A document nobody attached anything to has no such upload, so it expires by
    its own date.

    `expired` keeps `created_at < cutoff` as a plain conjunct so the planner can use
    `idx_extra_documents_company_id_created_at` rather than wrapping it in a `NOT`.
    """
    fresh_upload = (
        db.query(attachment.id)
        .filter(
            attachment.extra_document_id == document.id,
            attachment.created_at >= cutoff,
        )
        .exists()
    )
    expired = and_(document.created_at < cutoff, ~fresh_upload)
    live = or_(document.created_at >= cutoff, fresh_upload)
    return expired, live


def _remove_upload_file(file_url: str | None) -> bool:
    """Delete the bytes behind an attachment row. Never raises.

    `file_url` comes from the database, but it is still validated: a row holding
    `../` must not let a purge delete outside `uploads/`.
    """
    if not file_url:
        return False
    root = os.path.normpath(UPLOAD_ROOT)
    path = os.path.normpath(os.path.join(root, file_url))
    if not path.startswith(root + os.sep):
        logger.warning("refusing to delete a file outside %s/: %s", root, file_url)
        return False
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        # A stuck file must not stop the database purge.
        logger.warning("could not delete upload %s: %s", path, exc)
        return False


def purge_attachments(
    db: Session,
    company_id: UUID,
    cutoff: datetime,
    batch_size: int = RETENTION_BATCH_SIZE,
    dry_run: bool = False,
) -> int:
    """Delete (or count) this company's expired uploads and their files."""
    base = _attachment_scope(db, company_id, cutoff)
    if dry_run:
        return base.count()

    deleted = 0
    while True:
        rows = (
            base.with_entities(models.Attachment.id, models.Attachment.file_url)
            .order_by(models.Attachment.created_at.asc())
            .limit(batch_size)
            .all()
        )
        if not rows:
            break
        ids = [row[0] for row in rows]
        db.query(models.Attachment).filter(models.Attachment.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        # After the commit, never before: a failed commit must not leave rows
        # pointing at files that are already gone.
        for _, file_url in rows:
            _remove_upload_file(file_url)
        deleted += len(ids)
        if len(rows) < batch_size:
            break
    return deleted


def purge_documents(
    db: Session,
    company_id: UUID,
    cutoff: datetime,
    batch_size: int = RETENTION_BATCH_SIZE,
    dry_run: bool = False,
) -> int:
    """Delete (or count) this company's expired imported documents.

    An `extra_documents` row is the document itself: its text is what the assistant
    searches, so removing only the file would leave the answers in place. The
    embeddings and any remaining attachments are deleted explicitly rather than
    relying on the database cascade, so the behaviour is the same on every engine
    (and visible in the tests).

    The document's age alone is the wrong test: adding a file today to a document
    imported 40 days ago is current use of it, and deleting that fresh upload (and
    the embeddings rebuilt from it) would destroy work the owner just did. A
    document therefore expires only when it is past the cutoff **and** nothing was
    attached to it at or after the cutoff. A document nobody attached anything to
    has no such attachment, so a text-only document still expires by its own date.
    """
    expired, _ = document_expiry(db, cutoff)
    filters = [models.ExtraDocument.company_id == company_id, expired]
    if dry_run:
        return db.query(models.ExtraDocument).filter(*filters).count()

    deleted = 0
    while True:
        ids = batch_ids(db, models.ExtraDocument, filters, batch_size)
        if not ids:
            break
        file_urls = [
            file_url
            for (file_url,) in db.query(models.Attachment.file_url)
            .filter(models.Attachment.extra_document_id.in_(ids))
            .all()
        ]
        db.query(models.Embedding).filter(
            models.Embedding.extra_document_id.in_(ids)
        ).delete(synchronize_session=False)
        db.query(models.Attachment).filter(
            models.Attachment.extra_document_id.in_(ids)
        ).delete(synchronize_session=False)
        deleted += (
            db.query(models.ExtraDocument)
            .filter(models.ExtraDocument.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        # After the commit, never before: a rollback must not leave rows pointing
        # at bytes that are already gone.
        for file_url in file_urls:
            _remove_upload_file(file_url)
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
    deleted: dict[str, int] = {
        name: 0 for name, _ in SCOPED_BY_WEBSITE + SCOPED_BY_COMPANY
    }
    deleted["conversations"] = 0
    deleted["attachments"] = 0
    deleted["extra_documents"] = 0

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
            deleted[name] = delete_in_batches(
                db, model, filters, batch_size, dry_run
            )

        # Inbox metadata goes when its **newest** message is past the cutoff: the
        # messages above are deleted by message age, so at that point the session
        # has no transcript left to read. A conversation with a fresh message
        # keeps its state and assignee, whichever way its `created_at` falls.
        conversation_filters = [models.Conversation.last_message_at < cutoff]
        if website_ids:
            conversation_filters.append(
                models.Conversation.website_id.in_(website_ids)
            )
        else:
            conversation_filters.append(false())
        deleted["conversations"] = delete_in_batches(
            db, models.Conversation, conversation_filters, batch_size, dry_run
        )

        for name, model in SCOPED_BY_COMPANY:
            filters = [model.company_id == company_id, model.created_at < cutoff]
            deleted[name] = delete_in_batches(
                db, model, filters, batch_size, dry_run
            )

        # Uploaded files and the rows that point at them, then the documents
        # themselves: an expired upload must stop answering questions, not just
        # stop having a file.
        deleted["attachments"] = purge_attachments(
            db, company_id, cutoff, batch_size=batch_size, dry_run=dry_run
        )
        deleted["extra_documents"] = purge_documents(
            db, company_id, cutoff, batch_size=batch_size, dry_run=dry_run
        )

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


# The span of one topic window. Kept next to the containment check so the
# clustering schedule and the invalidation cannot drift apart.
WINDOW_SPAN = timedelta(days=7)


def _window_overlap(column, stamps: list[datetime]):
    """Rows whose weekly window contains at least one of `stamps`.

    Expressed as `period_start > min - 7d AND period_start <= max`, which is
    alignment-agnostic: it holds whether the company's windows start on Monday or
    on the `digest_day` it configured. A window is at most seven days, so this
    cannot miss one.

    It is exact only while `stamps` span no more than a week: past that, a start
    in the middle belongs to a window that contains neither the first nor the last
    stamp. Callers group stamps first (`_window_groups`) rather than passing a
    whole conversation's timestamps.
    """
    return and_(
        column > min(stamps) - WINDOW_SPAN,
        column <= max(stamps),
    )


def _window_groups(stamps: list[datetime]) -> list[list[datetime]]:
    """Split stamps into runs that are at most one window apart.

    Two moments more than seven days apart belong to different weeks under every
    alignment, so they are matched separately: a conversation that goes quiet for
    a fortnight must not erase the week in between. That week's clusters were built
    from messages the erasure did not touch, so dropping them would delete derived
    data nobody asked to remove (and cost the worker a needless rebuild).
    """
    groups: list[list[datetime]] = []
    for stamp in sorted(set(stamps)):
        if groups and stamp - groups[-1][-1] <= WINDOW_SPAN:
            groups[-1].append(stamp)
        else:
            groups.append([stamp])
    return groups


def _window_any(column, stamps: list[datetime]):
    """`or_` of one containment range per group of stamps."""
    return or_(*[_window_overlap(column, group) for group in _window_groups(stamps)])


def invalidate_topic_windows(
    db: Session,
    company_id: UUID,
    moments: list[datetime | None],
    *,
    commit: bool = False,
) -> dict[str, int]:
    """Drop the derived clusters for every window an erased moment fell in.

    Called after a conversation is erased. The labels and summaries were built
    from questions that no longer exist, so the only honest state is "no clusters
    for that week"; the run row is deleted too, which is what lets the worker
    rebuild it later. No provider is called here — invalidation is local, cheap
    and unconditional.

    Which window a moment fell in is decided by containment, not by reading the
    company's `digest_day`: any seven-day window holding an erased message is
    dropped, whatever day it starts on. Moments are matched week by week, not as
    one min→max range, so a conversation spanning several weeks loses exactly the
    weeks it holds messages in — the silent weeks between its first and last
    message were not built from erased text and are left alone.
    """
    stamps = [
        moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
        for moment in moments
        if moment is not None
    ]
    if not stamps:
        return {"topic_clusters": 0, "topic_cluster_runs": 0}

    deleted = {
        "topic_clusters": db.query(models.TopicCluster)
        .filter(
            models.TopicCluster.company_id == company_id,
            _window_any(models.TopicCluster.period_start, stamps),
        )
        .delete(synchronize_session=False),
        "topic_cluster_runs": db.query(models.TopicClusterRun)
        .filter(
            models.TopicClusterRun.company_id == company_id,
            _window_any(models.TopicClusterRun.period_start, stamps),
        )
        .delete(synchronize_session=False),
    }
    if commit:
        db.commit()
    return deleted


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
