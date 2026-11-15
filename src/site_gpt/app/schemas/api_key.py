from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ApiKeyCreate(BaseModel):
    """Create a company key. `scopes` defaults to read-only."""

    name: str
    scopes: list[str] = ["read"]


class ApiKeyRes(BaseModel):
    """A key as listed in the dashboard: never includes the secret."""

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreated(ApiKeyRes):
    """Creation response: the only time the raw `key` is ever returned."""

    key: str
