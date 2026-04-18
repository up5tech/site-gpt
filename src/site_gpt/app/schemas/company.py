from pydantic import BaseModel

from site_gpt.app.schemas.app import PaginatedResponse, ResponseBase


class CompanyBase(BaseModel):
    name: str
    description: str


class Company(CompanyBase, ResponseBase):
    model_config = {"from_attributes": True}


class CompanyPaginated(PaginatedResponse):
    items: list[Company]


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
