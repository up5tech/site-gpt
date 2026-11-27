from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from site_gpt.app.services import audit, entitlements

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
    # The plan's seat ceiling (V5-31), before the insert and outside the
    # try/except whose 500 would swallow the refusal. Only active users hold a
    # seat, so a deactivated account never blocks a new invite.
    seats = entitlements.seat_count(db, user.company_id)
    try:
        entitlements.enforce_count(db, user.company_id, "seats", seats)
    except entitlements.PlanLimitError as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc
    try:
        hashed_password = hash_password(user_in.password)
        member = models.User(
            email=user_in.email,
            password_hash=hashed_password,
            company_id=user.company_id,
            first_name=user_in.first_name,
            last_name=user_in.last_name,
            role=user_in.role or "user",
            status=user_in.status or "active",
            phone=user_in.phone or None,
        )
        db.add(member)
        # The audit row lands in the same transaction as the insert (V6-14).
        db.flush()
        audit.record(
            db,
            company_id=user.company_id,
            action="user.create",
            target_type="user",
            target_id=member.id,
            actor=user,
            detail={"role": member.role, "status": member.status},
        )
        db.commit()
        db.refresh(member)
        return UserRes.model_validate(member)
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
                models.User.id == user_id,
                models.User.company_id == user.company_id,
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
                models.User.id == user_id,
                models.User.company_id == user.company_id,
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        db.delete(query)
        audit.record(
            db,
            company_id=user.company_id,
            action="user.delete",
            target_type="user",
            target_id=query.id,
            actor=user,
        )
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
                models.User.id == user_id,
                models.User.company_id == user.company_id,
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        # Field names, the new role and status — never the email, name, phone
        # or anything else the request carried (V6-14 stores metadata only).
        changed: list[str] = []
        if user_in.email:
            query.email = user_in.email
            changed.append("email")
        if user_in.first_name:
            query.first_name = user_in.first_name
            changed.append("first_name")
        if user_in.last_name:
            query.last_name = user_in.last_name
            changed.append("last_name")
        if user_in.role:
            query.role = user_in.role or query.role
            changed.append("role")
        if user_in.status:
            query.status = user_in.status or query.status
            changed.append("status")
        if user_in.phone:
            query.phone = user_in.phone
            changed.append("phone")
        if changed:
            audit.record(
                db,
                company_id=user.company_id,
                action="user.update",
                target_type="user",
                target_id=query.id,
                actor=user,
                detail={
                    "fields": sorted(set(changed)),
                    "role": query.role,
                    "status": query.status,
                },
            )
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
                models.User.id == user_id,
                models.User.company_id == user.company_id,
            )
            .first()
        )
        if not query:
            raise HTTPException(status_code=404, detail="User not found")
        query.password_hash = hash_password(password)
        # A credential event, never the credential itself.
        audit.record(
            db,
            company_id=user.company_id,
            action="user.password.change",
            target_type="user",
            target_id=query.id,
            actor=user,
        )
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
