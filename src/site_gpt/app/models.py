import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from site_gpt.app.db.base import BaseModel


class Company(BaseModel):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(nullable=True)
    expired_at: Mapped[datetime] = mapped_column(nullable=True)


class User(BaseModel):
    __tablename__ = "users"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=True, default="user")
    status: Mapped[str] = mapped_column(String(50), nullable=True, default="active")


class Setting(BaseModel):
    __tablename__ = "settings"

    __table_args__ = (Index("idx_settings_company_id", "company_id"),)

    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False
    )


class Website(BaseModel):
    __tablename__ = "websites"

    __table_args__ = (Index("idx_websites_company_id", "company_id"),)

    url: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False
    )
    site_map_url: Mapped[str] = mapped_column(String(255), nullable=False)


class Document(BaseModel):
    __tablename__ = "documents"

    __table_args__ = (Index("idx_documents_website_id", "website_id"),)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("websites.id"), nullable=False
    )


class ExtraDocument(BaseModel):
    __tablename__ = "extra_documents"

    __table_args__ = (Index("idx_extra_documents_company_id", "company_id"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False
    )


class Attachment(BaseModel):
    __tablename__ = "attachments"

    extra_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extra_documents.id"), nullable=False
    )

    filename: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(50))
    file_size: Mapped[int] = mapped_column(nullable=True)


class Embedding(BaseModel):
    __tablename__ = "embeddings"

    __table_args__ = (
        Index("idx_embeddings_document_id", "document_id"),
        Index("idx_embeddings_extra_document_id", "extra_document_id"),
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )
    extra_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extra_documents.id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(1536))
