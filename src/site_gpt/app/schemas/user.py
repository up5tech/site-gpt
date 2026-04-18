from pydantic import BaseModel

from site_gpt.app.schemas.app import ResponseBase


class UserBase(BaseModel):
    company_id: int
    email: str
    phone: str | None = None
    first_name: str
    last_name: str


class User(UserBase, ResponseBase):
    pass


class UserCreate(UserBase):
    password: str


class UserUpdate(UserBase):
    pass


class UserChangePassword(BaseModel):
    password: str


class UserLogin(BaseModel):
    email: str
    password: str
