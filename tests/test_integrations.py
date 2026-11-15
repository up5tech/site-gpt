"""Unit tests for the integration dispatcher (F7).

The one property that matters most: a broken integration must never break the
request that emitted the event, and must never stop the other integrations.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
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
    def _db(self, rows):
        db = MagicMock()
        db.query.return_value = _chain(all_value=rows)
        return db

    def test_no_integrations_delivers_nothing(self):
        delivered = asyncio.run(
            integrations.emit_event_async(self._db([]), uuid4(), "ping")
        )
        self.assertEqual(delivered, 0)

    def test_a_failing_provider_is_swallowed(self):
        provider = _Provider("webhook", error=RuntimeError("connection refused"))
        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            delivered = asyncio.run(
                integrations.emit_event_async(
                    self._db([_row()]), uuid4(), "ping", {"website_name": "Acme"}
                )
            )
        self.assertEqual(delivered, 0)
        self.assertEqual(len(provider.calls), 1)

    def test_one_failure_does_not_stop_the_other_integration(self):
        failing = _Provider("webhook", error=RuntimeError("boom"))
        healthy = _Provider("slack")
        rows = [_row(), _row(type="slack", config='{"webhook_url": "https://x"}')]
        with patch.dict(
            integrations.PROVIDERS, {"webhook": failing, "slack": healthy}
        ):
            delivered = asyncio.run(
                integrations.emit_event_async(self._db(rows), uuid4(), "ping")
            )
        self.assertEqual(delivered, 1)
        self.assertEqual(len(healthy.calls), 1)
        self.assertEqual(healthy.calls[0][1], "ping")

    def test_unsubscribed_event_is_not_delivered(self):
        provider = _Provider("webhook")
        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            delivered = asyncio.run(
                integrations.emit_event_async(
                    self._db([_row(events='["lead.captured"]')]), uuid4(), "ping"
                )
            )
        self.assertEqual(delivered, 0)
        self.assertEqual(provider.calls, [])

    def test_unknown_type_is_skipped(self):
        provider = _Provider("webhook")
        with patch.dict(integrations.PROVIDERS, {"webhook": provider}):
            delivered = asyncio.run(
                integrations.emit_event_async(
                    self._db([_row(type="nosuchprovider")]), uuid4(), "ping"
                )
            )
        self.assertEqual(delivered, 0)

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
