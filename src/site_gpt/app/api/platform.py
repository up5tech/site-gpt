"""The platform-owner surface (V5-40 … V5-43, Wave 4).

Everything here answers 404 while `PLATFORM_CONSOLE_ENABLED` is false, and every
route requires `require_platform_owner` — a grant provisioned out of band, never
a tenant role. The surface is separate from `/app`: it can see across companies,
but it cannot impersonate one, mint a grant, mark a subscription paid or read a
secret.

* **V5-41** — overview, paginated companies/subscriptions and two audited
  actions. `cancel_at_period_end` asks Stripe only; the local mirror changes
  only through a verified webhook.
* **V5-42** — the durable catalog. Draft/create/edit, immutable price changes,
  publish and archive, all validated and audited. Public pricing keeps its old
  response contract.
* **V5-43** — the typed, non-secret global-settings allowlist. Unknown keys are
  rejected, values are validated, a preview writes nothing, and every change is
  audited in the same transaction.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.core.auth import require_platform_owner
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.platform import (
    PlanCreateRequest,
    PlanLifecycleRequest,
    PlanPriceRequest,
    PlanUpdateRequest,
    PlatformAuditEvent,
    PlatformAuditList,
    PlatformCompanyList,
    PlatformOverview,
    PlatformPlan,
    PlatformPlanList,
    PlatformPrice,
    PlatformSession,
    PlatformSetting,
    PlatformSettingList,
    PlatformSubscriptionList,
    SettingPreview,
    SettingPreviewRequest,
    SettingUpdateRequest,
    SubscriptionActionRequest,
    SubscriptionActionResult,
)
from site_gpt.app.services import (
    plan_catalog,
    platform,
    platform_ops,
    platform_settings,
)

router = APIRouter()


def platform_console_enabled() -> None:
    """404 for the whole surface while the console switch is off."""
    if not config.PLATFORM_CONSOLE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )


def _catalog_http(exc: plan_catalog.CatalogError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _settings_http(exc: platform_settings.SettingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _action_http(exc: platform_ops.PlatformActionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _price_payload(price: models.PlanPrice) -> PlatformPrice:
    return PlatformPrice(
        id=price.id,
        interval=price.interval,
        currency=price.currency,
        price_minor=price.price_minor,
        stripe_price_id=price.stripe_price_id,
        active=price.active,
        created_at=price.created_at,
    )


def _plan_payload(row: models.CatalogPlan) -> PlatformPlan:
    return PlatformPlan(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description or "",
        features=list(row.features or []),
        limits=dict(row.limits or {}),
        self_serve_checkout=bool(row.self_serve_checkout),
        status=row.status,
        prices=[_price_payload(price) for price in row.prices],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/api/platform/session",
    response_model=PlatformSession,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_session(
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformSession:
    """Who the signed-in operator is, resolved through their active grant."""
    grant = platform.active_grant(db, user.id)
    return PlatformSession(
        user_id=user.id, email=user.email, granted_at=grant.created_at
    )


@router.get(
    "/api/platform/overview",
    response_model=PlatformOverview,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_overview(
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformOverview:
    return PlatformOverview(**platform_ops.overview(db))


@router.get(
    "/api/platform/companies",
    response_model=PlatformCompanyList,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_companies(
    search: str | None = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=platform_ops.MAX_PAGE_SIZE),
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformCompanyList:
    return PlatformCompanyList(
        **platform_ops.list_companies(
            db, search=search, page=page, page_size=page_size
        )
    )


@router.get(
    "/api/platform/subscriptions",
    response_model=PlatformSubscriptionList,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_subscriptions(
    status_filter: str | None = Query(None, alias="status", max_length=32),
    search: str | None = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=platform_ops.MAX_PAGE_SIZE),
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformSubscriptionList:
    return PlatformSubscriptionList(
        **platform_ops.list_subscriptions(
            db,
            status=status_filter,
            search=search,
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/api/platform/subscriptions/{company_id}/actions",
    response_model=SubscriptionActionResult,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_subscription_action(
    company_id: uuid.UUID,
    body: SubscriptionActionRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> SubscriptionActionResult:
    """One approved action; the service audits every outcome itself."""
    try:
        result = platform_ops.apply_action(
            db,
            company_id,
            action=body.action,
            reason=body.reason,
            confirm=body.confirm,
            actor_user_id=user.id,
        )
    except platform_ops.PlatformActionError as exc:
        raise _action_http(exc) from exc
    return SubscriptionActionResult(**result)


@router.get(
    "/api/platform/plans",
    response_model=PlatformPlanList,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_plans(
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformPlanList:
    """Draft, published and archived plans with their price history."""
    return PlatformPlanList(
        plans=[_plan_payload(row) for row in plan_catalog.list_plans(db)]
    )


@router.post(
    "/api/platform/plans",
    response_model=PlatformPlan,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_create_plan(
    body: PlanCreateRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformPlan:
    try:
        row = plan_catalog.create_plan(
            db,
            code=body.code,
            name=body.name,
            description=body.description,
            features=body.features,
            limits=body.limits,
            self_serve_checkout=body.self_serve_checkout,
            interval=body.interval,
            currency=body.currency,
            price_minor=body.price_minor,
            stripe_price_id=body.stripe_price_id,
            commit=False,
        )
    except plan_catalog.CatalogError as exc:
        raise _catalog_http(exc) from exc
    platform.record_audit(
        db,
        action="platform.plan.create",
        target_type="plan",
        target_id=row.code,
        actor_user_id=user.id,
        detail={
            "reason": body.reason,
            "status": row.status,
            "interval": body.interval,
            "currency": body.currency.upper(),
            "price_minor": body.price_minor,
            "stripe_mapped": bool(body.stripe_price_id),
        },
    )
    db.refresh(row)
    return _plan_payload(row)


@router.put(
    "/api/platform/plans/{code}",
    response_model=PlatformPlan,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_update_plan(
    code: str,
    body: PlanUpdateRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformPlan:
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm the plan edit explicitly.",
        )
    try:
        row = plan_catalog.update_plan(
            db,
            code,
            name=body.name,
            description=body.description,
            features=body.features,
            limits=body.limits,
            self_serve_checkout=body.self_serve_checkout,
            commit=False,
        )
    except plan_catalog.CatalogError as exc:
        raise _catalog_http(exc) from exc
    platform.record_audit(
        db,
        action="platform.plan.update",
        target_type="plan",
        target_id=row.code,
        actor_user_id=user.id,
        detail={
            "reason": body.reason,
            "fields": [
                name
                for name in (
                    "name",
                    "description",
                    "features",
                    "limits",
                    "self_serve_checkout",
                )
                if getattr(body, name) is not None
            ],
        },
    )
    db.refresh(row)
    return _plan_payload(row)


@router.post(
    "/api/platform/plans/{code}/prices",
    response_model=PlatformPlan,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_add_price(
    code: str,
    body: PlanPriceRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformPlan:
    """Create a new immutable price row; the old one stays as history."""
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm the price change explicitly.",
        )
    try:
        row = plan_catalog.add_price(
            db,
            code,
            interval=body.interval,
            currency=body.currency,
            price_minor=body.price_minor,
            stripe_price_id=body.stripe_price_id,
            commit=False,
        )
    except plan_catalog.CatalogError as exc:
        raise _catalog_http(exc) from exc
    platform.record_audit(
        db,
        action="platform.plan.price",
        target_type="plan",
        target_id=row.code,
        actor_user_id=user.id,
        detail={
            "reason": body.reason,
            "interval": body.interval,
            "currency": body.currency.upper(),
            "price_minor": body.price_minor,
            "stripe_mapped": bool(body.stripe_price_id),
        },
    )
    db.refresh(row)
    return _plan_payload(row)


@router.post(
    "/api/platform/plans/{code}/publish",
    response_model=PlatformPlan,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_publish_plan(
    code: str,
    body: PlanLifecycleRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformPlan:
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm publishing this plan explicitly.",
        )
    try:
        row = plan_catalog.publish_plan(db, code, commit=False)
    except plan_catalog.CatalogError as exc:
        raise _catalog_http(exc) from exc
    platform.record_audit(
        db,
        action="platform.plan.publish",
        target_type="plan",
        target_id=row.code,
        actor_user_id=user.id,
        detail={"reason": body.reason},
    )
    db.refresh(row)
    return _plan_payload(row)


@router.post(
    "/api/platform/plans/{code}/archive",
    response_model=PlatformPlan,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_archive_plan(
    code: str,
    body: PlanLifecycleRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformPlan:
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm archiving this plan explicitly.",
        )
    try:
        row = plan_catalog.archive_plan(db, code, commit=False)
    except plan_catalog.CatalogError as exc:
        raise _catalog_http(exc) from exc
    platform.record_audit(
        db,
        action="platform.plan.archive",
        target_type="plan",
        target_id=row.code,
        actor_user_id=user.id,
        detail={"reason": body.reason},
    )
    db.refresh(row)
    return _plan_payload(row)


@router.get(
    "/api/platform/settings",
    response_model=PlatformSettingList,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_settings_list(
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformSettingList:
    return PlatformSettingList(
        settings=[
            PlatformSetting(**entry) for entry in platform_settings.entries(db)
        ]
    )


@router.post(
    "/api/platform/settings/{key}/preview",
    response_model=SettingPreview,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_setting_preview(
    key: str,
    body: SettingPreviewRequest,
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> SettingPreview:
    """Validate a proposed value without writing it or auditing a change."""
    try:
        return SettingPreview(**platform_settings.preview(db, key, body.value))
    except platform_settings.SettingError as exc:
        raise _settings_http(exc) from exc


@router.put(
    "/api/platform/settings/{key}",
    response_model=PlatformSetting,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_setting_update(
    key: str,
    body: SettingUpdateRequest,
    user: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformSetting:
    try:
        item = platform_settings.spec(key)
        value = platform_settings.validate(key, body.value)
        if item.high_impact and not body.confirm:
            raise platform_settings.SettingError(
                400, "Confirm this high-impact setting explicitly."
            )
        row, previous = platform_settings.set_value(
            db, key, value, actor_user_id=user.id, commit=False
        )
        platform.record_audit(
            db,
            action="platform.setting.update",
            target_type="setting",
            target_id=key,
            actor_user_id=user.id,
            detail={"reason": body.reason, "previous": previous, "value": value},
            commit=False,
        )
        db.commit()
    except platform_settings.SettingError as exc:
        db.rollback()
        raise _settings_http(exc) from exc
    db.refresh(row)
    return PlatformSetting(
        **next(
            entry for entry in platform_settings.entries(db) if entry["key"] == key
        )
    )


@router.get(
    "/api/platform/audit",
    response_model=PlatformAuditList,
    tags=["platform"],
    dependencies=[Depends(platform_console_enabled)],
)
def platform_audit(
    limit: int = Query(50, ge=1, le=200),
    _: models.User = Depends(require_platform_owner),
    db: Session = Depends(get_db),
) -> PlatformAuditList:
    """Newest-first audit rows, bounded so a read cannot dump the table."""
    rows = platform.recent_audit(db, limit)
    return PlatformAuditList(
        events=[
            PlatformAuditEvent(
                id=row.id,
                created_at=row.created_at,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                actor_user_id=row.actor_user_id,
                actor_label=row.actor_label,
                detail=row.detail,
            )
            for row in rows
        ]
    )
