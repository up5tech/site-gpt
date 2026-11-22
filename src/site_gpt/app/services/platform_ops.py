"""Cross-company reads and approved subscription actions (V5-41).

The operator console needs a view no tenant route can offer: every company and
its mirrored subscription state. Two rules keep that safe:

* **Read narrowly.** The list endpoints return counts, lifecycle state, period
  dates and Stripe *identifiers* — never card data, a secret or a raw Stripe
  object. A page is capped and searchable.
* **Stripe stays authoritative.** The only mutation here is asking Stripe to
  cancel at period end; it never writes the local mirror. That mirror changes
  only when a verified webhook arrives, so an operator cannot "mark paid" from
  the console. A reconciliation request is an audit record, not a state change.

Every action requires a reason, a destructive one requires `confirm=true`, and
the result (including a provider failure) is written to the append-only audit
trail by the route through `services.platform.record_audit`.
"""

import uuid
from typing import Any

import stripe
from sqlalchemy import func
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.services import platform

ACTIONS = ("cancel_at_period_end", "request_reconciliation")

MAX_PAGE_SIZE = 100


class PlatformActionError(Exception):
    """An action that must not proceed, with the HTTP answer to send."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _page(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, int(page or 1))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 25)))
    return page, page_size


def overview(db: Session) -> dict[str, Any]:
    """Company/subscription totals for the console landing section."""
    status_rows = (
        db.query(models.Subscription.status, func.count(models.Subscription.id))
        .group_by(models.Subscription.status)
        .all()
    )
    by_status = {status: int(count) for status, count in status_rows}
    return {
        "companies": int(db.query(func.count(models.Company.id)).scalar() or 0),
        "websites": int(db.query(func.count(models.Website.id)).scalar() or 0),
        "active_users": int(
            db.query(func.count(models.User.id))
            .filter(models.User.status == "active")
            .scalar()
            or 0
        ),
        "published_plans": int(
            db.query(func.count(models.CatalogPlan.id))
            .filter(models.CatalogPlan.status == "published")
            .scalar()
            or 0
        ),
        "subscriptions": by_status,
    }


def _company_usage(db: Session, company_ids: list[uuid.UUID]) -> dict:
    if not company_ids:
        return {"users": {}, "websites": {}}
    users = dict(
        db.query(models.User.company_id, func.count(models.User.id))
        .filter(
            models.User.company_id.in_(company_ids),
            models.User.status == "active",
        )
        .group_by(models.User.company_id)
        .all()
    )
    websites = dict(
        db.query(models.Website.company_id, func.count(models.Website.id))
        .filter(models.Website.company_id.in_(company_ids))
        .group_by(models.Website.company_id)
        .all()
    )
    return {"users": users, "websites": websites}


def list_companies(
    db: Session,
    *,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Paginated companies with usage counts and mirrored plan state."""
    page, page_size = _page(page, page_size)
    query = db.query(models.Company)
    value = (search or "").strip()
    if value:
        query = query.filter(
            func.lower(models.Company.name).contains(value.lower())
        )
    total = query.count()
    rows = (
        query.order_by(models.Company.created_at.desc(), models.Company.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [row.id for row in rows]
    usage = _company_usage(db, ids)
    subscriptions = {
        row.company_id: row
        for row in db.query(models.Subscription)
        .filter(models.Subscription.company_id.in_(ids))
        .all()
    }

    items = []
    for company in rows:
        subscription = subscriptions.get(company.id)
        items.append(
            {
                "id": company.id,
                "name": company.name,
                "created_at": company.created_at,
                "websites": int(usage["websites"].get(company.id, 0)),
                "active_users": int(usage["users"].get(company.id, 0)),
                "plan_code": subscription.plan_code if subscription else None,
                "status": subscription.status if subscription else None,
                "interval": subscription.interval if subscription else None,
                "current_period_end": (
                    subscription.current_period_end if subscription else None
                ),
                "cancel_at_period_end": bool(
                    subscription.cancel_at_period_end if subscription else False
                ),
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def list_subscriptions(
    db: Session,
    *,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Paginated mirrored subscriptions, newest period first.

    The Stripe customer/subscription identifiers are included because support
    and reconciliation need them; they are opaque references, not credentials.
    """
    page, page_size = _page(page, page_size)
    query = db.query(models.Subscription, models.Company).join(
        models.Company, models.Company.id == models.Subscription.company_id
    )
    wanted = (status or "").strip().lower()
    if wanted:
        query = query.filter(models.Subscription.status == wanted)
    value = (search or "").strip()
    if value:
        query = query.filter(
            func.lower(models.Company.name).contains(value.lower())
        )
    total = query.count()
    rows = (
        query.order_by(
            models.Subscription.current_period_end.desc(),
            models.Subscription.created_at.desc(),
            models.Subscription.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "company_id": company.id,
                "company_name": company.name,
                "plan_code": subscription.plan_code,
                "status": subscription.status,
                "interval": subscription.interval,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": bool(subscription.cancel_at_period_end),
                "stripe_customer_id": subscription.stripe_customer_id,
                "stripe_subscription_id": subscription.stripe_subscription_id,
                "last_event_at": subscription.last_event_at,
            }
            for subscription, company in rows
        ],
    }


def _clean_reason(reason: str) -> str:
    value = (reason or "").strip()
    if len(value) < 3:
        raise PlatformActionError(400, "A reason is required for this action.")
    if len(value) > 500:
        raise PlatformActionError(400, "The reason is limited to 500 characters.")
    return value


def _subscription(
    db: Session, company_id: uuid.UUID
) -> tuple[models.Subscription, models.Company]:
    row = (
        db.query(models.Subscription)
        .filter(models.Subscription.company_id == company_id)
        .first()
    )
    company = db.get(models.Company, company_id)
    if company is None or row is None:
        raise PlatformActionError(404, "No subscription for that company")
    return row, company


def apply_action(
    db: Session,
    company_id: uuid.UUID,
    *,
    action: str,
    reason: str,
    confirm: bool,
    actor_user_id: uuid.UUID,
) -> dict[str, Any]:
    """Run one allowlisted subscription action and audit its outcome.

    `cancel_at_period_end` asks Stripe and never writes the mirror; a verified
    webhook does that. `request_reconciliation` only records that an operator
    asked for a Stripe check. There is deliberately no action that grants,
    extends or marks a subscription paid.
    """
    reason = _clean_reason(reason)
    if action not in ACTIONS:
        raise PlatformActionError(400, "Unknown subscription action")
    if action == "cancel_at_period_end" and not confirm:
        raise PlatformActionError(
            400, "Confirm this destructive action explicitly."
        )
    subscription, company = _subscription(db, company_id)

    if action == "request_reconciliation":
        outcome = {"action": action, "company_id": str(company.id), "status": "requested"}
        platform.record_audit(
            db,
            action="platform.subscription.reconciliation_requested",
            target_type="company",
            target_id=str(company.id),
            actor_user_id=actor_user_id,
            detail={
                "reason": reason,
                "plan_code": subscription.plan_code,
                "status": subscription.status,
            },
        )
        return outcome

    if not config.BILLING_ENABLED:
        platform.record_audit(
            db,
            action="platform.subscription.cancel_at_period_end",
            target_type="company",
            target_id=str(company.id),
            actor_user_id=actor_user_id,
            detail={"reason": reason, "outcome": "refused_billing_disabled"},
        )
        raise PlatformActionError(409, "Billing is not enabled on this deployment.")
    if not subscription.stripe_subscription_id:
        raise PlatformActionError(404, "That company has no Stripe subscription")

    try:
        stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            cancel_at_period_end=True,
            api_key=config.STRIPE_SECRET_KEY,
        )
    except Exception as exc:  # never echo the provider message or request body
        platform.record_audit(
            db,
            action="platform.subscription.cancel_at_period_end",
            target_type="company",
            target_id=str(company.id),
            actor_user_id=actor_user_id,
            detail={
                "reason": reason,
                "outcome": "provider_error",
                "error": type(exc).__name__,
            },
        )
        raise PlatformActionError(
            502, "Stripe did not accept the cancellation request."
        ) from exc

    platform.record_audit(
        db,
        action="platform.subscription.cancel_at_period_end",
        target_type="company",
        target_id=str(company.id),
        actor_user_id=actor_user_id,
        detail={
            "reason": reason,
            "outcome": "requested",
            "plan_code": subscription.plan_code,
            "status": subscription.status,
        },
    )
    return {
        "action": action,
        "company_id": str(company.id),
        "status": "requested",
        "stripe_updated": True,
    }
