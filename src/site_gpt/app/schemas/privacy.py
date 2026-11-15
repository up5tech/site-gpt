"""Schemas for the privacy export and erasure endpoints (F9)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PrivacyMessage(BaseModel):
    id: UUID
    session_id: str
    role: str
    message: str
    created_at: datetime


class PrivacyContact(BaseModel):
    id: UUID
    session_id: str
    first_name: str
    last_name: str
    email: str
    consent_at: datetime | None = None
    created_at: datetime


class PrivacyFeedback(BaseModel):
    id: UUID
    session_id: str
    rating: str
    comment: str | None = None
    status: str
    created_at: datetime


class PrivacyHandoff(BaseModel):
    id: UUID
    session_id: str
    message: str | None = None
    status: str
    channel: str | None = None
    created_at: datetime


class PrivacyExport(BaseModel):
    """Everything the app stores about one website, for a data-subject request.

    One object per section rather than a flat blob so a caller can hand each
    part to the person who asked without parsing the rest.
    """

    website_id: UUID
    website_name: str
    generated_at: datetime
    chat_messages: list[PrivacyMessage]
    contacts: list[PrivacyContact]
    chat_feedback: list[PrivacyFeedback]
    handoff_requests: list[PrivacyHandoff]


class PrivacyDeletionResult(BaseModel):
    website_id: UUID
    session_id: str
    deleted: dict[str, int]


class RetentionPurgeRequest(BaseModel):
    """Preview or run the retention purge for the caller's company.

    `dry_run` defaults to True on purpose: a purge is destructive, so the default
    answers "what would go?" and deleting takes an explicit `false`.
    """

    dry_run: bool = True
    # Override the stored `retention_days` for a what-if preview.
    retention_days: int | None = None


class RetentionPurgeResult(BaseModel):
    retention_days: int
    # Rows strictly older than this go; `null` when the policy is "keep for ever".
    cutoff: datetime | None
    dry_run: bool
    deleted: dict[str, int]
    total: int
