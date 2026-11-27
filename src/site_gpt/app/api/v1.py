"""Versioned, API-key-authenticated surface (SPEC F8).

Every route here reuses the shared service helpers rather than copying route
logic: `ensure_website_active` for a disabled bot, `ensure_embed_allowed` for a
foreign Origin, `claim_ingest` for the one-crawl-per-website race,
`list_conversations`, `rag.ask`, `build_digest` and `apply_settings`. All resource
lookups are scoped by the key's `company_id`, never by anything the caller sends.

The settings surface is deliberately narrower than the admin one: only the public
widget keys and the chat-model pair can be read or written here, so a leaked key
cannot redirect handoff mail, change digest recipients or raise a message quota.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.api.setting import WIDGET_PUBLIC_KEYS, apply_settings
from site_gpt.app.api.setting import (
    company_daily_message_limit,
    company_session_message_limit,
)
from site_gpt.app.core.auth import get_api_key, require_scope
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationListResponse,
)
from site_gpt.app.schemas.contact import ContactListResponse, ContactRes
from site_gpt.app.schemas.digest import AnalyticsSummary
from site_gpt.app.schemas.setting import SettingRes
from site_gpt.app.services import analytics, entitlements
from site_gpt.app.services.conversations import list_conversations
from site_gpt.app.services.digest import build_digest
from site_gpt.app.services.embed_guard import ensure_embed_allowed
from site_gpt.app.services.ingest_claim import claim_ingest
from site_gpt.app.services.quota import (
    SESSION_CAP_MESSAGE,
    consume_message,
    consume_session_message,
)
from site_gpt.app.services.rag import ask
from site_gpt.app.services.redis import enqueue_job
from site_gpt.app.services.website_state import ensure_website_active

router = APIRouter()

# Keys a key-authenticated caller may read or write. Public widget keys plus the
# chat-model pair; everything internal (mail, digest, quota) stays admin-only.
API_SETTABLE_KEYS: tuple[str, ...] = WIDGET_PUBLIC_KEYS + (
    "llm_provider",
    "llm_model",
)


def _scoped_website(db: Session, api_key: models.ApiKey, website_id: UUID):
    """The website only if it belongs to the key's company."""
    website = (
        db.query(models.Website)
        .filter(
            models.Website.id == website_id,
            models.Website.company_id == api_key.company_id,
        )
        .first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    return website


@router.post("/ingest", tags=["v1"])
async def ingest(
    website_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """Queue a crawl for one website. Requires the `ingest:write` scope."""
    require_scope(api_key, "ingest:write")

    website = _scoped_website(db, api_key, website_id)

    ensure_website_active(website)
    # The caller authenticated with a secret key, so the browser-oriented embed
    # token is not required here: turning on `EMBED_TOKEN_MODE=enforce` must not
    # break an existing `/api/v1` integration.
    ensure_embed_allowed(request, db, website, require_embed_token=False)

    if not claim_ingest(db, website.id, api_key.company_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingest is already running for this website.",
        )

    await enqueue_job({"type": "ingest", "website_id": str(website.id)})
    return {"status": "ok", "website_id": str(website.id)}


@router.get("/settings", tags=["v1"], response_model=list[SettingRes])
def get_settings_v1(
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """The writable settings of this company. Requires the `read` scope."""
    require_scope(api_key, "read")
    rows = (
        db.query(models.Setting)
        .filter(
            models.Setting.company_id == api_key.company_id,
            models.Setting.key.in_(API_SETTABLE_KEYS),
        )
        .order_by(models.Setting.key)
        .all()
    )
    return [SettingRes.model_validate(row, from_attributes=True) for row in rows]


@router.put("/settings", tags=["v1"])
def put_settings_v1(
    settings: list[SettingRes],
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """Upsert settings. Requires the `settings:write` scope."""
    require_scope(api_key, "settings:write")

    unknown = sorted({setting.key for setting in settings} - set(API_SETTABLE_KEYS))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not settable through the API: {', '.join(unknown)}. "
            f"Allowed: {', '.join(API_SETTABLE_KEYS)}.",
        )

    written = apply_settings(
        db,
        api_key.company_id,
        [(setting.key, setting.value) for setting in settings],
        # An API-key caller has no user session; the prefix identifies the key
        # without storing the key or its hash (V6-14).
        actor_label=f"api-key:{api_key.key_prefix}",
    )
    return {"updated": written}


@router.get(
    "/conversations", tags=["v1"], response_model=ConversationListResponse
)
def get_conversations_v1(
    website_id: UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """A website's conversations, newest first. Requires the `read` scope."""
    require_scope(api_key, "read")
    website = _scoped_website(db, api_key, website_id)
    summaries, total = list_conversations(db, website.id, limit, offset)
    return ConversationListResponse(
        items=summaries,
        total=total,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )


@router.get("/contacts", tags=["v1"], response_model=ContactListResponse)
def get_contacts_v1(
    website_id: UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """A website's captured contacts. Requires the `read` scope."""
    require_scope(api_key, "read")
    website = _scoped_website(db, api_key, website_id)

    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    query = (
        db.query(models.Contact)
        .filter(models.Contact.website_id == website.id)
        .order_by(models.Contact.created_at.desc())
    )
    total = query.count()
    rows = query.limit(limit).offset(offset).all()
    return ContactListResponse(
        items=[ContactRes.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/chat", tags=["v1"], response_model=ChatResponse)
async def chat_v1(
    body: ChatRequest,
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """Ask one website a question. Requires the `chat:write` scope."""
    require_scope(api_key, "chat:write")
    website = _scoped_website(db, api_key, body.website_id)
    ensure_website_active(website)

    # Same order as the widget (V4 F4, D6): the session cap is checked before the
    # daily ceiling, so a capped conversation spends no daily budget. A key
    # caller gets the friendly answer (200) rather than a 429 — the session is
    # capped, not the website.
    # One snapshot for the whole request, shared by both ceilings below.
    snapshot = entitlements.resolve(db, website.company_id)
    if not await consume_session_message(
        website.id,
        body.session_id,
        limit=entitlements.session_message_limit(
            snapshot, company_session_message_limit(db, website.company_id)
        ),
    ):
        return {"answer": SESSION_CAP_MESSAGE, "sources": [], "message_id": None}

    # The company's daily ceiling still applies: a key must not be a way to spend
    # past the limit the owner set for their websites, and the plan ceiling
    # applies here exactly as it does to the widget (V5-31).
    if not await consume_message(
        website.id,
        limit=entitlements.daily_message_limit(
            snapshot, company_daily_message_limit(db, website.company_id)
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="This website reached its daily message limit.",
        )

    # `ask` does blocking I/O (embedding, pgvector, LLM); keep it off the loop.
    return await asyncio.to_thread(
        ask, db, body.website_id, body.session_id, body.question
    )


@router.get("/analytics/summary", tags=["v1"], response_model=AnalyticsSummary)
def get_analytics_v1(
    days: int = 7,
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """Counts, topics, trend, funnel and top questions. Requires the `read` scope."""
    require_scope(api_key, "read")
    days = max(1, min(days, 90))
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    data = build_digest(db, api_key.company_id, start, end)
    return {
        **data,
        "days": days,
        "trend": analytics.daily_trend(db, api_key.company_id, start, end),
        "funnel": analytics.engagement_funnel(db, api_key.company_id, start, end),
        "top_questions": analytics.top_questions(
            db, api_key.company_id, start, end
        ),
    }
