"""Outbound integration event bus.

Wave 0 ships the *contract* only. ``emit_event`` is what the handoff and digest
code (Wave 2) calls to notify integrations that do not exist yet; the real
provider implementations and the dispatcher land in Wave 3 (V2-31). Keeping the
final signature here means those call sites never have to change again.

Two rules already hold in this skeleton and must survive V2-31:

* an integration failure never reaches the originating request — chat, lead
  capture and handoff must succeed even when a webhook endpoint is down;
* payloads are never logged, because they can carry visitor contact details.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Registry of provider name -> provider class, filled in V2-31
# (`webhook`, `slack`, `zendesk`, `crisp`). Empty means "no integration can be
# configured yet", so emitting an event is a no-op.
PROVIDERS: dict[str, Any] = {}


def emit_event(
    db: Session,
    company_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Hand one company-scoped event to the integrations subscribed to it.

    Today it logs that the event happened and returns. Never raises: callers
    emit events from request paths that must not fail because an external
    service is unavailable.
    """
    try:
        logger.info(
            "integration event %s for company %s (%d provider(s) configured)",
            event_type,
            company_id,
            len(PROVIDERS),
        )
    except Exception:
        logger.exception("integration event %s could not be recorded", event_type)
    return None
