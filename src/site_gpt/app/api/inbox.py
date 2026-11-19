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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.inbox import (
    InboxAssign,
    InboxConversation,
    InboxConversationDetail,
    InboxPresence,
)
from site_gpt.app.services import conversations, inbox
from site_gpt.app.services import redis as redis_service

router = APIRouter()

NOT_ENABLED = "Live inbox is not enabled for this company"
STREAM_UNAVAILABLE = (
    "The live inbox stream needs Redis; poll the queue until it is back"
)


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
    """Take a waiting conversation. The loser of a race gets 409.

    Sync on purpose: this runs a `FOR UPDATE` transaction, and executing it on
    the event loop would stall every open SSE stream while it waits. The
    notification is queued after `inbox.claim` committed (never before, or the
    consoles would be told about a claim the database might still roll back)
    and delivered off the request thread.
    """
    try:
        row = inbox.claim(db, user.company_id, conversation_id, user)
        item = inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc
    inbox.publish_after_commit(
        user.company_id, inbox.conversation_event(row, "claimed")
    )
    return item


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
        item = inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc
    inbox.publish_after_commit(
        user.company_id, inbox.conversation_event(row, "assigned")
    )
    return item


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
        item = inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc
    inbox.publish_after_commit(
        user.company_id, inbox.conversation_event(row, "released")
    )
    return item


@router.post(
    "/conversations/{conversation_id}/close", response_model=InboxConversation
)
def close_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """Close a queued or claimed conversation; no further agent work is expected."""
    try:
        row = inbox.close(db, user.company_id, conversation_id, user)
        item = inbox.item_for(db, user.company_id, row)
    except inbox.InboxNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (inbox.InboxConflict, conversations.ConversationStateError) as exc:
        raise _conflict(exc) from exc
    inbox.publish_after_commit(
        user.company_id, inbox.conversation_event(row, "closed")
    )
    return item


@router.get("/events")
async def inbox_events(
    request: Request,
    user: models.User = Depends(live_inbox_user),
):
    """Live inbox notifications as server-sent events.

    Read with `fetch()` and a streaming body reader, not `EventSource`: the
    console already sends `Authorization: Bearer …` on every call, and
    `EventSource` cannot attach a header. Both gates run **before** the response
    starts — the flag (the whole surface is a 404 when off) and Redis (503, and
    the console keeps polling the queue), because a stream that can never
    deliver anything is worse than a clear failure.

    Notifications are hints: after `ready` and after every event the console
    re-reads the row/list it cares about, so a lost message costs a refresh
    rather than a stale screen. Proxies must not buffer the body
    (`X-Accel-Buffering: no`, `Cache-Control: no-transform`).
    """
    if not await redis_service.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=STREAM_UNAVAILABLE,
        )

    return StreamingResponse(
        inbox.event_stream(
            user.company_id, user.id, disconnect=request.is_disconnected
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/presence", response_model=list[InboxPresence])
async def inbox_presence(
    db: Session = Depends(get_db),
    user: models.User = Depends(live_inbox_user),
):
    """Which agents currently have the inbox open, counted by connection.

    Read from Redis leases rather than the database: presence is ephemeral and
    must disappear on its own when a tab crashes, which a TTL gives for free.
    A Redis outage answers an empty list — the queue is still usable without
    avatars.
    """
    return [
        InboxPresence(**row) for row in await inbox.presence(db, user.company_id)
    ]
