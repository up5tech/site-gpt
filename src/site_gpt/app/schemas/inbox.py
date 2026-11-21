"""Schemas for the live-agent inbox (V3-41, F3).

Every route is addressed by the conversation UUID, so these shapes carry the id
the agent console keeps: a `session_id` alone would be ambiguous across two of a
company's websites.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InboxStatus(BaseModel):
    """Whether the company runs the agent console (V3-44 navigation gate).

    Manager-readable on purpose: the console's navigation needs to know whether
    the page exists without probing a route that answers 404 when it is off.
    """

    enabled: bool


class InboxConversation(BaseModel):
    """One queue entry: who owns it, how far along it is, who the visitor is."""

    id: UUID
    website_id: UUID
    website_name: str | None = None
    session_id: str
    state: str  # "bot" | "waiting" | "human" | "closed"
    assigned_user_id: UUID | None = None
    assigned_user_name: str | None = None
    claimed_at: datetime | None = None
    closed_at: datetime | None = None
    last_message_at: datetime
    created_at: datetime
    message_count: int = 0
    # First visitor question, truncated for display — the same title the
    # conversation list uses.
    title: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    # The AI's read of this conversation (V4 F2, opt-in). All three stay null for
    # a company that never opted in, and a conversation no run has classified yet;
    # they are read from `conversation_insights`, never written here.
    sentiment: str | None = None
    resolution: str | None = None
    summary: str | None = None


class InboxMessage(BaseModel):
    """One stored message of the conversation, including agent replies."""

    id: UUID
    role: str  # "user" | "assistant" | "agent"
    message: str
    author_user_id: UUID | None = None
    author_name: str | None = None
    created_at: datetime


class InboxContact(BaseModel):
    """The lead the visitor left in this session."""

    id: UUID
    first_name: str
    last_name: str
    email: str
    consent_at: datetime | None = None
    created_at: datetime


class InboxConversationDetail(InboxConversation):
    """The queue entry plus everything the agent console shows beside it."""

    messages: list[InboxMessage] = []
    contact: InboxContact | None = None


class InboxAssign(BaseModel):
    """Hand a waiting conversation to a teammate."""

    user_id: UUID


class InboxReply(BaseModel):
    """An agent's reply to the visitor (V3-43).

    Whitespace-only is refused by the route: an empty bubble in the transcript
    would look like a reply the visitor never received.
    """

    message: str


class InboxPresence(BaseModel):
    """An agent watching the inbox right now (V3-42).

    One entry per user, `connections` counting their open event streams: two
    tabs are one agent, and closing one tab leaves the other's lease alive.
    """

    user_id: UUID
    name: str | None = None
    connections: int = 1
