import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from site_gpt.app import worker
from site_gpt.app.worker import (
    STUCK_INGEST_AFTER,
    _is_stuck,
    recover_stuck_ingests,
    requeue_stuck_ingests,
)

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def make_site(status="processing", age_hours=0.0, updated_at="auto"):
    if updated_at == "auto":
        updated_at = NOW - timedelta(hours=age_hours)
    return SimpleNamespace(
        id=uuid4(), ingest_status=status, updated_at=updated_at
    )


def make_db(sites):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = sites
    return db


class IsStuckTests(unittest.TestCase):
    def test_recent_processing_is_not_stuck(self):
        self.assertFalse(_is_stuck(make_site(age_hours=1), now=NOW))

    def test_old_processing_is_stuck(self):
        site = make_site(age_hours=STUCK_INGEST_AFTER.total_seconds() / 3600 + 1)
        self.assertTrue(_is_stuck(site, now=NOW))

    def test_exactly_at_threshold_is_not_stuck(self):
        site = make_site(age_hours=STUCK_INGEST_AFTER.total_seconds() / 3600)
        self.assertFalse(_is_stuck(site, now=NOW))

    def test_processing_without_timestamp_is_stuck(self):
        self.assertTrue(_is_stuck(make_site(updated_at=None), now=NOW))

    def test_naive_timestamp_is_handled(self):
        site = make_site(updated_at=datetime(2026, 11, 14, 1, 0))  # naive
        self.assertTrue(_is_stuck(site, now=NOW))

    def test_other_statuses_are_never_stuck(self):
        for status in ("completed", "failed", "none"):
            with self.subTest(status=status):
                self.assertFalse(_is_stuck(make_site(status=status, age_hours=48), now=NOW))


class RecoverStuckIngestsTests(unittest.TestCase):
    def test_only_orphaned_processing_rows_are_flipped_to_failed(self):
        stuck_a = make_site(age_hours=7)
        stuck_b = make_site(age_hours=24)
        fresh = make_site(age_hours=1)
        done = make_site(status="completed", age_hours=48)
        db = make_db([stuck_a, stuck_b, fresh, done])

        recovered = recover_stuck_ingests(db, now=NOW)

        self.assertEqual(recovered, [str(stuck_a.id), str(stuck_b.id)])
        self.assertEqual(stuck_a.ingest_status, "failed")
        self.assertEqual(stuck_b.ingest_status, "failed")
        self.assertEqual(fresh.ingest_status, "processing")
        self.assertEqual(done.ingest_status, "completed")
        db.commit.assert_called_once()

    def test_nothing_stuck_means_no_commit(self):
        db = make_db([make_site(age_hours=1)])
        self.assertEqual(recover_stuck_ingests(db, now=NOW), [])
        db.commit.assert_not_called()

    def test_empty_table_is_safe(self):
        db = make_db([])
        self.assertEqual(recover_stuck_ingests(db, now=NOW), [])


class RequeueStuckIngestsTests(unittest.TestCase):
    def test_recovered_sites_are_enqueued_and_session_closed(self):
        stuck = make_site(age_hours=7)
        fresh = make_site(age_hours=1)
        db = make_db([stuck, fresh])

        with patch.object(worker, "SessionLocal", return_value=db), patch.object(
            worker, "enqueue_job", new=AsyncMock()
        ) as enqueue:
            recovered = asyncio.run(requeue_stuck_ingests(now=NOW))

        self.assertEqual(recovered, [str(stuck.id)])
        enqueue.assert_awaited_once_with(
            {"type": "ingest", "website_id": str(stuck.id)}
        )
        db.close.assert_called_once()

    def test_no_enqueue_when_nothing_is_stuck(self):
        db = make_db([make_site(age_hours=1)])

        with patch.object(worker, "SessionLocal", return_value=db), patch.object(
            worker, "enqueue_job", new=AsyncMock()
        ) as enqueue:
            recovered = asyncio.run(requeue_stuck_ingests(now=NOW))

        self.assertEqual(recovered, [])
        enqueue.assert_not_awaited()
        db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
