from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AttachmentBase(BaseModel):
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extra_document_id: UUID | None = None
    user_id: UUID | None = None
    filename: str | None = None
    status: str | None = None
    file_url: str | None = None
    file_size: int | None = None
    file_type: str | None = None


class AttachmentRes(AttachmentBase):
    model_config = {"from_attributes": True}


class AttachmentCreate(AttachmentBase):
    pass


class ExtraDocumentBase(BaseModel):
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    name: str | None = None
    content: str | None = None
    company_id: UUID | None = None
    attachments: list[AttachmentRes] | None = None


class ExtraDocumentCreate(ExtraDocumentBase):
    file_ids: list[str] | None = None


class ExtraDocumentRes(ExtraDocumentBase):
    model_config = {"from_attributes": True}


class ExtraDocumentUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    delete_file_ids: list[str] | None = None
