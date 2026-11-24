"""Health probes and the V6-21 operator snapshot.

`/health` in `api/routes.py` keeps its original contract and payload; the probes
here are additive, as D8 requires. The split exists so an orchestrator can tell
"restart this process" from "stop sending it traffic":

* `/health/live` answers while the process can run a handler. It checks nothing,
  so a dependency outage never restarts a merely degraded process.
* `/health/ready` requires the database — without it nothing can be served — and
  reports Redis without failing on it, because the API degrades rather than
  stops when Redis is down (the limiter fails open, chat keeps working). A
  single-container deployment would otherwise take itself out of service for an
  outage it can still serve through.

`GET /api/ops/status` is the operator view: worker heartbeat age, queue depth
and age, job-failure count, this process's 5xx window and the resulting alerts.
It is not a tenant feature: the route answers 404 unless `OPS_STATUS_TOKEN` is
set, and then requires that token (`X-Ops-Token`) compared in constant time.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from site_gpt.app.core import telemetry
from site_gpt.app.core.config import OPS_STATUS_TOKEN
from site_gpt.app.db.session import get_db
from site_gpt.app.services.redis import get_client, ping as redis_ping

router = APIRouter(tags=["ops"])


def _db_answers(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - a probe reports, it does not raise
        return False
    return True


@router.get("/health/live")
async def live():
    """Liveness only: the process is running and can answer HTTP."""
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(response: Response, db: Session = Depends(get_db)):
    """Readiness: the database is required, Redis is reported as degraded."""
    db_ok = _db_answers(db)
    try:
        redis_ok = await redis_ping()
    except Exception:  # noqa: BLE001 - ping never raises, but never 500 a probe
        redis_ok = False

    if not db_ok:
        response.status_code = 503
        status = "not_ready"
    elif not redis_ok:
        status = "degraded"
    else:
        status = "ready"
    return {"status": status, "db": db_ok, "redis": redis_ok}


@router.get("/api/ops/status")
async def ops_status(
    response: Response,
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    db: Session = Depends(get_db),
):
    """The D8 alert snapshot. Disabled (404) unless `OPS_STATUS_TOKEN` is set."""
    if not OPS_STATUS_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    if not x_ops_token or not hmac.compare_digest(x_ops_token, OPS_STATUS_TOKEN):
        raise HTTPException(status_code=401, detail="invalid ops token")

    client = get_client()
    snapshot = telemetry.build_snapshot(
        db_ok=_db_answers(db),
        redis=await telemetry.redis_snapshot(client),
        # V6-23: the sum every replica writes, beside this instance's window.
        fleet=await telemetry.fleet_window(client),
    )
    # Operator data, never cached by a proxy or the browser.
    response.headers["Cache-Control"] = "no-store"
    return snapshot
