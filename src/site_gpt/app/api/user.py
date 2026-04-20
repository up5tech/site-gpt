from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user, hash_password
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.user import UserUpdate, UserRes

router = APIRouter()


@router.get("/users/me")
def read_users_me(
    user=Depends(get_current_user),
):
    return UserRes.model_validate(user)


@router.put("/users/me")
def update_users_me(
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if user_update.first_name:
        user.first_name = user_update.first_name
    if user_update.last_name:
        user.last_name = user_update.last_name
    if user_update.phone:
        user.phone = user_update.phone
    db.commit()
    db.refresh(user)
    return UserRes.model_validate(user)


@router.post("/users/forgot-password")
def forgot_password(
    email: str,
    db: Session = Depends(get_db),
):
    # check email exist
    exist_user = db.query(models.User).filter(models.User.email == email).first()
    if not exist_user:
        raise HTTPException(status_code=404, detail="User not found")
    # hash string
    uuid_string = UUID().hex
    hash_string = hash_password(f"{email}{uuid_string}")
    # update user
    try:
        exist_user.hash_password = hash_string
        exist_user.hash_type = "forgot_password"
        db.commit()
        db.refresh(exist_user)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/reset-password")
def reset_password(
    email: str,
    password: str,
    db: Session = Depends(get_db),
):
    # check email exist
    exist_user = db.query(models.User).filter(models.User.email == email).first()
    if not exist_user:
        raise HTTPException(status_code=404, detail="User not found")
    # hash string
    hash_string = hash_password(password)
    # update user
    try:
        exist_user.password_hash = hash_string
        exist_user.hash_string = ""
        exist_user.hash_type = "reset_password"
        db.commit()
        db.refresh(exist_user)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
