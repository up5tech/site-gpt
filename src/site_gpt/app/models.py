import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from site_gpt.app.core.config import EMBEDDING_DIMENSIONS
from site_gpt.app.db.base import BaseModel


class Company(BaseModel):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(nullable=True)
    expired_at: Mapped[datetime] = mapped_column(nullable=True)

    users = relationship("User", cascade="all, delete-orphan", passive_deletes=True)
    websites = relationship(
        "Website", cascade="all, delete-orphan", passive_deletes=True
    )
    settings = relationship(
        "Setting", cascade="all, delete-orphan", passive_deletes=True
    )
    extra_documents = relationship(
        "ExtraDocument", cascade="all, delete-orphan", passive_deletes=True
    )
    api_keys = relationship(
        "ApiKey", cascade="all, delete-orphan", passive_deletes=True
    )
    digest_logs = relationship(
        "DigestLog", cascade="all, delete-orphan", passive_deletes=True
    )
    integrations = relationship(
        "Integration", cascade="all, delete-orphan", passive_deletes=True
    )


class User(BaseModel):
    __tablename__ = "users"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=True, default="user")
    status: Mapped[str] = mapped_column(String(50), nullable=True, default="active")
    hash_string: Mapped[str] = mapped_column(String(255), nullable=True)
    hash_type: Mapped[str] = mapped_column(
        String(50), nullable=True, default="forgot-password"
    )
    reset_token: Mapped[str] = mapped_column(String(255), nullable=True)
    reset_token_expires_at: Mapped[datetime] = mapped_column(nullable=True)


class Setting(BaseModel):
    __tablename__ = "settings"

    __table_args__ = (Index("idx_settings_company_id", "company_id"),)

    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )


class Website(BaseModel):
    __tablename__ = "websites"

    __table_args__ = (Index("idx_websites_company_id", "company_id"),)

    url: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    site_map_url: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=True, default="active")
    ingest_status: Mapped[str] = mapped_column(
        String(50), nullable=True, default="none"
    )

    website_pages = relationship(
        "WebsitePage", cascade="all, delete-orphan", passive_deletes=True
    )
    documents = relationship(
        "Document", cascade="all, delete-orphan", passive_deletes=True
    )
    extra_documents = relationship(
        "ExtraDocument", cascade="all, delete-orphan", passive_deletes=True
    )
    contacts = relationship(
        "Contact", cascade="all, delete-orphan", passive_deletes=True
    )
    handoff_requests = relationship(
        "HandoffRequest", cascade="all, delete-orphan", passive_deletes=True
    )


class WebsitePage(BaseModel):
    __tablename__ = "website_pages"

    __table_args__ = (
        Index("idx_website_pages_website_id", "website_id"),
        UniqueConstraint("website_id", "url"),
    )

    url: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=True, default="active")
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )


class Document(BaseModel):
    __tablename__ = "documents"

    __table_args__ = (Index("idx_documents_website_id", "website_id"),)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )

    embeddings = relationship(
        "Embedding", cascade="all, delete-orphan", passive_deletes=True
    )


class ExtraDocument(BaseModel):
    __tablename__ = "extra_documents"

    __table_args__ = (Index("idx_extra_documents_company_id", "company_id"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=True
    )

    embeddings = relationship(
        "Embedding", cascade="all, delete-orphan", passive_deletes=True
    )
    attachments = relationship(
        "Attachment", cascade="all, delete-orphan", passive_deletes=True
    )


class Attachment(BaseModel):
    __tablename__ = "attachments"

    __table_args__ = (
        Index("idx_attachments_extra_document_id", "extra_document_id"),
        Index("idx_attachments_user_id", "user_id"),
    )

    extra_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extra_documents.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=True, default="tmp")
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int] = mapped_column(nullable=True)

    # Where the file bytes came from. "local" = uploaded directly; other values
    # ("url", "google_drive", ...) are resolved by services/sources.py. `source_ref`
    # stores the origin identifier (remote URL, cloud file id, ...) while the
    # actual bytes are always normalized into a local file under uploads/.
    source: Mapped[str] = mapped_column(String(50), nullable=True, default="local")
    source_ref: Mapped[str] = mapped_column(String(500), nullable=True)


class Embedding(BaseModel):
    __tablename__ = "embeddings"

    __table_args__ = (
        CheckConstraint(
            "(document_id IS NOT NULL AND extra_document_id IS NULL) OR "
            "(document_id IS NULL AND extra_document_id IS NOT NULL)",
            name="check_one_source_only",
        ),
        Index("idx_embeddings_document_id", "document_id"),
        Index("idx_embeddings_extra_document_id", "extra_document_id"),
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    extra_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extra_documents.id", ondelete="CASCADE"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class ChatMessage(BaseModel):
    __tablename__ = "chat_messages"

    __table_args__ = (
        Index("idx_chat_messages_session_id", "session_id"),
        # Retention always filters by website + age, so one composite index serves
        # the purge (`website_id IN (...) AND created_at < cutoff`) and
        # website-scoped history reads.
        Index("idx_chat_messages_website_id_created_at", "website_id", "created_at"),
    )

    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    # Whether the answer was grounded in retrieved context (ADR-7). NULL means
    # "unknown" — rows written before V2, and the partial answer saved after a
    # stream failure — never "unanswered".
    answered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ChatFeedback(BaseModel):
    __tablename__ = "chat_feedback"

    __table_args__ = (
        Index("idx_chat_feedback_website_id", "website_id"),
        Index("idx_chat_feedback_website_id_created_at", "website_id", "created_at"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)  # "up" | "down"
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    # The assistant message this rating refers to (F4). NULL for ratings made
    # before the widget sent one: still reviewable, but not trainable, because
    # the question cannot be resolved unambiguously.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # "pending" | "approved" | "rejected"
    # The admin's corrected answer, written together with status="approved" and
    # rendered into the Q&A training document.
    reviewed_answer: Mapped[str] = mapped_column(Text, nullable=True)


class HandoffRequest(BaseModel):
    """A visitor asking to be handed to a human (F5, notify-and-callback)."""

    __tablename__ = "handoff_requests"

    __table_args__ = (
        Index("idx_handoff_requests_website_id", "website_id"),
        Index("idx_handoff_requests_status", "status"),
        Index("idx_handoff_requests_website_id_created_at", "website_id", "created_at"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional: a visitor can ask for a human before giving contact details, and
    # deleting the contact must not erase the request history.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # "pending" | "accepted" | "closed"
    channel: Mapped[str] = mapped_column(String(50), nullable=True)


class DigestLog(BaseModel):
    """One weekly digest period for one company (F6).

    The row is inserted *before* the email goes out with `sent_at` NULL, so a
    crash, a retry or a second worker cannot send the same period twice;
    `sent_at` is stamped once delivery succeeded.
    """

    __tablename__ = "digest_log"

    __table_args__ = (
        UniqueConstraint("company_id", "period_start"),
        # The purge filters on `company_id` + `created_at`.
        Index("idx_digest_log_company_id_created_at", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    # Explicitly timezone-aware, like the migration and db/base.py. The rest of
    # the models rely on inference (naive DateTime), which is why autogenerate
    # keeps proposing ALTERs they deliberately do not take.
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recipient_count: Mapped[int] = mapped_column(nullable=False, default=0)


class Integration(BaseModel):
    """An outbound integration for one company (F7).

    `config` and `events` are JSON text, like `ApiKey.scopes`. Credentials live
    inside `config` and are masked on every read, so a token never round-trips
    to a browser, a log line or an API response.
    """

    __tablename__ = "integrations"

    __table_args__ = (
        Index("idx_integrations_company_id_enabled", "company_id", "enabled"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    # "webhook" | "slack" | "zendesk" | "crisp" — the key in PROVIDERS.
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    events: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SessionToken(BaseModel):
    """The per-session credential the widget presents to read its own history
    (K4).

    The session id is a client-chosen identifier, so on its own it is a
    capability: anyone who learns `website_id` + `session_id` could read the
    transcript. The widget therefore mints a random token for a session and
    stores it in the visitor's browser; only the hash is kept server-side, like
    an API key. `session_id` stays the lookup key so nothing else changes.
    """

    __tablename__ = "session_tokens"

    __table_args__ = (
        UniqueConstraint("website_id", "session_id"),
        Index("idx_session_tokens_website_id", "website_id"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IntegrationDelivery(BaseModel):
    """One attempt-tracked delivery of one event to one integration (F7).

    The row is written **before** the first HTTP call, so a crash, a restart or a
    dead endpoint leaves work to retry instead of losing the lead silently. The
    payload is kept for retries but never returned by the API (it carries visitor
    contact details).

    `integration_id` is nullable and ON DELETE SET NULL: deleting an integration
    must not erase the record that its events failed, and a delivery whose
    integration is gone is marked dead on the next attempt.
    """

    __tablename__ = "integration_deliveries"

    __table_args__ = (
        UniqueConstraint("integration_id", "event_id"),
        Index("idx_integration_deliveries_company_id", "company_id"),
        Index("idx_integration_deliveries_due", "status", "next_attempt_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True
    )
    # Copied from the integration so the row stays readable after a deletion.
    integration_type: Mapped[str] = mapped_column(String(50), nullable=False)
    integration_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Shared by every integration subscribed to the same event, and sent to the
    # receiver so it can drop a duplicate retry.
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # "pending" (will retry) | "delivered" | "dead" (retries exhausted)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    last_status_code: Mapped[int] = mapped_column(nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApiKey(BaseModel):
    """A company key for the versioned `/api/v1` API.

    Only the SHA-256 hash (plus the pepper from the environment) is stored; the
    raw key is returned once on creation and never persisted or logged.
    """

    __tablename__ = "api_keys"

    __table_args__ = (
        Index("idx_api_keys_company_id", "company_id"),
        Index("idx_api_keys_key_prefix", "key_prefix"),
        UniqueConstraint("key_hash"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # JSON array of granted scopes, e.g. '["read", "ingest:write"]'.
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    last_used_at: Mapped[datetime] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime] = mapped_column(nullable=True)


class Contact(BaseModel):
    __tablename__ = "contacts"

    __table_args__ = (
        Index("idx_contacts_website_id", "website_id"),
        Index("idx_contacts_website_id_created_at", "website_id", "created_at"),
        UniqueConstraint("website_id", "session_id"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # When the visitor ticked the consent box (F9). NULL means "no recorded
    # consent", which is also the state of every row created before V2.
    consent_at: Mapped[datetime] = mapped_column(nullable=True)
