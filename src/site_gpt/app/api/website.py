from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user, get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.models import Website
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.website import WebsiteCreate, WebsiteRes, WebsiteUpdate
from site_gpt.app.schemas.website_page import (
    WebsitePageCreate,
    WebsitePageRes,
    WebsitePageUpdate,
)
from site_gpt.app.services.crawler import extract_urls_from_sitemap

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
    try:
        website = (
            db.query(Website)
            .filter(Website.id == website_id, Website.company_id == user.company_id)
            .first()
        )
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
        urls = extract_urls_from_sitemap(website.site_map_url)
        for url in urls:
            if (
                db.query(models.WebsitePage)
                .filter(models.WebsitePage.url == url)
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
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
