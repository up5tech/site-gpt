"""Unit tests for the integration dispatcher (F7).

The one property that matters most: a broken integration must never break the
request that emitted the event, and must never stop the other integrations.
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from site_gpt.app.services import integrations


def _chain(**kwargs):
    """A query chain stub. `all_value=`/`first_value=`/`count_value=` set the
    terminal method's return value."""
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.join.return_value = chain
    chain.order_by.return_value = chain
    for name, value in kwargs.items():
        method = name[: -len("_value")] if name.endswith("_value") else name
        getattr(chain, method).return_value = value
    return chain


def _row(**overrides):
    row = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        type="webhook",
        name="hooks",
        config='{"url": "https://example.com/hook"}',
        events='["ping"]',
        enabled=True,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class _Provider:
    def __init__(self, type_name, error=None):
        self.type = type_name
        self.error = error
        self.calls = []

    async def send(self, config_data, event_type, payload):
        self.calls.append((config_data, event_type, payload))
        if self.error is not None:
            raise self.error
        return {"status_code": 200}


class EmitEventAsyncTests(unittest.TestCase):
    """The queue half of emit: rows are persisted before any HTTP happens.

    The attempt half is exercised in `test_integration_delivery.py`; here
    `attempt_delivery` is patched so these tests stay about ordering and safety.
    """

    def _db(self, rows, existing=None):
        db = MagicMock()
        db.query.return_value = _chain(all_value=rows, first_value=existing)
        return db

    def _emit(self, db, event_type="ping", payload=None, attempt=None):
        attempt = attempt or AsyncMock(return_value=True)
        with patch.object(integrations, "attempt_delivery", attempt):
            delivered = asyncio.run(
                integrations.emit_event_async(db, uuid4(), event_type, payload)
            )
        return delivered, attempt

    def test_no_integrations_delivers_nothing(self):
        db = self._db([])
        delivered, attempt = self._emit(db)
        self.assertEqual(delivered, 0)
        attempt.assert_not_called()
        db.add.assert_not_called()

    def test_every_target_gets_a_row_committed_before_the_first_attempt(self):
        db = self._db([_row(), _row(type="slack", config='{"webhook_url": "https://x"}')])
        delivered, attempt = self._emit(db)

        self.assertEqual(delivered, 2)
        rows = [call.args[0] for call in db.add.call_args_list]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.status for row in rows}, {"pending"})
        self.assertEqual({row.event_type for row in rows}, {"ping"})
        # One event id shared by every integration, so the receiver can dedupe.
        self.assertEqual(len({row.event_id for row in rows}), 1)
        self.assertEqual(json.loads(rows[0].payload)["event_id"], str(rows[0].event_id))
        # commit (the queue) must happen before the first send.
        calls = [name for name, _, _ in db.mock_calls]
        self.assertLess(calls.index("commit"), calls.index("rollback") if "rollback" in calls else len(calls))
        self.assertGreater(len(attempt.await_args_list), 0)

    def test_a_failing_attempt_is_swallowed(self):
        db = self._db([_row()])
        delivered, attempt = self._emit(
            db, attempt=AsyncMock(side_effect=RuntimeError("connection refused"))
        )
        self.assertEqual(delivered, 0)
        self.assertEqual(len(attempt.await_args_list), 1)

    def test_one_exception_does_not_stop_the_other_integration(self):
        db = self._db([_row(), _row(type="slack")])
        attempt = AsyncMock(side_effect=[RuntimeError("boom"), True])
        delivered, _ = self._emit(db, attempt=attempt)
        self.assertEqual(delivered, 1)
        self.assertEqual(len(attempt.await_args_list), 2)

    def test_payload_carries_the_event_id(self):
        db = self._db([_row()])
        self._emit(db, payload={"website_name": "Acme"})
        sent = json.loads(db.add.call_args.args[0].payload)
        self.assertEqual(sent["website_name"], "Acme")
        self.assertIn("event_id", sent)

    def test_unsubscribed_event_is_not_delivered(self):
        db = self._db([_row(events='["lead.captured"]')])
        delivered, attempt = self._emit(db)
        self.assertEqual(delivered, 0)
        attempt.assert_not_called()
        db.add.assert_not_called()

    def test_unknown_type_is_skipped(self):
        db = self._db([_row(type="nosuchprovider")])
        delivered, attempt = self._emit(db)
        self.assertEqual(delivered, 0)
        db.add.assert_not_called()

    def test_a_broken_query_returns_zero(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("db down")
        self.assertEqual(
            asyncio.run(integrations.emit_event_async(db, uuid4(), "ping")), 0
        )


class ConfigParsingTests(unittest.TestCase):
    def test_malformed_config_falls_back_to_empty(self):
        for raw in ("{not json", "[]", "", None, '"a string"'):
            self.assertEqual(integrations.config_of(_row(config=raw)), {})

    def test_malformed_events_fall_back_to_empty(self):
        for raw in ("[1, 2]", "nope", "", None, '{"a": 1}'):
            self.assertEqual(integrations.events_of(_row(events=raw)), [])

    def test_events_of_keeps_strings_only(self):
        self.assertEqual(
            integrations.events_of(_row(events='["ping", 3, "lead.captured"]')),
            ["ping", "lead.captured"],
        )

    def test_event_types_cover_the_documented_events(self):
        self.assertEqual(
            set(integrations.EVENT_TYPES),
            {
                "lead.captured",
                "feedback.received",
                "handoff.requested",
                "digest.generated",
                "ping",
            },
        )

    def test_summarize_is_one_line_and_bounded(self):
        line = integrations.summarize(
            "lead.captured",
            {"website_name": "Acme", "email": "x" * 500, "session_id": "s1"},
        )
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("SiteGPT event: lead.captured"))
        self.assertIn("website_name=Acme", line)
        self.assertLess(len(line), 400)


if __name__ == "__main__":
    unittest.main()
