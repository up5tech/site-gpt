"""Weekly digest endpoints (F6): preview renders, send-now delivers once.

Both report the last complete digest week (`services.digest.previous_period`) —
the window the topic worker clusters — and both go through the same claim, so two
clicks on "Send now" in one week cannot email twice and a scheduled send already
owns the period.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user, get_manager_user
from site_gpt.app.core.config import DIGEST_CHECK_SECONDS
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.digest import DigestPreview, DigestSendResult
from site_gpt.app.services import company_settings
from site_gpt.app.services.digest import (
    build_digest,
    company_name,
    previous_period,
    render_digest_html,
    send_period,
)

router = APIRouter()


def _period(db: Session, company_id) -> tuple[datetime, datetime]:
    digest_day = company_settings.value(
        db, company_id, "digest_day", "monday"
    )
    return previous_period(datetime.now(UTC), digest_day)


@router.post("/api/digest/preview", response_model=DigestPreview)
def preview_digest(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    """Render the current week's digest; sends nothing."""
    start, end = _period(db, user.company_id)
    data = build_digest(db, user.company_id, start, end)
    return DigestPreview(
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        html=render_digest_html(data, company_name(db, user.company_id)),
        summary=data,
    )


@router.post("/api/digest/send-now", response_model=DigestSendResult)
async def send_digest_now(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Send this week's digest now; a second call for the week is a no-op."""
    now = datetime.now(UTC)
    start, end = _period(db, user.company_id)
    stale_before = now - timedelta(seconds=DIGEST_CHECK_SECONDS)
    return await send_period(db, user.company_id, start, end, stale_before)
