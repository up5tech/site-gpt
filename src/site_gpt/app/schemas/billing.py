from datetime import datetime

from pydantic import BaseModel, Field


class BillingStatus(BaseModel):
    """Whether paid billing is switched on for this deployment (V5 F2)."""

    enabled: bool


class BillingSummary(BaseModel):
    """One company's mirrored subscription state.

    Deliberately carries no Stripe customer/subscription id, no secret and no
    payment method: the console renders plan, state and renewal only.
    """

    has_billing_account: bool
    plan_code: str | None = None
    interval: str | None = None
    status: str | None = None
    active: bool
    cancel_at_period_end: bool = False
    current_period_end: datetime | None = None


class UsageEntry(BaseModel):
    """One countable resource against its granted ceiling (V5 F3).

    `limit` is null when the company's plan does not enforce that key (billing
    off, unpaid, or a plan without the entitlement) — the console then shows the
    raw count instead of inventing a ceiling.
    """

    key: str
    used: int
    limit: int | None = None


class BillingUsage(BaseModel):
    """Plan state plus current usage, company-scoped and read-only (V5-32).

    Carries no Stripe id and no price: the console already reads the public
    catalog for those.
    """

    plan_code: str | None = None
    status: str | None = None
    enforced: bool
    websites: UsageEntry
    seats: UsageEntry


class CheckoutRequest(BaseModel):
    """The only client input a Checkout start accepts.

    Extra fields are ignored by Pydantic, so a posted `amount`, `price_id`,
    `customer` or `success_url` can never reach Stripe.
    """

    plan_code: str = Field(min_length=1, max_length=64)


class CheckoutResponse(BaseModel):
    url: str


class PortalResponse(BaseModel):
    url: str


class WebhookReceived(BaseModel):
    received: bool
    duplicate: bool = False
