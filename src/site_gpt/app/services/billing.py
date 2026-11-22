"""Stripe billing: Checkout, Billing Portal and signed webhooks (V5 F2).

Three rules shape this module:

* **The server owns the price.** A browser sends a plan *code*; the code is
  resolved against `services.plan_catalog` (published plans only) and then to a
  private Stripe Price ID from `STRIPE_PRICE_IDS`. An unknown plan, a
  contact-sales plan or a plan without a mapping is refused with no Stripe call,
  so no client-supplied amount, currency, URL or Price ID can change what is
  charged (V5 invariant 2 and 8).
* **Only a verified webhook changes state.** Starting Checkout writes a row with
  status `incomplete`; access becomes paid only after a Stripe-signed event has
  been verified with the endpoint secret. Returning from Checkout changes
  nothing (V5 invariant 3).
* **Replays are harmless and stale events lose.** Every event id is inserted
  once (`unique`), so a duplicate delivery is acknowledged without applying
  twice; `Subscription.last_event_at` keeps an older, delayed event from
  restoring a state Stripe has already moved past.

Billing is off by default: nothing here is called, and no Stripe credential is
read, unless `BILLING_ENABLED` is true (V5 invariant 5).
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID

import stripe
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.services import plan_catalog

logger = logging.getLogger(__name__)

#: Stripe subscription states this mirror accepts. Anything else is ignored
#: rather than stored, so an unexpected provider value cannot become a made-up
#: lifecycle state.
SUBSCRIPTION_STATUSES = (
    "incomplete",
    "trialing",
    "active",
    "past_due",
    "unpaid",
    "canceled",
    "paused",
)

#: The events V5 acts on. Others are still receipted (so a retry is cheap) but
#: change no row.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }
)

ACTIVE_STATUSES = ("active", "trialing")


class BillingError(Exception):
    """A billing request that must not proceed, with the HTTP answer to send."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class BillingSignatureError(BillingError):
    """The webhook body did not verify against the endpoint signing secret."""

    def __init__(self):
        super().__init__(400, "Invalid Stripe signature")


# -- Stripe object helpers ----------------------------------------------------
#
# `Webhook.construct_event` returns a `stripe.Event` (dict-like object access),
# while tests pass plain dicts. These helpers accept both.


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _nested(obj: Any, *keys: str) -> Any:
    for key in keys:
        obj = _get(obj, key)
        if obj is None:
            return None
    return obj


def _text(obj: Any, key: str) -> str | None:
    value = _get(obj, key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(obj: Any, key: str) -> int | None:
    value = _get(obj, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _moment(epoch: int | None) -> datetime | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; comparisons here are always UTC-aware."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _company_id(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except (TypeError, ValueError):
        return None


# -- catalog configuration ----------------------------------------------------


def price_ids(raw: str | None = None) -> dict[str, str]:
    """Parse the private plan → Stripe Price mapping.

    Accepts a JSON object or comma-separated `code:interval=price_...` entries.
    Keys are normalized to lowercase `code:interval`; a value that is not a
    Stripe Price id is dropped, because a typo must fail closed, not be sent to
    the provider as a price.
    """
    value = config.STRIPE_PRICE_IDS if raw is None else raw
    value = (value or "").strip()
    if not value:
        return {}

    items: list[tuple[Any, Any]] = []
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            items = list(parsed.items())
    else:
        for entry in value.split(","):
            if "=" in entry:
                key, price = entry.split("=", 1)
                items.append((key, price))

    mapping: dict[str, str] = {}
    for key, price in items:
        key = str(key).strip().lower()
        price = str(price).strip()
        if key and price.startswith("price_"):
            mapping[key] = price
    return mapping


def price_id_for(plan: plan_catalog.Plan) -> str | None:
    """The private Stripe Price ID for a published plan, if configured."""
    key = f"{plan.code.strip().lower()}:{plan.interval}"
    return price_ids().get(key)


def _checkout_plan(code: str) -> tuple[plan_catalog.Plan, str]:
    plan = plan_catalog.find_plan(code)
    if plan is None:
        raise BillingError(400, "Unknown plan")
    if not plan.self_serve_checkout:
        raise BillingError(409, "This plan is not available for self-serve checkout.")
    price_id = price_id_for(plan)
    if price_id is None:
        raise BillingError(409, "This plan is not configured for checkout.")
    return plan, price_id


# -- company state ------------------------------------------------------------


def company_subscription(
    db: Session, company_id: UUID
) -> models.Subscription | None:
    """One company's subscription row, if Checkout was ever started."""
    return (
        db.query(models.Subscription)
        .filter(models.Subscription.company_id == company_id)
        .first()
    )


def summary(db: Session, company_id: UUID) -> dict:
    """The company-scoped billing state a console may read.

    No Stripe id, secret or raw object is included: the browser sees the plan
    code, the mirrored lifecycle state and the renewal date only.
    """
    row = company_subscription(db, company_id)
    if row is None:
        return {
            "has_billing_account": False,
            "plan_code": None,
            "interval": None,
            "status": None,
            "active": False,
            "cancel_at_period_end": False,
            "current_period_end": None,
        }
    return {
        "has_billing_account": True,
        "plan_code": row.plan_code or None,
        "interval": row.interval,
        "status": row.status,
        "active": row.status in ACTIVE_STATUSES,
        "cancel_at_period_end": bool(row.cancel_at_period_end),
        "current_period_end": row.current_period_end,
    }


def _frontend_base() -> str:
    """Configured return URL base. Never a value from the request (invariant 2)."""
    return config.FRONTEND_URL.rstrip("/")


def _ensure_customer(
    db: Session, company: models.Company, plan: plan_catalog.Plan
) -> str:
    """Reuse the company's Stripe Customer, creating it once if needed.

    The metadata is set server-side and is the mapping a webhook can trust; the
    deterministic idempotency key means two concurrent Checkout clicks resolve to
    the same customer instead of creating an orphan.
    """
    row = company_subscription(db, company.id)
    if row is not None and row.stripe_customer_id:
        if row.plan_code != plan.code.strip() or row.interval != plan.interval:
            row.plan_code = plan.code.strip()
            row.interval = plan.interval
            db.commit()
        return row.stripe_customer_id

    customer = stripe.Customer.create(
        api_key=config.STRIPE_SECRET_KEY,
        name=company.name,
        metadata={"company_id": str(company.id)},
        idempotency_key=f"sitegpt-customer-{company.id}",
    )
    customer_id = _text(customer, "id")
    if not customer_id:
        raise BillingError(502, "Stripe did not return a customer id")

    if row is None:
        row = models.Subscription(
            company_id=company.id,
            plan_code=plan.code.strip(),
            interval=plan.interval,
            status="incomplete",
            stripe_customer_id=customer_id,
        )
        db.add(row)
    else:
        row.stripe_customer_id = customer_id
    db.commit()
    return customer_id


def start_checkout(db: Session, company_id: UUID, plan_code: str) -> str:
    """Create a Stripe-hosted Checkout Session in `subscription` mode.

    Only hosted card entry is used: SiteGPT never sees a PAN or CVC. The caller
    already authenticated as a company admin; the company is resolved here from
    the token, never from the body.
    """
    company = db.get(models.Company, company_id)
    if company is None:
        raise BillingError(404, "Company not found")

    plan, price_id = _checkout_plan(plan_code)
    customer_id = _ensure_customer(db, company, plan)
    metadata = {
        "company_id": str(company.id),
        "plan_code": plan.code.strip(),
        "plan_interval": plan.interval,
    }

    session = stripe.checkout.Session.create(
        api_key=config.STRIPE_SECRET_KEY,
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{_frontend_base()}/app/billing?checkout=success",
        cancel_url=f"{_frontend_base()}/app/billing?checkout=cancelled",
        client_reference_id=str(company.id),
        metadata=metadata,
        subscription_data={"metadata": metadata},
        idempotency_key=(
            f"sitegpt-checkout-{company.id}-{plan.code.strip()}-{plan.interval}"
        ),
    )
    url = _text(session, "url")
    if not url:
        raise BillingError(502, "Stripe did not return a checkout URL")
    return url


def portal_url(db: Session, company_id: UUID) -> str:
    """A Stripe Billing Portal session for this company's own customer only.

    A company without a stored customer has no portal — a 404 rather than a new
    customer, so a foreign or unknown Stripe id is never addressable.
    """
    row = company_subscription(db, company_id)
    if row is None or not row.stripe_customer_id:
        raise BillingError(404, "No billing account yet")

    session = stripe.billing_portal.Session.create(
        api_key=config.STRIPE_SECRET_KEY,
        customer=row.stripe_customer_id,
        return_url=f"{_frontend_base()}/app/billing",
    )
    url = _text(session, "url")
    if not url:
        raise BillingError(502, "Stripe did not return a portal URL")
    return url


# -- webhook processing -------------------------------------------------------


def process_webhook(
    db: Session, payload: bytes, signature: str | None
) -> str:
    """Verify, receipt and apply one Stripe event.

    Returns `"processed"`, `"duplicate"`, `"ignored"` (unknown customer/company)
    or `"stale"` (older than the applied state). A signature failure raises
    `BillingSignatureError` before any row is touched; an exception while
    applying rolls the receipt back so Stripe's retry can process it again.
    """
    if not signature:
        raise BillingSignatureError()
    secret = config.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise BillingError(503, "Stripe webhook is not configured")

    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise BillingSignatureError() from exc

    event_id = _text(event, "id")
    event_type = _text(event, "type")
    created = _moment(_number(event, "created"))
    if not event_id or not event_type or created is None:
        raise BillingSignatureError()

    receipt = models.BillingEvent(
        stripe_event_id=event_id,
        type=event_type,
        stripe_created_at=created,
    )
    db.add(receipt)
    try:
        db.flush()
    except IntegrityError:
        # Already receipted: a Stripe retry, a replay or a concurrent delivery.
        db.rollback()
        return "duplicate"

    try:
        outcome = _apply(db, event, event_type, created)
        receipt.processed_at = datetime.now(UTC)
        db.commit()
    except Exception:
        # The receipt must not survive a failed apply, or Stripe's retry would
        # be answered as a duplicate and the state change would never happen.
        db.rollback()
        raise
    return outcome


def _fresh(row: models.Subscription, created: datetime) -> bool:
    """Whether `created` is at least as new as the state already applied."""
    last = _aware(row.last_event_at)
    return last is None or created >= last


def _latest(current: datetime | None, created: datetime) -> datetime:
    existing = _aware(current)
    if existing is None or created > existing:
        return created
    return existing


def _row_for(
    db: Session,
    customer_id: str | None,
    subscription_id: str | None,
    company_id: UUID | None,
) -> models.Subscription | None:
    """Resolve the tenant from trusted stored ids, and only then from metadata.

    A row found by a Stripe id whose `company_id` disagrees with a metadata
    company id is a mismatch, not a match: an event cannot move another tenant's
    subscription by claiming its customer.
    """
    query = db.query(models.Subscription)
    row = None
    if subscription_id:
        row = query.filter(
            models.Subscription.stripe_subscription_id == subscription_id
        ).first()
    if row is None and customer_id:
        row = query.filter(
            models.Subscription.stripe_customer_id == customer_id
        ).first()
    if row is None and company_id is not None:
        row = query.filter(models.Subscription.company_id == company_id).first()
    if row is None:
        return None
    if company_id is not None and row.company_id != company_id:
        return None
    return row


def _plan_metadata(row: models.Subscription, obj: Any) -> None:
    metadata = _get(obj, "metadata")
    plan_code = _text(metadata, "plan_code")
    interval = _text(metadata, "plan_interval")
    # Only our own server-written metadata reaches this point; it is length
    # bounded like the column rather than trusted as a price.
    if plan_code and len(plan_code) <= 64:
        row.plan_code = plan_code
    if interval in ("month", "year"):
        row.interval = interval


def _apply(
    db: Session, event: Any, event_type: str, created: datetime
) -> str:
    if event_type not in HANDLED_EVENTS:
        return "ignored"

    obj = _nested(event, "data", "object")
    if obj is None:
        return "ignored"

    metadata_company = _company_id(
        _text(_get(obj, "metadata"), "company_id")
    )
    customer_id = _text(obj, "customer")

    if event_type == "checkout.session.completed":
        return _apply_checkout(db, obj, created, customer_id, metadata_company)
    if event_type.startswith("customer.subscription."):
        return _apply_subscription(
            db, obj, event_type, created, customer_id, metadata_company
        )
    return _apply_invoice(db, obj, event_type, created, customer_id)


def _apply_checkout(
    db: Session,
    obj: Any,
    created: datetime,
    customer_id: str | None,
    metadata_company: UUID | None,
) -> str:
    subscription_id = _text(obj, "subscription")
    company_id = metadata_company or _company_id(
        _text(obj, "client_reference_id")
    )
    row = _row_for(db, customer_id, subscription_id, company_id)
    if row is None:
        return "ignored"
    if not _fresh(row, created):
        return "stale"

    if customer_id:
        row.stripe_customer_id = customer_id
    if subscription_id:
        row.stripe_subscription_id = subscription_id
    _plan_metadata(row, obj)
    # `payment_status` is Stripe's verified confirmation for this session; the
    # browser's return URL is never consulted.
    if _text(obj, "payment_status") == "paid" and row.status != "canceled":
        row.status = "active"
    row.last_event_at = _latest(row.last_event_at, created)
    db.flush()
    return "processed"


def _apply_subscription(
    db: Session,
    obj: Any,
    event_type: str,
    created: datetime,
    customer_id: str | None,
    metadata_company: UUID | None,
) -> str:
    subscription_id = _text(obj, "id")
    row = _row_for(db, customer_id, subscription_id, metadata_company)
    if row is None:
        return "ignored"
    if not _fresh(row, created):
        return "stale"

    status = _text(obj, "status")
    if status in SUBSCRIPTION_STATUSES:
        row.status = status
    if customer_id:
        row.stripe_customer_id = customer_id
    if subscription_id:
        row.stripe_subscription_id = subscription_id

    start = _moment(_number(obj, "current_period_start"))
    end = _moment(_number(obj, "current_period_end"))
    if start is not None:
        row.current_period_start = start
    if end is not None:
        row.current_period_end = end
    row.cancel_at_period_end = bool(_get(obj, "cancel_at_period_end", False))
    _plan_metadata(row, obj)

    if event_type == "customer.subscription.deleted":
        row.status = "canceled"
        row.cancel_at_period_end = True
        row.canceled_at = created

    row.last_event_at = _latest(row.last_event_at, created)
    db.flush()
    return "processed"


def _apply_invoice(
    db: Session,
    obj: Any,
    event_type: str,
    created: datetime,
    customer_id: str | None,
) -> str:
    row = _row_for(db, customer_id, _text(obj, "subscription"), None)
    if row is None:
        return "ignored"
    if not _fresh(row, created):
        return "stale"
    # An invoice event must never resurrect a canceled subscription; Stripe
    # reactivation arrives as a subscription event, not as a payment.
    if row.status != "canceled":
        row.status = "active" if event_type == "invoice.paid" else "past_due"
    row.last_event_at = _latest(row.last_event_at, created)
    db.flush()
    return "processed"
