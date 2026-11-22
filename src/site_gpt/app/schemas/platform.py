"""Platform (operator) request/response models (V5-40 … V5-43).

Nothing here carries a credential, a secret, card data or a raw provider object.
The subscription views include opaque Stripe identifiers for support and
reconciliation; the public plan payload never does.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PlatformSession(BaseModel):
    """The authenticated operator, as the grant resolves them."""

    user_id: UUID
    email: str
    granted_at: datetime


class PlatformAuditEvent(BaseModel):
    """One append-only audit row; `detail` is already redacted when stored."""

    id: UUID
    created_at: datetime
    action: str
    target_type: str
    target_id: str | None = None
    actor_user_id: UUID | None = None
    actor_label: str | None = None
    detail: dict | None = None


class PlatformAuditList(BaseModel):
    events: list[PlatformAuditEvent]


# -- overview and cross-company reads (V5-41) --------------------------------


class PlatformOverview(BaseModel):
    companies: int
    websites: int
    active_users: int
    published_plans: int
    subscriptions: dict[str, int]


class PlatformCompany(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    websites: int
    active_users: int
    plan_code: str | None = None
    status: str | None = None
    interval: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


class PlatformCompanyList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PlatformCompany]


class PlatformSubscription(BaseModel):
    company_id: UUID
    company_name: str
    plan_code: str
    status: str
    interval: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    last_event_at: datetime | None = None


class PlatformSubscriptionList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PlatformSubscription]


class SubscriptionActionRequest(BaseModel):
    """The only accepted inputs; no company/plan/status can be set here."""

    action: Literal["cancel_at_period_end", "request_reconciliation"]
    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


class SubscriptionActionResult(BaseModel):
    action: str
    company_id: str
    status: str
    stripe_updated: bool = False


# -- durable catalog (V5-42) -------------------------------------------------


class PlatformPrice(BaseModel):
    """One immutable price record. `stripe_price_id` is operator-only."""

    id: UUID
    interval: str
    currency: str
    price_minor: int
    stripe_price_id: str | None = None
    active: bool
    created_at: datetime


class PlatformPlan(BaseModel):
    id: UUID
    code: str
    name: str
    description: str
    features: list[str]
    limits: dict[str, int]
    self_serve_checkout: bool
    status: str
    prices: list[PlatformPrice]
    created_at: datetime
    updated_at: datetime


class PlatformPlanList(BaseModel):
    plans: list[PlatformPlan]


class PlanCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    features: list[str] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)
    self_serve_checkout: bool = True
    interval: Literal["month", "year"] = "month"
    currency: str = Field(min_length=3, max_length=3)
    price_minor: int = Field(ge=0)
    stripe_price_id: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=3, max_length=500)


class PlanUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    features: list[str] | None = None
    limits: dict[str, int] | None = None
    self_serve_checkout: bool | None = None
    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


class PlanPriceRequest(BaseModel):
    interval: Literal["month", "year"]
    currency: str = Field(min_length=3, max_length=3)
    price_minor: int = Field(ge=0)
    stripe_price_id: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


class PlanLifecycleRequest(BaseModel):
    """Publish/archive confirmation. High-impact changes need `confirm`."""

    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


# -- typed global settings (V5-43, D12) --------------------------------------


class PlatformSetting(BaseModel):
    key: str
    label: str
    description: str
    kind: str
    max_length: int
    default: Any
    value: Any
    is_override: bool
    high_impact: bool
    updated_at: datetime | None = None
    updated_by_user_id: UUID | None = None


class PlatformSettingList(BaseModel):
    settings: list[PlatformSetting]


class SettingPreviewRequest(BaseModel):
    value: Any


class SettingPreview(BaseModel):
    key: str
    current: Any
    next: Any
    changed: bool


class SettingUpdateRequest(BaseModel):
    """No key or actor here: the path key must be allowlisted and the actor is
    the authenticated operator, never a client-supplied identity."""

    value: Any
    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


# -- public display config (V5-43) -------------------------------------------


class PublicConfig(BaseModel):
    status_message: str = ""
    support_email: str = ""
