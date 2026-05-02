from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class WebsitePageBase(BaseModel):
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    url: str | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    website_id: UUID | None = None


class WebsitePageRes(WebsitePageBase):
    model_config = {"from_attributes": True}


class WebsitePageCreate(BaseModel):
    url: str
    name: str
    description: str | None = None
    status: str | None = None
    website_id: UUID


class WebsitePageUpdate(BaseModel):
    url: str | None = None
    name: str | None = None
    status: str | None = None
    description: str | None = None
