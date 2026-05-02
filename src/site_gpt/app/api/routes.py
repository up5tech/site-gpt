from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
)
from site_gpt.app.core.config import JWT_SECRET_KEY, JWT_ALGORITHM
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.company import CompanyRegister
from site_gpt.app.schemas.user import UserLogin
from site_gpt.app.services.rag import ask
from site_gpt.app.services.redis import enqueue_job

router = APIRouter()


@router.post("/ingest")
async def ingest(website_id: str, db: Session = Depends(get_db)):
    website = (
        db.query(models.Website).filter(models.Website.id == website_id).first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    website.ingest_status = "processing"
    db.commit()
    await enqueue_job({"type": "ingest", "website_id": website_id})
    return {"status": "ok"}


@router.get("/chat")
def chat(q: str, website_id: Optional[str] = None):
    return {"answer": ask(q, website_id)}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/api/register")
def register(
    registration: CompanyRegister,
    db: Session = Depends(get_db),
):
    # check params
    if (
        not registration.company_name
        or not registration.first_name
        or not registration.last_name
        or not registration.email
        or not registration.password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All fields are required",
        )
    # check if company exists
    company = (
        db.query(models.Company)
        .filter(models.Company.name == registration.company_name)
        .first()
    )
    if company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company already exists",
        )
    # create company
    company = models.Company(name=registration.company_name, description="")
    db.add(company)
    db.commit()
    hashed_password = hash_password(registration.password)
    user = models.User(
        email=registration.email,
        password_hash=hashed_password,
        company_id=company.id,
        first_name=registration.first_name,
        last_name=registration.last_name,
        role="admin",
        status="active",
    )
    db.add(user)
    db.commit()
    return {"status": "ok"}


@router.post("/api/token")
def get_token(login: UserLogin, db: Session = Depends(get_db)):
    user = (
        db.query(models.User)
        .filter(models.User.email == login.email, models.User.status == "active")
        .first()
    )

    if not user or not verify_password(login.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email},
        secret_key=JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    return {"access_token": access_token, "token_type": "bearer"}
