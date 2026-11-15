"""Admin review surface for chat feedback (F4).

A rating only becomes training material once an admin approves it; rejecting it
keeps the row for the record. Nothing here trusts text from the client: the
question and the original answer are resolved from `chat_messages` through the
stored `message_id`, so a rating can only ever teach the pair that was actually
exchanged in that session.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.feedback import FeedbackItem, FeedbackReview
from site_gpt.app.services.conversations import question_for_answer

router = APIRouter()

REVIEW_STATUSES = ("pending", "approved", "rejected")


def _scoped_feedback(db: Session, company_id: UUID, feedback_id: UUID):
    """One feedback row, only if it belongs to this company."""
    return (
        db.query(models.ChatFeedback)
        .join(models.Website, models.Website.id == models.ChatFeedback.website_id)
        .filter(
            models.ChatFeedback.id == feedback_id,
            models.Website.company_id == company_id,
        )
        .first()
    )


def _to_item(db: Session, feedback: models.ChatFeedback) -> FeedbackItem:
    """Attach the resolved question and answer to a feedback row."""
    answer = None
    question = None
    if feedback.message_id is not None:
        answer = (
            db.query(models.ChatMessage)
            .filter(models.ChatMessage.id == feedback.message_id)
            .first()
        )
    if answer is not None:
        question_row = question_for_answer(
            db, feedback.website_id, feedback.session_id, answer
        )
        question = question_row.message if question_row else None
    return FeedbackItem(
        id=feedback.id,
        website_id=feedback.website_id,
        session_id=feedback.session_id,
        rating=feedback.rating,
        comment=feedback.comment,
        message_id=feedback.message_id,
        status=feedback.status,
        reviewed_answer=feedback.reviewed_answer,
        question=question,
        answer=answer.message if answer is not None else None,
        created_at=feedback.created_at,
    )


@router.get("", response_model=PaginatedResponse)
def list_feedback(
    website_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    rating: str | None = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Feedback across the caller's company, newest first."""
    limit = max(1, min(limit, 100))
    page = max(1, page)

    query = (
        db.query(models.ChatFeedback)
        .join(models.Website, models.Website.id == models.ChatFeedback.website_id)
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
        query = query.filter(models.ChatFeedback.website_id == website_id)
    if status_filter:
        if status_filter not in REVIEW_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status must be pending, approved or rejected",
            )
        query = query.filter(models.ChatFeedback.status == status_filter)
    if rating:
        if rating not in ("up", "down"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="rating must be 'up' or 'down'",
            )
        query = query.filter(models.ChatFeedback.rating == rating)

    total = query.count()
    rows = (
        query.order_by(models.ChatFeedback.created_at.desc())
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


@router.patch("/{feedback_id}", response_model=FeedbackItem)
def review_feedback(
    feedback_id: UUID,
    body: FeedbackReview,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Approve or reject a rating and optionally store a corrected answer."""
    feedback = _scoped_feedback(db, user.company_id, feedback_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found"
        )
    if body.status is not None:
        if body.status not in REVIEW_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status must be pending, approved or rejected",
            )
        feedback.status = body.status
    if body.reviewed_answer is not None:
        feedback.reviewed_answer = body.reviewed_answer
    db.commit()
    db.refresh(feedback)
    return _to_item(db, feedback)
