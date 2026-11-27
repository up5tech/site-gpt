"""Tenant-admin audit read (V6-14).

One route, admin-only and company-scoped: a company sees its own trail and never
another tenant's, and the page is bounded by the service (`MAX_PAGE_SIZE`), so a
read cannot dump a year of rows in one response. Writes happen at the action
sites (`api/company.py`, `api/api_key.py`, `api/setting.py`, `api/privacy.py`)
through `services.audit.record`; this module only reads.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.audit import TenantAuditEvent, TenantAuditList
from site_gpt.app.services import audit

router = APIRouter()


@router.get("/", response_model=TenantAuditList, tags=["audit"])
def list_audit_events(
    limit: int = Query(50, ge=1, le=audit.MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Newest-first page of this company's security-relevant actions."""
    total, rows = audit.recent(
        db, user.company_id, limit=limit, offset=offset, action=action
    )
    return TenantAuditList(
        total=total,
        limit=limit,
        offset=offset,
        events=[
            TenantAuditEvent(
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
        ],
    )
