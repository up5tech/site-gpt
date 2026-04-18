from datetime import datetime
from typing import Any, List

from pydantic import BaseModel


class PaginatedResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[Any]


class ResponseBase(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
