"""Privacy export and erasure (F9).

Two rights a customer of the owner will ask about sooner or later: "give me
everything you hold about me" and "delete it". Both are scoped the same way as
every other admin route — the `website_id` must belong to the caller's company,
so one tenant can never read or erase another tenant's visitors.

Deletion is a hard delete of rows, not a flag: an erasure request that keeps a
copy "just in case" is not an erasure. The audit trail for API keys is separate
and unaffected.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.privacy import (
    PrivacyContact,
    PrivacyConversation,
    PrivacyDeletionResult,
    PrivacyExport,
    PrivacyFeedback,
    PrivacyHandoff,
    PrivacyMessage,
    RetentionPurgeRequest,
    RetentionPurgeResult,
)
from site_gpt.app.services import audit, retention
from site_gpt.app.services.conversations import erase_session

router = APIRouter()

logger = logging.getLogger(__name__)


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
    # M9: the inbox state of each session (assignee id only — the export never
    # includes another user's credentials).
    inbox = (
        db.query(models.Conversation)
        .filter(models.Conversation.website_id == website.id)
        .order_by(models.Conversation.created_at.asc())
        .all()
    )

    # A read of everything the company holds is itself auditable (V6-14): who
    # exported which website and when, never the rows that were returned.
    audit.record(
        db,
        company_id=user.company_id,
        action="data.export",
        target_type="website",
        target_id=website.id,
        actor=user,
        commit=True,
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
                author_user_id=m.author_user_id,
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
        conversations=[
            PrivacyConversation(
                id=row.id,
                session_id=row.session_id,
                state=row.state,
                assigned_user_id=row.assigned_user_id,
                claimed_at=row.claimed_at,
                closed_at=row.closed_at,
                last_message_at=row.last_message_at,
                created_at=row.created_at,
            )
            for row in inbox
        ],
    )


@router.delete("/conversations/{session_id}", response_model=PrivacyDeletionResult)
def erase_conversation(
    session_id: str,
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Erase one conversation: messages, inbox row, ratings, handoffs and token.

    The contact row is kept — it is the owner's lead record, and it has its own
    endpoint below. Everything session-scoped is deleted by **one** service call
    in one transaction (`conversations.erase_session`), including the K4 session
    token: leaving a credential behind for a session that no longer exists would
    be a dangling capability. Anything pointing at the erased messages is cleared
    by the schema (`chat_feedback.message_id` is ON DELETE SET NULL).

    Derived topic clusters for the weeks those messages fell in are dropped too:
    their labels and summaries were generated from the erased questions, so
    keeping them would keep a readable trace of text this call removed. The run
    rows go with them, which is what lets the worker rebuild those windows later.
    """
    website = _scoped_website(db, website_id, user.company_id)
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required"
        )

    # Taken before the delete: these timestamps decide which weekly topic-cluster
    # windows were derived from this conversation.
    erased_moments = [
        created_at
        for (created_at,) in db.query(models.ChatMessage.created_at)
        .filter(
            models.ChatMessage.website_id == website.id,
            models.ChatMessage.session_id == session_id,
        )
        .all()
    ]

    # Ratings, handoffs, the inbox row and the session token carry the visitor's
    # session too, so they go with the messages, in one transaction: a partial
    # erasure that leaves any of them behind is not an erasure.
    deleted = erase_session(db, website.id, session_id)
    # Local, unconditional and provider-free: derived rows are rebuilt by the
    # worker, never kept as a copy of erased text.
    deleted_clusters = retention.invalidate_topic_windows(
        db, user.company_id, erased_moments, commit=True
    )

    audit.record(
        db,
        company_id=user.company_id,
        action="data.erase",
        target_type="website",
        target_id=website.id,
        actor=user,
        detail={"rows": deleted, "topic_windows": deleted_clusters},
        commit=True,
    )

    return PrivacyDeletionResult(
        website_id=website.id,
        session_id=session_id,
        deleted={**deleted, **deleted_clusters},
    )


@router.post("/retention", response_model=RetentionPurgeResult)
def purge_expired_data(
    body: RetentionPurgeRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Preview (default) or apply the company's `retention_days` policy now.

    The worker runs the same code once a day; this endpoint exists so an owner can
    see what a policy would delete before letting it run, and so the purge can be
    triggered without waiting for the nightly job.
    """
    if body.retention_days is not None and body.retention_days < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="retention_days cannot be negative",
        )

    result = retention.purge_company(
        db,
        user.company_id,
        days=body.retention_days,
        dry_run=body.dry_run,
    )
    # Only an applied purge is an erasure; a preview changes nothing and is not
    # audited as one (V6-14).
    if not result["dry_run"]:
        audit.record(
            db,
            company_id=user.company_id,
            action="data.retention.apply",
            target_type="company",
            target_id=user.company_id,
            actor=user,
            detail={
                "retention_days": result["retention_days"],
                "rows": result["total"],
            },
            commit=True,
        )
    logger.info(
        "retention purge (%s) for company %s: %s rows",
        "dry run" if result["dry_run"] else "applied",
        user.company_id,
        result["total"],
    )
    return RetentionPurgeResult(**result)


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

    audit.record(
        db,
        company_id=user.company_id,
        action="data.erase_contact",
        target_type="website",
        target_id=website.id,
        actor=user,
        detail={
            "contacts": deleted_contacts,
            "handoff_requests": deleted_handoffs,
        },
        commit=True,
    )

    return PrivacyDeletionResult(
        website_id=website.id,
        session_id=session_id,
        deleted={
            "contacts": deleted_contacts,
            "handoff_requests": deleted_handoffs,
        },
    )
