from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SessionTokenRequest(BaseModel):
    """Mint (or rotate) the token of one widget session."""

    website_id: UUID
    session_id: str


class SessionTokenResponse(BaseModel):
    token: str
    expires_at: datetime
