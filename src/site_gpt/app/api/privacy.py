"""Privacy export and erasure (F9).

Two rights a customer of the owner will ask about sooner or later: "give me
everything you hold about me" and "delete it". Both are scoped the same way as
every other admin route — the `website_id` must belong to the caller's company,
so one tenant can never read or erase another tenant's visitors.

Deletion is a hard delete of rows, not a flag: an erasure request that keeps a
copy "just in case" is not an erasure. The audit trail for API keys is separate
and unaffected.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.privacy import (
    PrivacyContact,
    PrivacyDeletionResult,
    PrivacyExport,
    PrivacyFeedback,
    PrivacyHandoff,
    PrivacyMessage,
)
from site_gpt.app.services.conversations import delete_conversation

router = APIRouter()


def _scoped_website(db: Session, website_id: UUID, company_id: UUID) -> models.Website:
    """The website, only if it belongs to `company_id`. 404 otherwise.

    A 404 rather than a 403 on purpose: whether another tenant owns a given id
    is not information this endpoint should confirm.
    """
    website = (
        db.query(models.Website)
        .filter(
            models.Website.id == website_id,
            models.Website.company_id == company_id,
        )
        .first()
    )
    if website is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    return website


@router.get("/export", response_model=PrivacyExport)
def export_website_data(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Every stored record of one website: messages, contacts, ratings, handoffs."""
    website = _scoped_website(db, website_id, user.company_id)

    messages = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.website_id == website.id)
        .order_by(models.ChatMessage.created_at.asc())
        .all()
    )
    contacts = (
        db.query(models.Contact)
        .filter(models.Contact.website_id == website.id)
        .order_by(models.Contact.created_at.asc())
        .all()
    )
    feedback = (
        db.query(models.ChatFeedback)
        .filter(models.ChatFeedback.website_id == website.id)
        .order_by(models.ChatFeedback.created_at.asc())
        .all()
    )
    handoffs = (
        db.query(models.HandoffRequest)
        .filter(models.HandoffRequest.website_id == website.id)
        .order_by(models.HandoffRequest.created_at.asc())
        .all()
    )

    return PrivacyExport(
        website_id=website.id,
        website_name=website.name,
        generated_at=datetime.now(UTC),
        chat_messages=[
            PrivacyMessage(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                message=m.message,
                created_at=m.created_at,
            )
            for m in messages
        ],
        contacts=[
            PrivacyContact(
                id=c.id,
                session_id=c.session_id,
                first_name=c.first_name,
                last_name=c.last_name,
                email=c.email,
                consent_at=c.consent_at,
                created_at=c.created_at,
            )
            for c in contacts
        ],
        chat_feedback=[
            PrivacyFeedback(
                id=f.id,
                session_id=f.session_id,
                rating=f.rating,
                comment=f.comment,
                status=f.status,
                created_at=f.created_at,
            )
            for f in feedback
        ],
        handoff_requests=[
            PrivacyHandoff(
                id=h.id,
                session_id=h.session_id,
                message=h.message,
                status=h.status,
                channel=h.channel,
                created_at=h.created_at,
            )
            for h in handoffs
        ],
    )


@router.delete("/conversations/{session_id}", response_model=PrivacyDeletionResult)
def erase_conversation(
    session_id: str,
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Erase one conversation: its messages, its ratings and its handoffs.

    The contact row is kept — it is the owner's lead record, and it has its own
    endpoint below. Anything pointing at the erased messages is cleared by the
    schema (`chat_feedback.message_id` is ON DELETE SET NULL), so no dangling
    reference survives.
    """
    website = _scoped_website(db, website_id, user.company_id)
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required"
        )

    # Ratings and handoffs carry the visitor's words too, so they go with the
    # conversation; leaving them would make the erasure incomplete.
    deleted_feedback = (
        db.query(models.ChatFeedback)
        .filter(
            models.ChatFeedback.website_id == website.id,
            models.ChatFeedback.session_id == session_id,
        )
        .delete()
    )
    deleted_handoffs = (
        db.query(models.HandoffRequest)
        .filter(
            models.HandoffRequest.website_id == website.id,
            models.HandoffRequest.session_id == session_id,
        )
        .delete()
    )
    db.commit()
    deleted_messages = delete_conversation(db, website.id, session_id)

    return PrivacyDeletionResult(
        website_id=website.id,
        session_id=session_id,
        deleted={
            "chat_messages": deleted_messages,
            "chat_feedback": deleted_feedback,
            "handoff_requests": deleted_handoffs,
        },
    )


@router.delete("/contacts/{session_id}", response_model=PrivacyDeletionResult)
def erase_contact(
    session_id: str,
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Erase the contact record of a session, plus the handoffs it produced.

    `handoff_requests.contact_id` is ON DELETE SET NULL, so the database alone
    would keep a request that names the same session; deleting those rows here
    is what makes the erasure complete.
    """
    website = _scoped_website(db, website_id, user.company_id)
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required"
        )

    deleted_handoffs = (
        db.query(models.HandoffRequest)
        .filter(
            models.HandoffRequest.website_id == website.id,
            models.HandoffRequest.session_id == session_id,
        )
        .delete()
    )
    deleted_contacts = (
        db.query(models.Contact)
        .filter(
            models.Contact.website_id == website.id,
            models.Contact.session_id == session_id,
        )
        .delete()
    )
    db.commit()

    return PrivacyDeletionResult(
        website_id=website.id,
        session_id=session_id,
        deleted={
            "contacts": deleted_contacts,
            "handoff_requests": deleted_handoffs,
        },
    )
