"""The public plan catalog (V5 F1/F5, tasks V5-11 and V5-42).

One endpoint, ``GET /api/plans``: read-only, unauthenticated, and derived only
from `services.plan_catalog.published_plans`, so the pricing page has a single
source of truth and cannot drift from what the server would charge.

The read is database-backed now that the platform owner can publish plans
(V5-42); an empty catalog table still falls back to the code-defined list, and
with billing disabled (the V5 default) an empty catalog answers
``{"plans": []}`` — which is the V4 state plus one public page, not a purchase
attempt. No Stripe call or credential is involved.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.plan import PublicPlan, PublicPlanList
from site_gpt.app.services.plan_catalog import public_payload, published_plans

router = APIRouter()


@router.get("/api/plans", response_model=PublicPlanList, tags=["plans"])
def list_plans(db: Session = Depends(get_db)) -> PublicPlanList:
    return PublicPlanList(
        plans=[
            PublicPlan(**public_payload(plan))
            for plan in published_plans(db)
        ]
    )
