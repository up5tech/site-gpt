import os
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.app import PaginatedResponse
from site_gpt.app.schemas.extra_document import (
    AttachmentRes,
    ExtraDocumentCreate,
    ExtraDocumentRes,
    ExtraDocumentUpdate,
)

router = APIRouter()


@router.get("/", response_model=PaginatedResponse)
def get_extra_documents(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        query = db.query(models.ExtraDocument).filter(
            models.ExtraDocument.company_id == user.company_id
        )
        total = query.count()
        documents = query.offset((page - 1) * limit).limit(limit).all()
        items: List[ExtraDocumentRes] = [];
        for doc in documents:
            item = ExtraDocumentRes.model_validate(doc)
            # get attachments
            attachments = (
                db.query(models.Attachment)
                .filter(models.Attachment.extra_document_id == doc.id)
                .all()
            )
            item.attachments = [
                AttachmentRes.model_validate(a) for a in attachments
            ]
            items.append(item)
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{extra_document_id}", response_model=ExtraDocumentRes)
def get_extra_document(
    extra_document_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        document = (
            db.query(models.ExtraDocument)
            .filter(
                models.ExtraDocument.id == extra_document_id,
                models.ExtraDocument.company_id == user.company_id,
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return ExtraDocumentRes.model_validate(document)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{extra_document_id}")
def delete_extra_document(
    extra_document_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        document = (
            db.query(models.ExtraDocument)
            .filter(
                models.ExtraDocument.id == extra_document_id,
                models.ExtraDocument.company_id == user.company_id,
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        db.delete(document)
        db.commit()
        return {"message": "Document deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=ExtraDocumentRes)
def create_extra_document(
    document_in: ExtraDocumentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        # Create the extra document
        extra_document = models.ExtraDocument(
            name=document_in.name,
            content=document_in.content,
            website_id=document_in.website_id,
            company_id=user.company_id,
        )
        db.add(extra_document)
        db.commit()
        db.refresh(extra_document)
        # attachments
        if document_in.file_ids:
            for file_id in document_in.file_ids:
                attachment = (
                    db.query(models.Attachment)
                    .filter(
                        models.Attachment.id == file_id,
                        models.Attachment.user_id == user.id,
                    )
                    .first()
                )
                if attachment:
                    attachment.extra_document_id = extra_document.id
                    attachment.status = "uploaded"
            db.commit()
        return ExtraDocumentRes.model_validate(extra_document)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{extra_document_id}", response_model=ExtraDocumentRes)
def update_extra_document(
    extra_document_id: UUID,
    document_in: ExtraDocumentUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        document = (
            db.query(models.ExtraDocument)
            .filter(
                models.ExtraDocument.id == extra_document_id,
                models.ExtraDocument.company_id == user.company_id,
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        for key, value in document_in.model_dump(exclude_unset=True).items():
            setattr(document, key, value)
        db.commit()
        db.refresh(document)
        # add attachments
        if document_in.file_ids:
            for file_id in document_in.file_ids:
                attachment = (
                    db.query(models.Attachment)
                    .filter(
                        models.Attachment.id == file_id,
                        models.Attachment.user_id == user.id,
                    )
                    .first()
                )
                if attachment:
                    attachment.extra_document_id = document.id
                    attachment.status = "uploaded"
            db.commit()
        # remove attachments
        if document_in.delete_file_ids:
            for file_id in document_in.delete_file_ids:
                attachment = (
                    db.query(models.Attachment)
                    .filter(
                        models.Attachment.id == file_id,
                        models.Attachment.user_id == user.id,
                    )
                    .first()
                )
                if attachment:
                    # delete file
                    file_path = f"uploads/{attachment.file_url}"
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    # delete from db
                    db.delete(attachment)
            db.commit()
        return ExtraDocumentRes.model_validate(document)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
