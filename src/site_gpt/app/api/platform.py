"""The platform-owner surface (V5-40, Wave 4).

Two read-only routes exist so far: who the operator is and the recent audit
trail. Everything here is behind three independent gates:

1. `PLATFORM_CONSOLE_ENABLED` — off by default, so an installation that has not
   deliberately opened the operator console answers 404 for the whole surface.
   D10 requires approved strong auth or a private-network restriction before
   production exposure; until one is approved this switch stays off.
2. `require_platform_owner` — a JWT for an `active` user with an active
   `platform_owners` grant. A tenant `admin` is *not* an operator.
3. Nothing here can mint that grant: it is provisioned only out of band through
   `scripts/platform_owner.py`, so no request can escalate itself.

Subscription operations, catalog edits and the `/platform` UI are V5-41…V5-43;
this module deliberately exposes no mutation yet.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.core.auth import require_platform_owner
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.platform import (
    PlatformAuditEvent,
    PlatformAuditList,
    PlatformSession,
)
from site_gpt.app.services import platform

router = APIRouter()


def platform_console_enabled() -> None:
    """404 for the whole surface while the console switch is off."""
    if not config.PLATFORM_CONSOLE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )


@router.get(
    "/api/platform/session",
    response_model=PlatformSession,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_session(
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformSession:
    """Who the signed-in operator is, resolved through their active grant."""
    grant = platform.active_grant(db, user.id)
    return PlatformSession(
        user_id=user.id,
        email=user.email,
        granted_at=grant.created_at,
    )


@router.get(
    "/api/platform/audit",
    response_model=PlatformAuditList,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_audit(
    limit: int = Query(50, ge=1, le=200),
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformAuditList:
    """Newest-first audit rows, bounded so a read cannot dump the table."""
    rows = platform.recent_audit(db, limit)
    return PlatformAuditList(
        events=[
            PlatformAuditEvent(
                id=row.id,
                created_at=row.created_at,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                actor_user_id=row.actor_user_id,
                actor_label=row.actor_label,
                detail=row.detail,
            )
            for row in rows
        ]
    )
