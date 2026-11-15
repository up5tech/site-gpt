"""Analytics summary for the admin page (F6).

Same aggregation as the weekly digest (`services.digest.build_digest`), over a
rolling window instead of a normalised week, so the page and the email can never
disagree about what a conversation or an unanswered question is.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.digest import AnalyticsSummary
from site_gpt.app.services.digest import build_digest

router = APIRouter()


@router.get("/api/analytics/summary", response_model=AnalyticsSummary)
def analytics_summary(
    days: int = 7,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Counts, top topics and unanswered questions for the last `days` days."""
    days = max(1, min(days, 90))
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    data = build_digest(db, user.company_id, start, end)
    return {**data, "days": days}
