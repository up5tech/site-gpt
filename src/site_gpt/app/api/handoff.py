"""Human handoff — notify and callback, not an agent inbox (F5, ADR-4).

A visitor's click writes one row, emails the team and emits `handoff.requested`;
there is no live chat with an agent. The create endpoint is public and
rate-limited, so it only trusts the message the visitor typed: the website, the
company, the contact and the transcript are all resolved from stored rows.
"""

import html
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.handoff import HandoffCreate, HandoffItem, HandoffUpdate
from site_gpt.app.services import company_settings
from site_gpt.app.services.integrations import emit_event_async
from site_gpt.app.services.mail import send_email_async
from site_gpt.app.services.rag import get_chat_history
from site_gpt.app.services.ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_STATUSES = ("pending", "accepted", "closed")
TRANSCRIPT_LIMIT = 10


def _to_item(db: Session, request: models.HandoffRequest) -> HandoffItem:
    website = (
        db.query(models.Website)
        .filter(models.Website.id == request.website_id)
        .first()
    )
    contact = None
    if request.contact_id is not None:
        contact = (
            db.query(models.Contact)
            .filter(models.Contact.id == request.contact_id)
            .first()
        )
    contact_name = None
    if contact is not None:
        contact_name = f"{contact.first_name} {contact.last_name}".strip() or None
    return HandoffItem(
        id=request.id,
        website_id=request.website_id,
        website_name=website.name if website is not None else None,
        session_id=request.session_id,
        contact_id=request.contact_id,
        contact_name=contact_name,
        contact_email=contact.email if contact is not None else None,
        message=request.message,
        status=request.status,
        channel=request.channel,
        created_at=request.created_at,
    )


def _recipients(db: Session, company_id: UUID) -> list[str]:
    """`handoff_email`, or every active admin/manager of the company."""
    configured = company_settings.emails(
        db,
        company_id,
        company_settings.value(db, company_id, "handoff_email"),
    )
    return configured or company_settings.team_emails(db, company_id)


def _render_email(
    website: models.Website,
    request: models.HandoffRequest,
    contact: models.Contact | None,
    transcript: list[models.ChatMessage],
) -> str:
    """Plain f-string HTML: no templating dependency, nothing user-authored raw."""
    who = "Anonymous visitor"
    if contact is not None:
        name = f"{contact.first_name} {contact.last_name}".strip()
        who = f"{html.escape(name)} &lt;{html.escape(contact.email)}&gt;"
    lines = [
        f"<h2>New handoff request — {html.escape(website.name)}</h2>",
        f"<p><strong>Visitor:</strong> {who}<br>",
        f"<strong>Session:</strong> {html.escape(request.session_id)}<br>",
        f"<strong>Website:</strong> {html.escape(website.url)}</p>",
    ]
    if request.message:
        lines.append(
            f"<p><strong>Message:</strong><br>{html.escape(request.message)}</p>"
        )
    if transcript:
        lines.append("<h3>Recent conversation</h3><ul>")
        for message in transcript:
            speaker = "Visitor" if message.role == "user" else "Assistant"
            lines.append(
                f"<li><strong>{speaker}:</strong> "
                f"{html.escape(message.message or '')}</li>"
            )
        lines.append("</ul>")
    return "".join(lines)


async def _notify(db: Session, website: models.Website, request: models.HandoffRequest):
    """Email the team and emit the event; never raise.

    A missing SMTP configuration or a broken integration must not turn a
    visitor's click into an error: the row is already stored.
    """
    try:
        contact = None
        if request.contact_id is not None:
            contact = (
                db.query(models.Contact)
                .filter(models.Contact.id == request.contact_id)
                .first()
            )
        transcript = get_chat_history(
            db, website.id, request.session_id, TRANSCRIPT_LIMIT
        )
        body = _render_email(website, request, contact, transcript)
        subject = f"Handoff request — {website.name}"
        for recipient in _recipients(db, website.company_id):
            await send_email_async(recipient, subject, body)
    except Exception:
        logger.exception("handoff %s could not be emailed", request.id)

    await emit_event_async(
        db,
        website.company_id,
        "handoff.requested",
        {
            "handoff_id": str(request.id),
            "website_id": str(website.id),
            "session_id": request.session_id,
            "status": request.status,
        },
    )


@router.post("/api/handoff", response_model=HandoffItem)
async def create_handoff(
    body: HandoffCreate,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit("chat", max_requests=10, window_seconds=60)),
):
    """Public: the widget's "talk to a human" button.

    Repeated clicks in the same session update the existing row instead of
    creating a second one, so the team is not emailed twice for one request.
    """
    website = (
        db.query(models.Website)
        .filter(models.Website.id == body.website_id)
        .first()
    )
    if website is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    if not company_settings.flag(db, website.company_id, "handoff_enabled"):
        # Off is indistinguishable from "no such endpoint" for the public.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handoff is not available for this website",
        )

    contact = (
        db.query(models.Contact)
        .filter(
            models.Contact.website_id == website.id,
            models.Contact.session_id == body.session_id,
        )
        .first()
    )

    existing = (
        db.query(models.HandoffRequest)
        .filter(
            models.HandoffRequest.website_id == website.id,
            models.HandoffRequest.session_id == body.session_id,
        )
        .first()
    )
    if existing is not None:
        reopened = existing.status == "closed"
        if contact is not None:
            existing.contact_id = contact.id
        if body.message:
            existing.message = body.message
        if reopened:
            # A closed request asked for again is a new call for attention.
            existing.status = "pending"
        db.commit()
        db.refresh(existing)
        if reopened:
            await _notify(db, website, existing)
        return _to_item(db, existing)

    request = models.HandoffRequest(
        website_id=website.id,
        session_id=body.session_id,
        contact_id=contact.id if contact is not None else None,
        message=body.message,
        status="pending",
        channel="widget",
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    await _notify(db, website, request)
    return _to_item(db, request)


@router.get("/api/handoffs", response_model=PaginatedResponse)
def list_handoffs(
    website_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Handoff requests across the caller's company, newest first."""
    limit = max(1, min(limit, 100))
    page = max(1, page)

    query = (
        db.query(models.HandoffRequest)
        .join(models.Website, models.Website.id == models.HandoffRequest.website_id)
        .filter(models.Website.company_id == user.company_id)
    )
    if website_id is not None:
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
        query = query.filter(models.HandoffRequest.website_id == website_id)
    if status_filter:
        if status_filter not in ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status must be pending, accepted or closed",
            )
        query = query.filter(models.HandoffRequest.status == status_filter)

    total = query.count()
    rows = (
        query.order_by(models.HandoffRequest.created_at.desc())
        .limit(limit)
        .offset((page - 1) * limit)
        .all()
    )
    return PaginatedResponse(
        total=total,
        page=page,
        limit=limit,
        items=[_to_item(db, row) for row in rows],
    )


@router.patch("/api/handoffs/{handoff_id}", response_model=HandoffItem)
def update_handoff(
    handoff_id: UUID,
    body: HandoffUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Move a request along: accepted, closed, or back to pending."""
    request = (
        db.query(models.HandoffRequest)
        .join(models.Website, models.Website.id == models.HandoffRequest.website_id)
        .filter(
            models.HandoffRequest.id == handoff_id,
            models.Website.company_id == user.company_id,
        )
        .first()
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found"
        )
    if body.status is not None:
        if body.status not in ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status must be pending, accepted or closed",
            )
        request.status = body.status
    db.commit()
    db.refresh(request)
    return _to_item(db, request)
