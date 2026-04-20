from pydantic import BaseModel

from site_gpt.app.schemas.app import ResponseBase


class SettingBase(BaseModel):
    key: str
    value: str


class SettingRes(SettingBase, ResponseBase):
    pass


class SettingCreate(SettingBase):
    pass


class SettingUpdate(SettingBase):
    pass
