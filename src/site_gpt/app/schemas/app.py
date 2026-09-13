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
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DashboardStats(BaseModel):
    """Aggregated counts for the current user's company, shown on the dashboard."""

    total_websites: int
    indexed_websites: int
    ingesting_websites: int
    total_documents: int
    total_chat_messages: int
    team_members: int



