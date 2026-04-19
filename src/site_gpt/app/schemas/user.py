from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from site_gpt.app.schemas.app import ResponseBase


class UserBase(BaseModel):
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    company_id: UUID
    email: str
    phone: str | None = None
    first_name: str
    last_name: str
    role: str | None = None
    status: str | None = None


class UserRes(UserBase, ResponseBase):
    model_config = {"from_attributes": True}


class UserCreate(UserBase):
    password: str


class UserUpdate(UserBase):
    pass


class UserChangePassword(BaseModel):
    password: str


class UserLogin(BaseModel):
    email: str
    password: str
