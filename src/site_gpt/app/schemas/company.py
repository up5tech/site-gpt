from pydantic import BaseModel

from site_gpt.app.schemas.app import ResponseBase


class CompanyBase(BaseModel):
    name: str
    description: str


class Company(CompanyBase, ResponseBase):
    pass


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(CompanyBase):
    pass
