from uuid import UUID
from datetime import datetime

from pydantic import BaseModel

from site_gpt.app.schemas.app import ResponseBase


class CompanyBase(BaseModel):
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    name: str
    description: str


class CompanyRes(CompanyBase, ResponseBase):
    model_config = {"from_attributes": True}


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(CompanyBase):
    pass


class CompanyRegister(BaseModel):
    company_name: str
    first_name: str
    last_name: str
    email: str
    password: str
