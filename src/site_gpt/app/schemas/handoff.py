from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HandoffCreate(BaseModel):
    """A visitor asking for a human. Public: only this body is trusted."""

    website_id: UUID
    session_id: str
    message: str | None = None


class HandoffItem(BaseModel):
    id: UUID
    website_id: UUID
    website_name: str | None = None
    session_id: str
    contact_id: UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    message: str | None = None
    status: str  # "pending" | "accepted" | "closed"
    channel: str | None = None
    created_at: datetime


class HandoffUpdate(BaseModel):
    status: str | None = None  # "pending" | "accepted" | "closed"
