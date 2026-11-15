from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class IntegrationCreate(BaseModel):
    """A new outbound integration. `config` holds the provider's credentials."""

    type: str
    name: str
    config: dict = {}
    events: list[str] = []
    enabled: bool = True


class IntegrationUpdate(BaseModel):
    """Partial update. Omitted fields keep their stored value.

    In `config`, a field sent as `"***"` is a masked placeholder and keeps the
    stored secret, so a form that only shows the mask never erases a token.
    """

    name: str | None = None
    config: dict | None = None
    events: list[str] | None = None
    enabled: bool | None = None


class IntegrationRes(BaseModel):
    """An integration as read back: every secret is `"***"` or absent."""

    id: UUID
    type: str
    name: str
    config: dict
    events: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    # Which config keys the UI should render as stored placeholders.
    secret_fields: list[str] = []


class IntegrationTestResult(BaseModel):
    type: str
    delivered: bool
    status_code: int | None = None
    error: str | None = None
