from fastapi import APIRouter, Depends, HTTPException, status

from site_gpt.app import models
from site_gpt.app.core.auth import (
    hash_password,
    hash_password,
    verify_password,
    create_access_token,
)
from site_gpt.app.core.config import JWT_SECRET_KEY, JWT_ALGORITHM
from site_gpt.app.db.session import get_db
from site_gpt.app.services.crawler import load_sitemap
from site_gpt.app.services.ingest import ingest_documents, split_docs
from site_gpt.app.services.rag import ask

router = APIRouter()


@router.post("/ingest")
def ingest(sitemap_url: str):
    docs = load_sitemap(sitemap_url)
    chunks = split_docs(docs)
    ingest_documents(chunks)
    return {"status": "ok"}


@router.get("/chat")
def chat(q: str):
    return {"answer": ask(q)}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/api/register")
def register(
    company_name: str,
    first_name: str,
    last_name: str,
    email: str,
    password: str,
    db: models.Session = Depends(get_db),
):
    # check params
    if not company_name or not first_name or not last_name or not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All fields are required",
        )
    # check if company exists
    company = (
        db.query(models.Company).filter(models.Company.name == company_name).first()
    )
    if company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company already exists",
        )
    # create company
    company = models.Company(name=company_name)
    db.add(company)
    db.commit()
    hashed_password = hash_password(password)
    user = models.User(
        email=email,
        password_hash=hashed_password,
        company_id=company.id,
        first_name=first_name,
        last_name=last_name,
    )
    db.add(user)
    db.commit()
    return {"status": "ok"}


@router.post("/api/token")
def get_token(username: str, password: str, db: models.Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == username).first()

    if not user or not verify_password(password, user.password_hash):
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
