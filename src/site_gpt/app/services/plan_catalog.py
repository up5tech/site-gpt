"""The server-owned plan catalog (V5 F1/F5, tasks V5-11 and V5-42).

This is the **only** place a saleable plan is defined. ``GET /api/plans`` serves
it read-only and unauthenticated, Checkout resolves a plan code through it, and
the entitlement resolver reads its limits. The browser never supplies a price, a
currency, a feature list or a Stripe identifier.

Two sources exist on purpose:

* **Durable records (V5-42).** `catalog_plans` / `plan_prices` are written by the
  platform owner (M12). Once at least one row exists they are authoritative: a
  draft is invisible, a published plan is public, an archived plan is history.
* **The static fallback.** ``PLANS`` stays empty until product/legal approval
  (V5-01, decisions D2/D4/D5/D7) and is what the code-defined catalog used
  before the durable one existed. An empty table falls back to it, so a
  deployment that has not used the owner console yet keeps the old behaviour
  exactly, and the first row an owner creates takes over without a code change.

A plan is published **only** when its status is `published` *and* it carries a
usable active price; the public payload is unchanged from V5-11. Stripe Price
IDs, secret keys and any other provider configuration are never public: they
live on `PlanPrice.stripe_price_id` and are read only by the checkout path.
"""

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config

#: Billing cadences the public page can render. Stripe accepts more; only these
#: are approved for sale, so anything else is a misconfiguration and is hidden.
VALID_INTERVALS = ("month", "year")

#: Plan codes travel in URLs and in subscription rows, so they stay boring.
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

STATUSES = ("draft", "published", "archived")


class CatalogError(Exception):
    """A catalog edit that must not proceed, with the HTTP answer to send."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Plan:
    """One saleable plan.

    ``price_minor`` is an integer in the currency's minor unit (e.g. cents) so
    no float ever reaches a price. ``limits`` is the machine-readable entitlement
    map the resolver reads in Wave 3; ``features`` is display copy for the same
    plan. Neither is enforced by this module.
    """

    code: str
    name: str
    description: str
    price_minor: int
    currency: str
    interval: str = "month"
    features: tuple[str, ...] = ()
    limits: Mapping[str, int] = None  # type: ignore[assignment]
    self_serve_checkout: bool = True
    published: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.limits, Mapping):
            object.__setattr__(self, "limits", {})


#: The approved catalog. Empty by default: V5-01 is blocked on product/legal
#: approval, and no price may be guessed in the meantime.
PLANS: tuple[Plan, ...] = ()


def _is_valid(plan: Plan) -> bool:
    """A plan is renderable only if every public field is usable.

    A half-filled definition is a misconfiguration, not a cheap tier: serving it
    would show a heading without a price or a price without a cadence, so it is
    withheld from the public list instead of being rendered wrong.
    """
    return (
        bool(plan.code.strip())
        and bool(plan.name.strip())
        and plan.price_minor >= 0
        and plan.interval in VALID_INTERVALS
        and len(plan.currency.strip()) == 3
        and plan.currency.strip().isalpha()
        and all(
            isinstance(value, int) and value >= 0
            for value in plan.limits.values()
        )
    )


# -- durable catalog reads ----------------------------------------------------


def _catalog_has_rows(db: Session) -> bool:
    return db.query(models.CatalogPlan.id).first() is not None


def _plan_from_row(row: models.CatalogPlan) -> Plan | None:
    """The public shape of one durable row, or None when it has no price."""
    price = row.active_price()
    if price is None:
        return None
    return Plan(
        code=row.code,
        name=row.name,
        description=row.description or "",
        price_minor=price.price_minor,
        currency=price.currency,
        interval=price.interval,
        features=tuple(row.features or ()),
        limits=dict(row.limits or {}),
        self_serve_checkout=bool(row.self_serve_checkout),
        published=row.status == "published",
    )


def published_plans(db: Session | None = None) -> tuple[Plan, ...]:
    """The plans the public page may show, in catalog order.

    With no database (or an empty catalog table) the static `PLANS` fallback is
    used, so the pre-cutover behaviour is unchanged. Unpublished *and* invalid
    entries are filtered out, so a catalog mistake degrades the page to "nothing
    on sale yet" rather than to wrong numbers.
    """
    if db is None or not _catalog_has_rows(db):
        return tuple(plan for plan in PLANS if plan.published and _is_valid(plan))

    rows = (
        db.query(models.CatalogPlan)
        .filter(models.CatalogPlan.status == "published")
        .order_by(models.CatalogPlan.code, models.CatalogPlan.id)
        .all()
    )
    plans = [_plan_from_row(row) for row in rows]
    return tuple(
        sorted(
            (plan for plan in plans if plan is not None and _is_valid(plan)),
            key=lambda plan: (plan.code, plan.interval),
        )
    )


def find_plan(code: str | None, db: Session | None = None) -> Plan | None:
    """Resolve a public plan code, matching case-insensitively.

    Only published plans resolve: a stale or hand-typed ``?plan=`` value can
    never select a plan the owner has not approved for sale.
    """
    wanted = (code or "").strip().lower()
    if not wanted:
        return None
    for plan in published_plans(db):
        if plan.code.strip().lower() == wanted:
            return plan
    return None


def stored_price_id(db: Session, plan: Plan) -> str | None:
    """The active, private Stripe Price ID for a published plan, if mapped."""
    row = (
        db.query(models.CatalogPlan)
        .filter(
            models.CatalogPlan.code == plan.code.strip().lower(),
            models.CatalogPlan.status == "published",
        )
        .first()
    )
    if row is None:
        return None
    price = row.active_price()
    return price.stripe_price_id if price else None


def public_payload(plan: Plan) -> dict:
    """The complete public representation of one plan.

    Adding a key here is a public API change; adding a key anywhere else on
    ``Plan`` is not. Keep Stripe IDs and secrets out of this mapping.
    """
    return {
        "code": plan.code.strip(),
        "name": plan.name.strip(),
        "description": plan.description,
        "price_minor": plan.price_minor,
        "currency": plan.currency.strip().upper(),
        "interval": plan.interval,
        "features": list(plan.features),
        "limits": [
            {"key": key, "value": value} for key, value in plan.limits.items()
        ],
        "self_serve_checkout": plan.self_serve_checkout,
    }


# -- operator-managed writes (V5-42) -----------------------------------------


def clean_code(code: str) -> str:
    value = (code or "").strip().lower()
    if not CODE_RE.fullmatch(value):
        raise CatalogError(
            400,
            "Plan codes are 1–64 lowercase letters, digits, dashes or underscores.",
        )
    return value


def clean_currency(currency: str) -> str:
    value = (currency or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise CatalogError(400, "Currency must be a three-letter code.")
    return value


def clean_interval(interval: str) -> str:
    value = (interval or "").strip().lower()
    if value not in VALID_INTERVALS:
        raise CatalogError(400, "Interval must be 'month' or 'year'.")
    return value


def clean_price(price_minor: int) -> int:
    if not isinstance(price_minor, int) or isinstance(price_minor, bool):
        raise CatalogError(400, "Price must be an integer in minor units.")
    if price_minor < 0:
        raise CatalogError(400, "Price cannot be negative.")
    return price_minor


def clean_features(features: Iterable[str] | None) -> list[str]:
    cleaned: list[str] = []
    for feature in features or ():
        text = str(feature).strip()
        if not text:
            raise CatalogError(400, "Feature copy cannot be blank.")
        if len(text) > 200:
            raise CatalogError(400, "Feature copy is limited to 200 characters.")
        cleaned.append(text)
    if len(cleaned) > 20:
        raise CatalogError(400, "A plan has at most 20 feature lines.")
    return cleaned


def clean_limits(limits: Mapping[str, int] | None) -> dict[str, int]:
    cleaned: dict[str, int] = {}
    for key, value in (limits or {}).items():
        name = str(key).strip()
        if not name or len(name) > 64:
            raise CatalogError(400, "A limit key is 1–64 characters.")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CatalogError(
                400, "Every limit value must be a non-negative integer."
            )
        cleaned[name] = value
    return cleaned


def clean_stripe_price_id(value: str | None) -> str | None:
    """Validate a pre-created Stripe Price ID. Never a secret, still private."""
    text = (value or "").strip()
    if not text:
        return None
    if not text.startswith("price_") or len(text) > 255:
        raise CatalogError(400, "Stripe Price IDs start with 'price_'.")
    return text


def list_plans(db: Session) -> list[models.CatalogPlan]:
    return db.query(models.CatalogPlan).order_by(models.CatalogPlan.code).all()


def get_plan(db: Session, code: str) -> models.CatalogPlan | None:
    value = (code or "").strip().lower()
    if not value:
        return None
    return (
        db.query(models.CatalogPlan)
        .filter(models.CatalogPlan.code == value)
        .first()
    )


def create_plan(
    db: Session,
    *,
    code: str,
    name: str,
    description: str = "",
    features: Sequence[str] | None = None,
    limits: Mapping[str, int] | None = None,
    self_serve_checkout: bool = True,
    interval: str = "month",
    currency: str,
    price_minor: int,
    stripe_price_id: str | None = None,
    commit: bool = True,
) -> models.CatalogPlan:
    """Create a draft plan and its first price record."""
    clean = clean_code(code)
    name = (name or "").strip()
    if not name:
        raise CatalogError(400, "A plan needs a name.")
    if get_plan(db, clean) is not None:
        raise CatalogError(409, "A plan with that code already exists.")

    row = models.CatalogPlan(
        code=clean,
        name=name[:255],
        description=(description or "").strip(),
        features=clean_features(features),
        limits=clean_limits(limits),
        self_serve_checkout=bool(self_serve_checkout),
        status="draft",
    )
    row.prices = [
        models.PlanPrice(
            interval=clean_interval(interval),
            currency=clean_currency(currency),
            price_minor=clean_price(price_minor),
            stripe_price_id=clean_stripe_price_id(stripe_price_id),
            active=True,
        )
    ]
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CatalogError(409, "A plan with that code already exists.") from exc
    if commit:
        db.commit()
        db.refresh(row)
    return row


def update_plan(
    db: Session,
    code: str,
    *,
    name: str | None = None,
    description: str | None = None,
    features: Sequence[str] | None = None,
    limits: Mapping[str, int] | None = None,
    self_serve_checkout: bool | None = None,
    commit: bool = True,
) -> models.CatalogPlan:
    """Edit a draft or published plan's display copy and limits.

    The code and the price are immutable here: a price change goes through
    `add_price`, which archives the old record instead of rewriting it.
    """
    row = get_plan(db, code)
    if row is None:
        raise CatalogError(404, "Plan not found")
    if row.status == "archived":
        raise CatalogError(409, "Archived plans cannot be edited.")
    if name is not None:
        value = name.strip()
        if not value:
            raise CatalogError(400, "A plan needs a name.")
        row.name = value[:255]
    if description is not None:
        row.description = description.strip()
    if features is not None:
        row.features = clean_features(features)
    if limits is not None:
        row.limits = clean_limits(limits)
    if self_serve_checkout is not None:
        row.self_serve_checkout = bool(self_serve_checkout)
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def add_price(
    db: Session,
    code: str,
    *,
    interval: str,
    currency: str,
    price_minor: int,
    stripe_price_id: str | None = None,
    commit: bool = True,
) -> models.CatalogPlan:
    """Replace the active price with a new immutable record.

    Existing Stripe subscribers keep the Price they bought; only new Checkout
    sessions resolve the new active row. The old row stays as history.
    """
    row = get_plan(db, code)
    if row is None:
        raise CatalogError(404, "Plan not found")
    if row.status == "archived":
        raise CatalogError(409, "Archived plans cannot change price.")

    price = models.PlanPrice(
        plan_id=row.id,
        interval=clean_interval(interval),
        currency=clean_currency(currency),
        price_minor=clean_price(price_minor),
        stripe_price_id=clean_stripe_price_id(stripe_price_id),
        active=True,
    )
    for existing in row.prices:
        if existing.active:
            existing.active = False
    db.add(price)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CatalogError(
            409, "Another price change is already active for this plan."
        ) from exc
    if commit:
        db.commit()
        db.refresh(row)
    return row


def publish_plan(
    db: Session, code: str, *, commit: bool = True
) -> models.CatalogPlan:
    """Make a draft public.

    A self-serve plan needs a usable active price, and a configured Stripe
    Price mapping whenever billing is enabled — publishing a plan that cannot
    be bought would show a price the checkout then refuses (V5 invariant 8).
    """
    row = get_plan(db, code)
    if row is None:
        raise CatalogError(404, "Plan not found")
    if row.status == "archived":
        raise CatalogError(409, "Archived plans cannot be published.")
    price = row.active_price()
    if price is None:
        raise CatalogError(409, "A plan needs an active price before publishing.")
    public = _plan_from_row(row)
    if public is None or not _is_valid(public):
        raise CatalogError(409, "The plan's public fields are incomplete.")
    if (
        config.BILLING_ENABLED
        and row.self_serve_checkout
        and not price.stripe_price_id
    ):
        raise CatalogError(
            409, "Add a Stripe Price mapping before publishing this plan."
        )
    row.status = "published"
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def archive_plan(
    db: Session, code: str, *, commit: bool = True
) -> models.CatalogPlan:
    """Retire a plan from sale and from the public list without deleting it."""
    row = get_plan(db, code)
    if row is None:
        raise CatalogError(404, "Plan not found")
    row.status = "archived"
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row
