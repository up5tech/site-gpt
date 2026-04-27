from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.document import DocumentRes
from uuid import UUID

router = APIRouter()


@router.get("/", response_model=PaginatedResponse)
def get_documents(
    website_id: UUID,
    title: str | None = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        query = (
            db.query(models.Document)
            .join(models.Website)
            .filter(
                models.Document.website_id == website_id,
                models.Website.company_id == user.company_id,
            )
        )
        if title:
            query = query.filter(models.Document.title.ilike(f"%{title}%"))
        total = query.count()
        documents = query.offset((page - 1) * limit).limit(limit).all()
        return PaginatedResponse(
            items=[DocumentRes.model_validate(doc) for doc in documents],
            total=total,
            page=page,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}", response_model=DocumentRes)
def get_document(
    id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        document = (
            db.query(models.Document)
            .join(models.Website)
            .filter(
                models.Document.id == id, models.Website.company_id == user.company_id
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentRes.model_validate(document)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
