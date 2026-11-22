"""Platform-owner grants and the audit trail (V5-40, D10).

The operator boundary is *not* a tenant role. A grant is a row in
`platform_owners` bound to an existing user, created only out of band
(`scripts/platform_owner.py`) — there is no API that can grant or revoke it, so
no company admin, manager, member or API key can promote themselves.

Only `active` grants count: `revoked_at` is a timestamp so the history survives,
and a re-grant inserts a fresh row rather than clearing the old one. Removal of
the granted row (`ON DELETE CASCADE` on the user) simply ends the privilege.

Every grant, revoke and owner action writes one `platform_audit_logs` row. The
writer redacts sensitive keys and refuses non-scalar values, so a caller that
passes a token by mistake cannot persist it.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from site_gpt.app import models

REDACTED = "[redacted]"

# Keys whose value is never stored, whatever it looks like. Case-insensitive and
# matched as a substring so `stripe_secret_key`, `X-Api-Key` and `db_password`
# all fall under it.
SENSITIVE_KEY = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|private[_-]?key|"
    r"authorization|bearer|credential|dsn|database[_-]?url|session)",
    re.IGNORECASE,
)


def redact_detail(value: Any) -> Any:
    """Copy `value`, replacing anything secret-looking with `REDACTED`.

    Only JSON-safe scalars survive: a nested dict is filitered key by key, a
    list keeps its scalar items, and anything else (bytes, objects, an ORM row)
    becomes `REDACTED` instead of being coerced into a leak.
    """
    if isinstance(value, dict):
        return {
            str(key): REDACTED if SENSITIVE_KEY.search(str(key)) else redact_detail(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_detail(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return REDACTED


def active_grant(db: Session, user_id: uuid.UUID) -> models.PlatformOwner | None:
    """The live grant for `user_id`, or None (revoked rows do not count)."""
    return (
        db.query(models.PlatformOwner)
        .filter(
            models.PlatformOwner.user_id == user_id,
            models.PlatformOwner.revoked_at.is_(None),
        )
        .first()
    )


def is_owner(db: Session, user_id: uuid.UUID) -> bool:
    return active_grant(db, user_id) is not None


def record_audit(
    db: Session,
    *,
    action: str,
    target_type: str,
    target_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    detail: dict | None = None,
    commit: bool = True,
) -> models.PlatformAuditLog:
    """Insert one audit row. Never updates or deletes: the table is append-only."""
    row = models.PlatformAuditLog(
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=redact_detail(detail) if detail else None,
    )
    db.add(row)
    if commit:
        db.commit()
    return row


def grant_owner(
    db: Session,
    user_id: uuid.UUID,
    *,
    actor_label: str,
    note: str | None = None,
) -> tuple[models.PlatformOwner, bool]:
    """Grant operator access; returns `(row, created)`.

    Idempotent: an existing active grant is returned untouched and nothing is
    audited twice. A lost insert race (two operators granting at once) is the
    partial unique index's job — the loser rolls back and reads the winner.
    """
    existing = active_grant(db, user_id)
    if existing is not None:
        return existing, False

    row = models.PlatformOwner(user_id=user_id, note=note)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = active_grant(db, user_id)
        if existing is None:  # pragma: no cover - the only other cause is a bad FK
            raise
        return existing, False

    record_audit(
        db,
        action="platform_owner.grant",
        target_type="user",
        target_id=str(user_id),
        actor_label=actor_label,
        detail={"note": note} if note else None,
        commit=False,
    )
    db.commit()
    return row, True


def revoke_owner(
    db: Session,
    user_id: uuid.UUID,
    *,
    actor_label: str,
) -> bool:
    """Stamp `revoked_at` on the active grant; False when there was none."""
    row = active_grant(db, user_id)
    if row is None:
        return False

    row.revoked_at = datetime.now(UTC)
    record_audit(
        db,
        action="platform_owner.revoke",
        target_type="user",
        target_id=str(user_id),
        actor_label=actor_label,
        commit=False,
    )
    db.commit()
    return True


def recent_audit(db: Session, limit: int = 50) -> list[models.PlatformAuditLog]:
    """Newest-first audit rows for the console read, capped by the caller."""
    return (
        db.query(models.PlatformAuditLog)
        .order_by(
            models.PlatformAuditLog.created_at.desc(),
            models.PlatformAuditLog.id.desc(),
        )
        .limit(limit)
        .all()
    )
