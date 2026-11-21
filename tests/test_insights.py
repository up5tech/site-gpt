"""Per-conversation insight service tests (V4-41).

The properties D3 promises: the unique row is the claim (one winner, stale
takeover, refresh only when the conversation grows), the run is bounded by the
configured caps rather than by the company's size, enums are clamped and the
summary truncated, a provider or parse failure marks its batch `failed` and is
retried on the next tick without erasing the previous labels, and no transcript
text is persisted beyond those derived fields. The chat model is stubbed — a test
must not spend a provider call — but the queries, the batching, the validation and
the inserts are the real code, against a real SQLite database.
"""

import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.db.base import Base
from site_gpt.app.services import insights

NOW = datetime.now(UTC)

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.Setting.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
]

REMEMBER = "TOPSECRET-4917"


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


def _conversation(db, website, session_id="s1", last_message_at=None):
    row = models.Conversation(
        website_id=website.id,
        session_id=session_id,
        last_message_at=last_message_at or (NOW - timedelta(hours=2)),
    )
    db.add(row)
    db.commit()
    return row


def _message(db, website, text, created, session_id="s1", role="user"):
    row = models.ChatMessage(
        website_id=website.id,
        session_id=session_id,
        role=role,
        message=text,
        created_at=created,
        updated_at=created,
    )
    db.add(row)
    db.commit()
    return row


def _settled(
    db,
    website,
    session_id="s1",
    question="How much does it cost?",
    answer="Plans start at $10.",
    last_message_at=None,
):
    """One settled conversation: a visitor question and the bot's answer."""
    conversation = _conversation(db, website, session_id, last_message_at)
    _message(
        db, website, question, NOW - timedelta(hours=2, minutes=5), session_id=session_id
    )
    _message(
        db,
        website,
        answer,
        NOW - timedelta(hours=2, minutes=4),
        session_id=session_id,
        role="assistant",
    )
    return conversation


def _results(count, sentiment="positive", resolution="resolved", summary=None):
    summary = summary or "Visitor asked about pricing and the answer satisfied them."
    return json.dumps(
        [
            {
                "sentiment": sentiment,
                "resolution": resolution,
                "summary": summary,
            }
            for _ in range(count)
        ]
    )


def _blocks(human: str) -> int:
    """How many conversations a prompt carried (`Conversation 1:` …)."""
    return human.count("Conversation ")


def _default_reply(human, index):
    return _results(_blocks(human))


class _FakeLLM:
    """Stands in for `get_llm()`: records the prompt, returns or raises."""

    def __init__(self, reply=_default_reply, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        index = len(self.calls) - 1
        failure = (
            self.error(messages[1].content, index)
            if callable(self.error)
            else self.error
        )
        if failure is not None:
            raise failure
        content = (
            self.reply(messages[1].content, index)
            if callable(self.reply)
            else self.reply
        )
        return SimpleNamespace(content=content)


class _InsightCase(unittest.TestCase):
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

    def _run(self, llm=None, **overrides):
        llm = llm or _FakeLLM()
        started = [patch.object(insights, name, value) for name, value in overrides.items()]
        for item in started:
            item.start()
        try:
            with patch.object(insights, "get_llm", lambda **_: llm):
                result = insights.run_for_company(self.db, self.company.id, now=NOW)
        finally:
            for item in started:
                item.stop()
        return llm, result

    def _rows(self):
        return self.db.query(models.ConversationInsight).all()


class ClaimTests(_InsightCase):
    def test_the_insert_is_the_claim(self):
        conversation = _settled(self.db, self.website)

        row = insights.claim(self.db, conversation.id)

        self.assertIsNotNone(row)
        self.assertEqual(row.status, "processing")
        self.assertIsNotNone(row.claimed_at)
        self.assertEqual(len(self._rows()), 1)

    def test_one_row_per_conversation_is_a_unique_constraint(self):
        conversation = _settled(self.db, self.website)
        insights.claim(self.db, conversation.id)

        self.db.add(
            models.ConversationInsight(
                conversation_id=conversation.id, status="processing"
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        self.assertEqual(len(self._rows()), 1)

    def test_a_lost_insert_race_rolls_back_and_returns_none(self):
        # The other run committed its claim between our SELECT and our INSERT, so
        # our insert hits the unique constraint: the winner keeps the work and we
        # write nothing.
        conversation = _settled(self.db, self.website)

        with patch.object(
            self.db,
            "commit",
            side_effect=IntegrityError(
                "INSERT INTO conversation_insights", {}, Exception("duplicate key")
            ),
        ):
            self.assertIsNone(insights.claim(self.db, conversation.id))

        self.assertEqual(self._rows(), [])
        # The winner's row is the only one, and it can be claimed by nobody else.
        winner = insights.claim(self.db, conversation.id)
        self.assertIsNotNone(winner)
        self.assertIsNone(insights.claim(self.db, conversation.id))
        self.assertEqual(len(self._rows()), 1)

    def test_a_live_claim_is_not_taken_over(self):
        conversation = _settled(self.db, self.website)
        insights.claim(self.db, conversation.id)

        again = insights.claim(
            self.db, conversation.id, stale_before=NOW - timedelta(minutes=5)
        )

        self.assertIsNone(again)

    def test_a_stale_claim_is_taken_over_in_place(self):
        conversation = _settled(self.db, self.website)
        row = insights.claim(self.db, conversation.id)
        self.db.query(models.ConversationInsight).update(
            {"claimed_at": NOW - timedelta(hours=2)}, synchronize_session=False
        )
        self.db.commit()

        taken = insights.claim(self.db, conversation.id, stale_before=NOW)

        self.assertIsNotNone(taken)
        self.assertEqual(taken.id, row.id)
        self.assertEqual(taken.status, "processing")
        self.assertEqual(len(self._rows()), 1)

    def test_a_completed_row_is_kept_until_the_conversation_grows(self):
        conversation = _settled(self.db, self.website)
        row = insights.claim(self.db, conversation.id)
        row.status = "completed"
        row.sentiment = "positive"
        self.db.commit()

        self.assertIsNone(insights.claim(self.db, conversation.id))

        # A newer message than the row is what makes it refresh-due (D3).
        self.db.query(models.ConversationInsight).update(
            {"updated_at": NOW - timedelta(hours=1)}, synchronize_session=False
        )
        self.db.query(models.Conversation).update(
            {"last_message_at": NOW - timedelta(minutes=10)},
            synchronize_session=False,
        )
        self.db.commit()

        again = insights.claim(self.db, conversation.id)

        self.assertIsNotNone(again)
        self.assertEqual(again.id, row.id)
        self.assertEqual(again.status, "processing")
        # The previous label survives the takeover until the batch writes a new one.
        self.assertEqual(again.sentiment, "positive")

    def test_a_missing_conversation_is_never_claimed(self):
        self.assertIsNone(insights.claim(self.db, uuid.uuid4()))


class RunTests(_InsightCase):
    def test_a_flag_off_company_writes_nothing_and_calls_no_model(self):
        _settled(self.db, self.website)

        def never(**kwargs):
            raise AssertionError("the model must not be called")

        with patch.object(insights, "get_llm", never):
            result = insights.run_for_company(self.db, self.company.id, now=NOW)

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["claimed"], 0)
        self.assertEqual(result["calls"], 0)
        self.assertEqual(self._rows(), [])

    def test_a_settled_conversation_is_classified_and_only_derived_values_stored(self):
        self._enable()
        _settled(
            self.db,
            self.website,
            question=f"How much does it cost? {REMEMBER}",
            answer="Plans start at $10.",
        )

        llm, result = self._run()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(len(llm.calls), 1)
        system, human = llm.calls[0]
        self.assertEqual(system.content, insights.CLASSIFY_SYSTEM_PROMPT)
        self.assertIn("visitor: How much does it cost?", human.content)
        self.assertIn("assistant: Plans start at $10.", human.content)

        row = self._rows()[0]
        self.assertEqual(row.status, "completed")
        self.assertEqual(row.sentiment, "positive")
        self.assertEqual(row.resolution, "resolved")
        self.assertLessEqual(len(row.summary), insights.MAX_SUMMARY_LENGTH)
        self.assertTrue(row.model)
        # Nothing from the transcript is stored: only the bounded derived fields.
        for field in (row.sentiment, row.resolution, row.summary, row.model):
            self.assertNotIn(REMEMBER, field or "")

    def test_a_second_run_does_no_work_and_spends_nothing(self):
        self._enable()
        _settled(self.db, self.website)
        self._run()

        llm, result = self._run()

        self.assertEqual(result["eligible"], 0)
        self.assertEqual(result["claimed"], 0)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(llm.calls, [])
        self.assertEqual(len(self._rows()), 1)

    def test_a_new_message_makes_the_conversation_refresh_due(self):
        self._enable()
        conversation = _settled(self.db, self.website)
        self._run()
        first = self._rows()[0]
        self.assertEqual(first.sentiment, "positive")

        # Newer than the row, and still settled (older than the settle delay).
        _message(
            self.db,
            self.website,
            "Actually this still does not work.",
            NOW - timedelta(minutes=90),
        )
        self.db.query(models.Conversation).filter(
            models.Conversation.id == conversation.id
        ).update({"last_message_at": NOW - timedelta(minutes=90)})
        self.db.query(models.ConversationInsight).update(
            {"updated_at": NOW - timedelta(hours=3)}, synchronize_session=False
        )
        self.db.commit()

        _, result = self._run(llm=_FakeLLM(reply=lambda human, _: _results(
            _blocks(human), sentiment="frustrated", resolution="unresolved"
        )))

        self.assertEqual(result["claimed"], 1)
        refreshed = self._rows()[0]
        self.assertEqual(refreshed.id, first.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.sentiment, "frustrated")
        self.assertEqual(refreshed.resolution, "unresolved")
        self.assertEqual(len(self._rows()), 1)

    def test_unsettled_and_visitor_less_conversations_are_skipped(self):
        self._enable()
        # Still live: one minute of silence is not settled.
        live = _conversation(self.db, self.website, "live", NOW - timedelta(minutes=1))
        _message(self.db, self.website, "Hello?", NOW - timedelta(minutes=1), "live")
        # Only the bot wrote: there is no visitor question to classify.
        quiet = _conversation(self.db, self.website, "quiet")
        _message(
            self.db,
            self.website,
            "Welcome!",
            NOW - timedelta(hours=2, minutes=3),
            "quiet",
            role="assistant",
        )
        # A blank visitor message is not a question either.
        blank = _conversation(self.db, self.website, "blank")
        _message(self.db, self.website, "   ", NOW - timedelta(hours=2), "blank")

        llm, result = self._run()

        self.assertEqual(result["eligible"], 0)
        self.assertEqual(result["claimed"], 0)
        self.assertEqual(llm.calls, [])
        self.assertEqual(self._rows(), [])
        self.assertEqual(len({live.id, quiet.id, blank.id}), 3)

    def test_another_companys_conversations_never_enter_a_run(self):
        self._enable()
        other = _company(self.db, "Other")
        other_site = _website(self.db, other, "theirs")
        _settled(
            self.db,
            other_site,
            question=f"SECRET other tenant question {REMEMBER}",
        )
        _settled(self.db, self.website)

        llm, result = self._run()

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(len(llm.calls), 1)
        self.assertNotIn("SECRET other tenant", llm.calls[0][1].content)
        self.assertNotIn(REMEMBER, llm.calls[0][1].content)
        self.assertEqual(len(self._rows()), 1)


class BoundTests(_InsightCase):
    def test_the_conversation_cap_bounds_a_run_oldest_first(self):
        self._enable()
        conversations = [
            _settled(
                self.db,
                self.website,
                session_id=f"s{index}",
                last_message_at=NOW - timedelta(hours=5 - index),
            )
            for index in range(4)
        ]

        llm, result = self._run(INSIGHT_MAX_CONVERSATIONS=2)

        self.assertEqual(result["eligible"], 2)
        self.assertEqual(result["claimed"], 2)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(
            {row.conversation_id for row in self._rows()},
            {conversations[0].id, conversations[1].id},
        )

    def test_one_call_per_batch_of_ten_and_no_embedding_call(self):
        self._enable()
        for index in range(25):
            _settled(
                self.db,
                self.website,
                session_id=f"s{index}",
                last_message_at=NOW - timedelta(hours=2, minutes=index),
            )

        llm, result = self._run(INSIGHT_MAX_CONVERSATIONS=25, INSIGHT_BATCH_SIZE=10)

        self.assertEqual(result["claimed"], 25)
        self.assertEqual(result["completed"], 25)
        self.assertEqual(len(llm.calls), 3)
        self.assertEqual(result["calls"], 3)
        self.assertEqual([_blocks(call[1].content) for call in llm.calls], [10, 10, 5])
        # The plan's ceiling: ⌈50 / 10⌉ calls for the default caps, zero embeddings.
        self.assertLessEqual(
            -(-insights.INSIGHT_MAX_CONVERSATIONS // insights.INSIGHT_BATCH_SIZE), 5
        )

    def test_the_transcript_is_the_last_twenty_messages_in_characters(self):
        conversation = _conversation(self.db, self.website)
        for index in range(30):
            _message(
                self.db,
                self.website,
                f"message-{index} " + "x" * 260,
                NOW - timedelta(hours=3) + timedelta(minutes=index),
            )

        with patch.object(insights, "INSIGHT_TRANSCRIPT_CHARS", 20000):
            whole = insights.transcript(self.db, conversation)
        self.assertEqual(whole.count("\n") + 1, insights.MAX_TRANSCRIPT_MESSAGES)
        self.assertNotIn("message-9 ", whole)
        self.assertIn("message-29 ", whole)

        text = insights.transcript(self.db, conversation)
        self.assertEqual(len(text), insights.INSIGHT_TRANSCRIPT_CHARS)
        self.assertNotIn("message-9 ", text)
        self.assertIn("message-29 ", text)

        # The cut keeps the end of the conversation, not its beginning.
        with patch.object(insights, "INSIGHT_TRANSCRIPT_CHARS", 40):
            tail = insights.transcript(self.db, conversation)
        self.assertEqual(len(tail), 40)
        self.assertTrue(tail.endswith("x" * 40))

    def test_blank_messages_do_not_consume_the_transcript(self):
        conversation = _conversation(self.db, self.website)
        _message(self.db, self.website, "   ", NOW - timedelta(hours=2, minutes=1))
        _message(self.db, self.website, "visible question", NOW - timedelta(hours=2))

        text = insights.transcript(self.db, conversation)

        self.assertEqual(text, "visitor: visible question")


class FailureTests(_InsightCase):
    def test_a_provider_failure_marks_failed_and_the_next_tick_retries(self):
        self._enable()
        _settled(self.db, self.website)

        llm, result = self._run(
            llm=_FakeLLM(error=RuntimeError("provider down"))
        )

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self._rows()[0].status, "failed")

        _, retried = self._run()

        self.assertEqual(retried["claimed"], 1)
        self.assertEqual(retried["completed"], 1)
        self.assertEqual(self._rows()[0].status, "completed")
        self.assertEqual(len(self._rows()), 1)

    def test_a_failed_refresh_keeps_the_previous_classification(self):
        self._enable()
        conversation = _settled(self.db, self.website)
        self._run()
        first = self._rows()[0]
        self.assertEqual(first.sentiment, "positive")

        _message(self.db, self.website, "It broke again.", NOW - timedelta(minutes=90))
        self.db.query(models.Conversation).filter(
            models.Conversation.id == conversation.id
        ).update({"last_message_at": NOW - timedelta(minutes=90)})
        self.db.query(models.ConversationInsight).update(
            {"updated_at": NOW - timedelta(hours=3)}, synchronize_session=False
        )
        self.db.commit()

        _, result = self._run(llm=_FakeLLM(error=RuntimeError("provider down")))

        self.assertEqual(result["failed"], 1)
        row = self._rows()[0]
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.sentiment, "positive")
        self.assertEqual(row.summary, first.summary)

    def test_a_malformed_reply_fails_the_batch_and_never_raises(self):
        self._enable()
        _settled(self.db, self.website)

        _, result = self._run(llm=_FakeLLM(reply="Sorry, I cannot help with that."))

        self.assertEqual(result["failed"], 1)
        self.assertEqual(self._rows()[0].status, "failed")
        self.assertIsNone(self._rows()[0].sentiment)

    def test_a_bad_batch_does_not_stop_the_next_one(self):
        self._enable()
        for index in range(2):
            _settled(self.db, self.website, session_id=f"s{index}")

        def failing_first_call(human, index):
            return RuntimeError("provider down") if index == 0 else None

        llm = _FakeLLM(error=failing_first_call)
        _, result = self._run(llm=llm, INSIGHT_BATCH_SIZE=1)

        self.assertEqual(result["claimed"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(llm.calls), 2)
        statuses = sorted(row.status for row in self._rows())
        self.assertEqual(statuses, ["completed", "failed"])

    def test_enums_are_clamped_and_the_summary_is_truncated(self):
        self._enable()
        _settled(self.db, self.website)
        reply = json.dumps(
            [
                {
                    "sentiment": "ANGRY",
                    "resolution": "maybe later",
                    "summary": "line\nbreak " * 60,
                }
            ]
        )

        _, result = self._run(llm=_FakeLLM(reply=reply))

        self.assertEqual(result["completed"], 1)
        row = self._rows()[0]
        self.assertEqual(row.sentiment, insights.DEFAULT_SENTIMENT)
        self.assertEqual(row.resolution, insights.DEFAULT_RESOLUTION)
        self.assertNotIn("\n", row.summary)
        self.assertLessEqual(len(row.summary), insights.MAX_SUMMARY_LENGTH)

    def test_an_unusable_entry_fails_only_its_conversation(self):
        self._enable()
        for index in range(2):
            _settled(self.db, self.website, session_id=f"s{index}")
        reply = json.dumps(
            [
                {"sentiment": "negative", "resolution": "resolved", "summary": "ok"},
                "not an object",
            ]
        )

        _, result = self._run(llm=_FakeLLM(reply=reply))

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 1)
        statuses = sorted(row.status for row in self._rows())
        self.assertEqual(statuses, ["completed", "failed"])


if __name__ == "__main__":
    unittest.main()
