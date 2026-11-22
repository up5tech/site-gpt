import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
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
    subscription = relationship(
        "Subscription",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
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
    embed_tokens = relationship(
        "EmbedToken", cascade="all, delete-orphan", passive_deletes=True
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

    __table_args__ = (
        # The retention purge looks up one company's expired documents and orders
        # them by age. The composite's `company_id` prefix also serves plain tenant
        # lookups, which is why there is no single-column index here any more.
        Index(
            "idx_extra_documents_company_id_created_at", "company_id", "created_at"
        ),
        # The worker ingests one website's documents and `qa_training` looks its
        # document up by name; both filter on `website_id`, which nothing indexed.
        Index("idx_extra_documents_website_id_name", "website_id", "name"),
    )

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
        # The retention anti-join asks "does this document hold an upload from
        # inside the window?" once per document; this answers it from the index, and
        # its `extra_document_id` prefix also serves plain per-document lookups
        # (there is no single-column index for that any more).
        Index(
            "idx_attachments_extra_document_id_created_at",
            "extra_document_id",
            "created_at",
        ),
        Index("idx_attachments_user_id", "user_id"),
        # The retention purge selects and orders expired uploads by this column.
        Index("idx_attachments_created_at", "created_at"),
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
    # 120, not 50: the OOXML MIME types are 73 characters
    # (`application/vnd.openxmlformats-officedocument...`), and a `.pptx` or
    # `.docx` upload answered 500 when the value did not fit (V4-3G gate).
    file_type: Mapped[str] = mapped_column(String(120), nullable=True)
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
    # Set on `role='agent'` rows: the team member who answered inside the widget
    # (M9). NULL for the visitor, for the bot, and for every row written before
    # V3 — the author is optional history, not a required attribute.
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Conversation(BaseModel):
    """Durable inbox state for one widget session (M9, F3).

    Until V3 a session existed only as `chat_messages.session_id`; an agent needs
    something to attach to, so this row carries the state machine (`bot` →
    `waiting` → `human`, `human` → `waiting` on release, `human` → `closed`), the
    assignee and the queue timestamps. Rows are created lazily when a session
    first writes a message (D2) — no backfill, and a session without a row still
    lists, reads and deletes through the message helpers.
    """

    __tablename__ = "conversations"

    __table_args__ = (
        # The same `session_id` may be reused on two websites; the pair is the
        # identity, and it is also what makes lazy creation race-safe.
        UniqueConstraint("website_id", "session_id"),
        # The inbox lists one website's queue by state, newest activity first.
        # The website is company-scoped by its own FK, so this composite is what
        # keeps "waiting, newest first" from sorting every session of a tenant.
        Index(
            "idx_conversations_website_id_state_last_message_at",
            "website_id",
            "state",
            "last_message_at",
        ),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # "bot" | "waiting" | "human" | "closed" — see services.conversations.
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="bot")
    # Whoever holds the session; NULL while the bot or the queue owns it.
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The newest message moment. Retention expires a conversation on this clock,
    # so metadata can never outlive the messages it describes.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ConversationInsight(BaseModel):
    """Derived sentiment/resolution/summary for one conversation (M10, V4 F2).

    One row per conversation: the unique `conversation_id` is both the claim lock
    (a lost insert race means another run is classifying that conversation) and
    the erasure mechanism — the FK cascades, so deleting the conversation deletes
    its classifications. Only bounded derived values live here: the summary is at
    most 280 characters and the transcript itself is never stored (D3).
    """

    __tablename__ = "conversation_insights"

    __table_args__ = (
        UniqueConstraint("conversation_id"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_conversation_insights_status",
        ),
        CheckConstraint(
            "sentiment IS NULL OR sentiment IN "
            "('positive', 'neutral', 'negative', 'frustrated')",
            name="ck_conversation_insights_sentiment",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN "
            "('resolved', 'unresolved', 'escalated', 'unknown')",
            name="ck_conversation_insights_resolution",
        ),
        # A run recovers dead claims by scanning `processing` rows by age.
        Index(
            "idx_conversation_insights_status_claimed_at", "status", "claimed_at"
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # "processing" | "completed" | "failed" — see services.insights (V4-41).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="processing"
    )
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(280), nullable=True)
    # Which provider/model pair produced this row, for audit.
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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


class TopicCluster(BaseModel):
    """One named topic cluster for one company in one weekly window (V3 M8, F2).

    Derived data only: labels, summaries, aggregates and a centroid — never the
    visitor questions themselves. Chat messages carry no stored vector, so a run
    embeds its bounded sample and keeps the centroid; the text stays wherever it
    already lives and an erasure removes it from here by dropping the window.
    """

    __tablename__ = "topic_clusters"

    __table_args__ = (
        # A window's rebuild replaces rows through this identity: two runs over
        # the same input cannot produce two rows for the same cluster.
        UniqueConstraint("company_id", "period_start", "cluster_key"),
        # The retention purge and the post-erasure invalidation both filter on
        # company + created_at, like `digest_log`'s purge index.
        Index("idx_topic_clusters_company_id_created_at", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    # Aligned with `digest.normalize_period`, never a rolling 7-day window.
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Stable within the window: derived from the ordered clusters, not a random
    # uuid, so rebuilding identical input yields identical keys.
    cluster_key: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Same dimension as `Embedding`: M8 changes no dimension, so no re-ingest.
    centroid: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    # `eligible` counts every visitor question in the window, `sampled` the ones
    # actually clustered; they differ when `TOPIC_CLUSTER_MAX_MESSAGES` truncates.
    sampled_messages: Mapped[int] = mapped_column(nullable=False, default=0)
    eligible_messages: Mapped[int] = mapped_column(nullable=False, default=0)


class TopicClusterRun(BaseModel):
    """The durable claim for one company + weekly window (V3 M8, F2).

    One row per `(company_id, period_start)` is what makes clustering idempotent:
    a run inserts its claim first, so a duplicate job or a second worker loses the
    insert instead of building the window twice. `status` plus `claimed_at` also
    make a crashed run recoverable — a row still `running` past the stale timeout
    can be reclaimed, while `completed` is final.
    """

    __tablename__ = "topic_cluster_runs"

    __table_args__ = (
        UniqueConstraint("company_id", "period_start"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_topic_cluster_runs_status",
        ),
        # Stale-run recovery scans exactly this pair.
        Index("idx_topic_cluster_runs_status_claimed_at", "status", "claimed_at"),
        Index(
            "idx_topic_cluster_runs_company_id_created_at", "company_id", "created_at"
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bounded on purpose: a provider error can quote a URL or a key fragment, and
    # this value is read back by the dashboard.
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


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


class EmbedToken(BaseModel):
    """The per-website token a deployed widget snippet presents (V3 F4).

    This is **not** a secret in the API-key sense: it ships in a public HTML page
    and any visitor can read and replay it. It exists so an operator can revoke
    the snippets they no longer deploy and can require a token at all
    (`EMBED_TOKEN_MODE=enforce`); it cannot prove browser origin or stop
    deliberate copying (K18 stays an accepted residual).

    Only the SHA-256 hash is stored, like `ApiKey`, and the raw value is shown
    once on mint. The partial unique index below is the real invariant: a website
    has at most one **active** token, so rotation can revoke the old row and insert
    the new one in one transaction without ever exposing two live tokens.
    """

    __tablename__ = "embed_tokens"

    __table_args__ = (
        UniqueConstraint("token_hash"),
        # Not a UniqueConstraint: revoked rows must accumulate as history, so the
        # uniqueness covers only the active one. The index also serves the active
        # lookup by website, which is why there is no separate website_id index.
        Index(
            "uq_embed_tokens_website_id_active",
            "website_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            # The test suite runs on SQLite; without the same predicate there it
            # would build a plain unique index and reject the revoked history
            # that rotation depends on, so the tests could not see the real rule.
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    # The same 12-character prefix convention as `ApiKey.key_prefix`: enough to
    # recognize a token in the UI without making it usable.
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Throttled by the guard: at most one write per token per minute.
    last_used_at: Mapped[datetime | None] = mapped_column(
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
        # Retention filters settled rows by status + age; without this the hourly
        # pass is a sequential scan of every delivery ever stored.
        Index("idx_integration_deliveries_status_created_at", "status", "created_at"),
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


class Subscription(BaseModel):
    """One company's current Stripe subscription state (M11, V5 F2).

    A single row per company is the whole lifecycle record: the unique
    `company_id` means a second Checkout can never create a second paid
    subscription by accident, and the stored Stripe customer/subscription ids are
    the only trusted mapping from a webhook back to a tenant. `last_event_at` is
    the Stripe event timestamp that produced the current state, so a delayed or
    replayed older event cannot restore stale access.

    No card data, price object or raw webhook payload is stored — Stripe remains
    the system of record for payment; this row only mirrors confirmed state.
    """

    __tablename__ = "subscriptions"

    __table_args__ = (
        UniqueConstraint("company_id"),
        UniqueConstraint("stripe_customer_id"),
        UniqueConstraint("stripe_subscription_id"),
        CheckConstraint(
            "status IN ('incomplete', 'trialing', 'active', 'past_due', "
            "'unpaid', 'canceled', 'paused')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "interval IS NULL OR interval IN ('month', 'year')",
            name="ck_subscriptions_interval",
        ),
        # The platform console lists subscriptions by lifecycle state and renewal
        # date (V5 Wave 4); this is the read that must not scan the table.
        Index(
            "idx_subscriptions_status_current_period_end",
            "status",
            "current_period_end",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    # The approved catalog code selected at Checkout (server-resolved, never a
    # client-supplied price or Stripe Price ID).
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    interval: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # "incomplete" until a verified webhook confirms Stripe's own state.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="incomplete"
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Stripe's `created` for the newest applied event: the out-of-order guard.
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BillingEvent(BaseModel):
    """The minimal idempotency receipt for one Stripe webhook event (M11).

    The unique Stripe event id is the replay protection: the row is inserted
    before any state change, so a retried or concurrent delivery of the same
    event loses the insert instead of applying twice. Only the fields needed to
    reconcile and support an account are kept — never the raw payload, a card or
    a customer's personal details.
    """

    __tablename__ = "billing_events"

    __table_args__ = (
        UniqueConstraint("stripe_event_id"),
        Index("idx_billing_events_created_at", "created_at"),
    )

    stripe_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Stripe's own event timestamp (seconds), not our receipt time.
    stripe_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlatformOwner(BaseModel):
    """One out-of-band operator grant bound to an existing user (M12, V5-40).

    This is the **operator** boundary, deliberately separate from every tenant
    role: `users.role='admin'` never implies it, and no company endpoint can
    grant or revoke it. A grant is created out of band
    (`scripts/platform_owner.py`) and revoked by stamping `revoked_at`, so the
    history of who held operator access survives while only one grant per user
    can be active.

    The partial unique index is the whole invariant: a user has at most one
    **active** grant, so a revoked row stays as history and a re-grant inserts a
    fresh one. Revocation is a timestamp, never a delete.
    """

    __tablename__ = "platform_owners"

    __table_args__ = (
        Index(
            "uq_platform_owners_user_id_active",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            # The suite runs on SQLite; without the predicate there a plain
            # unique index would reject the revoked history re-granting needs.
            sqlite_where=text("revoked_at IS NULL"),
        ),
        Index("idx_platform_owners_revoked_at", "revoked_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Free-text operator note ("on-call SRE, ticket OPS-12"). Never a secret.
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user = relationship("User", passive_deletes=True)


class PlatformAuditLog(BaseModel):
    """An append-only record of a platform-owner action (M12, V5-40).

    `actor_user_id` covers an action taken through the API; `actor_label` covers
    the out-of-band CLI, which has no authenticated session but still has to say
    who ran it. `detail` is JSON already redacted by the writer, and the table
    carries no raw request body, token or credential column at all.
    """

    __tablename__ = "platform_audit_logs"

    __table_args__ = (
        # Newest-first console reads: the only query shape this table has.
        Index("idx_platform_audit_logs_created_at", "created_at"),
        Index("idx_platform_audit_logs_target", "target_type", "target_id"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Operator identity for an out-of-band action (CLI `--actor`), e.g. an email
    # or a ticket handle. Not a credential and never checked as one.
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    actor = relationship("User", passive_deletes=True)
