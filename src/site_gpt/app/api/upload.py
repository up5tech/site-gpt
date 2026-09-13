import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session
from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db

router = APIRouter()


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
    }
