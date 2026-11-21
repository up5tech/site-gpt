from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer


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


class TrendPoint(BaseModel):
    """One UTC day of the rolling window (V4 F1).

    `conversations` is that day's distinct sessions, so the daily rows do not sum
    to `conversation_volume`; `unanswered` counts answers tagged `answered=False`.
    """

    date: str
    conversations: int
    messages: int
    visitor_messages: int
    new_contacts: int
    feedback_up: int
    feedback_down: int
    unanswered: int


class FunnelStage(BaseModel):
    """One engagement stage: `started` | `answered` | `lead` | `handoff` | `human`.

    Stages are counts of distinct sessions that overlap, not a strict subset
    chain (D4): a lead without a handoff still counts, and so does a handoff that
    never reached a human.
    """

    stage: str
    sessions: int


class TopQuestion(BaseModel):
    """A normalized visitor question and how often it was asked (D4)."""

    question: str
    count: int


class OutcomeCount(BaseModel):
    """One insight label and how many classified conversations ended with it.

    Every allowed label is present, zeros included, so the dashboard's shape does
    not depend on what a window happens to contain.
    """

    value: str
    count: int


class Outcomes(BaseModel):
    """The window's sentiment/resolution breakdown (V4 F2, opt-in only).

    Only `completed` insight rows count: a `processing` row has no verdict yet and
    a `failed` row keeps its previous labels but is not a fresh result.
    """

    classified: int
    sentiment: list[OutcomeCount] = []
    resolution: list[OutcomeCount] = []


class AnalyticsSummary(DigestData):
    """The same aggregation as the digest, over a rolling window.

    `trend`, `funnel` and `top_questions` are additive (V4 F1): every V3 key keeps
    its exact meaning and value, so `/api/v1/analytics/summary` gains the fields
    without breaking an existing client. `outcomes` is the V4 F2 addition and is
    only ever populated for an opted-in company (`_omit_absent_outcomes`).
    """

    days: int
    trend: list[TrendPoint] = []
    funnel: list[FunnelStage] = []
    top_questions: list[TopQuestion] = []
    outcomes: Outcomes | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_outcomes(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict:
        """Drop `outcomes` when insights are off — absent, not null.

        With the flag off the summary must stay the V4-1G payload byte for byte,
        so a V3 client reads exactly the keys it always had; only a company that
        opted in ever sees the extra key.
        """
        data = handler(self)
        if data.get("outcomes") is None:
            data.pop("outcomes", None)
        return data
