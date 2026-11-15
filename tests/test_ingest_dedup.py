"""POST /api/ingest must start exactly one crawl per website.

The first version checked `ingest_status` in Python and then wrote it, so two
simultaneous requests could both pass the check and enqueue two crawls. The
claim is now an atomic `UPDATE ... WHERE`, and the loser of that race must get a
409 with nothing queued.
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import routes
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import ratelimit
from site_gpt.app.worker import STUCK_INGEST_AFTER


class IngestDedupTests(unittest.TestCase):
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
                models.WebsitePage.__table__,
                models.Setting.__table__,
            ],
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
            ingest_status="completed",
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[routes.get_manager_user] = lambda: MagicMock(
            id=uuid4(), company_id=self.company.id
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- helpers -----------------------------------------------------------
    def set_state(self, status, *, started_ago=None):
        """Put the row in `status`, last written `started_ago` ago (None = now)."""
        self.site.ingest_status = status
        self.site.updated_at = datetime.now(UTC) - (started_ago or timedelta(0))
        self.db.commit()

    def reload(self):
        self.db.refresh(self.site)
        return self.site

    def ingest(self):
        with patch.object(routes, "enqueue_job", new=AsyncMock()) as enqueue:
            response = self.client.post(
                "/api/ingest", params={"website_id": str(self.site.id)}
            )
        return response, enqueue

    # ---- the race ----------------------------------------------------------
    def test_a_second_request_loses_the_claim(self):
        self.set_state("completed")

        first, enqueue_first = self.ingest()
        self.assertEqual(first.status_code, 200, first.text)
        enqueue_first.assert_awaited_once()
        self.assertEqual(self.reload().ingest_status, "processing")

        # The double click, or a genuinely concurrent second request.
        second, enqueue_second = self.ingest()

        self.assertEqual(second.status_code, 409, second.text)
        self.assertIn("already running", second.json()["detail"])
        enqueue_second.assert_not_called()

    def test_losing_the_update_race_refuses_without_enqueuing(self):
        """The row looks claimable, but a concurrent request claimed it first.

        Simulates the losing side of the race directly: the lookup still returns
        the row, the atomic claim reports zero rows updated.
        """
        self.set_state("completed")
        real_db = self.db

        class RaceLostQuery:
            def __init__(self, real):
                self._real = real

            def filter(self, *args, **kwargs):
                self._real = self._real.filter(*args, **kwargs)
                return self

            def first(self):
                return self._real.first()

            def update(self, *args, **kwargs):
                return 0

        class RaceLostDb:
            def __getattr__(self, name):
                return getattr(real_db, name)

            def query(self, *args, **kwargs):
                return RaceLostQuery(real_db.query(*args, **kwargs))

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: RaceLostDb()
        app.dependency_overrides[routes.get_manager_user] = lambda: MagicMock(
            id=uuid4(), company_id=self.company.id
        )

        with patch.object(routes, "enqueue_job", new=AsyncMock()) as enqueue:
            response = TestClient(app).post(
                "/api/ingest", params={"website_id": str(self.site.id)}
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("already running", response.json()["detail"])
        enqueue.assert_not_called()
        # Nothing was claimed, so the row is untouched.
        self.assertEqual(self.reload().ingest_status, "completed")

    def test_the_claim_is_a_single_atomic_update(self):
        """No Python-side status check gates the write any more."""
        self.set_state("completed")

        with patch.object(routes, "enqueue_job", new=AsyncMock()):
            response = self.client.post(
                "/api/ingest", params={"website_id": str(self.site.id)}
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.reload().ingest_status, "processing")
        # The take-over refreshes the timestamp, so an immediate second click is
        # refused again instead of looking stale.
        second, enqueue_second = self.ingest()
        self.assertEqual(second.status_code, 409, second.text)
        enqueue_second.assert_not_called()

    # ---- fresh vs stranded -------------------------------------------------
    def test_a_fresh_processing_row_is_refused(self):
        self.set_state("processing")

        response, enqueue = self.ingest()

        self.assertEqual(response.status_code, 409, response.text)
        enqueue.assert_not_called()

    def test_a_row_stuck_for_hours_can_be_reindexed(self):
        self.set_state("processing", started_ago=timedelta(hours=7))

        response, enqueue = self.ingest()

        self.assertEqual(response.status_code, 200, response.text)
        enqueue.assert_awaited_once()
        self.assertEqual(self.reload().ingest_status, "processing")

    def test_the_threshold_matches_the_worker_recovery_window(self):
        self.set_state(
            "processing", started_ago=STUCK_INGEST_AFTER - timedelta(minutes=5)
        )
        under, enqueue_under = self.ingest()
        self.assertEqual(under.status_code, 409, under.text)
        enqueue_under.assert_not_called()

        self.set_state(
            "processing", started_ago=STUCK_INGEST_AFTER + timedelta(minutes=5)
        )
        over, enqueue_over = self.ingest()
        self.assertEqual(over.status_code, 200, over.text)
        enqueue_over.assert_awaited_once()

    # ---- retryable states --------------------------------------------------
    def test_retry_after_a_finished_or_failed_ingest_is_allowed(self):
        for status in ("completed", "failed", "none", "", None):
            with self.subTest(ingest_status=status):
                self.set_state(status)
                response, enqueue = self.ingest()
                self.assertEqual(response.status_code, 200, response.text)
                enqueue.assert_awaited_once()
                self.assertEqual(self.reload().ingest_status, "processing")


if __name__ == "__main__":
    unittest.main()
