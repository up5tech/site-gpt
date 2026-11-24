"""Sitemap sync used to wrap every failure in `except Exception` and re-raise it
as a 500 carrying `str(e)`. A missing website therefore answered 500 instead of
404, and an unsafe or unreachable sitemap leaked internal text to the browser.

These tests pin the mapping: HTTPException untouched, crawler/UnsafeUrl -> 400
with a friendly message, anything else -> a generic 500 that is logged, and the
response reports how many pages were added.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.api import website as website_api
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import crawler
from site_gpt.app.services import sitemap as sitemap_service
from site_gpt.app.services.net_guard import UnsafeUrl

SITEMAP_URLS = [
    "https://example.com/about",
    "https://example.com/pricing",
]
UNSAFE_DETAIL = "'127.0.0.1' resolves to a non-public address and cannot be fetched."


class SiteMapEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Website.__table__,
                models.WebsitePage.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        company = models.Company(name="Customer", description="")
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)

        self.site = models.Website(
            url="https://example.com",
            name="Customer",
            site_map_url="https://example.com/sitemap.xml",
            company_id=company.id,
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

        app = FastAPI()
        app.include_router(website_api.router, prefix="/api/websites")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=company.id
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def sync(self, website_id=None):
        return self.client.post(
            f"/api/websites/{website_id or self.site.id}/load-site-map"
        )

    # ---- success -----------------------------------------------------------
    def test_reports_how_many_pages_were_added(self):
        with patch.object(
            website_api, "extract_urls_from_sitemap", return_value=list(SITEMAP_URLS)
        ):
            first = self.sync()
            second = self.sync()

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["added"], 2)
        self.assertEqual(first.json()["total"], 2)
        self.assertFalse(first.json()["truncated"])
        self.assertEqual(second.json()["added"], 0)
        self.assertEqual(second.json()["total"], 2)
        self.assertFalse(second.json()["truncated"])

    # ---- 404 stays a 404 ---------------------------------------------------
    def test_unknown_website_is_404_not_500(self):
        response = self.sync(website_id=uuid4())

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "Website not found")

    # ---- crawler failures are the user's 400 -------------------------------
    def test_unsafe_sitemap_url_is_400_without_internal_text(self):
        with patch.object(
            website_api,
            "extract_urls_from_sitemap",
            side_effect=UnsafeUrl(UNSAFE_DETAIL),
        ):
            with self.assertLogs("site_gpt.app", level="WARNING") as captured:
                response = self.sync()

        self.assertEqual(response.status_code, 400, response.text)
        detail = response.json()["detail"]
        self.assertIn("public http(s)", detail)
        for leak in ("127.0.0.1", "resolves", "UnsafeUrl"):
            self.assertNotIn(leak, detail)
        # The reason is still logged server-side as a structured event.
        self.assertIn("sitemap.refused_unsafe_url", "\n".join(captured.output))

    def test_fetch_failure_is_400_without_internal_text(self):
        with patch.object(
            website_api,
            "extract_urls_from_sitemap",
            side_effect=RuntimeError("connection reset by peer at 10.0.0.5"),
        ), patch("builtins.print"):
            response = self.sync()

        self.assertEqual(response.status_code, 400, response.text)
        detail = response.json()["detail"]
        self.assertIn("Could not download the sitemap", detail)
        self.assertNotIn("10.0.0.5", detail)
        self.assertNotIn("connection reset", detail)

    def test_the_endpoint_asks_the_crawler_to_raise(self):
        extract = MagicMock(return_value=[])
        with patch.object(website_api, "extract_urls_from_sitemap", extract):
            self.sync()

        extract.assert_called_once_with(self.site.site_map_url, raise_on_error=True)

    # ---- anything else is a generic, logged 500 ----------------------------
    def test_storage_failure_is_a_generic_logged_500(self):
        with patch.object(
            website_api, "extract_urls_from_sitemap", return_value=list(SITEMAP_URLS)
        ), patch.object(
            self.db, "commit", side_effect=RuntimeError("disk full")
        ), patch.object(self.db, "rollback") as rollback:
            with self.assertLogs("site_gpt.app", level="ERROR") as captured:
                response = self.sync()

        self.assertEqual(response.status_code, 500, response.text)
        detail = response.json()["detail"]
        self.assertIn("Could not save the sitemap pages", detail)
        self.assertNotIn("disk full", detail)
        rollback.assert_called_once()
        # V6-22: the reason survives server-side as a structured event.
        self.assertIn("sitemap.save_failed", "\n".join(captured.output))
        self.assertIn("disk full", captured.records[0].fields["error_message"])


class SitemapSyncCapTests(unittest.TestCase):
    """A single sitemap can list tens of thousands of URLs; one sync must not
    create all of them, and it must say when it stopped short."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Website.__table__,
                models.WebsitePage.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        company = models.Company(name="Customer", description="")
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)

        self.site = models.Website(
            url="https://example.com",
            name="Customer",
            site_map_url="https://example.com/sitemap.xml",
            company_id=company.id,
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

        app = FastAPI()
        app.include_router(website_api.router, prefix="/api/websites")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=company.id
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def sync(self, urls, limit):
        with patch.object(
            website_api, "extract_urls_from_sitemap", return_value=list(urls)
        ), patch.object(sitemap_service, "SITEMAP_SYNC_MAX_URLS", limit):
            return self.client.post(f"/api/websites/{self.site.id}/load-site-map")

    def page_count(self):
        return self.db.query(models.WebsitePage).count()

    def test_cap_limits_created_pages_and_reports_truncation(self):
        urls = [f"https://example.com/p{i}" for i in range(5)]

        response = self.sync(urls, limit=2)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["added"], 2)
        self.assertEqual(body["total"], 5)
        self.assertTrue(body["truncated"])
        self.assertEqual(body["limit"], 2)
        self.assertEqual(self.page_count(), 2)

    def test_repeated_syncs_continue_where_the_last_stopped(self):
        urls = [f"https://example.com/p{i}" for i in range(5)]

        first = self.sync(urls, limit=2).json()
        second = self.sync(urls, limit=2).json()
        third = self.sync(urls, limit=2).json()

        self.assertEqual((first["added"], first["truncated"]), (2, True))
        self.assertEqual((second["added"], second["truncated"]), (2, True))
        # Last sync consumes the rest and has nothing left to truncate.
        self.assertEqual((third["added"], third["truncated"]), (1, False))
        self.assertEqual(self.page_count(), 5)
        for body in (first, second, third):
            self.assertEqual(body["total"], 5)

    def test_a_sitemap_under_the_cap_is_not_truncated(self):
        urls = [f"https://example.com/p{i}" for i in range(3)]

        body = self.sync(urls, limit=10).json()

        self.assertEqual(body["added"], 3)
        self.assertFalse(body["truncated"])

    def test_exactly_at_the_cap_is_not_truncated(self):
        urls = [f"https://example.com/p{i}" for i in range(2)]

        body = self.sync(urls, limit=2).json()

        self.assertEqual((body["added"], body["total"]), (2, 2))
        self.assertFalse(body["truncated"])

    def test_existing_pages_do_not_consume_the_budget(self):
        urls = [f"https://example.com/p{i}" for i in range(3)]
        self.sync(urls, limit=10)

        # A cap of 1 with 3 already-known URLs must still add nothing new.
        body = self.sync(urls, limit=1).json()

        self.assertEqual(body["added"], 0)
        self.assertFalse(body["truncated"])
        self.assertEqual(self.page_count(), 3)

    def test_zero_disables_the_cap(self):
        urls = [f"https://example.com/p{i}" for i in range(5)]

        body = self.sync(urls, limit=0).json()

        self.assertEqual(body["added"], 5)
        self.assertFalse(body["truncated"])
        self.assertEqual(self.page_count(), 5)

    def test_default_cap_comes_from_config(self):
        # No patch: the module constant is what ships.
        urls = [f"https://example.com/p{i}" for i in range(3)]
        with patch.object(
            website_api, "extract_urls_from_sitemap", return_value=list(urls)
        ):
            body = self.client.post(
                f"/api/websites/{self.site.id}/load-site-map"
            ).json()

        self.assertEqual(body["limit"], sitemap_service.SITEMAP_SYNC_MAX_URLS)
        self.assertGreater(body["limit"], 0)
        self.assertEqual(body["added"], 3)


class CrawlerRaiseOnErrorTests(unittest.TestCase):
    """The crawl path must keep skipping a broken sitemap silently."""

    def test_default_returns_empty_instead_of_raising(self):
        with patch.object(
            crawler, "_safe_get", side_effect=UnsafeUrl(UNSAFE_DETAIL)
        ), patch("builtins.print"):
            self.assertEqual(crawler.extract_urls_from_sitemap("http://x/sitemap.xml"), [])

    def test_raise_on_error_propagates_unsafe_url(self):
        with patch.object(
            crawler, "_safe_get", side_effect=UnsafeUrl(UNSAFE_DETAIL)
        ), patch("builtins.print"):
            with self.assertRaises(UnsafeUrl):
                crawler.extract_urls_from_sitemap(
                    "http://x/sitemap.xml", raise_on_error=True
                )

    def test_raise_on_error_propagates_fetch_errors(self):
        with patch.object(
            crawler, "_safe_get", side_effect=RuntimeError("boom")
        ), patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                crawler.extract_urls_from_sitemap(
                    "http://x/sitemap.xml", raise_on_error=True
                )


if __name__ == "__main__":
    unittest.main()
