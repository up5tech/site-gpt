"""Admin CRUD for outbound integrations (F7).

Reads are always masked: a stored token comes back as `"***"`, never as its
value, so this router cannot be used as a secret exfiltration path. A PATCH that
echoes the mask keeps the stored secret instead of overwriting it with `"***"`.

Nothing here logs a config value: the audit in V2-44 asserts that.
"""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.integration import (
    IntegrationCreate,
    IntegrationRes,
    IntegrationTestResult,
    IntegrationUpdate,
)
from site_gpt.app.services.integrations import (
    EVENT_TYPES,
    PROVIDERS,
    config_of,
    events_of,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MASK = "***"


def _provider(integration_type: str):
    provider = PROVIDERS.get(integration_type)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown integration type. Allowed: {', '.join(sorted(PROVIDERS))}.",
        )
    return provider


def _masked(type_name: str, config_data: dict) -> dict:
    """Copy of the config with every secret replaced by the mask."""
    provider = PROVIDERS.get(type_name)
    masked = dict(config_data)
    for field in provider.secret_fields if provider is not None else ():
        if masked.get(field):
            masked[field] = MASK
    return masked


def _to_res(integration: models.Integration) -> IntegrationRes:
    provider = PROVIDERS.get(integration.type)
    return IntegrationRes(
        id=integration.id,
        type=integration.type,
        name=integration.name,
        config=_masked(integration.type, config_of(integration)),
        events=events_of(integration),
        enabled=integration.enabled,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        secret_fields=list(provider.secret_fields if provider else ()),
    )


def _merge_config(
    stored: dict, incoming: dict, secret_fields: tuple[str, ...]
) -> dict:
    """Apply an update, keeping a stored secret when the client sent the mask."""
    merged = dict(stored)
    for key, value in incoming.items():
        if key in secret_fields and value == MASK:
            continue
        merged[key] = value
    return merged


def _safe_error(exc: Exception, config_data: dict, secret_fields) -> str:
    """An operator-readable error with any credential scrubbed out.

    httpx puts the URL in its messages, and a Slack webhook URL *is* the secret,
    so every stored secret value is redacted before the message is returned.
    """
    message = f"{type(exc).__name__}: {exc}"
    for field in secret_fields:
        value = str(config_data.get(field) or "")
        if value:
            message = message.replace(value, MASK)
    return message[:300]


def _scoped(db: Session, company_id: UUID, integration_id: UUID):
    return (
        db.query(models.Integration)
        .filter(
            models.Integration.id == integration_id,
            models.Integration.company_id == company_id,
        )
        .first()
    )


def _validate_events(events: list[str]) -> list[str]:
    unknown = sorted(set(events) - set(EVENT_TYPES))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown event(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(EVENT_TYPES)}.",
        )
    return sorted(set(events))


@router.get("/", response_model=list[IntegrationRes])
def list_integrations(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    rows = (
        db.query(models.Integration)
        .filter(models.Integration.company_id == user.company_id)
        .order_by(models.Integration.created_at.desc())
        .all()
    )
    return [_to_res(row) for row in rows]


@router.post(
    "/", response_model=IntegrationRes, status_code=status.HTTP_201_CREATED
)
def create_integration(
    body: IntegrationCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    provider = _provider(body.type)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An integration needs a name.",
        )

    integration = models.Integration(
        company_id=user.company_id,
        type=body.type,
        name=name,
        config=json.dumps(body.config),
        events=json.dumps(_validate_events(body.events)),
        enabled=body.enabled,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    logger.info(
        "integration %s created for company %s (%s)",
        integration.id,
        user.company_id,
        provider.type,
    )
    return _to_res(integration)


@router.patch("/{integration_id}", response_model=IntegrationRes)
def update_integration(
    integration_id: UUID,
    body: IntegrationUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    integration = _scoped(db, user.company_id, integration_id)
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An integration needs a name.",
            )
        integration.name = name
    if body.events is not None:
        integration.events = json.dumps(_validate_events(body.events))
    if body.enabled is not None:
        integration.enabled = body.enabled
    if body.config is not None:
        provider = PROVIDERS.get(integration.type)
        integration.config = json.dumps(
            _merge_config(
                config_of(integration),
                body.config,
                provider.secret_fields if provider else (),
            )
        )

    db.commit()
    db.refresh(integration)
    return _to_res(integration)


@router.delete("/{integration_id}")
def delete_integration(
    integration_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    integration = _scoped(db, user.company_id, integration_id)
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    db.delete(integration)
    db.commit()
    return {"status": "deleted"}


@router.post("/{integration_id}/test", response_model=IntegrationTestResult)
async def test_integration(
    integration_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    """Send a synthetic `ping` to this integration only, and report the result."""
    integration = _scoped(db, user.company_id, integration_id)
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    provider = _provider(integration.type)
    config_data = config_of(integration)
    payload = {
        "event": "ping",
        "integration_id": str(integration.id),
        "company_id": str(user.company_id),
    }
    try:
        result = await provider.send(config_data, "ping", payload)
    except Exception as exc:
        return IntegrationTestResult(
            type=integration.type,
            delivered=False,
            error=_safe_error(exc, config_data, provider.secret_fields),
        )
    return IntegrationTestResult(
        type=integration.type,
        delivered=True,
        status_code=result.get("status_code"),
    )
