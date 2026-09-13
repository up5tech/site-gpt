from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatRequest(BaseModel):
    website_id: UUID
    question: str
    session_id: str


class ChatSource(BaseModel):
    """A citation shown under an answer: where the answer came from."""

    title: str | None = None
    url: str | None = None
    source_type: str | None = None  # "page" (crawled) or "document" (uploaded)


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource] = []


class FeedbackRequest(BaseModel):
    """👍/👎 rating for a chat answer (public, used by the widget)."""

    website_id: UUID
    session_id: str
    rating: str  # "up" | "down"
    comment: str | None = None


class ConversationMessage(BaseModel):
    """A single stored message inside a conversation (chat_messages row)."""

    id: UUID
    session_id: str
    website_id: UUID
    role: str  # "user" | "assistant"
    message: str
    created_at: datetime


class ConversationSummary(BaseModel):
    """One row in the conversation list: a session_id grouped with metadata."""

    session_id: str
    website_id: UUID
    title: str | None = None  # first user message, truncated for display
    message_count: int
    created_at: datetime
    last_message_at: datetime


class ConversationListResponse(BaseModel):
    """Paginated list of conversations for a website."""

    items: list[ConversationSummary] = []
    total: int
    limit: int
    offset: int


class ConversationMessagesResponse(BaseModel):
    """All messages of a single conversation, oldest first."""

    items: list[ConversationMessage] = []


class RecentConversation(BaseModel):
    """A recently active conversation across the whole company (any website)."""

    session_id: str
    website_id: UUID
    website_name: str
    title: str | None = None  # first user message, truncated
    message_count: int
    last_message_at: datetime


class RecentConversationsResponse(BaseModel):
    """Latest conversations across all of the company's websites."""

    items: list[RecentConversation] = []
