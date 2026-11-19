import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.api.setting import (
    WIDGET_PUBLIC_KEYS,
    _default_setting_rows,
    company_daily_message_limit,
)
from site_gpt.app.core.auth import (
    create_access_token,
    get_manager_user,
    hash_password,
    verify_password,
)
from site_gpt.app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.chat import (
    ChatRequest,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationSummary,
    FeedbackRequest,
    RecentConversation,
    RecentConversationsResponse,
    WidgetMessage,
    WidgetMessagesResponse,
)
from site_gpt.app.schemas.company import CompanyRegister
from site_gpt.app.services.integrations import emit_event
from site_gpt.app.schemas.contact import (
    ContactCreate,
    ContactListResponse,
    ContactRes,
)
from site_gpt.app.schemas.session_token import (
    SessionTokenRequest,
    SessionTokenResponse,
)
from site_gpt.app.schemas.user import UserLogin
from site_gpt.app.services import rag
from site_gpt.app.services.conversations import (
    agent_engaged,
    delete_conversation,
    get_conversation_messages,
    human_handling,
    list_conversations,
    list_recent_conversations,
    widget_state,
)
from site_gpt.app.services.embed_guard import ensure_embed_allowed
from site_gpt.app.services.ingest_claim import claim_ingest
from site_gpt.app.services.quota import (
    QUOTA_MESSAGE,
    consume_message,
    quota_sse_events,
)
from site_gpt.app.services.rag import ask, ask_stream
from site_gpt.app.services.ratelimit import limiter_backend, limiter_degraded, rate_limit_policy
from site_gpt.app.services import session_tokens as session_token_queries
from site_gpt.app.services.redis import enqueue_job, ping as redis_ping
from site_gpt.app.services.website_state import ensure_website_active

router = APIRouter()


@router.post("/api/ingest")
async def ingest(
    website_id: _UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
    _: None = Depends(rate_limit_policy("ingest")),
):
    website = (
        db.query(models.Website)
        .filter(
            models.Website.id == website_id,
            models.Website.company_id == user.company_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    ensure_website_active(website)

    # One ingest per website at a time. The claim is a single atomic UPDATE
    # (services/ingest_claim.py), so exactly one concurrent request can win it
    # and only the winner enqueues a crawl.
    if not claim_ingest(db, website.id, user.company_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingest is already running for this website.",
        )

    await enqueue_job({"type": "ingest", "website_id": str(website_id)})
    return {"status": "ok"}


@router.post("/api/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_policy("chat")),
):
    website = (
        db.query(models.Website)
        .filter(models.Website.id == body.website_id)
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website, allow_authenticated=True)
    # A teammate owns the session: store the visitor's message and stop. The bot
    # must not answer over the agent, and since nothing is generated no LLM call
    # is made and no daily quota is spent.
    if await asyncio.to_thread(human_handling, db, website.id, body.session_id):
        return await asyncio.to_thread(
            rag.queue_visitor_message, db, website.id, body.session_id, body.question
        )
    # Daily per-website ceiling: per-IP limits do not bound a viral embed. The
    # company's own setting wins; without one the env default applies.
    if not await consume_message(
        website.id, limit=company_daily_message_limit(db, website.company_id)
    ):
        return {"answer": QUOTA_MESSAGE, "sources": []}
    # `ask` does blocking I/O (embedding, pgvector, LLM); keep it off the loop,
    # which this handler now shares because it awaits the quota check.
    return await asyncio.to_thread(
        ask, db, body.website_id, body.session_id, body.question
    )


@router.post("/api/chat/feedback")
def chat_feedback(
    body: FeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_policy("feedback")),
):
    """Record a 👍/👎 rating for a chat answer. Public (no auth) so the
    embeddable widget can call it directly from any site."""
    website = (
        db.query(models.Website)
        .filter(models.Website.id == body.website_id)
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    rating = body.rating
    if rating not in ("up", "down"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rating must be 'up' or 'down'",
        )
    # A rating may point at the exact answer it judges. It must belong to this
    # website and session, otherwise the admin review would show another
    # visitor's answer; absent is fine (pre-V2 embeds), wrong is a client error.
    message = None
    if body.message_id is not None:
        message = (
            db.query(models.ChatMessage)
            .filter(
                models.ChatMessage.id == body.message_id,
                models.ChatMessage.website_id == body.website_id,
                models.ChatMessage.session_id == body.session_id,
                models.ChatMessage.role == "assistant",
            )
            .first()
        )
        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
            )
    feedback = models.ChatFeedback(
        website_id=body.website_id,
        session_id=body.session_id,
        rating=rating,
        comment=body.comment,
        message_id=message.id if message is not None else None,
    )
    db.add(feedback)
    db.commit()
    # Integration hook (F7). `emit_event` never raises, so a dead webhook can
    # never turn a visitor's rating into an error.
    emit_event(
        db,
        website.company_id,
        "feedback.received",
        {
            "website_id": str(website.id),
            "website_name": website.name,
            "session_id": body.session_id,
            "rating": rating,
            "comment": body.comment or "",
        },
    )
    return {"status": "ok"}


@router.post("/api/contacts")
def upsert_contact(
    body: ContactCreate,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_policy("contacts")),
):
    """Public: save the visitor's contact info before chatting.

    Upsert on (website_id, session_id) so resubmits overwrite instead of
    duplicating. No auth, by design — same scoping as the chat endpoints."""
    if not body.session_id.strip() or not body.first_name.strip() or not body.last_name.strip() or not body.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id, first_name, last_name and email are required",
        )
    website = (
        db.query(models.Website)
        .filter(models.Website.id == body.website_id)
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website)
    # Consent (F9) is enforced here, not only in the widget: a form that forgets
    # the checkbox, or a caller posting straight to the API, must not store a
    # lead the owner said they need consent for.
    consent_setting = (
        db.query(models.Setting)
        .filter(
            models.Setting.company_id == website.company_id,
            models.Setting.key == "require_consent",
        )
        .first()
    )
    requires_consent = bool(
        consent_setting
        and (consent_setting.value or "").strip().lower() == "true"
    )
    if requires_consent and body.consent is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required to save contact details",
        )
    contact = (
        db.query(models.Contact)
        .filter(
            models.Contact.website_id == body.website_id,
            models.Contact.session_id == body.session_id,
        )
        .first()
    )
    if contact:
        contact.first_name = body.first_name.strip()
        contact.last_name = body.last_name.strip()
        contact.email = body.email.strip()
    else:
        contact = models.Contact(
            website_id=body.website_id,
            session_id=body.session_id,
            first_name=body.first_name.strip(),
            last_name=body.last_name.strip(),
            email=body.email.strip(),
        )
        db.add(contact)
    # Stamped only on an actual yes; a later submission that omits `consent`
    # leaves the recorded timestamp alone rather than erasing the proof.
    if body.consent is True:
        contact.consent_at = datetime.now(UTC)
    db.commit()
    db.refresh(contact)
    # Integration hook (F7): the lead is stored before this runs, so a failing
    # integration cannot cost the owner the contact.
    emit_event(
        db,
        website.company_id,
        "lead.captured",
        {
            "website_id": str(website.id),
            "website_name": website.name,
            "session_id": contact.session_id,
            "email": contact.email,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
        },
    )
    return ContactRes.model_validate(contact)


@router.get("/api/contacts", response_model=ContactListResponse)
def list_contacts_endpoint(
    website_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """List a website's contacts. Manager-scoped by company."""
    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = (
        db.query(models.Website)
        .filter(
            models.Website.id == site_uuid,
            models.Website.company_id == user.company_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    q = (
        db.query(models.Contact)
        .filter(models.Contact.website_id == website.id)
        .order_by(models.Contact.created_at.desc())
    )
    total = q.count()
    rows = q.limit(limit).offset(offset).all()
    return ContactListResponse(
        items=[ContactRes.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/api/contacts/{session_id}", response_model=ContactRes)
def get_contact_endpoint(
    session_id: str,
    website_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    """Public: fetch one session's contact.

    Lets the widget restore (or prefill) contact info after localStorage
    was cleared. Same `website_id` scoping as the chat endpoints — no auth,
    by design."""
    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = (
        db.query(models.Website).filter(models.Website.id == site_uuid).first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website)
    # K4: same guard as the conversation read — this one returns an email.
    session_token_queries.authorize(db, website, session_id, x_session_token)
    contact = (
        db.query(models.Contact)
        .filter(
            models.Contact.website_id == site_uuid,
            models.Contact.session_id == session_id,
        )
        .first()
    )
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found"
        )
    return ContactRes.model_validate(contact)


def _session_website(db: Session, website_id: str) -> models.Website:
    """Resolve the website of a public session request (400/404 like the rest)."""
    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = db.query(models.Website).filter(models.Website.id == site_uuid).first()
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    return website


@router.post("/api/session-token", response_model=SessionTokenResponse)
def mint_session_token(
    body: SessionTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    _: None = Depends(rate_limit_policy("session-token")),
):
    """K4: mint (or rotate) the token the widget uses to read its own session.

    A new session gets one token; an existing session can only *rotate* with the
    token it already has (expiry does not block rotation). A session that was
    created before tokens existed cannot be claimed this way at all — otherwise
    knowing an id would be enough to obtain the credential.
    """
    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required"
        )
    website = _session_website(db, str(body.website_id))
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website)

    row = session_token_queries.row_for(db, website.id, session_id)
    if row is not None:
        # `mint` owns the rotation rules (presented token, revocation, absolute
        # lifetime) so the route cannot drift from them: it raises the 403 itself.
        token, row = session_token_queries.mint(
            db, website.id, session_id, presented_token=x_session_token
        )
        return SessionTokenResponse(token=token, expires_at=row.expires_at)

    if session_token_queries.session_has_data(db, website.id, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This session predates session tokens and cannot be claimed",
        )

    token, row = session_token_queries.mint(
        db, website.id, session_id, presented_token=x_session_token
    )
    return SessionTokenResponse(token=token, expires_at=row.expires_at)


@router.get("/api/widget-config")
def widget_config(
    website_id: str, request: Request, db: Session = Depends(get_db)
):
    """Public, unauthenticated config the embeddable widget fetches by
    website id: assistant name, colors, greeting, placeholder, position and
    suggested questions. Replaces the need to hardcode these in ChatWidgetConfig."""
    from uuid import UUID as _UUID

    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = (
        db.query(models.Website).filter(models.Website.id == site_uuid).first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website)
    # Allowlist only: this endpoint is public, so internal settings added in
    # future must never leak through it (see WIDGET_PUBLIC_KEYS).
    settings = (
        db.query(models.Setting)
        .filter(
            models.Setting.company_id == website.company_id,
            models.Setting.key.in_(WIDGET_PUBLIC_KEYS),
        )
        .all()
    )
    payload = {s.key: s.value for s in settings if s.key in WIDGET_PUBLIC_KEYS}

    # Every visitor's browser asks for this before the widget paints. A short
    # public TTL lets it be reused, and the ETag on the payload lets that reuse
    # be revalidated instead of paying a DB round trip each page load.
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    etag = '"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16] + '"'
    headers = {
        "Cache-Control": (
            f"public, max-age={WIDGET_CONFIG_MAX_AGE}, must-revalidate"
        ),
        "ETag": etag,
    }
    if (request.headers.get("if-none-match") or "").strip() == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.post("/api/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_policy("stream")),
):
    website = (
        db.query(models.Website)
        .filter(models.Website.id == body.website_id)
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website, allow_authenticated=True)
    # Same rule as the sync handler: while an agent answers, the message is
    # persisted and the stream says so, in the shape the widget already parses.
    if await asyncio.to_thread(human_handling, db, website.id, body.session_id):
        return StreamingResponse(
            rag.queued_stream(db, website.id, body.session_id, body.question),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if not await consume_message(
        website.id, limit=company_daily_message_limit(db, website.company_id)
    ):
        return StreamingResponse(
            quota_sse_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return StreamingResponse(
        ask_stream(db, body.website_id, body.session_id, body.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


WIDGET_STREAM_UNAVAILABLE = (
    "Live updates need Redis; the widget keeps polling the message endpoint"
)
WIDGET_STREAM_IDLE = (
    "No agent is handling this conversation; live updates are off"
)


def _widget_session(
    db: Session,
    website_id: str,
    session_id: str,
    request: Request,
    token: str | None,
) -> models.Website:
    """Resolve + authorize a public widget read (K4, F4, active website).

    The session token — never the embed token alone — is what allows reading a
    session's messages: the embed token is public in the page HTML, so it says
    nothing about who the visitor is.
    """
    website = _session_website(db, website_id)
    ensure_website_active(website)
    ensure_embed_allowed(request, db, website)
    session_token_queries.authorize(db, website, session_id, token)
    return website


@router.get("/api/chat/messages", response_model=WidgetMessagesResponse)
def widget_messages(
    website_id: str,
    session_id: str,
    request: Request,
    after: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    """Public: one session's messages after a `(created_at, id)` cursor.

    This is the widget's fallback when the live stream is blocked or
    reconnecting: the cursor makes it resumable, so an agent reply written
    while the socket was down is still delivered, exactly once.
    """
    website = _widget_session(db, website_id, session_id, request, x_session_token)
    rows = rag.messages_after(db, website.id, session_id, after, limit)
    return WidgetMessagesResponse(
        items=[WidgetMessage(**rag.widget_message(m)) for m in rows],
        next_cursor=rag.message_cursor(rows[-1]) if rows else after,
        state=widget_state(db, website.id, session_id),
    )


@router.get("/api/chat/messages/stream")
async def widget_message_stream(
    website_id: str,
    session_id: str,
    request: Request,
    after: str | None = None,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    """Public SSE of a session's messages: replayed from the cursor, then live.

    Read with `fetch()` so both widget tokens can be sent. Auth, the active
    website check and the embed guard all run before the response starts; with
    Redis unavailable the route answers 503 and the widget polls instead, so a
    Redis outage degrades to the cursor endpoint rather than a hanging socket.
    """
    website = _widget_session(db, website_id, session_id, request, x_session_token)
    # A session nobody escalated (or one an agent already closed) has nothing to
    # stream: refuse before a socket is held, and the widget stops its live path
    # instead of leaving a per-visitor connection open for every page view.
    if not agent_engaged(widget_state(db, website.id, session_id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=WIDGET_STREAM_IDLE
        )
    if not await redis_ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=WIDGET_STREAM_UNAVAILABLE,
        )
    replay = [
        rag.widget_message(m)
        for m in rag.messages_after(db, website.id, session_id, after, 50)
    ]
    return StreamingResponse(
        rag.message_stream(
            website.id, session_id, replay, disconnect=request.is_disconnected
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/conversations", response_model=ConversationListResponse)
def list_conversations_endpoint(
    website_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """List a website's conversations (sessions) for the admin panel.

    Manager-scoped: a user can only see conversations of websites that belong
    to their own company."""
    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = (
        db.query(models.Website)
        .filter(
            models.Website.id == site_uuid,
            models.Website.company_id == user.company_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    summaries, total = list_conversations(db, website.id, limit, offset)
    return ConversationListResponse(
        items=[ConversationSummary(**s) for s in summaries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/conversations/recent", response_model=RecentConversationsResponse
)
def recent_conversations_endpoint(
    limit: int = 10,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Latest conversations across all of the user's company websites.

    Manager-scoped: only the caller's company. Powers the Dashboard preview."""
    items = list_recent_conversations(db, user.company_id, limit)
    return RecentConversationsResponse(
        items=[RecentConversation(**i) for i in items]
    )


@router.get(
    "/api/conversations/{session_id}",
    response_model=ConversationMessagesResponse,
)
def get_conversation_endpoint(
    session_id: str,
    website_id: str,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    """Public: fetch the messages of one conversation.

    Used by the embeddable widget to restore a returning visitor's history.
    Same `website_id` scoping as the chat endpoints — no auth, by design."""
    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = (
        db.query(models.Website).filter(models.Website.id == site_uuid).first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    # K4: the id alone is no longer enough once the session has a token.
    session_token_queries.authorize(db, website, session_id, x_session_token)
    rows = get_conversation_messages(db, website.id, session_id)
    return ConversationMessagesResponse(
        items=[
            {
                "id": m.id,
                "session_id": m.session_id,
                "website_id": m.website_id,
                "role": m.role,
                "message": m.message,
                "created_at": m.created_at,
            }
            for m in rows
        ],
        state=widget_state(db, website.id, session_id),
    )


@router.delete("/api/conversations/{session_id}")
def delete_conversation_endpoint(
    session_id: str,
    website_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Delete a conversation (all its messages). Manager-scoped by company."""
    try:
        site_uuid = _UUID(str(website_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid website_id"
        )
    website = (
        db.query(models.Website)
        .filter(
            models.Website.id == site_uuid,
            models.Website.company_id == user.company_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    deleted = delete_conversation(db, website.id, session_id)
    return {"status": "ok", "deleted": deleted}


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    """Liveness/readiness probe. Verifies DB and Redis connectivity so an
    orchestrator can detect a degraded backend instead of a blind 'ok'.

    The Redis ping must run on the app's own loop: `redis.asyncio` binds its
    connection pool to the loop that first connects, so pinging from a private
    loop (as this endpoint used to) left the shared client attached to a closed
    loop and made the next enqueue fail with "attached to a different loop".
    """
    result: dict = {"status": "ok", "db": False, "redis": False}
    try:
        db.execute(text("SELECT 1"))
        result["db"] = True
    except Exception:
        pass
    try:
        result["redis"] = await redis_ping()
    except Exception:
        pass
    # V3 (F1): the limiter's own degraded signal — independent of the Redis
    # ping above, because the fallback to the per-process cap is a weaker
    # guarantee even while Redis answers again.
    result["rate_limiter"] = {
        "backend": limiter_backend(),
        "degraded": limiter_degraded(),
    }
    if not (result["db"] and result["redis"]):
        result["status"] = "degraded"
    if limiter_degraded():
        result["status"] = "degraded"
    return result


@router.post("/api/register")
def register(
    registration: CompanyRegister,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_policy("register")),
):
    # check params
    if (
        not registration.company_name
        or not registration.first_name
        or not registration.last_name
        or not registration.email
        or not registration.password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All fields are required",
        )
    # check if company exists
    company = (
        db.query(models.Company)
        .filter(models.Company.name == registration.company_name)
        .first()
    )
    if company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company already exists",
        )
    # create company
    company = models.Company(name=registration.company_name, description="")
    db.add(company)
    db.commit()
    hashed_password = hash_password(registration.password)
    user = models.User(
        email=registration.email,
        password_hash=hashed_password,
        company_id=company.id,
        first_name=registration.first_name,
        last_name=registration.last_name,
        role="admin",
        status="active",
    )
    db.add(user)
    db.commit()

    # Seed default company settings so the admin panel is usable immediately.
    for setting in _default_setting_rows(company.id):
        db.add(setting)
    db.commit()

    return {"status": "ok"}


@router.post("/api/token")
def get_token(
    login: UserLogin,
    db: Session = Depends(get_db),
    # Brute-force guard: the login endpoint is public and always reachable.
    _: None = Depends(rate_limit_policy("login")),
):
    user = (
        db.query(models.User)
        .filter(models.User.email == login.email, models.User.status == "active")
        .first()
    )

    if not user or not verify_password(login.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email},
        secret_key=JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    return {"access_token": access_token, "token_type": "bearer"}


# The widget is served to customers' sites, so a cache has to be short enough
# that a deployed fix reaches them on its own, while the ?v=<version> query in
# the install snippet busts it immediately.
WIDGET_JS_PATH = "./src/site_gpt/app/scripts/widget.js"
# Short enough that a settings change reaches embedded sites quickly, long
# enough that a page view does not repeat the widget-config DB query.
WIDGET_CONFIG_MAX_AGE = 60

WIDGET_JS_MAX_AGE = 300
_widget_version_cache: tuple[float, int, str] | None = None


def widget_version(path: str = WIDGET_JS_PATH) -> str:
    """Short content hash of widget.js — changes exactly when the file does."""
    global _widget_version_cache
    stat = os.stat(path)
    key = (stat.st_mtime, stat.st_size)
    if _widget_version_cache is None or _widget_version_cache[:2] != key:
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:8]
        _widget_version_cache = (key[0], key[1], digest)
    return _widget_version_cache[2]


@router.get("/widget.js")
def get_widget_js():
    return FileResponse(
        WIDGET_JS_PATH,
        media_type="application/javascript",
        headers={
            "Cache-Control": (
                f"public, max-age={WIDGET_JS_MAX_AGE}, must-revalidate"
            ),
            "X-Widget-Version": widget_version(),
        },
    )
