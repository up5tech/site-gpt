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


class DeliveryRes(BaseModel):
    """One tracked delivery.

    `payload` is deliberately absent: it is stored for retries, but it repeats the
    visitor's contact details and does not need to travel to the browser.
    """

    id: UUID
    integration_id: UUID | None
    integration_name: str
    integration_type: str
    event_id: UUID
    event_type: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    last_status_code: int | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


class DeliveryListRes(BaseModel):
    items: list[DeliveryRes]
    total: int
    # Counts by status, so the UI can show "2 dead" without a second request.
    pending: int
    dead: int
    delivered: int


class DeliveryAttemptRes(BaseModel):
    id: UUID
    status: str
    attempts: int
    delivered: bool
    last_error: str | None
    next_attempt_at: datetime | None
