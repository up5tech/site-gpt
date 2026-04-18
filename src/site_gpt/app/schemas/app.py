from datetime import datetime
from typing import Any, List
from uuid import UUID

from pydantic import BaseModel


class PaginatedResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[Any]


class ResponseBase(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
