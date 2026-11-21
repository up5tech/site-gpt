import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.core.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from site_gpt.app.db.session import get_db
from site_gpt.app.services.net_guard import UnsafeUrl
from site_gpt.app.services.sources import (
    AcquiredFile,
    FileTooLarge,
    SourceAuthError,
    SourceRefError,
    get_provider,
)

router = APIRouter()

# Read uploads in small chunks so an oversized body is rejected without ever
# being buffered in full (see MAX_UPLOAD_BYTES).
UPLOAD_CHUNK_SIZE = 64 * 1024


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=(
            "File too large. The maximum allowed size is "
            f"{MAX_UPLOAD_MB} MB."
        ),
    )


async def _stream_to_disk(file: UploadFile, file_path: str) -> int:
    """Write an upload to disk chunk by chunk, aborting over the limit.

    Returns the number of bytes written. The partial file is removed when the
    limit is exceeded (or anything else fails), so a rejected upload leaves no
    trace on disk.
    """
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise _too_large()

    total = 0
    try:
        with open(file_path, "wb") as out:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise _too_large()
                out.write(chunk)
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise
    return total


class UrlUploadIn(BaseModel):
    url: str
    # Optional bearer token for authenticated/protected URLs.
    token: str | None = None


class YoutubeUploadIn(BaseModel):
    # A video URL or id, a playlist URL or a channel URL.
    url: str


class NotionUploadIn(BaseModel):
    # A page or database URL, or its id.
    url: str
    # Notion integration token for this request only: never stored or echoed.
    token: str


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
    file_size = await _stream_to_disk(file, file_path)

    fileUpload = models.Attachment(
        filename=original_name,
        file_url=safe_name,
        status="tmp",
        file_size=file_size,
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
        "file_size": file_size,
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
    try:
        acquired = await provider.acquire(payload.url, payload.token)
    except FileTooLarge:
        raise _too_large()
    except UnsafeUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _save_attachment(
        db, user, acquired, source="url", source_ref=payload.url
    )


@router.post("/youtube")
async def upload_from_youtube(
    payload: YoutubeUploadIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Import a video, playlist or channel as caption markdown attachments.

    Every video is saved as its own file, so the rest of the flow (`file_ids` →
    `POST /api/extra_documents` → worker ingest) is exactly the local-upload one.
    The response carries the same per-file shape as `/url` and `/google-drive`,
    plus the sitemap-sync-style `added`/`total`/`truncated` counts and
    `total_exact` (always true here: the playlist/channel page is read in full).
    """
    provider = get_provider("youtube")
    try:
        acquired_files, total, truncated, total_exact = await provider.acquire_many(
            payload.url
        )
    except FileTooLarge:
        raise _too_large()
    except (SourceRefError, UnsafeUrl) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    files = [
        _save_attachment(
            db,
            user,
            acquired,
            source="youtube",
            source_ref=acquired.source_ref or payload.url,
        )
        for acquired in acquired_files
    ]
    return {
        "files": files,
        "added": len(files),
        "total": total,
        "truncated": truncated,
        "total_exact": total_exact,
    }


@router.post("/notion")
async def upload_from_notion(
    payload: NotionUploadIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Import a Notion page, or every page of a database, as markdown files.

    The integration token is used for this request only (the Google Drive
    `access_token` precedent): it is not stored, logged or echoed. One file per
    page, so the rest of the flow is the local-upload one, and the response
    carries the same per-file shape plus `added`/`total`/`truncated`/
    `total_exact`. `total` is the database's real page count while counting it
    stayed within `NOTION_MAX_COUNT_PAGES` (so a capped 500-page database says
    "25 of 500", never "25 of 100"); a database too large to count that cheaply
    reports a lower bound and `total_exact: false` instead.
    """
    provider = get_provider("notion")
    try:
        acquired_files, total, truncated, total_exact = await provider.acquire_many(
            payload.url, payload.token
        )
    except FileTooLarge:
        raise _too_large()
    except SourceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except (SourceRefError, UnsafeUrl) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    files = [
        _save_attachment(
            db,
            user,
            acquired,
            source="notion",
            source_ref=acquired.source_ref or payload.url,
        )
        for acquired in acquired_files
    ]
    return {
        "files": files,
        "added": len(files),
        "total": total,
        "truncated": truncated,
        "total_exact": total_exact,
    }


@router.post("/google-drive")
async def upload_from_google_drive(
    payload: GoogleDriveUploadIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Import a file from Google Drive given its file id + an access token."""
    provider = get_provider("google_drive")
    try:
        acquired = await provider.acquire(
            payload.file_id, payload.access_token
        )
    except FileTooLarge:
        raise _too_large()
    return _save_attachment(
        db, user, acquired, source="google_drive", source_ref=payload.file_id
    )
