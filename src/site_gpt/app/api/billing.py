"""Billing API: Checkout, Billing Portal, subscription summary and the webhook.

Every route is company-scoped through the authenticated user — there is no
company id or Stripe id in any request body — and only a company admin may start
Checkout or open the Stripe Billing Portal (V5 decisions D3/D5, invariant 4).

The Stripe webhook is the one unauthenticated route here, and it is not open: it
verifies `Stripe-Signature` against the endpoint secret over the exact raw body
before it touches a row. The browser's Checkout return URL is never read.

With `BILLING_ENABLED=false` (the default) the whole surface except `GET
/api/billing/status` answers 404, so a self-hosted deployment needs no Stripe
configuration and no route silently accepts a payment event (invariant 5).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.core.auth import get_admin_user, get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.billing import (
    BillingStatus,
    BillingSummary,
    BillingUsage,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    WebhookReceived,
)
from site_gpt.app.services import billing, entitlements

router = APIRouter()


def _enabled() -> None:
    """Refuse the billing surface when billing is switched off."""
    if not config.BILLING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing is not enabled",
        )


def _http(exc: billing.BillingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/api/billing/status", response_model=BillingStatus, tags=["billing"])
def billing_status(
    user: models.User = Depends(get_current_user),
) -> BillingStatus:
    """Whether billing is enabled, so the console can gate its navigation.

    Deliberately answers even when disabled: the console needs a truthful
    "billing is off" state instead of a 404 it would have to interpret.
    """
    return BillingStatus(enabled=config.BILLING_ENABLED)


@router.get(
    "/api/billing/subscription", response_model=BillingSummary, tags=["billing"]
)
def get_subscription(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> BillingSummary:
    """The signed-in user's company subscription state (read-only)."""
    _enabled()
    return BillingSummary(**billing.summary(db, user.company_id))


@router.get("/api/billing/usage", response_model=BillingUsage, tags=["billing"])
def get_usage(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> BillingUsage:
    """This company's plan state and countable usage (V5-32).

    Read-only and company-scoped, like the summary: a member may see what the
    plan includes, but only an admin can change billing.
    """
    _enabled()
    return BillingUsage(**entitlements.usage(db, user.company_id))


@router.post(
    "/api/billing/checkout", response_model=CheckoutResponse, tags=["billing"]
)
def create_checkout(
    body: CheckoutRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
) -> CheckoutResponse:
    """Start Stripe-hosted Checkout for an approved, configured plan.

    `plan_code` is the only accepted input; the price, customer and return URLs
    are resolved server-side, so a tampered body cannot change what is charged.
    """
    _enabled()
    try:
        url = billing.start_checkout(db, user.company_id, body.plan_code)
    except billing.BillingError as exc:
        raise _http(exc) from exc
    return CheckoutResponse(url=url)


@router.post("/api/billing/portal", response_model=PortalResponse, tags=["billing"])
def create_portal_session(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
) -> PortalResponse:
    """Open the Stripe Billing Portal for this company's own customer."""
    _enabled()
    try:
        url = billing.portal_url(db, user.company_id)
    except billing.BillingError as exc:
        raise _http(exc) from exc
    return PortalResponse(url=url)


@router.post(
    "/api/billing/webhook", response_model=WebhookReceived, tags=["billing"]
)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> WebhookReceived:
    """Receive a signed Stripe event.

    Runs the verification and the DB work off the event loop: the body must be
    read raw (not parsed as JSON) for the signature check, and the apply step is
    a synchronous transaction. A transient failure rolls back and answers 500 so
    Stripe retries; a duplicate is acknowledged with 200 and changes nothing.
    """
    _enabled()
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        outcome = await asyncio.to_thread(
            billing.process_webhook, db, payload, signature
        )
    except billing.BillingSignatureError as exc:
        raise _http(exc) from exc
    except billing.BillingError as exc:
        raise _http(exc) from exc
    return WebhookReceived(received=True, duplicate=outcome == "duplicate")
