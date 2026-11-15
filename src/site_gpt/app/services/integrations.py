"""Outbound integration event bus (F7).

`emit_event` is what chat, lead capture, feedback, handoff and the digest call to
tell the outside world something happened. The providers and the dispatcher that
filter by `enabled` + subscribed events live here.

Two rules hold for every path in this module:

* an integration failure never reaches the originating request — the chat still
  answers, the lead is still stored, even when a webhook endpoint is down;
* payloads are never logged, because they carry visitor contact details. Only the
  integration id, its type and the event name are logged.

There are no retries: a failed delivery is logged and dropped. A retry queue
would need its own table and worker, and the plan deliberately keeps V2 free of
that (ADR-4/ADR-7 spirit: notify and callback, do not build a pipeline).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0

# Kept in one place so the API can validate a subscription and the docs can list
# them; adding an event means adding it here.
EVENT_TYPES = (
    "lead.captured",
    "feedback.received",
    "handoff.requested",
    "digest.generated",
    "ping",
)

# Strong references to fire-and-forget deliveries so they are not garbage
# collected before they finish, exactly like `services/mail.py`.
_pending_tasks: set[asyncio.Task] = set()


def config_of(integration: models.Integration) -> dict[str, Any]:
    """The stored JSON config, tolerating a malformed row."""
    try:
        value = json.loads(integration.config or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def events_of(integration: models.Integration) -> list[str]:
    """The event names this integration subscribed to."""
    try:
        value = json.loads(integration.events or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [event for event in value if isinstance(event, str)]


def summarize(event_type: str, payload: dict[str, Any]) -> str:
    """One line a human can read in Slack/Zendesk/Crisp."""
    bits = [f"SiteGPT event: {event_type}"]
    for key in ("website_name", "question", "rating", "email", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            bits.append(f"{key}={value.strip()[:120]}")
    return " | ".join(bits)


class IntegrationProvider:
    """Base class: one `send` per provider, mirroring `services/sources.py`."""

    type = ""
    # Config keys that are credentials. The API masks these on every read, so a
    # token can never round-trip to the browser.
    secret_fields: tuple[str, ...] = ()

    async def send(
        self, config_data: dict[str, Any], event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError


class WebhookProvider(IntegrationProvider):
    """Signed generic webhook.

    The signature covers `timestamp.body`, so a receiver can both verify the
    sender and reject a replayed body. `X-SiteGPT-Signature` is
    `sha256=<hex digest>` keyed with `INTEGRATION_WEBHOOK_SECRET`.
    """

    type = "webhook"
    secret_fields = ()

    async def send(self, config_data, event_type, payload):
        url = str(config_data.get("url") or "").strip()
        if not url:
            raise ValueError("webhook integration has no url")

        body = json.dumps(
            {
                "event": event_type,
                "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": payload,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        timestamp = str(int(time.time()))
        secret = config.INTEGRATION_WEBHOOK_SECRET or ""
        digest = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-SiteGPT-Event": event_type,
            "X-SiteGPT-Timestamp": timestamp,
            "X-SiteGPT-Signature": f"sha256={digest}",
        }
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body, headers=headers)
        return {"status_code": response.status_code}


class SlackProvider(IntegrationProvider):
    """Slack Incoming Webhook: one text line per event."""

    type = "slack"
    secret_fields = ("webhook_url",)

    async def send(self, config_data, event_type, payload):
        url = str(config_data.get("webhook_url") or "").strip()
        if not url:
            raise ValueError("slack integration has no webhook_url")
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                url, json={"text": summarize(event_type, payload)}
            )
        return {"status_code": response.status_code}


class ZendeskProvider(IntegrationProvider):
    """Zendesk: open a ticket per event."""

    type = "zendesk"
    secret_fields = ("api_token",)

    async def send(self, config_data, event_type, payload):
        subdomain = str(config_data.get("subdomain") or "").strip()
        email = str(config_data.get("email") or "").strip()
        token = str(config_data.get("api_token") or "").strip()
        if not subdomain or not email or not token:
            raise ValueError("zendesk integration needs subdomain, email and api_token")

        body = {"ticket": {"subject": f"SiteGPT: {event_type}", "comment": {"body": summarize(event_type, payload)}}}
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"https://{subdomain}.zendesk.com/api/v2/tickets.json",
                json=body,
                auth=(f"{email}/token", token),
            )
        return {"status_code": response.status_code}


class CrispProvider(IntegrationProvider):
    """Crisp: post the event into a website conversation."""

    type = "crisp"
    secret_fields = ("token", "identifier")

    async def send(self, config_data, event_type, payload):
        website_id = str(config_data.get("website_id") or "").strip()
        identifier = str(config_data.get("identifier") or "").strip()
        token = str(config_data.get("token") or "").strip()
        if not website_id or not identifier or not token:
            raise ValueError("crisp integration needs website_id, identifier and token")

        auth = httpx.BasicAuth(identifier, token)
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"https://api.crisp.chat/v1/website/{website_id}/message",
                json={
                    "type": "text",
                    "from": "operator",
                    "origin": "email",
                    "content": summarize(event_type, payload),
                },
                auth=auth,
            )
        return {"status_code": response.status_code}


# Registry: integration type -> provider instance.
PROVIDERS: dict[str, IntegrationProvider] = {
    provider.type: provider()
    for provider in (
        WebhookProvider,
        SlackProvider,
        ZendeskProvider,
        CrispProvider,
    )
}


def _deliveries(
    db: Session, company_id: UUID, event_type: str, payload: dict[str, Any]
) -> list[tuple[IntegrationProvider, dict[str, Any]]]:
    """Enabled integrations of this company subscribed to `event_type`."""
    rows = (
        db.query(models.Integration)
        .filter(
            models.Integration.company_id == company_id,
            models.Integration.enabled.is_(True),
        )
        .all()
    )
    deliveries: list[tuple[IntegrationProvider, dict[str, Any]]] = []
    for row in rows:
        if event_type not in events_of(row):
            continue
        provider = PROVIDERS.get(row.type)
        if provider is None:
            logger.warning(
                "integration %s has unknown type %r; skipping", row.id, row.type
            )
            continue
        deliveries.append((provider, config_of(row)))
    return deliveries


async def emit_event_async(
    db: Session,
    company_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Deliver one company-scoped event; returns how many integrations were hit.

    Awaitable so worker jobs and async routes can deliver before finishing, and
    so tests do not have to guess when a background send happened. Every provider
    call is wrapped: one broken endpoint cannot stop the others and nothing is
    ever raised to the caller.
    """
    try:
        deliveries = _deliveries(db, company_id, event_type, payload or {})
    except Exception:
        logger.exception("integration event %s could not be prepared", event_type)
        return 0

    delivered = 0
    for provider, config_data in deliveries:
        try:
            result = await provider.send(config_data, event_type, payload or {})
            delivered += 1
            logger.info(
                "integration %s delivered %s (%s)",
                provider.type,
                event_type,
                result.get("status_code"),
            )
        except Exception:
            # The payload is deliberately absent from this line.
            logger.exception(
                "integration %s failed to deliver %s", provider.type, event_type
            )
    return delivered


def _schedule(coro) -> None:
    """Run `coro` to completion: await it, or schedule it if a loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    task = loop.create_task(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def emit_event(
    db: Session,
    company_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Sync entry point for sync request paths; never raises.

    When no loop is running (a sync FastAPI endpoint runs in a worker thread) the
    delivery completes before returning; when a loop is running (async route,
    worker) it is scheduled so the response is not blocked by a third party.
    """
    try:
        _schedule(emit_event_async(db, company_id, event_type, payload))
    except Exception:
        logger.exception("integration event %s could not be emitted", event_type)
    return None
