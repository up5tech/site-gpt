"""Live-agent inbox routes (V3-41, F3).

The agent console works on conversations, not sessions: every path carries the
conversation UUID, and the service resolves it inside the caller's company, so a
foreign id is a 404 and the same `session_id` on two websites can never be
confused. This module owns HTTP only — the queue queries, the claim lock and the
state transitions all live in `services/inbox.py` / `services/conversations.py`.

All routes are manager+ (the same RBAC the rest of the admin console uses) *and*
require the company's `live_inbox_enabled` flag: with the flag off every path
here is a 404, so an installation that runs no agent console does not advertise
an empty one. The public handoff endpoint is untouched and keeps working.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.inbox import (
    InboxAssign,
    InboxConversation,
    InboxConversationDetail,
)
from site_gpt.app.services import conversations, inbox

router = APIRouter()

NOT_ENABLED = "Live inbox is not enabled for this company"


def live_inbox_user(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
) -> models.User:
    """A manager+ of a company that turned the inbox on; 404 otherwise.

    Off is indistinguishable from "no such endpoint" on purpose: the feature is
    a per-company rollout, and an agent console that answers "disabled" would
    still tell an outsider that the company has one.
    """
    if not inbox.enabled(db, user.company_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=NOT_ENABLED
        )
    return user


def _conflict(exc: Exception) -> HTTPException:
    """Map a service refusal onto 409 (someone else holds it / bad transition)."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/conversations", response_model=PaginatedResponse)
def list_inbox_conversations(
    state_filter: str | None = Query(default=None, alias="state"),
    website_id: UUID | None = None,
    assigned_user_id: UUID | None = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """The company's inbox, newest activity first, filtered by queue state.

    A `state` the state machine does not define is a 400 rather than an empty
    page, so a typo in the console is visible instead of looking like an empty
    queue.
    """
    if state_filter is not None and state_filter not in conversations.STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state must be bot, waiting, human or closed",
        )
    try:
        items, total = inbox.list_conversations(
            db,
            user.company_id,
            state=state_filter,
            website_id=website_id,
            assigned_user_id=assigned_user_id,
            page=page,
            limit=limit,
        )
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return PaginatedResponse(
        total=total,
        page=max(1, page),
        limit=max(1, min(limit, 100)),
        items=[InboxConversation(**item) for item in items],
    )


@router.get("/conversations/{conversation_id}", response_model=InboxConversationDetail)
def get_inbox_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """One conversation with its transcript and the visitor's contact record."""
    try:
        return inbox.detail(db, user.company_id, conversation_id)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/conversations/{conversation_id}/claim", response_model=InboxConversation
)
def claim_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """Take a waiting conversation. The loser of a race gets 409."""
    try:
        row = inbox.claim(db, user.company_id, conversation_id, user)
        return inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc


@router.post(
    "/conversations/{conversation_id}/assign", response_model=InboxConversation
)
def assign_conversation(
    conversation_id: UUID,
    body: InboxAssign,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """Hand a waiting conversation to a teammate (active manager/admin)."""
    target = inbox.assignable_user(db, user.company_id, body.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    try:
        row = inbox.assign(db, user.company_id, conversation_id, target)
        return inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc


@router.post(
    "/conversations/{conversation_id}/release", response_model=InboxConversation
)
def release_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """Put the conversation back in the queue without closing it."""
    try:
        row = inbox.release(db, user.company_id, conversation_id, user)
        return inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc


@router.post("/conversations/{conversation_id}/close", response_model=InboxConversation)
def close_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """Close a queued or claimed conversation; no further agent work is expected."""
    try:
        row = inbox.close(db, user.company_id, conversation_id, user)
        return inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc
