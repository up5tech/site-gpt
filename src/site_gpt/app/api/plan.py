"""The public plan catalog (V5 F1, task V5-11).

One endpoint, ``GET /api/plans``: read-only, unauthenticated, and derived only
from `services.plan_catalog.published_plans`, so the pricing page has a single
source of truth and cannot drift from what the server would charge.

No database, no Stripe call, no credentials: with billing disabled (the V5
default) and an empty catalog this answers ``{"plans": []}`` — which is the V4
state plus one public page, not a purchase attempt.
"""

from fastapi import APIRouter

from site_gpt.app.schemas.plan import PublicPlan, PublicPlanList
from site_gpt.app.services.plan_catalog import public_payload, published_plans

router = APIRouter()


@router.get("/api/plans", response_model=PublicPlanList, tags=["plans"])
def list_plans() -> PublicPlanList:
    return PublicPlanList(
        plans=[PublicPlan(**public_payload(plan)) for plan in published_plans()]
    )
