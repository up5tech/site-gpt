"""V4-22: daily sitemap diff scan (F4, D7).

The scan is opt-in per company and must be unable to destroy a knowledge base:
only a fully successful, non-empty sitemap fetch may add pages or retire
vanished ones, removals take their documents (and cascading embeddings) with
them, a processing website is never double-queued, and with the flag off the
loop queues nothing at all.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models, worker
from site_gpt.app.services import sitemap as sitemap_service
from site_gpt.app.db.base import Base


class FakeRedis:
    """`exists`/`set` with the semantics the last-scan key uses."""

    def __init__(self):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def exists(self, key):
        return 1 if key in self.values else 0

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True


class BrokenRedis:
    async def exists(self, key):
        raise ConnectionError("redis is down")

    async def set(self, key, value, ex=None):  # pragma: no cover - still attempted
        raise ConnectionError("redis is down")


class ScanFixture(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Setting.__table__,
                models.Website.__table__,
                models.WebsitePage.__table__,
                models.Document.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        company = models.Company(name="Customer", description="")
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        self.company = company

        self.site = models.Website(
            id=uuid4(),
            url="https://example.com",
            name="Customer",
            site_map_url="https://example.com/sitemap.xml",
            company_id=company.id,
            status="active",
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def set_flag(self, value="true"):
        self.db.add(
            models.Setting(
                key="sitemap_scan_enabled", value=value, company_id=self.company.id
            )
        )
        self.db.commit()

    def add_page(self, url, status="active"):
        page = models.WebsitePage(
            url=url,
            name=url,
            description="",
            website_id=self.site.id,
            status=status,
        )
        self.db.add(page)
        self.db.commit()
        self.db.refresh(page)
        return page

    def add_document(self, url):
        document = models.Document(
            title=url, content="text", url=url, website_id=self.site.id
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def pages(self):
        session = self.Session()
        try:
            return {page.url: page.status for page in session.query(models.WebsitePage).all()}
        finally:
            session.close()

    def documents(self):
        session = self.Session()
        try:
            return sorted(document.url for document in session.query(models.Document).all())
        finally:
            session.close()

    def run_scan(self, sitemap_urls, *, claim=True):
        enqueue = AsyncMock()
        claim_mock = MagicMock(return_value=claim)
        with patch.object(worker, "SessionLocal", self.Session), patch.object(
            worker, "extract_urls_from_sitemap", return_value=list(sitemap_urls)
        ), patch.object(worker, "enqueue_job", enqueue), patch.object(
            worker, "claim_ingest", claim_mock
        ):
            asyncio.run(
                worker.handle_sitemap_scan(
                    {"type": "sitemap_scan", "website_id": str(self.site.id)}
                )
            )
        return enqueue, claim_mock


class SitemapScanFailSafeTests(ScanFixture):
    def test_a_failed_fetch_changes_zero_rows(self):
        self.add_page("https://example.com/old")
        self.add_document("https://example.com/old")

        enqueue, claim = self.run_scan([])

        self.assertEqual(self.pages(), {"https://example.com/old": "active"})
        self.assertEqual(self.documents(), ["https://example.com/old"])
        enqueue.assert_not_called()
        claim.assert_not_called()

    def test_an_empty_sitemap_changes_zero_rows(self):
        self.add_page("https://example.com/a")
        self.add_document("https://example.com/a")

        enqueue, claim = self.run_scan([])

        self.assertEqual(self.pages(), {"https://example.com/a": "active"})
        self.assertEqual(self.documents(), ["https://example.com/a"])
        enqueue.assert_not_called()
        claim.assert_not_called()

    def test_a_raising_fetch_writes_nothing_at_all(self):
        self.add_page("https://example.com/a")
        self.add_document("https://example.com/a")

        with patch.object(worker, "SessionLocal", self.Session), patch.object(
            worker, "extract_urls_from_sitemap", side_effect=RuntimeError("boom")
        ), patch.object(worker, "enqueue_job", new=AsyncMock()) as enqueue:
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    worker.handle_sitemap_scan(
                        {"type": "sitemap_scan", "website_id": str(self.site.id)}
                    )
                )

        # Nothing was retired or deleted before the fetch succeeded.
        self.assertEqual(self.pages(), {"https://example.com/a": "active"})
        self.assertEqual(self.documents(), ["https://example.com/a"])
        enqueue.assert_not_called()

    def test_a_disabled_website_is_never_scanned(self):
        self.site.status = "inactive"
        self.db.commit()
        self.add_page("https://example.com/a")

        enqueue, claim = self.run_scan(["https://example.com/b"])

        self.assertEqual(self.pages(), {"https://example.com/a": "active"})
        enqueue.assert_not_called()
        claim.assert_not_called()

    def test_a_website_without_a_sitemap_url_is_skipped(self):
        self.site.site_map_url = ""
        self.db.commit()

        enqueue, claim = self.run_scan(["https://example.com/b"])

        self.assertEqual(self.pages(), {})
        enqueue.assert_not_called()
        claim.assert_not_called()

    def test_an_incomplete_job_never_opens_a_session(self):
        with patch.object(worker, "SessionLocal") as session:
            asyncio.run(worker.handle_sitemap_scan({"type": "sitemap_scan"}))
        session.assert_not_called()


class SitemapScanDiffTests(ScanFixture):
    def test_a_successful_diff_adds_and_retires_exactly_the_delta(self):
        self.add_page("https://example.com/a")
        self.add_document("https://example.com/a")
        self.add_page("https://example.com/gone")
        self.add_document("https://example.com/gone")

        enqueue, claim = self.run_scan(
            [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ]
        )

        self.assertEqual(
            self.pages(),
            {
                "https://example.com/a": "active",
                "https://example.com/b": "active",
                "https://example.com/c": "active",
                "https://example.com/gone": "inactive",
            },
        )
        # The vanished page's knowledge is gone; the kept page's is untouched.
        self.assertEqual(self.documents(), ["https://example.com/a"])
        claim.assert_called_once()
        enqueue.assert_awaited_once_with(
            {"type": "ingest", "website_id": str(self.site.id)}
        )

    def test_every_document_of_a_retired_url_is_deleted(self):
        # A URL can own more than one document row; `first()` would retire the
        # page while one of them kept feeding the assistant.
        self.add_page("https://example.com/gone")
        self.add_document("https://example.com/gone")
        self.add_document("https://example.com/gone")
        self.add_page("https://example.com/a")
        self.add_document("https://example.com/a")

        enqueue, claim = self.run_scan(["https://example.com/a"])

        self.assertEqual(
            self.pages(),
            {
                "https://example.com/gone": "inactive",
                "https://example.com/a": "active",
            },
        )
        # Both rows of the retired URL are gone; the kept page's is untouched.
        self.assertEqual(self.documents(), ["https://example.com/a"])
        claim.assert_called_once()
        enqueue.assert_awaited_once()

    def test_no_difference_queues_no_ingest(self):
        self.add_page("https://example.com/a")

        enqueue, claim = self.run_scan(["https://example.com/a"])

        self.assertEqual(self.pages(), {"https://example.com/a": "active"})
        claim.assert_not_called()
        enqueue.assert_not_called()

    def test_an_ingest_already_running_is_not_queued_again(self):
        # The claim is the 409 path: a `processing` website loses it, so the scan
        # keeps its page changes but queues no second crawl.
        enqueue, claim = self.run_scan(
            ["https://example.com/b"], claim=False
        )

        self.assertEqual(self.pages(), {"https://example.com/b": "active"})
        claim.assert_called_once()
        enqueue.assert_not_called()

    def test_a_second_scan_of_the_same_sitemap_is_a_no_op(self):
        self.run_scan(["https://example.com/a"])
        enqueue, claim = self.run_scan(["https://example.com/a"])

        self.assertEqual(self.pages(), {"https://example.com/a": "active"})
        claim.assert_not_called()
        enqueue.assert_not_called()

    def test_an_already_retired_page_is_not_counted_twice(self):
        self.add_page("https://example.com/old", status="inactive")
        self.add_document("https://example.com/old")  # leftover, must not requeue

        enqueue, claim = self.run_scan(["https://example.com/new"])

        self.assertEqual(
            self.pages(),
            {
                "https://example.com/old": "inactive",
                "https://example.com/new": "active",
            },
        )
        # It is not "retired again": only the new page changed, so one ingest.
        self.assertEqual(self.documents(), ["https://example.com/old"])
        claim.assert_called_once()
        enqueue.assert_awaited_once()

    def test_the_cap_limits_only_the_pages_a_scan_creates(self):
        self.add_page("https://example.com/a")

        with patch.object(sitemap_service, "SITEMAP_SYNC_MAX_URLS", 1):
            enqueue, claim = self.run_scan(
                [
                    "https://example.com/a",
                    "https://example.com/b",
                    "https://example.com/c",
                ]
            )

        # `a` exists and costs nothing, so the one allowed page is `b`.
        self.assertEqual(
            self.pages(),
            {
                "https://example.com/a": "active",
                "https://example.com/b": "active",
            },
        )
        claim.assert_called_once()
        enqueue.assert_awaited_once()


class EnqueueDueScansTests(ScanFixture):
    def due(self, redis):
        enqueue = AsyncMock()
        with patch.object(worker, "SessionLocal", self.Session), patch.object(
            worker, "enqueue_job", enqueue
        ), patch.object(worker, "redis_client", redis):
            queued = asyncio.run(worker.enqueue_due_sitemap_scans())
        return queued, [call.args[0] for call in enqueue.await_args_list]

    def test_the_flag_off_queues_nothing(self):
        queued, jobs = self.due(FakeRedis())

        self.assertEqual(queued, [])
        self.assertEqual(jobs, [])

    def test_an_explicit_false_flag_queues_nothing(self):
        self.set_flag("false")

        queued, jobs = self.due(FakeRedis())

        self.assertEqual(queued, [])
        self.assertEqual(jobs, [])

    def test_an_opted_in_website_is_queued_once_and_marked_in_redis(self):
        self.set_flag("true")
        redis = FakeRedis()

        queued, jobs = self.due(redis)

        self.assertEqual(queued, [str(self.site.id)])
        self.assertEqual(
            jobs, [{"type": "sitemap_scan", "website_id": str(self.site.id)}]
        )
        key = worker.sitemap_scan_key(self.site.id)
        self.assertIn(key, redis.values)
        self.assertEqual(redis.ttls[key], worker.SITEMAP_SCAN_INTERVAL_SECONDS)

    def test_the_same_website_is_not_queued_twice_inside_one_interval(self):
        self.set_flag("true")
        redis = FakeRedis()

        first, first_jobs = self.due(redis)
        second, second_jobs = self.due(redis)

        self.assertEqual(first, [str(self.site.id)])
        self.assertEqual(len(first_jobs), 1)
        self.assertEqual(second, [])
        self.assertEqual(second_jobs, [])

    def test_an_inactive_website_is_not_queued(self):
        self.set_flag("true")
        self.site.status = "inactive"
        self.db.commit()

        queued, jobs = self.due(FakeRedis())

        self.assertEqual(queued, [])
        self.assertEqual(jobs, [])

    def test_a_website_without_a_sitemap_url_is_not_queued(self):
        self.set_flag("true")
        self.site.site_map_url = ""
        self.db.commit()

        queued, jobs = self.due(FakeRedis())

        self.assertEqual(queued, [])
        self.assertEqual(jobs, [])

    def test_redis_outage_still_queues_the_scan(self):
        # Best-effort bookkeeping: a lost key costs one extra scan, never a
        # missed one, and an outage must not raise out of the loop.
        self.set_flag("true")

        queued, jobs = self.due(BrokenRedis())

        self.assertEqual(queued, [str(self.site.id)])
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
