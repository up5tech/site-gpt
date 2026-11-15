import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    verify_token,
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
)
from site_gpt.app.schemas.company import CompanyRegister
from site_gpt.app.schemas.contact import (
    ContactCreate,
    ContactListResponse,
    ContactRes,
)
from site_gpt.app.schemas.user import UserLogin
from site_gpt.app.services import embed_guard
from site_gpt.app.services.conversations import (
    delete_conversation,
    get_conversation_messages,
    list_conversations,
    list_recent_conversations,
)
from site_gpt.app.services.quota import (
    QUOTA_MESSAGE,
    consume_message,
    quota_sse_events,
)
from site_gpt.app.services.rag import ask, ask_stream
from site_gpt.app.services.ratelimit import rate_limit
from site_gpt.app.services.redis import enqueue_job, redis_client
from site_gpt.app.worker import _is_stuck as _ingest_is_stuck

router = APIRouter()


def _is_authenticated(request: Request, db: Session) -> bool:
    """True when the request carries a valid JWT for an active user.

    The admin playground calls the same public chat endpoints as the widget but
    with the dashboard's token; those requests are not scoped by Origin.
    """
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    try:
        payload = verify_token(token, JWT_SECRET_KEY, [JWT_ALGORITHM])
    except HTTPException:
        return False
    user_id = payload.get("sub")
    if not user_id:
        return False
    return (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.status == "active")
        .first()
        is not None
    )


def _ensure_website_active(website: models.Website) -> None:
    """A website is only served while its `status` is `active`.

    `status` used to be written by the API and never read, so disabling a bot
    meant deleting the website and losing its documents, history and leads.

    Only an explicit other value disables the bot. `websites.status` is
    nullable, so a row created before the switch existed (or written by an old
    form that sent nothing) can hold NULL/empty — that means "never set", and
    treating it as disabled would silently kill a working bot.
    """
    current = (website.status or "").strip().lower()
    if current and current != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This website is disabled.",
        )


def _ensure_embed_allowed(
    request: Request,
    db: Session,
    website: models.Website,
    *,
    allow_authenticated: bool = False,
) -> None:
    """Refuse requests whose Origin/Referer names a foreign site.

    Guards the public widget surface against someone copying a `website_id`
    and embedding another customer's bot from their own site.
    """
    if allow_authenticated and _is_authenticated(request, db):
        return
    if not embed_guard.is_allowed_embed_request(request, website):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This origin is not allowed to embed that assistant.",
        )


@router.post("/api/ingest")
async def ingest(
    website_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
    _: None = Depends(rate_limit("ingest", max_requests=10, window_seconds=60)),
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
    _ensure_website_active(website)
    # One ingest per website at a time: a double click used to enqueue a second
    # crawl that re-embedded the same pages concurrently with the first. A
    # `processing` row older than STUCK_INGEST_AFTER belongs to a worker that
    # died (the scheduler only re-crawls `completed` sites), so a manual retry
    # must still be possible.
    if (website.ingest_status or "") == "processing" and not _ingest_is_stuck(
        website
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingest is already running for this website.",
        )
    website.ingest_status = "processing"
    # Reset the start timestamp, even when the status is already `processing`:
    # a stale take-over must not look stale again on the next request.
    website.updated_at = datetime.now(UTC)
    db.commit()
    await enqueue_job({"type": "ingest", "website_id": website_id})
    return {"status": "ok"}


@router.post("/api/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit("chat", max_requests=20, window_seconds=60)),
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
    _ensure_website_active(website)
    _ensure_embed_allowed(request, db, website, allow_authenticated=True)
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
    _: None = Depends(rate_limit("chat", max_requests=40, window_seconds=60)),
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
    feedback = models.ChatFeedback(
        website_id=body.website_id,
        session_id=body.session_id,
        rating=rating,
        comment=body.comment,
    )
    db.add(feedback)
    db.commit()
    return {"status": "ok"}


@router.post("/api/contacts")
def upsert_contact(
    body: ContactCreate,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit("chat", max_requests=40, window_seconds=60)),
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
    _ensure_website_active(website)
    _ensure_embed_allowed(request, db, website)
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
    db.commit()
    db.refresh(contact)
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
    _ensure_website_active(website)
    _ensure_embed_allowed(request, db, website)
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
    _ensure_website_active(website)
    _ensure_embed_allowed(request, db, website)
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
    _: None = Depends(rate_limit("chat", max_requests=20, window_seconds=60)),
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
    _ensure_website_active(website)
    _ensure_embed_allowed(request, db, website, allow_authenticated=True)
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
        ]
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
        result["redis"] = bool(await redis_client.ping())
    except Exception:
        pass
    if not (result["db"] and result["redis"]):
        result["status"] = "degraded"
    return result


@router.post("/api/register")
def register(
    registration: CompanyRegister,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit("register", max_requests=3, window_seconds=3600)),
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
    _: None = Depends(rate_limit("login", max_requests=10, window_seconds=60)),
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
