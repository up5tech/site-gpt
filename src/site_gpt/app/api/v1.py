"""Versioned, API-key-authenticated surface (SPEC F8).

Every route here reuses the shared service helpers rather than copying route
logic: `ensure_website_active` for a disabled bot, `ensure_embed_allowed` for a
foreign Origin, and `claim_ingest` for the one-crawl-per-website race. All
resource lookups are scoped by the key's `company_id`, never by anything the
caller supplies.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_api_key, require_scope
from site_gpt.app.db.session import get_db
from site_gpt.app.services.embed_guard import ensure_embed_allowed
from site_gpt.app.services.ingest_claim import claim_ingest
from site_gpt.app.services.redis import enqueue_job
from site_gpt.app.services.website_state import ensure_website_active

router = APIRouter()


@router.post("/ingest", tags=["v1"])
async def ingest(
    website_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    api_key: models.ApiKey = Depends(get_api_key),
):
    """Queue a crawl for one website. Requires the `ingest:write` scope."""
    require_scope(api_key, "ingest:write")

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

    ensure_website_active(website)
    ensure_embed_allowed(request, db, website)

    if not claim_ingest(db, website.id, api_key.company_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingest is already running for this website.",
        )

    await enqueue_job({"type": "ingest", "website_id": str(website.id)})
    return {"status": "ok", "website_id": str(website.id)}
