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
    # The stored assistant message, so a rating can point at the exact answer
    # (F4). Absent only on paths that persist nothing (e.g. the quota notice).
    message_id: UUID | None = None


class FeedbackRequest(BaseModel):
    """👍/👎 rating for a chat answer (public, used by the widget)."""

    website_id: UUID
    session_id: str
    rating: str  # "up" | "down"
    comment: str | None = None
    # Optional so a widget that has not been reloaded (or any pre-V2 embed) keeps
    # working; without it the row is stored but not trainable.
    message_id: UUID | None = None


class ConversationMessage(BaseModel):
    """A single stored message inside a conversation (chat_messages row)."""

    id: UUID
    session_id: str
    website_id: UUID
    role: str  # "user" | "assistant" | "agent" (a human teammate)
    message: str
    created_at: datetime


class WidgetMessage(BaseModel):
    """A message the widget renders from its live/poll endpoint (V3-43)."""

    id: UUID
    role: str  # "user" | "assistant" | "agent"
    message: str
    created_at: datetime


class WidgetMessagesResponse(BaseModel):
    """One page of a session's messages plus the cursor to resume from."""

    items: list[WidgetMessage] = []
    next_cursor: str | None = None
    # The inbox state, so the widget knows whether an agent is handling this
    # session at all (and can stop polling when it closed).
    state: str | None = None


class ConversationSummary(BaseModel):
    """One row in the conversation list: a session_id grouped with metadata."""

    session_id: str
    website_id: UUID
    title: str | None = None  # first user message, truncated for display
    message_count: int
    created_at: datetime
    last_message_at: datetime
    # M9 inbox state. Both stay `None` for a session whose row does not exist
    # yet (every session recorded before V3), so the old shape still parses.
    conversation_id: UUID | None = None
    state: str | None = None


class ConversationListResponse(BaseModel):
    """Paginated list of conversations for a website."""

    items: list[ConversationSummary] = []
    total: int
    limit: int
    offset: int


class ConversationMessagesResponse(BaseModel):
    """All messages of a single conversation, oldest first."""

    items: list[ConversationMessage] = []
    # Same signal as the widget message endpoint: a restored history that is
    # still `waiting`/`human` turns the widget's live path on after a reload.
    state: str | None = None


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
