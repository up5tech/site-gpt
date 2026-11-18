from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EmbedTokenRes(BaseModel):
    """An embed token as read back: the prefix and dates, never the secret.

    `active` is derived from `revoked_at`, so the dashboard does not have to
    compare timestamps to decide whether a snippet still works.
    """

    id: UUID
    website_id: UUID
    token_prefix: str
    active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class EmbedTokenCreated(EmbedTokenRes):
    """Mint/rotate response: the only time the raw `token` is ever returned."""

    token: str
