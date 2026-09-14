import asyncio
from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.api.setting import _default_setting_rows
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
)
from site_gpt.app.schemas.company import CompanyRegister
from site_gpt.app.schemas.user import UserLogin
from site_gpt.app.services.conversations import (
    delete_conversation,
    get_conversation_messages,
    list_conversations,
    list_recent_conversations,
)
from site_gpt.app.services.rag import ask, ask_stream
from site_gpt.app.services.ratelimit import rate_limit
from site_gpt.app.services.redis import enqueue_job, redis_client

router = APIRouter()


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
    website.ingest_status = "processing"
    db.commit()
    await enqueue_job({"type": "ingest", "website_id": website_id})
    return {"status": "ok"}


@router.post("/api/chat")
def chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit("chat", max_requests=20, window_seconds=60)),
):
    return ask(db, body.website_id, body.session_id, body.question)


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


@router.get("/api/widget-config")
def widget_config(website_id: str, db: Session = Depends(get_db)):
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
    settings = (
        db.query(models.Setting)
        .filter(models.Setting.company_id == website.company_id)
        .all()
    )
    return {s.key: s.value for s in settings}


@router.post("/api/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit("chat", max_requests=20, window_seconds=60)),
):
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
def health(db: Session = Depends(get_db)):
    """Liveness/readiness probe. Verifies DB and Redis connectivity so an
    orchestrator can detect a degraded backend instead of a blind 'ok'."""
    result: dict = {"status": "ok", "db": False, "redis": False}
    try:
        db.execute(text("SELECT 1"))
        result["db"] = True
    except Exception:
        pass
    try:
        loop = asyncio.new_event_loop()
        result["redis"] = bool(loop.run_until_complete(redis_client.ping()))
        loop.close()
    except Exception:
        pass
    if not (result["db"] and result["redis"]):
        result["status"] = "degraded"
    return result


@router.post("/api/register")
def register(
    registration: CompanyRegister,
    db: Session = Depends(get_db),
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
def get_token(login: UserLogin, db: Session = Depends(get_db)):
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


@router.get("/widget.js")
def get_widget_js():
    return FileResponse(
        "./src/site_gpt/app/scripts/widget.js", media_type="application/javascript"
    )
