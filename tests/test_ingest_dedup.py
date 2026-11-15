"""POST /api/ingest must not enqueue a crawl for a website that is already
processing: a double click used to start two concurrent crawls that re-embedded
the same pages, doubling the cost and racing on the same documents."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app import models
from site_gpt.app.api import routes
from site_gpt.app.db.session import get_db
from site_gpt.app.services import ratelimit
from site_gpt.app.worker import STUCK_INGEST_AFTER


def make_website(ingest_status, *, started_ago=None):
    """`started_ago` sets how long ago the row was last written (None = now)."""
    return models.Website(
        id=uuid4(),
        url="https://customer.example.com",
        name="Customer",
        description="",
        site_map_url="https://customer.example.com/sitemap.xml",
        company_id=uuid4(),
        status="active",
        ingest_status=ingest_status,
        updated_at=datetime.now(UTC) - (started_ago or timedelta(0)),
    )


class IngestDedupTests(unittest.TestCase):
    def setUp(self):
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

        self.site = make_website("completed")
        self.user = MagicMock(id=uuid4(), company_id=self.site.company_id)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self.site

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[routes.get_manager_user] = lambda: self.user
        self.client = TestClient(app)

    def ingest(self):
        with patch.object(routes, "enqueue_job", new=AsyncMock()) as enqueue:
            response = self.client.post(
                "/api/ingest", params={"website_id": str(self.site.id)}
            )
        return response, enqueue

    def test_second_request_while_processing_is_refused(self):
        first, enqueue_first = self.ingest()
        self.assertEqual(first.status_code, 200, first.text)
        enqueue_first.assert_awaited_once()
        self.assertEqual(self.site.ingest_status, "processing")

        # The double click.
        second, enqueue_second = self.ingest()
        self.assertEqual(second.status_code, 409, second.text)
        self.assertIn("already running", second.json()["detail"])
        enqueue_second.assert_not_called()

    def test_processing_website_is_refused_outright(self):
        self.site.ingest_status = "processing"

        response, enqueue = self.ingest()

        self.assertEqual(response.status_code, 409, response.text)
        enqueue.assert_not_called()

    def test_retry_after_a_finished_or_failed_ingest_is_allowed(self):
        for status in ("completed", "failed", "none", "", None):
            with self.subTest(ingest_status=status):
                self.site.ingest_status = status
                response, enqueue = self.ingest()
                self.assertEqual(response.status_code, 200, response.text)
                enqueue.assert_awaited_once()
                self.assertEqual(self.site.ingest_status, "processing")


class StuckIngestRetryTests(unittest.TestCase):
    """A `processing` row left by a dead worker must still be retryable."""

    def setUp(self):
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

    def build(self, website):
        self.site = website
        self.user = MagicMock(id=uuid4(), company_id=website.company_id)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = website

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[routes.get_manager_user] = lambda: self.user
        self.client = TestClient(app)

    def ingest(self):
        with patch.object(routes, "enqueue_job", new=AsyncMock()) as enqueue:
            response = self.client.post(
                "/api/ingest", params={"website_id": str(self.site.id)}
            )
        return response, enqueue

    def test_a_fresh_processing_row_is_still_refused(self):
        self.build(make_website("processing"))

        response, enqueue = self.ingest()

        self.assertEqual(response.status_code, 409, response.text)
        enqueue.assert_not_called()

    def test_a_row_stuck_for_hours_can_be_reindexed(self):
        self.build(make_website("processing", started_ago=timedelta(hours=7)))

        response, enqueue = self.ingest()

        self.assertEqual(response.status_code, 200, response.text)
        enqueue.assert_awaited_once()
        self.assertEqual(self.site.ingest_status, "processing")

    def test_the_threshold_matches_the_worker_recovery_window(self):
        self.build(
            make_website(
                "processing", started_ago=STUCK_INGEST_AFTER - timedelta(minutes=5)
            )
        )
        under, enqueue_under = self.ingest()
        self.assertEqual(under.status_code, 409, under.text)
        enqueue_under.assert_not_called()

        self.build(
            make_website(
                "processing", started_ago=STUCK_INGEST_AFTER + timedelta(minutes=5)
            )
        )
        over, enqueue_over = self.ingest()
        self.assertEqual(over.status_code, 200, over.text)
        enqueue_over.assert_awaited_once()

    def test_taking_over_a_stale_row_resets_its_timestamp(self):
        started = datetime.now(UTC) - timedelta(hours=7)
        self.build(make_website("processing", started_ago=timedelta(hours=7)))

        response, _ = self.ingest()

        self.assertEqual(response.status_code, 200, response.text)
        # Not stale any more, so an immediate second click is refused again.
        self.assertGreater(self.site.updated_at, started)
        second, enqueue_second = self.ingest()
        self.assertEqual(second.status_code, 409, second.text)
        enqueue_second.assert_not_called()

    def test_a_processing_row_without_a_timestamp_is_retryable(self):
        website = make_website("processing")
        website.updated_at = None
        self.build(website)

        response, enqueue = self.ingest()

        self.assertEqual(response.status_code, 200, response.text)
        enqueue.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
