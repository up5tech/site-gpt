from uuid import UUID

from pydantic import BaseModel


class DocumentBase(BaseModel):
    id: UUID | None = None
    title: str | None = None
    content: str | None = None
    url: str | None = None
    website_id: UUID | None = None


class DocumentRes(DocumentBase):
    model_config = {"from_attributes": True}
