from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FeedbackItem(BaseModel):
    """One 👍/👎 row with its question and answer resolved server-side.

    `question` and `answer` are read from `chat_messages` through the stored
    `message_id`; they are NULL for rows written before V2 or without a link.
    """

    id: UUID
    website_id: UUID
    session_id: str
    rating: str  # "up" | "down"
    comment: str | None = None
    message_id: UUID | None = None
    status: str  # "pending" | "approved" | "rejected"
    reviewed_answer: str | None = None
    question: str | None = None
    answer: str | None = None
    created_at: datetime


class FeedbackReview(BaseModel):
    """An admin decision for one row; omitted fields keep their value."""

    status: str | None = None  # "pending" | "approved" | "rejected"
    reviewed_answer: str | None = None
