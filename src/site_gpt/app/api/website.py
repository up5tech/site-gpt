from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user, get_manager_user
from site_gpt.app.core.config import SITEMAP_SYNC_MAX_URLS
from site_gpt.app.db.session import get_db
from site_gpt.app.models import Website
from site_gpt.app.schemas.app import DashboardStats, PaginatedResponse
from site_gpt.app.schemas.website import WebsiteCreate, WebsiteRes, WebsiteUpdate
from site_gpt.app.schemas.website_page import (
    WebsitePageCreate,
    WebsitePageRes,
    WebsitePageUpdate,
)
from site_gpt.app.services.crawler import extract_urls_from_sitemap
from site_gpt.app.services.net_guard import UnsafeUrl

router = APIRouter()


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
    try:
        website = Website(
            url=website_in.url,
            name=website_in.name,
            description=website_in.description,
            site_map_url=website_in.site_map_url,
            company_id=user.company_id,
            status=website_in.status or "active",
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
        website.status = website_in.status or website.status
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
        added = 0
        truncated = False
        for url in urls:
            # Stop creating pages once this sync hits the cap: a sitemap can list
            # tens of thousands of URLs, and the next ingest crawls them all.
            # Existing pages do not consume the budget, so repeated syncs keep
            # making progress instead of re-scanning the same first N URLs.
            if SITEMAP_SYNC_MAX_URLS > 0 and added >= SITEMAP_SYNC_MAX_URLS:
                truncated = True
                break
            # Scoped to this website: pages of another tenant that happen to
            # share a URL must not make this sync skip them.
            if (
                db.query(models.WebsitePage)
                .filter(
                    models.WebsitePage.website_id == website_id,
                    models.WebsitePage.url == url,
                )
                .first()
            ):
                continue
            db.add(
                models.WebsitePage(
                    url=url,
                    name=url,
                    description="",
                    website_id=website_id,
                )
            )
            added += 1
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
        "limit": SITEMAP_SYNC_MAX_URLS,
    }
