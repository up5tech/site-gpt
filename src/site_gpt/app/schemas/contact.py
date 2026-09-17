from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ContactCreate(BaseModel):
    website_id: UUID
    session_id: str
    first_name: str
    last_name: str
    email: str


class ContactRes(BaseModel):
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    website_id: UUID | None = None
    session_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None

    model_config = {"from_attributes": True}


class ContactListResponse(BaseModel):
    items: list[ContactRes] = []
    total: int
    limit: int
    offset: int
