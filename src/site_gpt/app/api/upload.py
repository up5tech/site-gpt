import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.services.sources import AcquiredFile, get_provider

router = APIRouter()


class UrlUploadIn(BaseModel):
    url: str
    # Optional bearer token for authenticated/protected URLs.
    token: str | None = None


class GoogleDriveUploadIn(BaseModel):
    file_id: str
    # Access token obtained by the frontend via the Google Picker / OAuth popup.
    access_token: str


def _save_attachment(
    db: Session,
    user: models.User,
    acquired: AcquiredFile,
    *,
    source: str,
    source_ref: str | None = None,
) -> dict:
    """Persist fetched bytes as a local file under uploads/ and create an
    Attachment row. Returns the same shape the frontend already expects."""
    original_name = acquired.filename or "file"
    ext = os.path.splitext(original_name)[1]
    safe_name = f"{uuid4().hex}{ext}"

    os.makedirs("uploads", exist_ok=True)
    file_path = os.path.join("uploads", safe_name)
    with open(file_path, "wb") as f:
        f.write(acquired.content)

    attachment = models.Attachment(
        filename=original_name,
        file_url=safe_name,
        status="tmp",
        file_size=len(acquired.content),
        file_type=acquired.content_type,
        user_id=user.id,
        source=source,
        source_ref=source_ref,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {
        "file_id": attachment.id,
        "filename": original_name,
        "file_url": safe_name,
        "file_size": len(acquired.content),
        "file_type": acquired.content_type,
        "source": source,
        "source_ref": source_ref,
    }


@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Store under a unique, sanitized name to avoid collisions / path traversal.
    original_name = os.path.basename(file.filename or "file")
    ext = os.path.splitext(original_name)[1]
    safe_name = f"{uuid4().hex}{ext}"

    os.makedirs("uploads", exist_ok=True)
    file_path = os.path.join("uploads", safe_name)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    fileUpload = models.Attachment(
        filename=original_name,
        file_url=safe_name,
        status="tmp",
        file_size=len(content),
        file_type=file.content_type,
        user_id=user.id,
        source="local",
    )
    db.add(fileUpload)
    db.commit()
    db.refresh(fileUpload)
    return {
        "file_id": fileUpload.id,
        "filename": original_name,
        "file_url": safe_name,
        "file_size": len(content),
        "file_type": file.content_type,
        "source": "local",
        "source_ref": None,
    }


@router.post("/url")
async def upload_from_url(
    payload: UrlUploadIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Fetch a file from any HTTP(S) URL and store it like a local upload."""
    provider = get_provider("url")
    acquired = await provider.acquire(payload.url, payload.token)
    return _save_attachment(
        db, user, acquired, source="url", source_ref=payload.url
    )


@router.post("/google-drive")
async def upload_from_google_drive(
    payload: GoogleDriveUploadIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Import a file from Google Drive given its file id + an access token."""
    provider = get_provider("google_drive")
    acquired = await provider.acquire(payload.file_id, payload.access_token)
    return _save_attachment(
        db, user, acquired, source="google_drive", source_ref=payload.file_id
    )
