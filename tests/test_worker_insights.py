"""Conversation-insight worker tests (V4-42).

The opt-in gate, the cadence and the handler are what make F2 safe to run: an
unopted deployment queues no job, writes no row and spends no provider call; the
loop wakes on `INSIGHT_INTERVAL_SECONDS` and tolerates a Redis hiccup; and a
failed run leaves the previous classification readable, so an outage degrades the
labels to the last known ones instead of erasing them (the topics guarantee). The
chat model is stubbed, but the scheduler, the handler and the database are real.
"""

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
from site_gpt.app.services import insights

# Every seeded conversation is settled well past the default 60-minute delay.
SETTLED = datetime.now(UTC) - timedelta(hours=2)

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.Setting.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
]


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    return engine, sessionmaker(bind=engine)()


def _company(db, name="Acme"):
    company = models.Company(name=name)
    db.add(company)
    db.commit()
    return company


def _website(db, company, name="site"):
    website = models.Website(
        company_id=company.id, name=name, url=f"https://{name}.test", site_map_url=""
    )
    db.add(website)
    db.commit()
    return website


def _settled(db, website, session_id="s1"):
    """One settled conversation: a visitor question and the bot's answer."""
    conversation = models.Conversation(
        website_id=website.id, session_id=session_id, last_message_at=SETTLED
    )
    db.add(conversation)
    db.add(
        models.ChatMessage(
            website_id=website.id,
            session_id=session_id,
            role="user",
            message="How much does it cost?",
            created_at=SETTLED - timedelta(minutes=2),
            updated_at=SETTLED - timedelta(minutes=2),
        )
    )
    db.add(
        models.ChatMessage(
            website_id=website.id,
            session_id=session_id,
            role="assistant",
            message="Plans start at $10.",
            created_at=SETTLED - timedelta(minutes=1),
            updated_at=SETTLED - timedelta(minutes=1),
        )
    )
    db.commit()
    return conversation


def _result(sentiment="positive", resolution="resolved", summary="Answered."):
    return json.dumps(
        [{"sentiment": sentiment, "resolution": resolution, "summary": summary}]
    )


class _FakeLLM:
    def __init__(self, reply=_result(), error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.reply)


class EnqueueDueInsightsTests(unittest.TestCase):
    """The scheduler queues opted-in companies only."""

    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self._website = _website(self.db, self.company)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _enable(self, company, value="true"):
        self.db.add(
            models.Setting(
                company_id=company.id,
                key="conversation_insights_enabled",
                value=value,
            )
        )
        self.db.commit()

    def _run(self):
        with patch.object(worker, "SessionLocal", return_value=self.db), patch.object(
            worker, "enqueue_job", new=AsyncMock()
        ) as enqueue:
            queued = asyncio.run(worker.enqueue_due_insights())
        return queued, enqueue

    def test_flag_off_queues_nothing(self):
        queued, enqueue = self._run()

        self.assertEqual(queued, [])
        enqueue.assert_not_awaited()

    def test_an_explicit_false_queues_nothing(self):
        self._enable(self.company, "false")

        queued, enqueue = self._run()

        self.assertEqual(queued, [])
        enqueue.assert_not_awaited()

    def test_flag_on_queues_one_run_for_the_company(self):
        self._enable(self.company)

        queued, enqueue = self._run()

        self.assertEqual(queued, [str(self.company.id)])
        enqueue.assert_awaited_once_with(
            {"type": "insights", "company_id": str(self.company.id)}
        )

    def test_only_the_opted_in_company_is_queued(self):
        other = _company(self.db, "Other")
        _website(self.db, other, "theirs")
        self._enable(other)

        queued, enqueue = self._run()

        self.assertEqual(queued, [str(other.id)])
        self.assertEqual(
            [call.args[0]["company_id"] for call in enqueue.await_args_list],
            [str(other.id)],
        )


class HandleInsightsTests(unittest.TestCase):
    """The job runs the bounded service and owns its session."""

    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.website = _website(self.db, self.company)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _enable(self, value="true"):
        self.db.add(
            models.Setting(
                company_id=self.company.id,
                key="conversation_insights_enabled",
                value=value,
            )
        )
        self.db.commit()

    def _run(self, llm=None):
        llm = llm or _FakeLLM()
        with patch.object(worker, "SessionLocal", return_value=self.db), patch.object(
            insights, "get_llm", lambda **_: llm
        ):
            asyncio.run(
                worker.handle_insights(
                    {"type": "insights", "company_id": str(self.company.id)}
                )
            )
        return llm

    def _rows(self):
        return self.db.query(models.ConversationInsight).all()

    def test_an_incomplete_job_never_opens_a_session(self):
        with patch.object(worker, "SessionLocal") as session:
            asyncio.run(worker.handle_insights({"type": "insights"}))

        session.assert_not_called()

    def test_the_job_parses_the_company_and_closes_its_session(self):
        db = MagicMock()
        run = MagicMock(return_value={"status": "skipped"})

        with patch.object(worker, "SessionLocal", return_value=db), patch.object(
            worker.insights, "run_for_company", run
        ):
            asyncio.run(
                worker.handle_insights(
                    {"type": "insights", "company_id": str(uuid4())}
                )
            )

        args, _ = run.call_args
        self.assertIs(args[0], db)
        self.assertEqual(args[1], UUID(str(args[1])))
        db.close.assert_called_once()

    def test_a_flag_off_job_writes_nothing_and_calls_no_model(self):
        _settled(self.db, self.website)

        def never(**kwargs):
            raise AssertionError("the model must not be called")

        with patch.object(worker, "SessionLocal", return_value=self.db), patch.object(
            insights, "get_llm", never
        ):
            asyncio.run(
                worker.handle_insights(
                    {"type": "insights", "company_id": str(self.company.id)}
                )
            )

        self.assertEqual(self._rows(), [])

    def test_a_successful_run_stores_the_classification(self):
        self._enable()
        _settled(self.db, self.website)

        llm = self._run()

        self.assertEqual(len(llm.calls), 1)
        row = self._rows()[0]
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.sentiment, "positive")
        self.assertEqual(row.resolution, "resolved")
        self.assertEqual(row.summary, "Answered.")
        self.assertTrue(row.model)

    def test_a_failed_run_keeps_the_previous_classification(self):
        self._enable()
        conversation = _settled(self.db, self.website)
        self.db.add(
            models.ConversationInsight(
                conversation_id=conversation.id,
                status="completed",
                sentiment="negative",
                resolution="unresolved",
                summary="Visitor could not get an answer.",
                model="openai/gpt-4.1-mini",
            )
        )
        self.db.commit()
        # The row predates the conversation's last message, so the run refreshes it.
        self.db.query(models.ConversationInsight).update(
            {"updated_at": SETTLED - timedelta(hours=1)}, synchronize_session=False
        )
        self.db.commit()

        self._run(llm=_FakeLLM(error=RuntimeError("provider down")))

        row = self._rows()[0]
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.sentiment, "negative")
        self.assertEqual(row.resolution, "unresolved")
        self.assertEqual(row.summary, "Visitor could not get an answer.")
        self.assertEqual(len(self._rows()), 1)


class InsightLoopTests(unittest.TestCase):
    """The loop sleeps the configured interval and survives a failed enqueue."""

    def _drive(self, ticks, enqueue):
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) > ticks:
                raise asyncio.CancelledError

        with patch.object(worker, "INSIGHT_INTERVAL_SECONDS", 7), patch.object(
            worker.asyncio, "sleep", fake_sleep
        ), patch.object(worker, "enqueue_due_insights", enqueue):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(worker.insight_loop())
        return sleeps

    def test_the_loop_wakes_on_the_interval_and_queues_each_tick(self):
        enqueue = AsyncMock()

        sleeps = self._drive(2, enqueue)

        self.assertEqual(sleeps, [7, 7, 7])
        self.assertEqual(enqueue.await_count, 2)

    def test_a_failing_enqueue_is_logged_and_the_loop_keeps_going(self):
        calls = []

        async def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("redis down")

        sleeps = self._drive(2, flaky)

        # The first tick raised and was swallowed; the second ran normally.
        self.assertEqual(sleeps, [7, 7, 7])
        self.assertEqual(calls, [1, 1])


if __name__ == "__main__":
    unittest.main()
