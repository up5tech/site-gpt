"""Owners must be able to see today's usage before visitors hit the cap."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import website as website_api
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import quota


class FakeRedis:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key):
        return self.values.get(key)

    async def incr(self, key):
        self.values[key] = int(self.values.get(key) or 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        return True


class BrokenRedis:
    async def get(self, key):
        raise ConnectionError("redis is down")


class WebsiteQuotaEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[models.Company.__table__, models.Website.__table__, models.Setting.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Customer", description="")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

        self.site = models.Website(
            url="https://customer.example.com",
            name="Customer",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=self.company.id,
            status="active",
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

        self.redis = FakeRedis()
        self.user = SimpleNamespace(id=uuid4(), company_id=self.company.id)

        app = FastAPI()
        app.include_router(website_api.router, prefix="/api/websites")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def set_limit(self, value):
        self.db.add(
            models.Setting(
                key="daily_message_limit", value=value, company_id=self.company.id
            )
        )
        self.db.commit()

    def get(self, website_id=None, redis=None):
        with patch.object(quota, "redis_client", redis or self.redis):
            return self.client.get(
                f"/api/websites/{website_id or self.site.id}/quota"
            )

    def key(self):
        from datetime import UTC, datetime

        return quota.quota_key(self.site.id, datetime.now(UTC))

    # ---- shape -------------------------------------------------------------
    def test_reports_today_count_limit_and_remaining(self):
        self.set_limit("100")
        self.redis.values[self.key()] = "42"

        response = self.get()

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["website_id"], str(self.site.id))
        self.assertEqual(body["used"], 42)
        self.assertEqual(body["limit"], 100)
        self.assertEqual(body["remaining"], 58)
        self.assertFalse(body["unlimited"])
        self.assertFalse(body["near_limit"])
        self.assertTrue(body["available"])
        self.assertRegex(body["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_an_untouched_website_reports_zero(self):
        self.set_limit("100")

        body = self.get().json()

        self.assertEqual(body["used"], 0)
        self.assertEqual(body["remaining"], 100)

    # ---- near / at the cap -------------------------------------------------
    def test_near_limit_starts_at_eighty_percent(self):
        self.set_limit("100")

        for used, expected in ((79, False), (80, True), (99, True), (100, True)):
            with self.subTest(used=used):
                self.redis.values[self.key()] = str(used)
                body = self.get().json()
                self.assertEqual(body["near_limit"], expected)

    def test_remaining_never_goes_negative_past_the_cap(self):
        self.set_limit("10")
        self.redis.values[self.key()] = "25"

        body = self.get().json()

        self.assertEqual(body["used"], 25)
        self.assertEqual(body["remaining"], 0)
        self.assertTrue(body["near_limit"])

    # ---- unlimited / unavailable ------------------------------------------
    def test_zero_limit_reports_unlimited(self):
        self.set_limit("0")

        body = self.get().json()

        self.assertTrue(body["unlimited"])
        self.assertIsNone(body["remaining"])
        self.assertFalse(body["near_limit"])
        self.assertEqual(body["limit"], 0)

    def test_the_company_setting_is_used_and_env_is_the_fallback(self):
        with patch.object(website_api, "company_daily_message_limit", return_value=7):
            body = self.get().json()
        self.assertEqual(body["limit"], 7)

    def test_a_company_without_the_setting_falls_back_to_the_env_default(self):
        body = self.get().json()

        self.assertEqual(body["limit"], quota.DAILY_MESSAGE_LIMIT)

    def test_redis_failure_is_reported_instead_of_a_fake_zero(self):
        self.set_limit("100")

        response = self.get(redis=BrokenRedis())

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["available"])
        self.assertIsNone(body["used"])
        self.assertIsNone(body["remaining"])
        self.assertFalse(body["near_limit"])

    # ---- ownership ---------------------------------------------------------
    def test_another_company_cannot_see_the_usage(self):
        other = models.Company(name="Other", description="")
        self.db.add(other)
        self.db.commit()
        self.db.refresh(other)
        self.user.company_id = other.id

        response = self.get()

        self.assertEqual(response.status_code, 404, response.text)

    def test_unknown_website_is_404(self):
        response = self.get(website_id=uuid4())

        self.assertEqual(response.status_code, 404, response.text)

    def test_usage_is_reported_for_a_disabled_website_too(self):
        self.site.status = "inactive"
        self.db.commit()
        self.set_limit("100")
        self.redis.values[self.key()] = "5"

        body = self.get().json()

        self.assertEqual(body["used"], 5)


if __name__ == "__main__":
    unittest.main()
