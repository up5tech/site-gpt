"""V4-20: per-session message cap (F4, D6).

The daily cap bounds what one website spends; this one bounds one visitor's
conversation. These tests pin the boundary (limit-th message allowed, limit+1
refused), the sliding TTL, the escape hatches (`0`, a typo, Redis down),
per-session isolation, and the required ordering: IP limiter → session cap →
daily quota, so a capped message spends no daily budget and calls no LLM.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app import models
from site_gpt.app.api import routes, v1
from site_gpt.app.api import setting as setting_api
from site_gpt.app.core.auth import get_api_key
from site_gpt.app.db.session import get_db
from site_gpt.app.services import quota, ratelimit


class FakeRedis:
    """Just the two commands both caps use, with Redis INCR semantics."""

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


class SessionCapUnitTests(unittest.TestCase):
    def run_consume(self, redis, website_id, session_id="s-1", **kwargs):
        with patch.object(quota, "redis_client", redis):
            return asyncio.run(
                quota.consume_session_message(website_id, session_id, **kwargs)
            )

    def test_the_limit_th_message_is_allowed_and_the_next_is_not(self):
        redis = FakeRedis()
        website_id = uuid4()

        allowed = [self.run_consume(redis, website_id, limit=3) for _ in range(3)]
        self.assertEqual(allowed, [True, True, True])

        # Boundary: exactly at the limit is fine, one past it is refused, and it
        # stays refused however many more messages arrive.
        self.assertFalse(self.run_consume(redis, website_id, limit=3))
        self.assertFalse(self.run_consume(redis, website_id, limit=3))
        self.assertEqual(redis.values[quota.session_cap_key(website_id, "s-1")], 5)

    def test_two_sessions_of_one_website_have_independent_counters(self):
        redis = FakeRedis()
        website_id = uuid4()

        self.assertTrue(self.run_consume(redis, website_id, "s-a", limit=1))
        self.assertFalse(self.run_consume(redis, website_id, "s-a", limit=1))
        # The website's other session is unaffected by the first one's ceiling.
        self.assertTrue(self.run_consume(redis, website_id, "s-b", limit=1))
        self.assertIn(quota.session_cap_key(website_id, "s-a"), redis.values)
        self.assertIn(quota.session_cap_key(website_id, "s-b"), redis.values)

    def test_the_same_session_id_on_two_websites_does_not_collide(self):
        redis = FakeRedis()
        session_id = "same-session"
        first, second = uuid4(), uuid4()

        self.assertTrue(self.run_consume(redis, first, session_id, limit=1))
        self.assertFalse(self.run_consume(redis, first, session_id, limit=1))
        self.assertTrue(self.run_consume(redis, second, session_id, limit=1))

    def test_ttl_is_refreshed_on_every_message(self):
        redis = FakeRedis()
        website_id = uuid4()

        for _ in range(3):
            self.run_consume(redis, website_id, limit=5)

        key = quota.session_cap_key(website_id, "s-1")
        self.assertEqual(redis.expirations[key], quota.SESSION_CAP_TTL_SECONDS)
        # Refreshed, not set once: an idle window that a returning visitor
        # restarts instead of a lifetime ban.
        self.assertEqual(redis.calls.count(("expire", key)), 3)

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
        self.assertIn("could not count session message", printed.call_args[0][0])

    def test_default_limit_comes_from_config(self):
        redis = FakeRedis()
        website_id = uuid4()
        with patch.object(quota, "SESSION_MESSAGE_LIMIT", 2):
            self.assertTrue(self.run_consume(redis, website_id))
            self.assertTrue(self.run_consume(redis, website_id))
            self.assertFalse(self.run_consume(redis, website_id))


class SessionLimitSettingTests(unittest.TestCase):
    """`company_session_message_limit` keeps the daily-cap fallback rules."""

    def resolve(self, raw, default=7):
        with patch.object(
            setting_api, "company_setting", return_value=raw
        ), patch.object(setting_api, "SESSION_MESSAGE_LIMIT", default):
            return setting_api.company_session_message_limit(MagicMock(), uuid4())

    def test_missing_row_falls_back_to_the_env_default(self):
        self.assertEqual(self.resolve(None), 7)

    def test_a_value_is_used_as_is(self):
        self.assertEqual(self.resolve("3"), 3)

    def test_a_zero_row_disables_the_cap(self):
        self.assertEqual(self.resolve("0"), 0)

    def test_garbage_negative_and_empty_values_fall_back_to_the_default(self):
        with patch("builtins.print"):
            self.assertEqual(self.resolve("three"), 7)
            self.assertEqual(self.resolve("-2"), 7)
            self.assertEqual(self.resolve(""), 7)


class _One:
    """Minimal single-row query stub (filter().first())."""

    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class SessionCapEndpointTests(unittest.TestCase):
    def setUp(self):
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

        self.site = models.Website(
            id=uuid4(),
            url="https://customer.example.com",
            name="Customer",
            description="",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=uuid4(),
            status="active",
        )
        db = MagicMock()

        def query(model):
            if model is models.Website:
                return _One(self.site)
            # No setting rows: the env defaults apply.
            return _One(None)

        db.query.side_effect = query

        api_key = models.ApiKey(
            company_id=self.site.company_id,
            name="session-cap-test",
            key_prefix="sk_test",
            scopes=json.dumps(["chat:write"]),
        )

        widget = FastAPI()
        widget.include_router(routes.router)
        widget.dependency_overrides[get_db] = lambda: db
        self.client = TestClient(widget)

        versioned = FastAPI()
        versioned.include_router(v1.router, prefix="/api/v1")
        versioned.dependency_overrides[get_db] = lambda: db
        versioned.dependency_overrides[get_api_key] = lambda: api_key
        self.v1_client = TestClient(versioned)

        self.body = {
            "website_id": str(self.site.id),
            "session_id": "s-1",
            "question": "what do you sell?",
        }

    def test_widget_chat_refuses_a_capped_session_without_spending_the_daily_budget(
        self,
    ):
        daily = AsyncMock(return_value=True)
        with patch.object(
            routes, "consume_session_message", new=AsyncMock(return_value=False)
        ), patch.object(routes, "consume_message", new=daily), patch.object(
            routes, "company_session_message_limit", return_value=3
        ), patch.object(routes, "ask") as ask:
            response = self.client.post("/api/chat", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], quota.SESSION_CAP_MESSAGE)
        self.assertEqual(response.json()["sources"], [])
        ask.assert_not_called()
        daily.assert_not_awaited()

    def test_widget_chat_checks_the_session_cap_before_the_daily_quota(self):
        order: list[str] = []

        async def cap(*args, **kwargs):
            order.append("session")
            return True

        async def daily(*args, **kwargs):
            order.append("daily")
            return True

        with patch.object(
            routes, "consume_session_message", new=cap
        ), patch.object(routes, "consume_message", new=daily), patch.object(
            routes, "company_session_message_limit", return_value=3
        ), patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ):
            response = self.client.post("/api/chat", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(order, ["session", "daily"])

    def test_the_session_limit_and_key_come_from_the_request_and_setting(self):
        cap = AsyncMock(return_value=True)
        with patch.object(
            routes, "consume_session_message", new=cap
        ), patch.object(
            routes, "company_session_message_limit", return_value=3
        ), patch.object(
            routes, "consume_message", new=AsyncMock(return_value=True)
        ), patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ):
            self.client.post("/api/chat", json=self.body)

        cap.assert_awaited_once()
        self.assertEqual(cap.await_args.args, (self.site.id, "s-1"))
        self.assertEqual(cap.await_args.kwargs["limit"], 3)

    def test_capped_stream_sends_the_session_notice_instead_of_streaming(self):
        daily = AsyncMock(return_value=True)
        with patch.object(
            routes, "consume_session_message", new=AsyncMock(return_value=False)
        ), patch.object(routes, "consume_message", new=daily), patch.object(
            routes, "company_session_message_limit", return_value=3
        ), patch.object(routes, "ask_stream") as ask_stream:
            response = self.client.post("/api/chat/stream", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(quota.SESSION_CAP_MESSAGE, response.text)
        self.assertIn('"done": true', response.text)
        ask_stream.assert_not_called()
        daily.assert_not_awaited()

    def test_v1_chat_refuses_a_capped_session_with_the_friendly_answer(self):
        daily = AsyncMock(return_value=True)
        with patch.object(
            v1, "consume_session_message", new=AsyncMock(return_value=False)
        ), patch.object(v1, "consume_message", new=daily), patch.object(
            v1, "company_session_message_limit", return_value=3
        ), patch.object(v1, "ask") as ask:
            response = self.v1_client.post("/api/v1/chat", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], quota.SESSION_CAP_MESSAGE)
        self.assertEqual(response.json()["sources"], [])
        ask.assert_not_called()
        daily.assert_not_awaited()

    def test_v1_chat_checks_the_session_cap_before_the_daily_quota(self):
        order: list[str] = []

        async def cap(*args, **kwargs):
            order.append("session")
            return True

        async def daily(*args, **kwargs):
            order.append("daily")
            return True

        with patch.object(
            v1, "consume_session_message", new=cap
        ), patch.object(v1, "consume_message", new=daily), patch.object(
            v1, "company_session_message_limit", return_value=3
        ), patch.object(
            v1, "ask", return_value={"answer": "hi", "sources": []}
        ):
            response = self.v1_client.post("/api/v1/chat", json=self.body)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(order, ["session", "daily"])


if __name__ == "__main__":
    unittest.main()
