"""The server-owned plan catalog (V5 F1, task V5-11).

This is the **only** place a saleable plan is defined. ``GET /api/plans`` serves
it read-only and unauthenticated, and the pricing page renders exactly what this
module publishes — the browser never supplies a price, a currency, a feature
list or a Stripe identifier.

Two deliberate states:

* ``PLANS`` is empty until product/legal approval (V5-01, decisions D2/D4/D5/D7)
  records the tier codes, limits, prices and cadence. That is a valid, honest
  state: the endpoint answers ``{"plans": []}`` and the pricing page says plans
  are being finalised rather than inventing one (V5 invariant 8 — no made-up
  price, tier promise or trial).
* A plan is published **only** when it carries ``published=True``; the default
  is unpublished, so adding a definition in code does not put it on the public
  site. V5-42 replaces this module with durable database records while keeping
  the same public response contract.

Stripe Price IDs, secret keys and any other provider configuration are *not*
catalog fields and must never be added here: `public_payload` is the complete
public surface and `tests/test_plans_catalog.py` pins its keys.
"""

from dataclasses import dataclass
from typing import Mapping

#: Billing cadences the public page can render. Stripe accepts more; only these
#: are approved for sale, so anything else is a misconfiguration and is hidden.
VALID_INTERVALS = ("month", "year")


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


def published_plans() -> tuple[Plan, ...]:
    """The plans the public page may show, in catalog order.

    Unpublished *and* invalid entries are filtered out, so a catalog mistake
    degrades the page to "nothing on sale yet" rather than to wrong numbers.
    """
    return tuple(plan for plan in PLANS if plan.published and _is_valid(plan))


def find_plan(code: str | None) -> Plan | None:
    """Resolve a public plan code, matching case-insensitively.

    Only published plans resolve: a stale or hand-typed ``?plan=`` value can
    never select a plan the owner has not approved for sale.
    """
    wanted = (code or "").strip().lower()
    if not wanted:
        return None
    for plan in published_plans():
        if plan.code.strip().lower() == wanted:
            return plan
    return None


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
