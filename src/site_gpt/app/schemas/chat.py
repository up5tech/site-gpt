from uuid import UUID

from pydantic import BaseModel


class ChatRequest(BaseModel):
    website_id: UUID
    question: str
    session_id: str
