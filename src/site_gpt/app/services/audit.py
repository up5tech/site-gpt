"""Tenant-admin audit trail (V6-14; D13 partially reopened 2026-11-27).

V6-14's minimum action set is recorded here, metadata only: who (actor user id
and the email they had at the time), which company, what action, which target
and when. `detail` is filtered by the same redactor the platform trail uses, and
no column exists for a transcript, request body, password, API key or token — a
caller that passes one by mistake gets `[redacted]` rather than a leak.

The read is bounded (one page cannot exceed `MAX_PAGE_SIZE` rows) and the trail
is append-only: nothing in this module updates or deletes a row except
`purge_expired`, which removes rows older than the approved one-year retention
(D7) in bounded, separately committed batches.

Callers record in the same transaction as the action where the action's own code
allows it (`commit=False`), so a failed write cannot leave an audit row for a
change that rolled back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.config import AUDIT_RETENTION_DAYS
from site_gpt.app.services import retention
from site_gpt.app.services.platform import redact_detail

#: The largest page a read may ask for.
MAX_PAGE_SIZE = 100

#: Every action this trail writes, so a reader knows the vocabulary. Kept here
#: instead of a database constraint because a new action must not need a
#: migration, and a typo is caught by the tests that pin each route.
ACTIONS = frozenset(
    {
        "user.create",
        "user.update",
        "user.delete",
        "user.password.change",
        "api_key.create",
        "api_key.revoke",
        "settings.update",
        "data.export",
        "data.erase",
        "data.erase_contact",
        "data.retention.apply",
    }
)


def record(
    db: Session,
    *,
    company_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: Any = None,
    actor: models.User | None = None,
    actor_label: str | None = None,
    detail: dict | None = None,
    commit: bool = False,
) -> models.TenantAuditLog:
    """Insert one audit row; never updates or deletes.

    `actor` supplies both the id and the email label, so a deleted account still
    leaves a readable "who". Only a persisted `models.User` becomes the FK: a
    caller that passes another principal (an API key, or a stub in a test) is
    recorded by `actor_label` alone, so the trail can never fail on a foreign
    key for an account that does not exist. `commit=False` is the default because
    the caller is usually inside the action's own transaction.
    """
    row = models.TenantAuditLog(
        company_id=company_id,
        actor_user_id=actor.id if isinstance(actor, models.User) else None,
        actor_label=(actor_label or getattr(actor, "email", None) or None),
        action=action[:64],
        target_type=target_type[:32],
        target_id=str(target_id)[:64] if target_id is not None else None,
        detail=redact_detail(detail) if detail else None,
    )
    db.add(row)
    if commit:
        db.commit()
    return row


def recent(
    db: Session,
    company_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
) -> tuple[int, list[models.TenantAuditLog]]:
    """Newest-first page of one company's rows, with the total for the pager."""
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    offset = max(0, int(offset))
    query = db.query(models.TenantAuditLog).filter(
        models.TenantAuditLog.company_id == company_id
    )
    if action:
        query = query.filter(models.TenantAuditLog.action == action)
    total = query.count()
    rows = (
        query.order_by(
            models.TenantAuditLog.created_at.desc(),
            models.TenantAuditLog.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return total, rows


def purge_expired(
    db: Session,
    *,
    days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> int:
    """Count or delete rows past the one-year retention window (D7).

    Uses the shared batched deleter, so a large trail is removed in bounded,
    separately committed batches rather than one long transaction. `days <= 0`
    keeps the trail for ever, matching the visitor-data policy's meaning of 0.
    """
    window = AUDIT_RETENTION_DAYS if days is None else int(days)
    if window <= 0:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(days=window)
    return retention.delete_in_batches(
        db,
        models.TenantAuditLog,
        [models.TenantAuditLog.created_at < cutoff],
        retention.RETENTION_BATCH_SIZE,
        dry_run=dry_run,
    )
