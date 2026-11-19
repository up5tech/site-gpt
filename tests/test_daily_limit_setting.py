"""The daily message cap used to be one global env value. It now lives in the
per-company settings registry, with the env value as the fallback whenever the
setting is absent (companies created before it existed) or unusable.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import routes
from site_gpt.app.api import setting as setting_api
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import quota, ratelimit

WEBSITE_URL = "https://customer.example.com"


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        return True


class ParseLimitTests(unittest.TestCase):
    def test_absent_or_empty_falls_back_to_the_default(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(quota.parse_limit(raw, default=1000), 1000)

    def test_a_number_is_used(self):
        self.assertEqual(quota.parse_limit("250", default=1000), 250)
        self.assertEqual(quota.parse_limit(" 250 ", default=1000), 250)

    def test_zero_is_a_real_value_that_disables_the_cap(self):
        self.assertEqual(quota.parse_limit("0", default=1000), 0)

    def test_garbage_and_negatives_fall_back_instead_of_removing_the_cap(self):
        for raw in ("abc", "1 000", "-5", "12.5", None):
            with self.subTest(raw=raw):
                self.assertEqual(quota.parse_limit(raw, default=1000), 1000)


class RegistryTests(unittest.TestCase):
    def test_the_limit_is_a_company_setting(self):
        self.assertIn("daily_message_limit", setting_api.ALL_SETTINGS)
        self.assertIn("daily_message_limit", setting_api.INTERNAL_SETTINGS)

    def test_it_is_never_published_by_the_public_widget_config(self):
        self.assertNotIn("daily_message_limit", setting_api.WIDGET_PUBLIC_KEYS)
        # The public allowlist is an explicit literal (7 appearance + 7 V2 widget
        # keys), every entry is a registered appearance setting, and no internal
        # key can reach it.
        self.assertEqual(len(setting_api.WIDGET_PUBLIC_KEYS), 14)
        self.assertTrue(
            set(setting_api.WIDGET_PUBLIC_KEYS) <= set(setting_api.DEFAULT_SETTINGS)
        )
        self.assertFalse(
            set(setting_api.WIDGET_PUBLIC_KEYS) & set(setting_api.INTERNAL_SETTINGS)
        )

    def test_new_companies_are_seeded_with_the_env_default(self):
        rows = setting_api._default_setting_rows(uuid4())
        seeded = {row.key: row.value for row in rows}
        self.assertIn("daily_message_limit", seeded)
        self.assertEqual(seeded["daily_message_limit"], str(setting_api.DAILY_MESSAGE_LIMIT))


class CompanyLimitResolutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(
            self.engine,
            tables=[models.Company.__table__, models.Setting.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()
        self.company = models.Company(name="Customer", description="")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def set_limit(self, value):
        self.db.add(
            models.Setting(
                key="daily_message_limit",
                value=value,
                company_id=self.company.id,
            )
        )
        self.db.commit()

    def resolve(self):
        return setting_api.company_daily_message_limit(self.db, self.company.id)

    def test_absent_setting_uses_the_env_default(self):
        with patch.object(setting_api, "DAILY_MESSAGE_LIMIT", 777):
            self.assertEqual(self.resolve(), 777)

    def test_the_company_value_wins(self):
        self.set_limit("50")
        with patch.object(setting_api, "DAILY_MESSAGE_LIMIT", 777):
            self.assertEqual(self.resolve(), 50)

    def test_zero_can_be_set_per_company(self):
        self.set_limit("0")
        self.assertEqual(self.resolve(), 0)

    def test_another_company_is_unaffected(self):
        self.set_limit("50")
        other = models.Company(name="Other", description="")
        self.db.add(other)
        self.db.commit()
        self.db.refresh(other)

        self.assertEqual(setting_api.company_daily_message_limit(self.db, other.id), setting_api.DAILY_MESSAGE_LIMIT)


class ChatUsesTheCompanyLimitTests(unittest.TestCase):
    """End to end through POST /api/chat with a fake Redis counter."""

    def setUp(self):
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Website.__table__,
                models.Setting.__table__,
                # The chat handlers read the inbox state (V3-43): a `human`
                # session is answered by a teammate, not the bot.
                models.Conversation.__table__,
            ],
        )
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Customer", description="")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

        self.site = models.Website(
            url=WEBSITE_URL,
            name="Customer",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=self.company.id,
            status="active",
            ingest_status="completed",
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.redis = FakeRedis()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def set_limit(self, value):
        self.db.add(
            models.Setting(
                key="daily_message_limit",
                value=value,
                company_id=self.company.id,
            )
        )
        self.db.commit()

    def chat(self):
        with patch.object(quota, "redis_client", self.redis), patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ) as ask:
            response = self.client.post(
                "/api/chat",
                json={
                    "website_id": str(self.site.id),
                    "session_id": "s-1",
                    "question": "hello",
                },
                headers={"Origin": WEBSITE_URL},
            )
        return response, ask

    def test_the_company_setting_sets_the_ceiling(self):
        self.set_limit("2")

        first, ask_first = self.chat()
        second, ask_second = self.chat()
        third, ask_third = self.chat()

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["answer"], "hi")
        ask_first.assert_called_once()
        self.assertEqual(second.status_code, 200, second.text)
        ask_second.assert_called_once()
        self.assertEqual(third.json()["answer"], quota.QUOTA_MESSAGE)
        ask_third.assert_not_called()

    def test_absent_setting_falls_back_to_the_env_value(self):
        with patch.object(setting_api, "DAILY_MESSAGE_LIMIT", 1):
            first, ask_first = self.chat()
            second, ask_second = self.chat()

        self.assertEqual(first.json()["answer"], "hi")
        ask_first.assert_called_once()
        self.assertEqual(second.json()["answer"], quota.QUOTA_MESSAGE)
        ask_second.assert_not_called()

    def test_a_company_limit_of_zero_disables_the_cap(self):
        self.set_limit("0")

        for _ in range(5):
            response, ask = self.chat()
            self.assertEqual(response.json()["answer"], "hi")
            ask.assert_called_once()
        self.assertEqual(self.redis.values, {})

    def test_an_invalid_company_value_falls_back_to_the_env_value(self):
        self.set_limit("not a number")

        with patch.object(setting_api, "DAILY_MESSAGE_LIMIT", 1):
            first, _ = self.chat()
            second, ask_second = self.chat()

        self.assertEqual(first.json()["answer"], "hi")
        self.assertEqual(second.json()["answer"], quota.QUOTA_MESSAGE)
        ask_second.assert_not_called()


class StreamUsesTheCompanyLimitTests(unittest.TestCase):
    def setUp(self):
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

        self.site = models.Website(
            id=uuid4(),
            url=WEBSITE_URL,
            name="Customer",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=uuid4(),
            status="active",
        )
        self.db = MagicMock()
        self.db.query.return_value.filter.return_value.first.return_value = self.site

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def stream(self):
        return self.client.post(
            "/api/chat/stream",
            json={
                "website_id": str(self.site.id),
                "session_id": "s-1",
                "question": "hello",
            },
            headers={"Origin": WEBSITE_URL},
        )

    def test_stream_also_reads_the_company_limit(self):
        resolved = MagicMock(return_value=1)
        with patch.object(routes, "company_daily_message_limit", resolved), patch.object(
            quota, "redis_client", FakeRedis()
        ), patch.object(
            routes, "ask_stream", return_value=iter([])
        ) as ask_stream, patch.object(
            # This handler's db is a mock, so the inbox lookup is stubbed: the
            # session is not held by an agent, which is the case under test.
            routes,
            "human_handling",
            return_value=False,
        ):
            self.stream()  # 1st message: allowed
            capped = self.stream()  # 2nd: over the company's limit of 1

        self.assertEqual(resolved.call_count, 2)
        self.assertEqual(capped.status_code, 200, capped.text)
        self.assertIn(quota.QUOTA_MESSAGE, capped.text)
        ask_stream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
