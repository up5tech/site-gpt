from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRes
from site_gpt.app.services import audit
from site_gpt.app.services.api_keys import (
    ALLOWED_SCOPES,
    create_api_key,
    scopes_of,
)

router = APIRouter()


def _to_res(key: models.ApiKey) -> ApiKeyRes:
    return ApiKeyRes(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=scopes_of(key),
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


@router.get("/", response_model=list[ApiKeyRes])
def list_api_keys(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Every key of the company, revoked ones included (they carry `revoked_at`)."""
    keys = (
        db.query(models.ApiKey)
        .filter(models.ApiKey.company_id == user.company_id)
        .order_by(models.ApiKey.created_at.desc())
        .all()
    )
    return [_to_res(key) for key in keys]


@router.post("/", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Mint a key. The raw value is in this response only — store it now."""
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A key needs a name.",
        )
    unknown = sorted(set(body.scopes) - set(ALLOWED_SCOPES))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown scope(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(ALLOWED_SCOPES)}.",
        )

    key, raw_key = create_api_key(
        db, company_id=user.company_id, name=name, scopes=body.scopes
    )
    # The raw key is in this response only; the trail keeps the prefix, never the
    # key or its hash (V6-14).
    audit.record(
        db,
        company_id=user.company_id,
        action="api_key.create",
        target_type="api_key",
        target_id=key.id,
        actor=user,
        detail={"name": key.name, "prefix": key.key_prefix, "scopes": key.scopes},
        commit=True,
    )
    return ApiKeyCreated(**_to_res(key).model_dump(), key=raw_key)


@router.delete("/{key_id}")
def revoke_key(
    key_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Revoke a key. Kept as a row (with `revoked_at`) for the audit trail."""
    key = (
        db.query(models.ApiKey)
        .filter(
            models.ApiKey.id == key_id,
            models.ApiKey.company_id == user.company_id,
        )
        .first()
    )
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit.record(
            db,
            company_id=user.company_id,
            action="api_key.revoke",
            target_type="api_key",
            target_id=key.id,
            actor=user,
        )
        db.commit()
    return {"status": "revoked"}
