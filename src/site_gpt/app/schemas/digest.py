from pydantic import BaseModel


class DigestTopic(BaseModel):
    term: str
    count: int


class DigestGroup(BaseModel):
    """A named topic group, read back from the stored clusters (V3 F2).

    Present only when the period was exactly one completed digest week;
    `sampled_messages`/`eligible_messages` (the week's counts, the same on every
    group) disclose a truncated sample.
    """

    label: str
    summary: str | None = None
    sampled_messages: int
    eligible_messages: int


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
    # Empty when clustering is off or the period is not exactly covered; the
    # term counts above are then the answer (and stay populated either way).
    topic_groups: list[DigestGroup] = []
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
