from pydantic import BaseModel


class DigestTopic(BaseModel):
    term: str
    count: int


class UnansweredQuestion(BaseModel):
    question: str | None = None
    website_id: str
    website_name: str | None = None
    session_id: str
    asked_at: str
    # Deep link into the admin transcript: ?website=…&focus=session
    link: str


class DigestData(BaseModel):
    company_id: str
    period_start: str
    period_end: str
    conversation_volume: int
    message_count: int
    new_contacts: int
    feedback_up: int
    feedback_down: int
    top_topics: list[DigestTopic] = []
    unanswered_questions: list[UnansweredQuestion] = []


class DigestPreview(BaseModel):
    """What would be emailed for the current period; nothing is sent."""

    period_start: str
    period_end: str
    html: str
    summary: DigestData


class DigestSendResult(BaseModel):
    status: str  # "sent" | "skipped" | "empty" | "failed"
    reason: str | None = None
    recipients: int | None = None
    period_start: str | None = None


class AnalyticsSummary(DigestData):
    """The same aggregation as the digest, over a rolling window."""

    days: int
