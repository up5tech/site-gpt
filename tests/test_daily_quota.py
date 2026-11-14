"""Daily per-website message cap.

Per-IP rate limiting caps one visitor; it does not cap a website's spend. These
tests pin the boundary (limit-th message allowed, limit+1 refused), the day
rollover, the escape hatches (0 = disabled, Redis down = fail open) and that the
endpoints answer with the friendly message instead of calling the LLM.
"""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app import models
from site_gpt.app.api import routes
from site_gpt.app.db.session import get_db
from site_gpt.app.services import quota, ratelimit

WEBSITE_URL = "https://customer.example.com"


class FakeRedis:
    """Just the two commands the quota uses, with Redis INCR semantics."""

    def __init__(self):
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}
        self.calls: list[tuple[str, str]] = []

    async def incr(self, key):
        self.calls.append(("incr", key))
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.calls.append(("expire", key))
        self.expirations[key] = seconds
        return True


class BrokenRedis:
    async def incr(self, key):
        raise ConnectionError("redis is down")

    async def expire(self, key, seconds):  # pragma: no cover - never reached
        raise ConnectionError("redis is down")


class QuotaUnitTests(unittest.TestCase):
    def run_consume(self, redis, website_id, **kwargs):
        with patch.object(quota, "redis_client", redis):
            return asyncio.run(quota.consume_message(website_id, **kwargs))

    def test_the_limit_th_message_is_allowed_and_the_next_is_not(self):
        redis = FakeRedis()
        website_id = uuid4()

        allowed = [
            self.run_consume(redis, website_id, limit=3) for _ in range(3)
        ]
        self.assertEqual(allowed, [True, True, True])

        # Boundary: exactly at the limit is fine, one past it is refused, and it
        # stays refused however many more messages arrive.
        self.assertFalse(self.run_consume(redis, website_id, limit=3))
        self.assertFalse(self.run_consume(redis, website_id, limit=3))
        self.assertEqual(redis.values[quota.quota_key(website_id, datetime.now(UTC))], 5)

    def test_counters_are_per_website(self):
        redis = FakeRedis()
        limited, other = uuid4(), uuid4()

        self.assertTrue(self.run_consume(redis, limited, limit=1))
        self.assertFalse(self.run_consume(redis, limited, limit=1))
        # A different website has its own counter and is unaffected.
        self.assertTrue(self.run_consume(redis, other, limit=1))

    def test_counter_resets_at_utc_midnight(self):
        redis = FakeRedis()
        website_id = uuid4()
        late = datetime(2026, 1, 1, 23, 59, 0, tzinfo=UTC)
        next_day = late + timedelta(minutes=2)

        self.assertTrue(self.run_consume(redis, website_id, limit=1, now=late))
        self.assertFalse(self.run_consume(redis, website_id, limit=1, now=late))
        # New date, new key: the visitor is served again.
        self.assertTrue(self.run_consume(redis, website_id, limit=1, now=next_day))
        self.assertIn(quota.quota_key(website_id, late), redis.values)
        self.assertIn(quota.quota_key(website_id, next_day), redis.values)

    def test_expiry_is_set_once_on_first_increment(self):
        redis = FakeRedis()
        website_id = uuid4()
        moment = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        self.run_consume(redis, website_id, limit=5, now=moment)
        self.run_consume(redis, website_id, limit=5, now=moment)

        key = quota.quota_key(website_id, moment)
        self.assertEqual(redis.expirations[key], quota.seconds_until_reset(moment))
        self.assertEqual(redis.calls.count(("expire", key)), 1)
        # 12:00 -> midnight is 12 hours.
        self.assertEqual(redis.expirations[key], 12 * 3600)

    def test_zero_limit_disables_the_cap(self):
        redis = FakeRedis()
        website_id = uuid4()

        for _ in range(5):
            self.assertTrue(self.run_consume(redis, website_id, limit=0))
        self.assertEqual(redis.calls, [])

    def test_redis_failure_fails_open(self):
        website_id = uuid4()
        with patch("builtins.print") as printed:
            self.assertTrue(self.run_consume(BrokenRedis(), website_id, limit=1))
        self.assertIn("could not count message", printed.call_args[0][0])

    def test_default_limit_comes_from_config(self):
        redis = FakeRedis()
        website_id = uuid4()
        with patch.object(quota, "DAILY_MESSAGE_LIMIT", 2):
            self.assertTrue(self.run_consume(redis, website_id))
            self.assertTrue(self.run_consume(redis, website_id))
            self.assertFalse(self.run_consume(redis, website_id))


class ChatQuotaEndpointTests(unittest.TestCase):
    def setUp(self):
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

        self.site = models.Website(
            id=uuid4(),
            url=WEBSITE_URL,
            name="Customer",
            description="",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=uuid4(),
            status="active",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self.site

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: db
        self.client = TestClient(app)
        self.body = {
            "website_id": str(self.site.id),
            "session_id": "s-1",
            "question": "what do you sell?",
        }

    def test_capped_chat_returns_the_friendly_message_without_calling_the_llm(self):
        with patch.object(
            routes, "consume_message", new=AsyncMock(return_value=False)
        ), patch.object(routes, "ask") as ask:
            response = self.client.post("/api/chat", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], quota.QUOTA_MESSAGE)
        self.assertEqual(response.json()["sources"], [])
        ask.assert_not_called()

    def test_allowed_chat_still_calls_the_llm(self):
        with patch.object(
            routes, "consume_message", new=AsyncMock(return_value=True)
        ), patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ) as ask:
            response = self.client.post("/api/chat", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        ask.assert_called_once()

    def test_capped_stream_sends_the_message_instead_of_streaming_the_llm(self):
        with patch.object(
            routes, "consume_message", new=AsyncMock(return_value=False)
        ), patch.object(routes, "ask_stream") as ask_stream:
            response = self.client.post("/api/chat/stream", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(quota.QUOTA_MESSAGE, response.text)
        self.assertIn('"done": true', response.text)
        ask_stream.assert_not_called()

    def test_quota_counts_the_website_id_from_the_request(self):
        consume = AsyncMock(return_value=True)
        with patch.object(routes, "consume_message", new=consume), patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ):
            self.client.post("/api/chat", json=self.body)

        consume.assert_awaited_once_with(self.site.id)


if __name__ == "__main__":
    unittest.main()
