"""Response models for the tenant-admin audit read (V6-14)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TenantAuditEvent(BaseModel):
    """One append-only row; `detail` is already redacted when stored."""

    id: UUID
    created_at: datetime
    action: str
    target_type: str
    target_id: str | None = None
    actor_user_id: UUID | None = None
    actor_label: str | None = None
    detail: dict | None = None


class TenantAuditList(BaseModel):
    total: int
    limit: int
    offset: int
    events: list[TenantAuditEvent]
