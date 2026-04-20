from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import (
    get_current_user,
    get_manager_user,
    hash_password,
)
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.company import CompanyRes, CompanyUpdate
from site_gpt.app.schemas.user import UserCreate, UserRes, UserUpdate


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


@router.put("/current")
def update_company(
    company_update: CompanyUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        query = (
            db.query(models.Company)
            .filter(models.Company.id == user.company_id)
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="Company not found")
        if company_update.name:
            query.name = company_update.name
        if company_update.description:
            query.description = company_update.description
        if company_update.started_at:
            query.started_at = company_update.started_at
        if company_update.expired_at:
            query.expired_at = company_update.expired_at
        db.commit()
        db.refresh(query)
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


@router.post("/users", response_model=UserRes)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        hashed_password = hash_password(user_in.password)
        user = models.User(
            email=user_in.email,
            password_hash=hashed_password,
            company_id=user.company_id,
            first_name=user_in.first_name,
            last_name=user_in.last_name,
            role=user_in.role or "user",
            status=user_in.status or "active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserRes.model_validate(user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}", response_model=UserRes)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        query = (
            db.query(models.User)
            .filter(
                models.User.id == user_id, models.User.company_id == user.company_id
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        return UserRes.model_validate(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        query = (
            db.query(models.User)
            .filter(
                models.User.id == user_id, models.User.company_id == user.company_id
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        db.delete(query)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}", response_model=UserRes)
def update_user(
    user_id: UUID,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        query = (
            db.query(models.User)
            .filter(
                models.User.id == user_id, models.User.company_id == user.company_id
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        if user_in.email:
            query.email = user_in.email
        if user_in.first_name:
            query.first_name = user_in.first_name
        if user_in.last_name:
            query.last_name = user_in.last_name
        if user_in.role:
            query.role = user_in.role or query.role
        if user_in.status:
            query.status = user_in.status or query.status
        db.commit()
        db.refresh(query)
        return UserRes.model_validate(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/change-password")
def change_password(
    user_id: UUID,
    password: str,
    db: Session = Depends(get_db),
    user=Depends(get_manager_user),
):
    try:
        query = (
            db.query(models.User)
            .filter(
                models.User.id == user_id, models.User.company_id == user.company_id
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        query.password_hash = hash_password(password)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
