from pydantic import BaseModel


class PlanLimit(BaseModel):
    """One machine-readable entitlement of a plan (e.g. ``websites: 1``)."""

    key: str
    value: int


class PublicPlan(BaseModel):
    """One plan as the public pricing page reads it.

    Deliberately has no Stripe Price ID, secret or internal identifier: those
    stay on the server (V5 invariant 8).
    """

    code: str
    name: str
    description: str
    price_minor: int
    currency: str
    interval: str
    features: list[str]
    limits: list[PlanLimit]
    self_serve_checkout: bool


class PublicPlanList(BaseModel):
    plans: list[PublicPlan]
