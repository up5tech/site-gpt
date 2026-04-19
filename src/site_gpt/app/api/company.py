from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user, get_current_user, get_manager_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.company import CompanyRes
from site_gpt.app.schemas.user import UserRes


router = APIRouter()


@router.get("/current", response_model=CompanyRes)
def get_company(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        query = (
            db.query(models.Company)
            .filter(models.Company.id == user.company_id)
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="Company not found")
        return CompanyRes.model_validate(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users", response_model=PaginatedResponse)
def query_users(
    name: Optional[str] = None,
    email: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        query = db.query(models.User).filter(models.User.company_id == user.company_id)
        if name:
            query = query.filter(
                (models.User.first_name.ilike(f"%{name}%"))
                | (models.User.last_name.ilike(f"%{name}%"))
            )
        if email:
            query = query.filter(models.User.email.ilike(f"%{email}%"))
        if role:
            query = query.filter(models.User.role == role)
        total = query.count()
        users = query.offset((page - 1) * limit).limit(limit).all()
        return PaginatedResponse(
            total=total,
            page=page,
            limit=limit,
            items=[UserRes.model_validate(u) for u in users],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
