from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.company import Company, CompanyPaginated


router = APIRouter()


@router.get("/", response_model=CompanyPaginated)
def query_companies(
    name: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        query = db.query(models.Company)
        if name:
            query = query.filter(models.Company.name.ilike(f"%{name}%"))
        total = query.count()
        companies = query.offset((page - 1) * limit).limit(limit).all()
        return CompanyPaginated(
            total=total,
            page=page,
            limit=limit,
            items=[Company.model_validate(c) for c in companies],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
