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


class WebsiteRes(WebsiteBase):
    model_config = {"from_attributes": True}


class WebsiteCreate(WebsiteBase):
    pass


class WebsiteUpdate(BaseModel):
    url: str | None = None
    name: str | None = None
    description: str | None = None
    site_map_url: str | None = None
