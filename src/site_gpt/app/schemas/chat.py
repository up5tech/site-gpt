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
