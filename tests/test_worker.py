import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models, worker
from site_gpt.app.db.base import Base
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


TOPIC_TABLES = [
    models.Company.__table__,
    models.Setting.__table__,
    models.TopicClusterRun.__table__,
]


def _topic_session():
    """An in-memory database with just the tables the topics scheduler touches."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TOPIC_TABLES)
    return engine, sessionmaker(bind=engine)()


def _aware(moment):
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class EnqueueDueTopicsTests(unittest.TestCase):
    """The scheduler queues the last complete week, and only for opted-in companies."""

    def setUp(self):
        self.engine, self.db = _topic_session()
        self.company = models.Company(name="Acme")
        self.db.add(self.company)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _setting(self, key, value):
        self.db.add(
            models.Setting(company_id=self.company.id, key=key, value=value)
        )
        self.db.commit()

    def _run(self):
        with patch.object(worker, "SessionLocal", return_value=self.db), patch.object(
            worker, "enqueue_job", new=AsyncMock()
        ) as enqueue:
            queued = asyncio.run(worker.enqueue_due_topics(now=NOW))
        return queued, enqueue

    def _stored_run(self):
        session = sessionmaker(bind=self.engine)()
        try:
            return session.query(models.TopicClusterRun).one()
        finally:
            session.close()

    def test_flag_off_queues_nothing(self):
        queued, enqueue = self._run()

        self.assertEqual(queued, [])
        enqueue.assert_not_awaited()

    def test_flag_on_queues_the_last_complete_week(self):
        self._setting("topic_clustering_enabled", "true")

        queued, enqueue = self._run()

        self.assertEqual(queued, [str(self.company.id)])
        payload = enqueue.await_args.args[0]
        self.assertEqual(payload["type"], "topic_clusters")
        self.assertEqual(payload["company_id"], str(self.company.id))
        # NOW is Saturday 2026-11-14: the week containing it starts Monday the
        # 9th, so the complete window is the 2nd → the 9th.
        self.assertEqual(payload["period_start"], "2026-11-02T00:00:00+00:00")
        self.assertEqual(payload["period_end"], "2026-11-09T00:00:00+00:00")

    def test_a_completed_window_is_not_queued_again(self):
        self._setting("topic_clustering_enabled", "true")
        self.db.add(
            models.TopicClusterRun(
                company_id=self.company.id,
                period_start=datetime(2026, 11, 2, tzinfo=UTC),
                status="completed",
                claimed_at=NOW - timedelta(days=1),
                completed_at=NOW - timedelta(days=1),
            )
        )
        self.db.commit()

        queued, enqueue = self._run()

        self.assertEqual(queued, [])
        enqueue.assert_not_awaited()

    def test_a_dead_claim_is_recovered_and_retried(self):
        self._setting("topic_clustering_enabled", "true")
        self.db.add(
            models.TopicClusterRun(
                company_id=self.company.id,
                period_start=datetime(2026, 11, 2, tzinfo=UTC),
                status="running",
                claimed_at=NOW - timedelta(hours=2),
            )
        )
        self.db.commit()

        queued, enqueue = self._run()

        self.assertEqual(queued, [str(self.company.id)])
        enqueue.assert_awaited_once()
        run = self._stored_run()
        self.assertEqual(run.status, "failed")
        self.assertIn("stale", run.error)


class HandleTopicClustersTests(unittest.TestCase):
    def test_an_incomplete_job_never_opens_a_session(self):
        with patch.object(worker, "SessionLocal") as session:
            asyncio.run(worker.handle_topic_clusters({"type": "topic_clusters"}))

        session.assert_not_called()

    def test_the_job_parses_the_window_and_closes_its_session(self):
        db = MagicMock()
        run_window = MagicMock(return_value={"status": "completed"})
        payload = {
            "type": "topic_clusters",
            "company_id": str(uuid4()),
            "period_start": "2026-11-02T00:00:00+00:00",
            "period_end": "2026-11-09T00:00:00+00:00",
        }

        with patch.object(worker, "SessionLocal", return_value=db), patch.object(
            worker.topics, "run_window", run_window
        ):
            asyncio.run(worker.handle_topic_clusters(payload))

        args, kwargs = run_window.call_args
        self.assertIs(args[0], db)
        self.assertEqual(args[1], UUID(payload["company_id"]))
        self.assertEqual(args[2], datetime(2026, 11, 2, tzinfo=UTC))
        self.assertEqual(args[3], datetime(2026, 11, 9, tzinfo=UTC))
        self.assertIn("stale_before", kwargs)
        db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
