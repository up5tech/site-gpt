"""Outbound integration event bus (F7).

`emit_event` is what chat, lead capture, feedback, handoff and the digest call to
tell the outside world something happened. The providers and the dispatcher that
filter by `enabled` + subscribed events live here.

Three rules hold for every path in this module:

* an integration failure never reaches the originating request — the chat still
  answers, the lead is still stored, even when a webhook endpoint is down;
* nothing is dropped: every event becomes an `integration_deliveries` row before
  the first HTTP call, failed attempts are retried with backoff, and a delivery
  that runs out of attempts is parked as `dead` instead of disappearing;
* payloads are never logged, because they carry visitor contact details. Only the
  integration id, its type, the event name and the attempt counter are logged.

The retry state lives in the database rather than in a task queue: a restart, a
crash or a deploy mid-delivery must not lose a lead. `process_due_deliveries` is
what the worker's `delivery_loop` calls; the endpoints in `api/integration.py`
read the rows and resend a dead one.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core import config
from site_gpt.app.services import retention

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0

# Default window for keeping a settled delivery row: `config.DELIVERY_RETENTION_DAYS`
# overrides it per deployment (0 = keep the rows, still clear dead payloads).

# Delay before retry N+1, after attempt N failed. The fifth failure parks the
# delivery, so a broken endpoint is retried five times over ~9 hours instead of
# for ever; a `dead` row is visible in the UI and can be resent by hand.
RETRY_BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)
MAX_DELIVERY_ATTEMPTS = len(RETRY_BACKOFF_SECONDS)

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
    for key in ("website_name", "question", "rating", "email", "session_id", "event_id"):
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
    # The URL is the credential here: hooks are routinely issued as
    # `/hooks/<token>`, so it is masked like a Slack webhook URL and a PATCH
    # echoing the mask keeps the stored value. Signature keys stay in the
    # environment (`INTEGRATION_WEBHOOK_SECRET`), never in `config`.
    secret_fields = ("url",)

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
        # Also in the body (`data.event_id`); the header saves a receiver from
        # parsing a body it may want to verify first. A retry reuses the id.
        if payload.get("event_id"):
            headers["X-SiteGPT-Event-Id"] = str(payload["event_id"])
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


def safe_error(exc: BaseException, config_data: dict[str, Any], secret_fields) -> str:
    """An error message fit to show an admin: credentials redacted.

    `str(httpx.ConnectError)` contains the URL, and for a webhook the URL *is*
    the credential. Anything matching a stored secret value or a `scheme://user:…@`
    pair is replaced before the message reaches the API, the logs or the DB.
    """
    message = f"{type(exc).__name__}: {exc}"
    for field in secret_fields or ():
        value = str(config_data.get(field) or "").strip()
        if value:
            message = message.replace(value, "***")
    if "://" in message:
        head, _, tail = message.partition("://")
        authority, slash, rest = tail.partition("/")
        if "@" in authority:
            message = f"{head}://***@{authority.rpartition('@')[2]}{slash}{rest}"
    return message[:500]


def targets(db: Session, company_id: UUID, event_type: str) -> list[models.Integration]:
    """Enabled integrations of this company subscribed to `event_type`."""
    rows = (
        db.query(models.Integration)
        .filter(
            models.Integration.company_id == company_id,
            models.Integration.enabled.is_(True),
        )
        .order_by(models.Integration.created_at.asc())
        .all()
    )
    selected: list[models.Integration] = []
    for row in rows:
        if event_type not in events_of(row):
            continue
        if row.type not in PROVIDERS:
            logger.warning(
                "integration %s has unknown type %r; skipping", row.id, row.type
            )
            continue
        selected.append(row)
    return selected


def retry_delay_seconds(attempts: int) -> int:
    """Backoff after `attempts` failures, clamped to the schedule."""
    index = min(max(attempts, 1), len(RETRY_BACKOFF_SECONDS)) - 1
    return RETRY_BACKOFF_SECONDS[index]


def _queue(
    db: Session,
    integration: models.Integration,
    event_type: str,
    event_id: UUID,
    payload: dict[str, Any],
) -> models.IntegrationDelivery | None:
    """Persist one delivery, or return None if this event is already queued."""
    existing = (
        db.query(models.IntegrationDelivery)
        .filter(
            models.IntegrationDelivery.integration_id == integration.id,
            models.IntegrationDelivery.event_id == event_id,
        )
        .first()
    )
    if existing is not None:
        return None
    delivery = models.IntegrationDelivery(
        company_id=integration.company_id,
        integration_id=integration.id,
        integration_type=integration.type,
        integration_name=integration.name,
        event_id=event_id,
        event_type=event_type,
        payload=json.dumps(payload, sort_keys=True, default=str),
        status="pending",
        attempts=0,
        next_attempt_at=datetime.now(UTC),
    )
    db.add(delivery)
    return delivery


def _gave_up(
    db: Session,
    delivery: models.IntegrationDelivery,
    message: str,
    retryable: bool = True,
) -> bool:
    """Record a failure: schedule the next attempt or park the delivery.

    `retryable=False` parks it on the first failure — a deleted integration or an
    unknown provider type will not heal by waiting.
    """
    delivery.last_error = (message or "delivery failed")[:500]
    if retryable and (delivery.attempts or 0) < MAX_DELIVERY_ATTEMPTS:
        delivery.status = "pending"
        delivery.next_attempt_at = datetime.now(UTC) + timedelta(
            seconds=retry_delay_seconds(delivery.attempts or 1)
        )
    else:
        delivery.status = "dead"
        delivery.next_attempt_at = None
    db.commit()
    return False


async def attempt_delivery(db: Session, delivery: models.IntegrationDelivery) -> bool:
    """Try one delivery once, recording the outcome. Never raises.

    The integration is re-read on every attempt so a fixed URL or a rotated token
    is used by the retry, and a deleted integration ends the retries instead of
    retrying for ever.
    """
    integration = None
    if delivery.integration_id is not None:
        integration = (
            db.query(models.Integration)
            .filter(
                models.Integration.id == delivery.integration_id,
                models.Integration.company_id == delivery.company_id,
            )
            .first()
        )
    if integration is None:
        delivery.attempts = (delivery.attempts or 0) + 1
        return _gave_up(db, delivery, "integration was deleted", retryable=False)

    provider = PROVIDERS.get(integration.type)
    if provider is None:
        delivery.attempts = (delivery.attempts or 0) + 1
        return _gave_up(
            db,
            delivery,
            f"unknown integration type {integration.type!r}",
            retryable=False,
        )

    config_data = config_of(integration)
    delivery.integration_type = integration.type
    delivery.integration_name = integration.name
    delivery.attempts = (delivery.attempts or 0) + 1
    try:
        payload = json.loads(delivery.payload or "{}")
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        result = await provider.send(config_data, delivery.event_type, payload)
    except Exception as exc:
        logger.warning(
            "integration %s failed to deliver %s (attempt %s/%s)",
            provider.type,
            delivery.event_type,
            delivery.attempts,
            MAX_DELIVERY_ATTEMPTS,
        )
        return _gave_up(db, delivery, safe_error(exc, config_data, provider.secret_fields))

    status_code = result.get("status_code") if isinstance(result, dict) else None
    if isinstance(status_code, int) and status_code >= 400:
        # A provider that answers 500 has not accepted the event: that is the
        # failure this whole table exists for. 408/429 are worth retrying, other
        # 4xx will not fix themselves (a 404 URL, a 401 token) so they park.
        delivery.last_status_code = status_code
        retryable = status_code >= 500 or status_code in (408, 429)
        return _gave_up(
            db, delivery, f"endpoint answered HTTP {status_code}", retryable=retryable
        )

    delivery.status = "delivered"
    delivery.delivered_at = datetime.now(UTC)
    delivery.next_attempt_at = None
    delivery.last_error = None
    delivery.last_status_code = status_code
    db.commit()
    logger.info(
        "integration %s delivered %s (%s)",
        provider.type,
        delivery.event_type,
        delivery.last_status_code,
    )
    return True


async def emit_event_async(
    db: Session,
    company_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Deliver one company-scoped event; returns how many integrations accepted it.

    Every target gets a row committed *before* the first HTTP call, so the event
    survives a crash or a dead endpoint. The first attempt happens inline (so a
    healthy webhook is still delivered right away and tests stay deterministic);
    anything that fails is picked up by `process_due_deliveries`. Nothing is ever
    raised to the caller.
    """
    payload = dict(payload or {})
    event_id = uuid4()
    payload["event_id"] = str(event_id)

    try:
        rows = targets(db, company_id, event_type)
    except Exception:
        logger.exception("integration event %s could not be prepared", event_type)
        return 0

    queued: list[models.IntegrationDelivery] = []
    for integration in rows:
        delivery = _queue(db, integration, event_type, event_id, payload)
        if delivery is not None:
            queued.append(delivery)
    if not queued:
        return 0
    # Commit the queue before talking to anyone: a rollback here would lose the
    # event that the retry loop is supposed to protect.
    try:
        db.commit()
    except Exception:
        logger.exception("integration event %s could not be queued", event_type)
        db.rollback()
        return 0

    delivered = 0
    for delivery in queued:
        try:
            if await attempt_delivery(db, delivery):
                delivered += 1
        except Exception:
            # attempt_delivery is meant not to raise; if it does, the row is left
            # pending and the worker retries it.
            logger.exception("integration delivery %s could not be attempted", delivery.id)
            db.rollback()
    return delivered


def due_deliveries_query(db: Session, now: datetime):
    """The due-row select, with the row claimed for the caller.

    `FOR UPDATE SKIP LOCKED` is what makes two workers safe: a row another worker
    is already sending is skipped instead of being sent twice. It must stay on
    this query — a plain select leaves the same row visible to both workers.
    SQLite ignores the clause (and has no `SKIP LOCKED`), which is why the
    concurrency behaviour is verified against Postgres.
    """
    return (
        db.query(models.IntegrationDelivery)
        .filter(
            models.IntegrationDelivery.status == "pending",
            or_(
                models.IntegrationDelivery.next_attempt_at.is_(None),
                models.IntegrationDelivery.next_attempt_at <= now,
            ),
        )
        .order_by(models.IntegrationDelivery.next_attempt_at.asc())
        .with_for_update(skip_locked=True)
    )


async def process_due_deliveries(db: Session, limit: int = 50) -> dict[str, int]:
    """Retry pending deliveries whose backoff has elapsed (worker entry point).

    One row per transaction, not a batch: `attempt_delivery` commits, which
    releases every lock the transaction held. Selecting a batch up front would
    therefore leave rows 2..N claimable while row 1 is still being sent. Claiming
    the next row *after* that commit, in the same session, keeps each delivery
    under one lock from selection to outcome.
    """
    attempted = 0
    delivered = 0
    for _ in range(max(limit, 0)):
        # A fresh `now` per row: a row whose backoff elapsed during the batch is
        # not starved until the next tick.
        delivery = due_deliveries_query(db, datetime.now(UTC)).first()
        if delivery is None:
            break
        attempted += 1
        try:
            if await attempt_delivery(db, delivery):
                delivered += 1
        except Exception:
            logger.exception("integration delivery %s could not be attempted", delivery.id)
            db.rollback()
    return {"attempted": attempted, "delivered": delivered}


def parse_delivery_retention_days(raw: str | int | None) -> int:
    """How long a settled delivery row is kept. Unusable input means "for ever"."""
    if raw is None or raw == "":
        return 0
    try:
        days = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return days if days > 0 else 0


def delivery_retention_cutoff(
    days: int, now: datetime | None = None
) -> datetime | None:
    if days <= 0:
        return None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - timedelta(days=days)


def payload_purged(delivery: models.IntegrationDelivery) -> bool:
    """Whether this row's payload is gone (cleared by retention, or empty).

    A purged payload cannot be resent: the event would arrive with no data at
    all, which is worse than a visible failure. The API reports this as
    `payload_available: false` so the UI can disable Resend.
    """
    return not (delivery.payload or "").strip()


# Rows changed per statement by the retention pass. The same reason as the
# visitor-data purge: a single delete over years of deliveries holds one
# transaction (and its locks) for the whole sweep and grows the WAL with it.
DELIVERY_PURGE_BATCH_SIZE = 1000


def _clear_dead_payloads(
    db: Session, filters: list, batch_size: int
) -> int:
    """Blank the payload of each dead row, one bounded batch at a time.

    An UPDATE rather than a delete, so it reuses only the batching shape:
    `retention.batch_ids` picks the ids, each batch commits on its own.
    """
    cleared = 0
    while True:
        ids = retention.batch_ids(
            db, models.IntegrationDelivery, filters, batch_size
        )
        if not ids:
            break
        cleared += (
            db.query(models.IntegrationDelivery)
            .filter(models.IntegrationDelivery.id.in_(ids))
            .update(
                {models.IntegrationDelivery.payload: ""}, synchronize_session=False
            )
        )
        db.commit()
        if len(ids) < batch_size:
            break
    return cleared


def purge_deliveries(
    db: Session,
    days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    company_id: UUID | None = None,
    batch_size: int = DELIVERY_PURGE_BATCH_SIZE,
) -> dict[str, Any]:
    """Drop the visitor data that delivery rows carry.

    Two separate controls, because they answer different questions:

    * **Every dead row loses its payload immediately.** It will never be retried,
      so nothing needs the name/email it was going to send; keeping it is pure
      PII exposure. Delivery-status and the scrubbed error stay, so "this lead
      was never delivered" is still visible.
    * **settled rows older than the window are deleted** (`delivered`/`dead`,
      `created_at < cutoff`). `pending` rows are never deleted — they are work
      that has not happened yet. A window of 0 disables deletion only; the payload
      clear still runs.

    Both steps run in `DELIVERY_PURGE_BATCH_SIZE` batches, each committed before the
    next, so a big backfill cannot hold one long transaction.
    """
    days = config.DELIVERY_RETENTION_DAYS if days is None else days
    now = now or datetime.now(UTC)
    batch_size = max(1, int(batch_size or 0))
    cutoff = delivery_retention_cutoff(days, now)

    def rows(model):
        query = db.query(model)
        if company_id is not None:
            # An admin may only clean their own company; the worker passes None
            # and sweeps every tenant.
            query = query.filter(model.company_id == company_id)
        return query

    dead_filters = [models.IntegrationDelivery.status == "dead"]
    if company_id is not None:
        dead_filters.append(models.IntegrationDelivery.company_id == company_id)
    carried = dead_filters + [models.IntegrationDelivery.payload != ""]
    cleared = (
        rows(models.IntegrationDelivery).filter(*carried).count()
        if dry_run
        else _clear_dead_payloads(db, carried, batch_size)
    )

    deleted = 0
    if cutoff is not None:
        settled_filters = [
            models.IntegrationDelivery.status.in_(("delivered", "dead")),
            models.IntegrationDelivery.created_at < cutoff,
        ]
        if company_id is not None:
            settled_filters.append(models.IntegrationDelivery.company_id == company_id)
        deleted = retention.delete_in_batches(
            db,
            models.IntegrationDelivery,
            settled_filters,
            batch_size,
            dry_run=dry_run,
        )

    if not dry_run:
        if cleared or deleted:
            logger.info(
                "delivery retention: cleared %s dead payload(s), deleted %s settled row(s)",
                cleared,
                deleted,
            )
    return {
        "retention_days": days,
        "cutoff": cutoff,
        "dry_run": dry_run,
        "cleared_payloads": cleared,
        "deleted": deleted,
    }


def resend_claim(db: Session, delivery_id: UUID):
    """Lock the row for this resend; `None` means another caller holds it.

    Two admins pressing Resend at once used to both re-arm and send the same row,
    so the receiver got it twice. `FOR UPDATE SKIP LOCKED` makes the claim
    exclusive: the loser is told to wait instead of sending again. The lock lasts
    until the attempt commits (`attempt_delivery` does that), which is exactly the
    window in which the event may be in flight.
    """
    return (
        db.query(models.IntegrationDelivery)
        .filter(models.IntegrationDelivery.id == delivery_id)
        .with_for_update(skip_locked=True)
        .first()
    )


async def resend_delivery(db: Session, delivery: models.IntegrationDelivery) -> bool:
    """Give a dead (or pending) delivery a fresh attempt budget and try once."""
    delivery_id = delivery.id
    claimed = resend_claim(db, delivery_id)
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This delivery is already being resent by another request; "
                "reload to see the result"
            ),
        )
    delivery = claimed
    if payload_purged(delivery):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The payload of this delivery was purged by retention and cannot be "
                "resent; the event has to be produced again"
            ),
        )
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.next_attempt_at = datetime.now(UTC)
    delivery.last_error = None
    delivery.delivered_at = None
    # No commit here: that would release the claim taken above, and a second
    # admin could re-arm and send the row while this one is still in flight.
    # `attempt_delivery` commits when the send has an outcome; a crash in between
    # rolls the re-arm back and leaves the row dead (still resendable) instead of
    # leaving a phantom `pending` nobody is sending.
    return await attempt_delivery(db, delivery)


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
