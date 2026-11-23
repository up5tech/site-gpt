import asyncio
import json
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


RETENTION_TABLES = [
    models.Company.__table__,
    models.Setting.__table__,
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


DIGEST_TABLES = [
    models.Company.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Contact.__table__,
    models.ChatFeedback.__table__,
    models.Setting.__table__,
    models.DigestLog.__table__,
    models.TopicCluster.__table__,
    models.TopicClusterRun.__table__,
]

# Saturday 12:00, so `digest_hour = 12` is due and the last complete digest week
# is the 2nd → the 9th (the week containing NOW started on the 9th).
DIGEST_NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
DIGEST_WINDOW = (
    datetime(2026, 11, 2, tzinfo=UTC),
    datetime(2026, 11, 9, tzinfo=UTC),
)


def _digest_session(engine):
    return sessionmaker(bind=engine)()


class DigestScheduleTests(unittest.TestCase):
    """The digest reports the week the topic worker clusters, not the live one."""

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=DIGEST_TABLES)
        self.sessions = []
        db = self._session()
        self.company = models.Company(name="Acme")
        db.add(self.company)
        db.commit()
        for key, value in (
            ("digest_enabled", "true"),
            ("digest_hour", "12"),
            ("digest_recipients", "owner@example.com"),
        ):
            self._setting(key, value)

    def _session(self):
        session = _digest_session(self.engine)
        self.sessions.append(session)
        return session

    def _setting(self, key, value):
        session = self._session()
        session.add(
            models.Setting(company_id=self.company.id, key=key, value=value)
        )
        session.commit()

    def tearDown(self):
        for session in self.sessions:
            session.close()
        self.engine.dispose()

    def _enqueue(self):
        enqueue = AsyncMock()
        with patch.object(worker, "SessionLocal", self._session), patch.object(
            worker, "enqueue_job", enqueue
        ):
            queued = asyncio.run(worker.enqueue_due_digests(now=DIGEST_NOW))
        return queued, [call.args[0] for call in enqueue.await_args_list]

    def test_the_period_is_the_last_complete_digest_week(self):
        queued, payloads = self._enqueue()

        self.assertEqual(queued, [str(self.company.id)])
        self.assertEqual([payload["type"] for payload in payloads], ["digest"])
        self.assertEqual(payloads[0]["period_start"], DIGEST_WINDOW[0].isoformat())
        self.assertEqual(payloads[0]["period_end"], DIGEST_WINDOW[1].isoformat())

    def test_the_week_is_queued_before_the_digest_that_reports_it(self):
        self._setting("topic_clustering_enabled", "true")

        _, payloads = self._enqueue()

        # FIFO queue: the clusters are built before the digest reads them.
        self.assertEqual(
            [payload["type"] for payload in payloads], ["topic_clusters", "digest"]
        )
        self.assertEqual(payloads[0]["period_start"], payloads[1]["period_start"])
        self.assertEqual(payloads[0]["period_end"], payloads[1]["period_end"])


class WorkerToDigestTests(unittest.TestCase):
    """End to end: the week the topic job builds is the week the digest emails."""

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=DIGEST_TABLES)
        self.sessions = []
        db = self._session()
        company = models.Company(name="Acme")
        db.add(company)
        db.commit()
        website = models.Website(
            company_id=company.id,
            name="site",
            url="https://site.test",
            site_map_url="",
        )
        db.add(website)
        db.commit()
        asked_at = DIGEST_WINDOW[0] + timedelta(days=1)
        for text in ("What is the price?", "Is the pricing monthly?"):
            db.add(
                models.ChatMessage(
                    website_id=website.id,
                    session_id="s1",
                    role="user",
                    message=text,
                    created_at=asked_at,
                    updated_at=asked_at,
                )
            )
        for key, value in (
            ("digest_enabled", "true"),
            ("digest_hour", "12"),
            ("digest_recipients", "owner@example.com"),
            ("topic_clustering_enabled", "true"),
        ):
            db.add(models.Setting(company_id=company.id, key=key, value=value))
        db.commit()

    def _session(self):
        session = _digest_session(self.engine)
        self.sessions.append(session)
        return session

    def tearDown(self):
        for session in self.sessions:
            session.close()
        self.engine.dispose()

    def test_the_digest_email_carries_the_clustered_week(self):
        email = AsyncMock()
        enqueue = AsyncMock()
        naming = SimpleNamespace(
            content=json.dumps(
                [{"label": "Pricing", "summary": "Visitors ask what it costs."}]
            )
        )

        with patch.object(worker, "SessionLocal", self._session), patch.object(
            worker, "enqueue_job", enqueue
        ), patch.object(
            worker.topics,
            "embed_texts",
            lambda texts: [[1.0] + [0.0] * 1535 for _ in texts],
        ), patch.object(
            worker.topics,
            "get_llm",
            lambda **_: SimpleNamespace(invoke=lambda messages: naming),
        ), patch.object(
            worker.digest, "send_email_async", email
        ), patch.object(
            worker.digest, "emit_event_async", AsyncMock()
        ):
            asyncio.run(worker.enqueue_due_topics(now=DIGEST_NOW))
            asyncio.run(worker.handle_topic_clusters(enqueue.await_args.args[0]))
            asyncio.run(worker.enqueue_due_digests(now=DIGEST_NOW))
            digest_payload = enqueue.await_args.args[0]
            asyncio.run(worker.handle_digest(digest_payload))

        # The completed run needs no second topic job, and both jobs name one week.
        self.assertEqual(
            [call.args[0]["type"] for call in enqueue.await_args_list],
            ["topic_clusters", "digest"],
        )
        self.assertEqual(digest_payload["period_start"], DIGEST_WINDOW[0].isoformat())
        self.assertEqual(digest_payload["period_end"], DIGEST_WINDOW[1].isoformat())

        recipient, _, body = email.await_args.args
        self.assertEqual(recipient, "owner@example.com")
        self.assertIn("Topic groups", body)
        self.assertIn("Pricing", body)
        self.assertIn("Named from 2 of 2 visitor questions", body)


class BackgroundLoopRetentionTests(unittest.TestCase):
    """The scheduler loops must stay referenced for as long as they run.

    asyncio keeps only weak references to tasks, and `worker()` used to create
    the loops without storing them, so one could be garbage-collected mid-run
    and stop silently.
    """

    def _start_then_cancel(self):
        async def scenario():
            tasks = worker.start_background_loops()
            self.assertTrue(all(task in worker._background_tasks for task in tasks))
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for _ in range(3):
                await asyncio.sleep(0)
            return tasks

        return asyncio.run(scenario())

    def test_every_scheduler_task_is_held_until_it_finishes(self):
        tasks = self._start_then_cancel()

        # the six always-on loops; the digest loop is opt-in
        self.assertEqual(len(tasks), 6)
        self.assertEqual(worker._background_tasks, set())

    def test_the_digest_loop_is_added_when_enabled(self):
        with patch.object(worker, "DIGEST_ENABLED", True):
            tasks = self._start_then_cancel()

        self.assertEqual(len(tasks), 7)

    def test_the_worker_starts_the_kept_loops(self):
        # `worker()` never returns on its own; cancelling the queue read ends it
        # after startup, leaving the loops it created behind for inspection.
        async def scenario():
            with patch.object(worker, "requeue_stuck_ingests", new=AsyncMock()):
                with patch.object(
                    worker.redis_client,
                    "brpop",
                    new=AsyncMock(side_effect=asyncio.CancelledError),
                ):
                    with self.assertRaises(asyncio.CancelledError):
                        await worker.worker()
            tasks = list(worker._background_tasks)
            self.assertEqual(len(tasks), 6)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for _ in range(3):
                await asyncio.sleep(0)

        asyncio.run(scenario())
        self.assertEqual(worker._background_tasks, set())


class EnqueueDueRetentionTests(unittest.TestCase):
    """The daily scheduler must actually push one job per company with a policy.

    Regression: `enqueue_due_retention` called the async `enqueue_job` without
    awaiting it, so the loop logged a queue it never wrote and no purge ever ran.
    """

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=RETENTION_TABLES)
        self.sessions = []
        db = self._session()
        self.company = models.Company(name="Acme")
        db.add(self.company)
        db.commit()

    def _session(self):
        session = sessionmaker(bind=self.engine)()
        self.sessions.append(session)
        return session

    def tearDown(self):
        for session in self.sessions:
            session.close()
        self.engine.dispose()

    def _policy(self, days):
        session = self._session()
        session.add(
            models.Setting(
                company_id=self.company.id, key="retention_days", value=days
            )
        )
        session.commit()

    def _run(self):
        enqueue = AsyncMock()
        with patch.object(worker, "SessionLocal", self._session), patch.object(
            worker, "enqueue_job", enqueue
        ):
            queued = asyncio.run(worker.enqueue_due_retention())
        return queued, enqueue

    def test_a_company_with_a_policy_is_enqueued(self):
        self._policy("30")

        queued, enqueue = self._run()

        self.assertEqual(queued, [str(self.company.id)])
        enqueue.assert_awaited_once()
        self.assertEqual(
            enqueue.await_args.args[0],
            {"type": "retention", "company_id": str(self.company.id)},
        )

    def test_a_company_without_a_policy_queues_nothing(self):
        self._policy("0")

        queued, enqueue = self._run()

        self.assertEqual(queued, [])
        enqueue.assert_not_awaited()


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
