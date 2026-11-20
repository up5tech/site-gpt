"""Analytics summary and aggregate CSV export (F6, V4 F1).

Same aggregation as the weekly digest (`services.digest.build_digest`), over a
rolling window instead of a normalised week, so the page and the email can never
disagree about what a conversation or an unanswered question is. The V4 fields
(trend, funnel, top questions) come from `services.analytics`, which reads the
same window through the digest's own definitions; the CSV export renders those
same three results as a file, never a second aggregation.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.digest import AnalyticsSummary
from site_gpt.app.services import analytics
from site_gpt.app.services.digest import build_digest

router = APIRouter()


@router.get("/api/analytics/summary", response_model=AnalyticsSummary)
def analytics_summary(
    days: int = 7,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Counts, topics, trend, funnel and top questions for the last `days` days."""
    days = max(1, min(days, 90))
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    data = build_digest(db, user.company_id, start, end)
    return {
        **data,
        "days": days,
        "trend": analytics.daily_trend(db, user.company_id, start, end),
        "funnel": analytics.engagement_funnel(db, user.company_id, start, end),
        "top_questions": analytics.top_questions(
            db, user.company_id, start, end
        ),
    }


@router.get("/api/analytics/export.csv")
def analytics_export(
    days: int = 7,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """The summary's trend, funnel and top questions as a CSV attachment (D5).

    Manager+ and company-scoped like the summary, and named with the window's
    first and last UTC day. Spreadsheet-safe: no session ids, contacts or
    transcript text, and every formula-looking cell is neutralized.
    """
    days = max(1, min(days, 90))
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    return Response(
        content=analytics.export_csv(db, user.company_id, start, end),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                "attachment; "
                f'filename="{analytics.export_filename(start, end)}"'
            )
        },
    )
