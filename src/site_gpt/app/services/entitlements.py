"""Plan entitlements: resolve a company's approved plan to enforceable ceilings.

This is the single place a paid plan turns into a number the rest of the app
checks. Routes and services read limits through here — they never compare plan
codes or trust a client — so a limit can only come from the server catalog
(V5 invariant 6).

Three rules shape the policy, all deliberately conservative while D5/D7 are
unapproved:

* **Billing off means no enforcement at all.** With ``BILLING_ENABLED=false``
  (the default) `resolve` answers an empty snapshot without touching the
  database, so self-hosted and V4 behaviour is byte-for-byte unchanged and no
  Stripe credential or subscription row is needed (invariant 5).
* **Only a confirmed active subscription grants a plan.** `active`/`trialing`
  plus a *currently published* catalog plan. A past-due, canceled, incomplete,
  paused or unknown subscription grants nothing, and a plan removed from the
  catalog stops granting its old limits: missing or stale Stripe data can never
  become a *higher* plan, only the V4 baseline (invariant 7 — never mistaken for
  a successful payment).
* **An ungranted plan does not lock anyone out.** With no granted limit a
  company keeps exactly its V4 settings/env ceilings. That is why an unapproved
  or unpaid state produces an empty limit map rather than a guessed free tier:
  no limit is invented, and nobody loses access because Stripe is quiet.

Only a fixed set of proof-reading keys is enforced (`ENFORCEABLE_LIMITS`); a
catalog entry with any other key is display copy and is ignored here.
"""

from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.services import billing, plan_catalog

#: Catalog limit keys this module understands. A plan may carry more (display
#: copy, or a key a later wave will enforce); only these become a ceiling.
ENFORCEABLE_LIMITS = (
    "websites",
    "seats",
    "daily_messages",
    "session_messages",
)

#: User statuses that occupy a seat. Everything else (a deactivated account)
#: keeps its rows and history but stops counting against the plan, matching
#: `core.auth`, which only signs in `active` users.
SEAT_STATUSES = ("active",)

#: Human wording for a refusal. Kept here so every boundary answers the same.
_LIMIT_LABELS = {
    "websites": "websites",
    "seats": "team members",
    "daily_messages": "messages per day",
    "session_messages": "messages per conversation",
}


class PlanLimitError(Exception):
    """A creation or use would exceed the plan's ceiling.

    The API layer turns this into a 403; the message names the ceiling but
    never the internal plan state, so a member learns what to upgrade rather
    than how the subscription is stored.
    """

    def __init__(self, key: str, limit: int):
        label = _LIMIT_LABELS.get(key, key.replace("_", " "))
        self.key = key
        self.limit = limit
        self.detail = f"Your plan's limit for {label} is {limit}."
        super().__init__(self.detail)


@dataclass(frozen=True)
class Snapshot:
    """A company's entitlement state at one moment.

    ``enforced`` is true only when a limit actually applies; ``limits`` is then
    a subset of `ENFORCEABLE_LIMITS`. When billing is off both are false/empty
    and callers must fall back to their existing behaviour.
    """

    billing_enabled: bool
    enforced: bool
    plan_code: str | None
    status: str | None
    limits: Mapping[str, int]

    def limit(self, key: str) -> int | None:
        return self.limits.get(key)


def _empty(billing_enabled: bool, status: str | None = None) -> Snapshot:
    return Snapshot(
        billing_enabled=billing_enabled,
        enforced=False,
        plan_code=None,
        status=status,
        limits={},
    )


def resolve(db: Session, company_id: UUID) -> Snapshot:
    """Resolve one company's enforceable plan limits.

    Reads one subscription row and one catalog lookup; no Stripe call, no
    network. With billing disabled it reads nothing at all.
    """
    if not config.BILLING_ENABLED:
        return _empty(False)

    row = billing.company_subscription(db, company_id)
    if row is None:
        return _empty(True)

    plan = plan_catalog.find_plan(row.plan_code)
    status = row.status
    if status not in billing.ACTIVE_STATUSES or plan is None:
        return _empty(True, status)

    limits = {
        key: value
        for key, value in (plan.limits or {}).items()
        if key in ENFORCEABLE_LIMITS and isinstance(value, int) and value > 0
    }
    return Snapshot(
        billing_enabled=True,
        enforced=bool(limits),
        plan_code=plan.code.strip(),
        status=status,
        limits=limits,
    )


def effective(configured: int, plan_limit: int | None) -> int:
    """The stricter of a company's own cap and the plan ceiling.

    `0` (or a negative value) is the app's "no cap" in `services.quota`, so it
    is treated as *not governed* here rather than as a zero ceiling: a plan
    limit of `0` is indistinguishable from "not stated" and is not enforced in
    this wave, and an uncapped company setting yields the plan ceiling instead
    of infinity. The result never exceeds the company's own configured cap, so a
    plan cannot silently raise a safety limit someone set deliberately.
    """
    if plan_limit is None or plan_limit <= 0:
        return configured
    if configured <= 0:
        return plan_limit
    return min(configured, plan_limit)


def seat_count(db: Session, company_id: UUID) -> int:
    """How many of a company's users currently hold a seat.

    The one count the seat ceiling and the usage report share: a deactivated
    account frees its seat without losing anything, and a caller never has to
    reimplement "who counts" (invariant 7 — nothing existing is removed).
    """
    return int(
        db.query(func.count(models.User.id))
        .filter(
            models.User.company_id == company_id,
            models.User.status.in_(SEAT_STATUSES),
        )
        .scalar()
        or 0
    )


def daily_message_limit(snapshot: Snapshot, configured: int) -> int:
    """The effective per-website daily ceiling from an already-resolved snapshot.

    Callers resolve once per request and pass that snapshot to both cap
    helpers, so one chat message reads the subscription once, not twice.
    """
    return effective(configured, snapshot.limit("daily_messages"))


def session_message_limit(snapshot: Snapshot, configured: int) -> int:
    """The effective per-conversation ceiling from an already-resolved snapshot."""
    return effective(configured, snapshot.limit("session_messages"))


def enforce_count(db: Session, company_id: UUID, key: str, current: int) -> None:
    """Refuse a creation that would exceed the plan's count ceiling.

    `current` is the count *before* the new row. A company at or over its
    ceiling keeps everything it has; only a new row is refused, so enabling a
    plan never deletes or disables existing resources (invariant 7).
    """
    plan_limit = resolve(db, company_id).limit(key)
    if plan_limit is not None and plan_limit > 0 and current >= plan_limit:
        raise PlanLimitError(key, plan_limit)


def usage(db: Session, company_id: UUID) -> dict:
    """Current countable usage against the granted ceilings.

    Only resources this module enforces have a number here; the console renders
    `limit: None` as "not included in your plan's enforced limits" rather than
    inventing a value. Counts are read in one query each and scoped by company;
    seats use `seat_count`, so a deactivated user is not billed against the plan.
    """
    snapshot = resolve(db, company_id)
    websites = (
        db.query(func.count(models.Website.id))
        .filter(models.Website.company_id == company_id)
        .scalar()
        or 0
    )
    seats = seat_count(db, company_id)
    return {
        "plan_code": snapshot.plan_code,
        "status": snapshot.status,
        "enforced": snapshot.enforced,
        "websites": {
            "key": "websites",
            "used": int(websites),
            "limit": snapshot.limit("websites"),
        },
        "seats": {
            "key": "seats",
            "used": int(seats),
            "limit": snapshot.limit("seats"),
        },
    }
