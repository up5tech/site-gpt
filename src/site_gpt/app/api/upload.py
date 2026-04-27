import os
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi import UploadFile, File
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
    # upload file
    os.makedirs("uploads", exist_ok=True)
    file_url = f"{file.filename}"
    file_path = f"uploads/{file_url}"
    with open(file_path, "wb") as f:
        f.write(file.file.read())
    # save to db
    fileUpload = models.Attachment(
        filename=file.filename,
        file_url=file_url,
        status="tmp",
        file_size=file.size,
        file_type=file.content_type,
        user_id=user.id,
    )
    db.add(fileUpload)
    db.commit()
    db.refresh(fileUpload)
    file_id = fileUpload.id
    return {
        "file_id": file_id,
        "filename": file.filename,
        "file_url": file_path,
        "file_size": file.size,
        "file_type": file.content_type,
    }
