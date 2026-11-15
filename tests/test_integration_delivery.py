"""Unit tests for tracked integration deliveries (retry, dead-letter, resend).

A lead that reached nobody must be visible and retryable, so these tests are
about the bookkeeping around a send: attempt counting, the backoff schedule, the
point where retries stop, and the fact that the event id never changes (a
receiver uses it to drop a duplicate retry).
"""

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from site_gpt.app import models
from site_gpt.app.services import integrations


class _FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, count):
        self.items = self.items[:count]
        return self

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    """Just enough ORM surface for the delivery code, with counters."""

    def __init__(self, integrations_rows=(), deliveries=()):
        self.integrations = list(integrations_rows)
        self.deliveries = list(deliveries)
        self.commits = 0
        self.rollbacks = 0

    def query(self, model, *args):
        if model is models.Integration:
            return _FakeQuery(self.integrations)
        if model is models.IntegrationDelivery:
            return _FakeQuery(self.deliveries)
        return _FakeQuery([])

    def add(self, row):
        if row not in self.deliveries:
            self.deliveries.append(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Provider:
    type = "webhook"
    secret_fields = ("url",)

    def __init__(self, error=None, status_code=200):
        self.error = error
        self.status_code = status_code
        self.calls = []

    async def send(self, config_data, event_type, payload):
        self.calls.append((config_data, event_type, dict(payload)))
        if self.error is not None:
            raise self.error
        return {"status_code": self.status_code}


def _integration(**overrides):
    row = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        type="webhook",
        name="Hooks",
        config='{"url": "https://hooks.example.com/secret-token"}',
        events='["lead.captured"]',
        enabled=True,
        created_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _delivery(integration, **overrides):
    row = models.IntegrationDelivery(
        company_id=integration.company_id,
        integration_id=integration.id,
        integration_type=integration.type,
        integration_name=integration.name,
        event_id=uuid4(),
        event_type="lead.captured",
        payload=json.dumps({"email": "lead@example.com", "event_id": "e-1"}),
        status="pending",
        attempts=0,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class BackoffTests(unittest.TestCase):
    def test_schedule_increases_and_is_clamped(self):
        delays = [integrations.retry_delay_seconds(n) for n in (1, 2, 3, 4)]
        self.assertEqual(delays, [60, 300, 1800, 7200])
        self.assertEqual(integrations.retry_delay_seconds(0), 60)
        self.assertEqual(
            integrations.retry_delay_seconds(99), integrations.RETRY_BACKOFF_SECONDS[-1]
        )

    def test_max_attempts_matches_the_schedule(self):
        self.assertEqual(
            integrations.MAX_DELIVERY_ATTEMPTS, len(integrations.RETRY_BACKOFF_SECONDS)
        )


class AttemptTests(unittest.TestCase):
    def test_success_marks_delivered(self):
        provider = _Provider(status_code=204)
        integration = _integration()
        delivery = _delivery(integration)
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            ok = asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertTrue(ok)
        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.last_status_code, 204)
        self.assertIsNotNone(delivery.delivered_at)
        self.assertIsNone(delivery.next_attempt_at)
        self.assertIsNone(delivery.last_error)
        # The receiver gets the stored event id, not a fresh one.
        self.assertEqual(provider.calls[0][2]["event_id"], "e-1")

    def test_failure_schedules_a_retry_with_backoff(self):
        provider = _Provider(error=RuntimeError("503 Service Unavailable"))
        integration = _integration()
        delivery = _delivery(integration)
        db = _FakeSession([integration], [delivery])

        before = datetime.now(UTC)
        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            ok = asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertFalse(ok)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNone(delivery.delivered_at)
        self.assertIn("RuntimeError", delivery.last_error)
        self.assertGreaterEqual(
            delivery.next_attempt_at, before + timedelta(seconds=60)
        )
        self.assertLessEqual(
            delivery.next_attempt_at, datetime.now(UTC) + timedelta(seconds=120)
        )

    def test_credentials_are_scrubbed_from_the_stored_error(self):
        provider = _Provider(
            error=RuntimeError(
                "cannot reach https://hooks.example.com/secret-token now"
            )
        )
        integration = _integration()
        delivery = _delivery(integration)
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertNotIn("secret-token", delivery.last_error)
        self.assertIn("***", delivery.last_error)

    def test_a_500_response_is_a_failure_not_a_delivery(self):
        # Providers return the status code instead of raising; a 500 must still
        # count as a failed attempt or nothing would ever be retried.
        provider = _Provider(status_code=500)
        integration = _integration()
        delivery = _delivery(integration)
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            ok = asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertFalse(ok)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.last_status_code, 500)
        self.assertIn("HTTP 500", delivery.last_error)
        self.assertIsNone(delivery.delivered_at)
        self.assertIsNotNone(delivery.next_attempt_at)

    def test_429_is_retried_but_404_is_not(self):
        for status_code, expected in ((429, "pending"), (404, "dead")):
            provider = _Provider(status_code=status_code)
            integration = _integration()
            delivery = _delivery(integration)
            db = _FakeSession([integration], [delivery])

            with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
                asyncio.run(integrations.attempt_delivery(db, delivery))

            self.assertEqual(delivery.status, expected, status_code)
            self.assertEqual(delivery.last_status_code, status_code)

    def test_last_allowed_failure_dead_letters_the_delivery(self):
        provider = _Provider(error=RuntimeError("timeout"))
        integration = _integration()
        delivery = _delivery(
            integration, attempts=integrations.MAX_DELIVERY_ATTEMPTS - 1
        )
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            ok = asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertFalse(ok)
        self.assertEqual(delivery.status, "dead")
        self.assertEqual(delivery.attempts, integrations.MAX_DELIVERY_ATTEMPTS)
        self.assertIsNone(delivery.next_attempt_at)

    def test_deleted_integration_is_dead_not_retried(self):
        integration = _integration()
        delivery = _delivery(integration)
        db = _FakeSession([], [delivery])  # integration row gone

        ok = asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertFalse(ok)
        self.assertEqual(delivery.status, "dead")
        self.assertIn("deleted", delivery.last_error)

    def test_unknown_provider_type_is_dead(self):
        integration = _integration(type="carrier-pigeon")
        delivery = _delivery(integration)
        db = _FakeSession([integration], [delivery])

        asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertEqual(delivery.status, "dead")
        self.assertIn("unknown integration type", delivery.last_error)

    def test_retry_rereads_the_integration_config(self):
        # A fixed URL must be used by the retry, so the endpoint is loaded fresh.
        provider = _Provider()
        integration = _integration(config='{"url": "https://new.example.com/hook"}')
        delivery = _delivery(integration)
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            asyncio.run(integrations.attempt_delivery(db, delivery))

        self.assertEqual(provider.calls[0][0]["url"], "https://new.example.com/hook")
        self.assertGreater(db.commits, 0)


class QueueTests(unittest.TestCase):
    def test_same_event_is_not_queued_twice_for_one_integration(self):
        integration = _integration()
        event_id = uuid4()
        payload = {"event_id": str(event_id)}
        db = _FakeSession([integration])

        first = integrations._queue(db, integration, "lead.captured", event_id, payload)
        second = integrations._queue(db, integration, "lead.captured", event_id, payload)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(db.deliveries), 1)


class _DueSession:
    """The query chain `process_due_deliveries` builds, scripted per call.

    `first()` returning None is exactly what `SKIP LOCKED` returns when another
    worker holds the only due row.
    """

    def __init__(self, rows):
        self.rows = list(rows)
        self.skip_locked = None
        self.commits = 0
        self.rollbacks = 0

    def query(self, model, *args):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self, skip_locked=False):
        self.skip_locked = skip_locked
        return self

    def first(self):
        return self.rows.pop(0) if self.rows else None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class DueDeliveryClaimTests(unittest.TestCase):
    """Two workers must never send the same delivery twice."""

    def _run(self, db, limit=50, attempt=None):
        attempt = attempt or AsyncMock(return_value=True)
        with patch.object(integrations, "attempt_delivery", attempt):
            result = asyncio.run(integrations.process_due_deliveries(db, limit=limit))
        return result, attempt

    def test_the_due_query_claims_the_row_and_skips_locked_ones(self):
        # Compiles the real query with the Postgres dialect: if the clause is ever
        # dropped, two workers start sending the same row again.
        from sqlalchemy import create_engine
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite+pysqlite:///:memory:")
        session = sessionmaker(bind=engine)()
        try:
            query = integrations.due_deliveries_query(session, datetime.now(UTC))
            sql = str(query.statement.compile(dialect=postgresql.dialect()))
        finally:
            session.close()
            engine.dispose()

        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("integration_deliveries", sql)

    def test_a_row_locked_by_another_worker_is_not_attempted(self):
        db = _DueSession([])  # the only due row is locked elsewhere
        result, attempt = self._run(db)

        self.assertEqual(result, {"attempted": 0, "delivered": 0})
        attempt.assert_not_called()
        # The claim is asked for on every tick, not just when rows are returned.
        self.assertTrue(db.skip_locked)

    def test_claimed_rows_are_attempted_one_at_a_time(self):
        integration = _integration()
        first, second = _delivery(integration), _delivery(integration)
        db = _DueSession([first, second])

        result, attempt = self._run(db)

        self.assertEqual(result, {"attempted": 2, "delivered": 2})
        self.assertEqual([call.args[1] for call in attempt.await_args_list], [first, second])

    def test_a_failed_attempt_does_not_stop_the_next_row(self):
        integration = _integration()
        first, second = _delivery(integration), _delivery(integration)
        db = _DueSession([first, second])

        result, attempt = self._run(db, attempt=AsyncMock(side_effect=[RuntimeError("boom"), True]))

        self.assertEqual(result, {"attempted": 2, "delivered": 1})
        self.assertEqual(db.rollbacks, 1)

    def test_the_limit_bounds_the_batch(self):
        integration = _integration()
        db = _DueSession([_delivery(integration) for _ in range(5)])

        result, _ = self._run(db, limit=2)

        self.assertEqual(result["attempted"], 2)
        self.assertEqual(len(db.rows), 3)

    def test_a_zero_limit_scans_nothing(self):
        db = _DueSession([_delivery(_integration())])
        result, attempt = self._run(db, limit=0)

        self.assertEqual(result["attempted"], 0)
        attempt.assert_not_called()


class ResendTests(unittest.TestCase):
    def test_resend_gives_a_fresh_budget_and_tries_now(self):
        provider = _Provider()
        integration = _integration()
        delivery = _delivery(
            integration,
            status="dead",
            attempts=5,
            last_error="boom",
            next_attempt_at=None,
        )
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            ok = asyncio.run(integrations.resend_delivery(db, delivery))

        self.assertTrue(ok)
        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNone(delivery.last_error)

    def test_resend_of_a_still_dead_delivery_stays_retryable(self):
        provider = _Provider(error=RuntimeError("still down"))
        integration = _integration()
        delivery = _delivery(integration, status="dead", attempts=5)
        db = _FakeSession([integration], [delivery])

        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            ok = asyncio.run(integrations.resend_delivery(db, delivery))

        self.assertFalse(ok)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.next_attempt_at)


class SafeErrorTests(unittest.TestCase):
    def test_webhook_url_is_redacted(self):
        message = integrations.safe_error(
            RuntimeError("ConnectError: https://hooks.example.com/abc123"),
            {"url": "https://hooks.example.com/abc123"},
            ("url",),
        )
        self.assertNotIn("abc123", message)

    def test_basic_auth_in_a_url_is_redacted(self):
        message = integrations.safe_error(
            RuntimeError("failed POST https://user:pa55@zendesk.example.com/x"),
            {},
            (),
        )
        self.assertNotIn("pa55", message)
        self.assertIn("zendesk.example.com", message)

    def test_message_is_bounded(self):
        self.assertLessEqual(len(integrations.safe_error(RuntimeError("x" * 900), {}, ())), 500)


if __name__ == "__main__":
    unittest.main()
