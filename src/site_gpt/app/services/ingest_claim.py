"""Atomic single-ingest claim for a website.

Every caller that wants to (re)crawl a website — the admin `POST /api/ingest`
endpoint and the versioned `POST /api/v1/ingest` — has to claim the row first.
Two concurrent requests both read a non-`processing` status, so the check has to
live in the `UPDATE` itself: exactly one statement can match the row, the loser
sees rowcount 0 and must not enqueue a second crawl.

The statement (and the stale-row window) live here so there is one copy of the
race fix. A route that re-implements the claim re-opens the double-crawl bug.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from site_gpt.app import models

# A website still in `processing` longer than this is assumed to belong to a
# worker that died mid-ingest (deploy, OOM kill, hard reboot). It must be
# recovered explicitly: the scheduler only picks up `completed` sites, so an
# orphaned `processing` row would otherwise never be re-ingested again.
# Deliberately generous so a legitimately slow crawl is not re-queued.
STUCK_INGEST_AFTER = timedelta(hours=6)


def claim_ingest(db: Session, website_id, company_id) -> bool:
    """Move a website to `processing`; True only for the request that won.

    A `processing` row older than `STUCK_INGEST_AFTER` is taken over (its worker
    is dead), and the take-over refreshes `updated_at` so an immediate second
    click is refused again instead of looking stale.

    `company_id` is part of the statement, so a caller cannot claim another
    tenant's website even if the id leaks. The claim is committed before
    returning; callers enqueue the crawl only when this returns True.
    """
    stale_before = datetime.now(UTC) - STUCK_INGEST_AFTER
    claimed = (
        db.query(models.Website)
        .filter(
            models.Website.id == website_id,
            models.Website.company_id == company_id,
            or_(
                models.Website.ingest_status.is_(None),
                models.Website.ingest_status != "processing",
                models.Website.updated_at.is_(None),
                models.Website.updated_at < stale_before,
            ),
        )
        .update(
            {"ingest_status": "processing", "updated_at": datetime.now(UTC)},
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(claimed)
