from uuid import UUID
from datetime import datetime

from pydantic import BaseModel


class WebsiteBase(BaseModel):
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    url: str | None = None
    name: str | None = None
    description: str | None = None
    site_map_url: str | None = None
    company_id: UUID | None = None
    status: str | None = None
    ingest_status: str | None = None


class WebsiteRes(WebsiteBase):
    model_config = {"from_attributes": True}


class WebsiteCreate(WebsiteBase):
    pass


class WebsiteQuotaRes(BaseModel):
    """Today's chat usage for one website, for the owner's dashboard."""

    website_id: UUID
    date: str
    # None when Redis could not be read; `available` says which case it is.
    used: int | None = None
    limit: int
    unlimited: bool
    remaining: int | None = None
    near_limit: bool
    available: bool


class WebsiteUpdate(BaseModel):
    url: str | None = None
    name: str | None = None
    description: str | None = None
    site_map_url: str | None = None
    status: str | None = None
