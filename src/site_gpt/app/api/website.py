from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user, get_current_user, get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.models import Website
from site_gpt.app.schemas.app import DashboardStats, PaginatedResponse
from site_gpt.app.schemas.embed_token import EmbedTokenCreated, EmbedTokenRes
from site_gpt.app.api.setting import company_daily_message_limit
from site_gpt.app.schemas.website import (
    WebsiteCreate,
    WebsiteQuotaRes,
    WebsiteRes,
    WebsiteUpdate,
)
from site_gpt.app.schemas.website_page import (
    WebsitePageCreate,
    WebsitePageRes,
    WebsitePageUpdate,
)
from site_gpt.app.services import embed_tokens, entitlements
from site_gpt.app.services import sitemap as sitemap_service
from site_gpt.app.services.crawler import extract_urls_from_sitemap
from site_gpt.app.services.net_guard import UnsafeUrl
from site_gpt.app.services.quota import usage as quota_usage

router = APIRouter()


def _owned_website(db: Session, website_id: UUID, user: models.User) -> Website:
    """The caller's website, or 404.

    A foreign id is a 404, never a 403 (same rule as `api/privacy.py`): the
    existence of another company's website is not the caller's business.
    """
    website = (
        db.query(Website)
        .filter(Website.id == website_id, Website.company_id == user.company_id)
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


def _token_res(row: models.EmbedToken) -> EmbedTokenRes:
    return EmbedTokenRes(
        id=row.id,
        website_id=row.website_id,
        token_prefix=row.token_prefix,
        active=row.revoked_at is None,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


@router.get("/", response_model=PaginatedResponse)
def get_websites(
    page: int = 1,
    limit: int = 10,
    name: str | None = None,
    url: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        query = db.query(Website).filter(Website.company_id == user.company_id)

        if name:
            query = query.filter(Website.name.ilike(f"%{name}%"))
        if url:
            query = query.filter(Website.url.ilike(f"%{url}%"))

        total = query.count()
        websites = query.offset((page - 1) * limit).limit(limit).all()

        return PaginatedResponse(
            total=total,
            page=page,
            limit=limit,
            items=[WebsiteRes.model_validate(w) for w in websites],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{website_id}/quota", response_model=WebsiteQuotaRes)
async def get_website_quota(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Today's message count against this website's daily cap.

    Lets an owner see the ceiling coming and raise `daily_message_limit` before
    visitors start getting the friendly refusal.
    """
    website = (
        db.query(Website)
        .filter(Website.id == website_id, Website.company_id == user.company_id)
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    limit = company_daily_message_limit(db, website.company_id)
    used = await quota_usage(website.id)
    unlimited = limit <= 0
    remaining = None if unlimited or used is None else max(0, limit - used)
    # 80% of the cap (integer math: used/limit >= 4/5).
    near_limit = (
        not unlimited and used is not None and used * 5 >= limit * 4
    )
    return WebsiteQuotaRes(
        website_id=website.id,
        date=datetime.now(UTC).strftime("%Y-%m-%d"),
        used=used,
        limit=limit,
        unlimited=unlimited,
        remaining=remaining,
        near_limit=near_limit,
        available=used is not None,
    )


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Aggregated dashboard counts for the current user's company."""
    try:
        total_websites = (
            db.query(Website).filter(Website.company_id == user.company_id).count()
        )
        indexed_websites = (
            db.query(Website)
            .filter(
                Website.company_id == user.company_id,
                Website.ingest_status == "completed",
            )
            .count()
        )
        ingesting_websites = (
            db.query(Website)
            .filter(
                Website.company_id == user.company_id,
                Website.ingest_status == "processing",
            )
            .count()
        )
        total_documents = (
            db.query(models.Document)
            .join(Website, models.Document.website_id == Website.id)
            .filter(Website.company_id == user.company_id)
            .count()
        )
        total_chat_messages = (
            db.query(models.ChatMessage)
            .join(Website, models.ChatMessage.website_id == Website.id)
            .filter(Website.company_id == user.company_id)
            .count()
        )
        team_members = (
            db.query(models.User)
            .filter(
                models.User.company_id == user.company_id,
                models.User.status == "active",
            )
            .count()
        )
        return DashboardStats(
            total_websites=total_websites,
            indexed_websites=indexed_websites,
            ingesting_websites=ingesting_websites,
            total_documents=total_documents,
            total_chat_messages=total_chat_messages,
            team_members=team_members,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{website_id}", response_model=WebsiteRes)
def get_website(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
        return WebsiteRes.model_validate(website)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=WebsiteRes)
def create_website(
    website_in: WebsiteCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    # The plan's website ceiling (V5-31). Checked before the insert and outside
    # the try/except below, whose 500 would otherwise swallow the refusal; an
    # existing company over its ceiling keeps every website it already has.
    existing = (
        db.query(models.Website)
        .filter(models.Website.company_id == user.company_id)
        .count()
    )
    try:
        entitlements.enforce_count(db, user.company_id, "websites", existing)
    except entitlements.PlanLimitError as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc
    try:
        website = Website(
            url=website_in.url,
            name=website_in.name,
            description=website_in.description,
            site_map_url=website_in.site_map_url,
            company_id=user.company_id,
            # The form sends 'active'/'inactive'; normalise so a stray case or
            # space (' Active ') cannot silently disable the bot.
            status=(website_in.status or "").strip().lower() or "active",
        )
        db.add(website)
        db.commit()
        db.refresh(website)
        return WebsiteRes.model_validate(website)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{website_id}", response_model=WebsiteRes)
def update_website(
    website_id: UUID,
    website_in: WebsiteUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
        website.url = website_in.url or website.url
        website.name = website_in.name or website.name
        website.description = website_in.description or website.description
        website.site_map_url = website_in.site_map_url or website.site_map_url
        website.status = (
            website_in.status or ""
        ).strip().lower() or website.status
        db.commit()
        db.refresh(website)
        return WebsiteRes.model_validate(website)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{website_id}")
def delete_website(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_manager_user),
):
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
        db.delete(website)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{website_id}/pages", response_model=PaginatedResponse)
def get_website_pages(
    website_id: UUID,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        query = db.query(models.WebsitePage).filter(
            models.WebsitePage.website_id == website_id
        )
        total = query.count()
        pages = query.offset((page - 1) * limit).limit(limit).all()
        return PaginatedResponse(
            total=total,
            page=page,
            limit=limit,
            items=[WebsitePageRes.model_validate(p) for p in pages],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{website_id}/pages", response_model=WebsitePageRes)
def create_website_page(
    website_id: UUID,
    website_page_in: WebsitePageCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )

        if not website:
            raise HTTPException(status_code=404, detail="Website not found")

        if (
            db.query(models.WebsitePage)
            .filter(models.WebsitePage.url == website_page_in.url)
            .first()
        ):
            raise HTTPException(status_code=400, detail="Page already exists")

        website_page = models.WebsitePage(
            url=website_page_in.url,
            name=website_page_in.name,
            description=website_page_in.description,
            website_id=website_id,
        )
        db.add(website_page)
        db.commit()
        db.refresh(website_page)
        return WebsitePageRes.model_validate(website_page)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{website_id}/pages/{page_id}", response_model=WebsitePageRes)
def update_website_page(
    website_id: UUID,
    page_id: UUID,
    website_page_in: WebsitePageUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )

        if not website:
            raise HTTPException(status_code=404, detail="Website not found")

        website_page = (
            db.query(models.WebsitePage)
            .filter(
                models.WebsitePage.id == page_id,
                models.WebsitePage.website_id == website_id,
            )
            .first()
        )
        if not website_page:
            raise HTTPException(status_code=404, detail="Page not found")
        website_page.url = website_page_in.url or website_page.url
        website_page.name = website_page_in.name or website_page.name
        website_page.description = (
            website_page_in.description or website_page.description
        )
        db.commit()
        db.refresh(website_page)
        return WebsitePageRes.model_validate(website_page)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{website_id}/pages/{page_id}")
def delete_website_page(
    website_id: UUID,
    page_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )

        if not website:
            raise HTTPException(status_code=404, detail="Website not found")

        website_page = (
            db.query(models.WebsitePage)
            .filter(
                models.WebsitePage.id == page_id,
                models.WebsitePage.website_id == website_id,
            )
            .first()
        )
        if not website_page:
            raise HTTPException(status_code=404, detail="Page not found")

        # Remove the page's crawled knowledge immediately so a deleted page
        # stops being answered by the bot without waiting for a re-ingest.
        doc = (
            db.query(models.Document)
            .filter(
                models.Document.url == website_page.url,
                models.Document.website_id == website_id,
            )
            .first()
        )
        if doc:
            # Embeddings cascade-delete via the FK ON DELETE CASCADE on
            # embeddings.document_id, so deleting the Document is sufficient.
            db.delete(doc)

        db.delete(website_page)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{website_id}/load-site-map")
def load_website_site_map(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    website = (
        db.query(Website)
        .filter(Website.id == website_id, Website.company_id == user.company_id)
        .first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    # Fetch outside the persistence block so a bad sitemap is the user's 400,
    # not an opaque 500.
    try:
        urls = extract_urls_from_sitemap(website.site_map_url, raise_on_error=True)
    except UnsafeUrl as e:
        print(f"[sitemap] refused {website.site_map_url}: {e}")
        raise HTTPException(
            status_code=400,
            detail=(
                "That sitemap address can't be fetched. Use a public http(s) "
                "URL for the sitemap and try again."
            ),
        )
    except Exception as e:
        # Network, HTTP status or parse failure from the crawler.
        print(f"[sitemap] could not read {website.site_map_url}: {e}")
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not download the sitemap. Check that the address is "
                "public and reachable, then try again."
            ),
        )

    try:
        added, truncated = sitemap_service.add_missing_pages(db, website_id, urls)
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"[sitemap] could not save pages for website {website_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not save the sitemap pages. Please try again.",
        )

    return {
        "status": "ok",
        "added": added,
        "total": len(urls),
        # True when the sitemap had more new URLs than this sync was allowed to
        # create; syncing again continues with the rest.
        "truncated": truncated,
        "limit": sitemap_service.SITEMAP_SYNC_MAX_URLS,
    }


# --- Embed token (V3 F4) ------------------------------------------------------
#
# The token ships inside a public HTML page, so it is a revocation/"require a
# token" control, not a secret: reads return the prefix only and the raw value
# exists in exactly one response. Admin-only because rotating it breaks every
# deployed snippet for that website.


@router.get("/{website_id}/embed-token", response_model=EmbedTokenRes)
def get_embed_token(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """The website's latest token as metadata — never the raw value."""
    website = _owned_website(db, website_id, user)
    row = embed_tokens.latest_token(db, website.id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No embed token has been issued for this website",
        )
    return _token_res(row)


@router.post(
    "/{website_id}/embed-token",
    response_model=EmbedTokenCreated,
    status_code=201,
)
def mint_embed_token(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Issue the website's first token. The raw value is in this response only.

    A website that already has an active token gets 409: issuing a second live
    token would make revocation a lie, so the caller has to rotate.
    """
    website = _owned_website(db, website_id, user)
    try:
        row, raw_token = embed_tokens.mint(db, website.id)
    except embed_tokens.EmbedTokenExists as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return EmbedTokenCreated(**_token_res(row).model_dump(), token=raw_token)


@router.post(
    "/{website_id}/embed-token/rotate",
    response_model=EmbedTokenCreated,
    status_code=201,
)
def rotate_embed_token(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Revoke the current token and return a new one (raw value, once).

    One transaction covers both rows: snippets carrying the old token stop
    working the moment this returns.
    """
    website = _owned_website(db, website_id, user)
    try:
        row, raw_token = embed_tokens.rotate(db, website.id)
    except embed_tokens.EmbedTokenExists as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return EmbedTokenCreated(**_token_res(row).model_dump(), token=raw_token)


@router.delete("/{website_id}/embed-token")
def revoke_embed_token(
    website_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Revoke the active token. The row stays as history (`revoked_at`)."""
    website = _owned_website(db, website_id, user)
    try:
        embed_tokens.revoke(db, website.id)
    except embed_tokens.EmbedTokenMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "revoked"}
