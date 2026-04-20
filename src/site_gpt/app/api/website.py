from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user, get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.models import Website
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.website import WebsiteCreate, WebsiteRes, WebsiteUpdate

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
