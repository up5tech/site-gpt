"""Platform (operator) response models (V5-40).

Read-only and minimal on purpose: this wave adds the boundary, not the console.
Neither model carries a credential, a Stripe id or another company's data.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PlatformSession(BaseModel):
    """The authenticated operator, as the grant resolves them."""

    user_id: UUID
    email: str
    granted_at: datetime


class PlatformAuditEvent(BaseModel):
    """One append-only audit row; `detail` is already redacted when stored."""

    id: UUID
    created_at: datetime
    action: str
    target_type: str
    target_id: str | None = None
    actor_user_id: UUID | None = None
    actor_label: str | None = None
    detail: dict | None = None


class PlatformAuditList(BaseModel):
    events: list[PlatformAuditEvent]
