"""GET /api/widget-config is fetched by every visitor's browser before the
widget paints. It used to answer with no cache headers at all, so each page view
paid a fresh DB round trip; it now carries a short public TTL and an ETag so the
response can be reused and revalidated instead."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app import models
from site_gpt.app.api import routes
from site_gpt.app.db.session import get_db

WEBSITE_URL = "https://customer.example.com"


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._result

    def first(self):
        return self._result


class WidgetConfigCacheTests(unittest.TestCase):
    def setUp(self):
        self.site = models.Website(
            id=uuid4(),
            url=WEBSITE_URL,
            name="Customer",
            description="",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=uuid4(),
            status="active",
        )
        self.settings = [
            SimpleNamespace(key="assistant_name", value="Ada"),
            SimpleNamespace(key="greeting_message", value="Hi there"),
        ]

        db = MagicMock()

        def query(model):
            if model is models.Website:
                return FakeQuery(self.site)
            if model is models.Setting:
                return FakeQuery(self.settings)
            return FakeQuery(None)

        db.query.side_effect = query

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: db
        self.client = TestClient(app)

    def get(self, if_none_match=None):
        headers = {"Origin": WEBSITE_URL}
        if if_none_match:
            headers["If-None-Match"] = if_none_match
        return self.client.get(
            "/api/widget-config",
            params={"website_id": str(self.site.id)},
            headers=headers,
        )

    def test_response_carries_a_short_public_cache_with_revalidation(self):
        response = self.get()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["cache-control"],
            f"public, max-age={routes.WIDGET_CONFIG_MAX_AGE}, must-revalidate",
        )
        self.assertIn("etag", response.headers)
        self.assertEqual(
            response.json(), {"assistant_name": "Ada", "greeting_message": "Hi there"}
        )

    def test_revalidation_with_the_same_etag_returns_304(self):
        first = self.get()
        etag = first.headers["etag"]

        second = self.get(if_none_match=etag)

        self.assertEqual(second.status_code, 304, second.text)
        self.assertEqual(second.content, b"")
        # 304 must repeat the cache policy, otherwise the reuse window is lost.
        self.assertEqual(
            second.headers["cache-control"], first.headers["cache-control"]
        )
        self.assertEqual(second.headers["etag"], etag)

    def test_etag_is_stable_for_the_same_settings(self):
        self.assertEqual(self.get().headers["etag"], self.get().headers["etag"])

    def test_etag_changes_when_a_setting_changes(self):
        before = self.get().headers["etag"]

        self.settings = [SimpleNamespace(key="assistant_name", value="Grace")]
        after = self.get().headers["etag"]

        self.assertNotEqual(before, after)
        stale = self.get(if_none_match=before)
        self.assertEqual(stale.status_code, 200, stale.text)
        self.assertEqual(json.loads(stale.content), {"assistant_name": "Grace"})

    def test_a_disabled_website_is_still_refused_and_not_cached(self):
        self.site.status = "inactive"

        response = self.get()

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNone(response.headers.get("cache-control"))


if __name__ == "__main__":
    unittest.main()
