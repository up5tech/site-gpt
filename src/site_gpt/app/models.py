import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    embedding = mapped_column(Vector(1536))
