from datetime import datetime, timedelta, UTC
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user, hash_password
from site_gpt.app.core.config import FRONTEND_URL
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserRes,
    UserUpdate,
)
from site_gpt.app.services.mail import send_email

router = APIRouter()

RESET_TOKEN_TTL_MINUTES = 30


@router.get("/me")
def read_users_me(
    user=Depends(get_current_user),
):
    return UserRes.model_validate(user)


@router.put("/me")
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


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    # Always return success to avoid leaking which emails are registered.
    exist_user = (
        db.query(models.User).filter(models.User.email == body.email).first()
    )
    if exist_user:
        token = secrets.token_urlsafe(32)
        exist_user.reset_token = token
        exist_user.reset_token_expires_at = datetime.now(UTC) + timedelta(
            minutes=RESET_TOKEN_TTL_MINUTES
        )
        db.commit()
        try:
            reset_link = (
                f"{FRONTEND_URL}/reset-password?token={token}&email={exist_user.email}"
            )
            send_email(
                recipient=exist_user.email,
                subject="Reset your SiteGPT password",
                body=(
                    f"Click the link below to reset your password. "
                    f"This link expires in {RESET_TOKEN_TTL_MINUTES} minutes.<br><br>"
                    f'<a href="{reset_link}">{reset_link}</a>'
                ),
            )
        except Exception as e:
            print(f"[mail] failed to send reset email: {e}")
    return {"status": "success"}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    exist_user = (
        db.query(models.User).filter(models.User.email == body.email).first()
    )
    if (
        not exist_user
        or not exist_user.reset_token
        or exist_user.reset_token != body.token
    ):
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if (
        exist_user.reset_token_expires_at is None
        or exist_user.reset_token_expires_at < datetime.now(UTC)
    ):
        raise HTTPException(status_code=400, detail="Reset token expired")

    exist_user.password_hash = hash_password(body.password)
    exist_user.reset_token = None
    exist_user.reset_token_expires_at = None
    db.commit()
    return {"status": "success"}
