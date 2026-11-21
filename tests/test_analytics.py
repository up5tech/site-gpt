"""Analytics tests (V4-10).

The properties worth pinning are the ones a quiet edit breaks: the trend is one
row per UTC day with zeros, the funnel stages count distinct sessions and
overlap, top questions group by the normalized text, a foreign company reads
nothing of ours, and the definitions still agree with the weekly digest — the
digest payload for the same fixture is compared key for key against the V3 shape
(V4-10 leaves `build_digest` untouched).

A real (in-memory SQLite) database is used for the queries; no provider is
called, so none of this depends on an API key.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import analytics as analytics_api
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import analytics, digest

# A Monday, so the window is exactly one digest week.
WEEK_START = datetime(2026, 11, 9, tzinfo=UTC)
WEEK_END = WEEK_START + timedelta(days=7)

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
    models.Contact.__table__,
    models.HandoffRequest.__table__,
    models.ChatFeedback.__table__,
    models.Setting.__table__,
]


def _at(day: int, hour: int = 9, minute: int = 0) -> datetime:
    """A moment inside the fixture week (day 9..15 November 2026)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


# The route reads `datetime.now(UTC)`; freezing it makes the rolling window
# deterministic, so a flag-off response can be compared byte for byte.
FROZEN_NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW


# What V4-1G's `/api/analytics/summary` returned: the V3 digest keys plus the
# three V4-10 additions, and nothing else.
V4_1G_KEYS = {
    "company_id",
    "period_start",
    "period_end",
    "conversation_volume",
    "message_count",
    "new_contacts",
    "feedback_up",
    "feedback_down",
    "top_topics",
    "topic_groups",
    "unanswered_questions",
    "days",
    "trend",
    "funnel",
    "top_questions",
}


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        # One shared in-memory connection: the route tests go through TestClient,
        # which runs the sync endpoint in a worker thread.
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = self._company("Acme")
        self.other = self._company("Globex")
        self.site_a = self._website(self.company, "site-a")
        self.site_b = self._website(self.company, "site-b")
        self.site_x = self._website(self.other, "site-x")

        # Session s1 — site-a, answered by the bot, becomes a lead, never handoffs.
        self._message(self.site_a, "s1", "user", "How much does it cost?", _at(10, 9))
        self._message(
            self.site_a, "s1", "assistant", "It costs $9.", _at(10, 9, 0), answered=True
        )
        self._contact(self.site_a, "s1", _at(10, 9, 30))
        # The same session asks again the next day (same question, no "?") and gets
        # an ungrounded answer.
        self._message(self.site_a, "s1", "user", "How much does it cost", _at(11, 10))
        self._message(
            self.site_a,
            "s1",
            "assistant",
            "I don't know.",
            _at(11, 10, 0),
            answered=False,
        )
        self._feedback(self.site_a, "s1", "up", _at(11, 10, 1))

        # Session s2 — site-b, answered by a human agent, handoff + reached human.
        self._message(
            self.site_b, "s2", "user", "Do you ship to Vietnam?", _at(11, 12)
        )
        self._message(self.site_b, "s2", "agent", "Yes, we do.", _at(11, 12, 0))
        self._handoff(self.site_b, "s2", _at(11, 12, 1))
        self._conversation(
            self.site_b, "s2", "human", _at(11, 12, 5), claimed_at=_at(11, 12, 2)
        )

        # Session s3 — site-a, the bot says it does not know; still `bot` in the queue.
        self._message(self.site_a, "s3", "user", "Can I get a refund?", _at(12, 8))
        self._message(
            self.site_a, "s3", "assistant", "No idea.", _at(12, 8, 0), answered=False
        )
        self._conversation(self.site_a, "s3", "bot", _at(12, 8, 0))
        self._feedback(self.site_b, "s3", "down", _at(12, 12, 10))
        # A whitespace-only "question" is not a question at all.
        self._message(self.site_a, "s3", "user", "   ", _at(14, 15))

        # Globex: a session that reuses the id "s1" on its own website.
        self._message(
            self.site_x, "s1", "user", "Where is my invoice?", _at(11, 15)
        )
        self._message(
            self.site_x, "s1", "assistant", "Unknown.", _at(11, 15, 0), answered=False
        )
        self._contact(self.site_x, "s1", _at(11, 15, 30))
        self._handoff(self.site_x, "s1", _at(11, 15, 45))
        self._conversation(
            self.site_x, "s1", "human", _at(11, 15, 50), claimed_at=_at(11, 15, 50)
        )
        self._feedback(self.site_x, "s1", "up", _at(11, 16))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # -- fixtures ---------------------------------------------------------

    def _company(self, name):
        company = models.Company(name=name)
        self.db.add(company)
        self.db.commit()
        return company

    def _website(self, company, name):
        website = models.Website(
            company_id=company.id,
            name=name,
            url=f"https://{name}.test",
            site_map_url="",
            status="active",
        )
        self.db.add(website)
        self.db.commit()
        return website

    def _message(self, website, session, role, text, at, answered=None):
        row = models.ChatMessage(
            website_id=website.id,
            session_id=session,
            role=role,
            message=text,
            answered=answered,
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _contact(self, website, session, at):
        row = models.Contact(
            website_id=website.id,
            session_id=session,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.test",
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _handoff(self, website, session, at):
        row = models.HandoffRequest(
            website_id=website.id,
            session_id=session,
            status="pending",
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _conversation(self, website, session, state, last_message_at, claimed_at=None):
        row = models.Conversation(
            website_id=website.id,
            session_id=session,
            state=state,
            claimed_at=claimed_at,
            closed_at=_at(13) if state == "closed" else None,
            last_message_at=last_message_at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _feedback(self, website, session, rating, at):
        row = models.ChatFeedback(
            website_id=website.id,
            session_id=session,
            rating=rating,
            created_at=at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _conversation_row(self, website, session):
        return (
            self.db.query(models.Conversation)
            .filter(
                models.Conversation.website_id == website.id,
                models.Conversation.session_id == session,
            )
            .one()
        )

    def _insight(
        self, conversation, sentiment=None, resolution=None, status="completed"
    ):
        row = models.ConversationInsight(
            conversation_id=conversation.id,
            status=status,
            sentiment=sentiment,
            resolution=resolution,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _setting(self, key, value):
        self.db.add(
            models.Setting(company_id=self.company.id, key=key, value=value)
        )
        self.db.commit()

    def rows(self, company_id=None):
        return {
            row["date"]: row
            for row in analytics.daily_trend(
                self.db, company_id or self.company.id, WEEK_START, WEEK_END
            )
        }


class DailyTrendTests(AnalyticsTestCase):
    def test_one_row_per_utc_day_including_the_empty_ones(self):
        trend = analytics.daily_trend(
            self.db, self.company.id, WEEK_START, WEEK_END
        )
        self.assertEqual(
            [row["date"] for row in trend],
            [
                "2026-11-09",
                "2026-11-10",
                "2026-11-11",
                "2026-11-12",
                "2026-11-13",
                "2026-11-14",
                "2026-11-15",
            ],
        )
        self.assertEqual(
            set(trend[0]),
            {
                "date",
                "conversations",
                "messages",
                "visitor_messages",
                "new_contacts",
                "feedback_up",
                "feedback_down",
                "unanswered",
            },
        )

    def test_a_quiet_day_is_all_zeros(self):
        self.assertEqual(
            self.rows()["2026-11-13"],
            {
                "date": "2026-11-13",
                "conversations": 0,
                "messages": 0,
                "visitor_messages": 0,
                "new_contacts": 0,
                "feedback_up": 0,
                "feedback_down": 0,
                "unanswered": 0,
            },
        )

    def test_counts_are_per_day_and_per_company(self):
        rows = self.rows()

        self.assertEqual(rows["2026-11-10"]["conversations"], 1)
        self.assertEqual(rows["2026-11-10"]["messages"], 2)
        self.assertEqual(rows["2026-11-10"]["visitor_messages"], 1)
        self.assertEqual(rows["2026-11-10"]["new_contacts"], 1)
        self.assertEqual(rows["2026-11-10"]["unanswered"], 0)

        # Two sessions on two websites, one bot answer and one agent answer: the
        # agent row counts as a message but not as a visitor message.
        self.assertEqual(rows["2026-11-11"]["conversations"], 2)
        self.assertEqual(rows["2026-11-11"]["messages"], 4)
        self.assertEqual(rows["2026-11-11"]["visitor_messages"], 2)
        self.assertEqual(rows["2026-11-11"]["feedback_up"], 1)
        self.assertEqual(rows["2026-11-11"]["unanswered"], 1)
        # Globex's rows on the same day must not be counted.
        self.assertEqual(rows["2026-11-11"]["new_contacts"], 0)

        self.assertEqual(rows["2026-11-12"]["unanswered"], 1)
        self.assertEqual(rows["2026-11-12"]["feedback_down"], 1)

        # A blank question is a message without becoming a question.
        self.assertEqual(rows["2026-11-14"]["messages"], 1)
        self.assertEqual(rows["2026-11-14"]["visitor_messages"], 1)

    def test_daily_conversations_do_not_double_count_across_days(self):
        # s1 is active on the 10th and the 11th: the daily rows show activity, so
        # they are not expected to sum to the window's conversation volume.
        rows = self.rows()
        self.assertEqual(sum(row["conversations"] for row in rows.values()), 5)
        payload = digest.build_digest(self.db, self.company.id, WEEK_START, WEEK_END)
        self.assertEqual(payload["conversation_volume"], 3)

    def test_an_unknown_company_reads_nothing_of_ours(self):
        trend = analytics.daily_trend(
            self.db, self.other.id, WEEK_START, WEEK_END
        )
        active = {row["date"]: row for row in trend if row["messages"]}
        self.assertEqual(list(active), ["2026-11-11"])
        self.assertEqual(active["2026-11-11"]["messages"], 2)
        self.assertEqual(active["2026-11-11"]["conversations"], 1)

    def test_the_window_is_half_open(self):
        # A message exactly at `end` belongs to the next window.
        self._message(self.site_a, "s1", "user", "Late one?", WEEK_END)
        trend = analytics.daily_trend(
            self.db, self.company.id, WEEK_START, WEEK_END
        )
        self.assertNotIn(
            "2026-11-16", {row["date"] for row in trend}
        )


class EngagementFunnelTests(AnalyticsTestCase):
    def test_the_five_stages_are_distinct_session_counts(self):
        funnel = analytics.engagement_funnel(
            self.db, self.company.id, WEEK_START, WEEK_END
        )
        self.assertEqual(
            funnel,
            [
                {"stage": "started", "sessions": 3},
                # s1 (bot), s2 (agent) and s3 (an ungrounded bot answer) all got
                # a reply; the quality of the answer is the trend's `unanswered`.
                {"stage": "answered", "sessions": 3},
                # A lead without a handoff still counts (D4: overlapping counts).
                {"stage": "lead", "sessions": 1},
                {"stage": "handoff", "sessions": 1},
                {"stage": "human", "sessions": 1},
            ],
        )

    def test_the_agent_reply_counts_as_answered(self):
        # s2 has no assistant row at all, only the human agent's reply.
        funnel = {
            item["stage"]: item["sessions"]
            for item in analytics.engagement_funnel(
                self.db, self.company.id, WEEK_START, WEEK_END
            )
        }
        self.assertEqual(funnel["answered"], funnel["started"])

    def test_a_closed_conversation_still_counts_as_having_reached_a_human(self):
        row = (
            self.db.query(models.Conversation)
            .filter(
                models.Conversation.website_id == self.site_b.id,
                models.Conversation.session_id == "s2",
            )
            .one()
        )
        # `close` clears the claim and stamps `closed_at`, which only ever
        # follows a human holding the session.
        row.state = "closed"
        row.claimed_at = None
        row.closed_at = _at(13)
        self.db.commit()

        funnel = {
            item["stage"]: item["sessions"]
            for item in analytics.engagement_funnel(
                self.db, self.company.id, WEEK_START, WEEK_END
            )
        }
        self.assertEqual(funnel["human"], 1)

    def test_a_released_session_is_not_counted_as_human(self):
        row = (
            self.db.query(models.Conversation)
            .filter(models.Conversation.website_id == self.site_b.id)
            .one()
        )
        row.state = "waiting"
        row.claimed_at = None
        self.db.commit()

        funnel = {
            item["stage"]: item["sessions"]
            for item in analytics.engagement_funnel(
                self.db, self.company.id, WEEK_START, WEEK_END
            )
        }
        self.assertEqual(funnel["human"], 0)

    def test_a_foreign_company_only_sees_its_own_stages(self):
        funnel = analytics.engagement_funnel(
            self.db, self.other.id, WEEK_START, WEEK_END
        )
        self.assertEqual(
            funnel,
            [
                {"stage": "started", "sessions": 1},
                {"stage": "answered", "sessions": 1},
                {"stage": "lead", "sessions": 1},
                {"stage": "handoff", "sessions": 1},
                {"stage": "human", "sessions": 1},
            ],
        )

    def test_started_agrees_with_the_digests_conversation_volume(self):
        started = next(
            item["sessions"]
            for item in analytics.engagement_funnel(
                self.db, self.company.id, WEEK_START, WEEK_END
            )
            if item["stage"] == "started"
        )
        payload = digest.build_digest(self.db, self.company.id, WEEK_START, WEEK_END)
        self.assertEqual(started, payload["conversation_volume"])


class TopQuestionTests(AnalyticsTestCase):
    def test_repeated_questions_group_on_the_normalized_text(self):
        self.assertEqual(
            analytics.top_questions(
                self.db, self.company.id, WEEK_START, WEEK_END
            ),
            [
                {"question": "how much does it cost", "count": 2},
                {"question": "do you ship to vietnam", "count": 1},
                {"question": "can i get a refund", "count": 1},
            ],
        )

    def test_the_limit_is_applied_after_the_ranking(self):
        self.assertEqual(
            analytics.top_questions(
                self.db, self.company.id, WEEK_START, WEEK_END, limit=1
            ),
            [{"question": "how much does it cost", "count": 2}],
        )
        self.assertEqual(
            analytics.top_questions(
                self.db, self.company.id, WEEK_START, WEEK_END, limit=0
            ),
            [],
        )

    def test_a_foreign_company_sees_only_its_questions(self):
        self.assertEqual(
            analytics.top_questions(self.db, self.other.id, WEEK_START, WEEK_END),
            [{"question": "where is my invoice", "count": 1}],
        )

    def test_normalization_strips_case_whitespace_and_trailing_punctuation(self):
        self.assertEqual(
            analytics.normalize_question("  How   MUCH\tdoes it cost???... "),
            "how much does it cost",
        )
        self.assertEqual(
            analytics.normalize_question("What's the price?!"), "what's the price"
        )
        self.assertEqual(analytics.normalize_question("   ...  "), "")
        self.assertEqual(analytics.normalize_question(None), "")


class SharedDefinitionTests(AnalyticsTestCase):
    """V4-10: one definition, so the page and the email cannot disagree."""

    def test_the_unanswered_rule_matches_the_digests_selection(self):
        messages = digest._period_messages(
            self.db, self.company.id, WEEK_START, WEEK_END
        )
        ours = {
            (message.session_id, message.created_at.isoformat())
            for message in messages
            if analytics.is_unanswered(message)
        }
        theirs = {
            (item["session_id"], item["asked_at"])
            for item in digest._unanswered(messages, {})
        }
        self.assertEqual(ours, theirs)
        # NULL (`answered is None`) is "unknown", never unanswered.
        self.assertFalse(
            analytics.is_unanswered(
                SimpleNamespace(role="assistant", answered=None)
            )
        )

    def test_the_digest_payload_is_unchanged_by_the_new_reads(self):
        # `build_digest` is not edited in V4-10. Running the analytics reads first
        # must not change what the digest returns for the same window, key for
        # key (V3 shape: no `topic_groups`, clustering off).
        analytics.daily_trend(self.db, self.company.id, WEEK_START, WEEK_END)
        analytics.engagement_funnel(self.db, self.company.id, WEEK_START, WEEK_END)
        analytics.top_questions(self.db, self.company.id, WEEK_START, WEEK_END)

        payload = digest.build_digest(self.db, self.company.id, WEEK_START, WEEK_END)
        self.assertEqual(
            set(payload),
            {
                "company_id",
                "period_start",
                "period_end",
                "conversation_volume",
                "message_count",
                "new_contacts",
                "feedback_up",
                "feedback_down",
                "top_topics",
                "unanswered_questions",
            },
        )
        self.assertEqual(payload["company_id"], str(self.company.id))
        self.assertEqual(payload["period_start"], WEEK_START.isoformat())
        self.assertEqual(payload["period_end"], WEEK_END.isoformat())
        self.assertEqual(payload["conversation_volume"], 3)
        self.assertEqual(payload["message_count"], 9)
        self.assertEqual(payload["new_contacts"], 1)
        self.assertEqual(payload["feedback_up"], 1)
        self.assertEqual(payload["feedback_down"], 1)
        self.assertEqual(
            payload["top_topics"],
            [
                {"term": "much", "count": 2},
                {"term": "cost", "count": 2},
                {"term": "ship", "count": 1},
                {"term": "vietnam", "count": 1},
                {"term": "refund", "count": 1},
            ],
        )
        # Newest first, the digest's own ordering.
        self.assertEqual(
            [item["question"] for item in payload["unanswered_questions"]],
            ["Can I get a refund?", "How much does it cost"],
        )


class OutcomeTests(AnalyticsTestCase):
    """V4-43: the breakdown counts stored classifications, never re-classifies."""

    def test_completed_labels_are_counted_in_enum_order(self):
        self._insight(
            self._conversation_row(self.site_b, "s2"),
            sentiment="positive",
            resolution="resolved",
        )
        self._insight(
            self._conversation_row(self.site_a, "s3"),
            sentiment="frustrated",
            resolution="unresolved",
        )

        self.assertEqual(
            analytics.outcomes(self.db, self.company.id, WEEK_START, WEEK_END),
            {
                "classified": 2,
                "sentiment": [
                    {"value": "positive", "count": 1},
                    {"value": "neutral", "count": 0},
                    {"value": "negative", "count": 0},
                    {"value": "frustrated", "count": 1},
                ],
                "resolution": [
                    {"value": "resolved", "count": 1},
                    {"value": "unresolved", "count": 1},
                    {"value": "escalated", "count": 0},
                    {"value": "unknown", "count": 0},
                ],
            },
        )

    def test_a_processing_or_failed_row_is_not_a_verdict(self):
        self._insight(
            self._conversation_row(self.site_b, "s2"), status="processing"
        )
        # A failed refresh keeps its previous labels on the row, but they are not
        # a fresh result and must not be counted as one.
        self._insight(
            self._conversation_row(self.site_a, "s3"),
            sentiment="positive",
            resolution="resolved",
            status="failed",
        )

        breakdown = analytics.outcomes(
            self.db, self.company.id, WEEK_START, WEEK_END
        )
        self.assertEqual(breakdown["classified"], 0)
        self.assertTrue(
            all(item["count"] == 0 for item in breakdown["sentiment"])
        )
        self.assertTrue(
            all(item["count"] == 0 for item in breakdown["resolution"])
        )

    def test_a_foreign_companys_insight_is_not_counted(self):
        self._insight(
            self._conversation_row(self.site_x, "s1"),
            sentiment="negative",
            resolution="unresolved",
        )

        self.assertEqual(
            analytics.outcomes(self.db, self.company.id, WEEK_START, WEEK_END)[
                "classified"
            ],
            0,
        )
        self.assertEqual(
            analytics.outcomes(self.db, self.other.id, WEEK_START, WEEK_END)[
                "classified"
            ],
            1,
        )

    def test_the_window_is_the_conversations_last_activity(self):
        conversation = self._conversation(self.site_b, "late", "human", WEEK_END)
        self._insight(conversation, sentiment="neutral", resolution="unknown")

        self.assertEqual(
            analytics.outcomes(self.db, self.company.id, WEEK_START, WEEK_END)[
                "classified"
            ],
            0,
        )

    def test_no_insight_rows_is_an_all_zero_breakdown(self):
        breakdown = analytics.outcomes(
            self.db, self.company.id, WEEK_START, WEEK_END
        )
        self.assertEqual(breakdown["classified"], 0)
        self.assertEqual(
            [item["value"] for item in breakdown["sentiment"]],
            ["positive", "neutral", "negative", "frustrated"],
        )
        self.assertEqual(
            [item["value"] for item in breakdown["resolution"]],
            ["resolved", "unresolved", "escalated", "unknown"],
        )


class AnalyticsSummaryRouteTests(AnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.user = models.User(
            company_id=self.company.id,
            email="manager@acme.test",
            password_hash="x",
            first_name="M",
            last_name="Manager",
            role="manager",
            status="active",
        )
        self.db.add(self.user)
        self.db.commit()

        app = FastAPI()
        app.include_router(analytics_api.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_manager_user] = lambda: self.user
        self.client = TestClient(app)

    def test_the_summary_carries_the_three_new_fields(self):
        response = self.client.get("/api/analytics/summary", params={"days": 7})
        self.assertEqual(response.status_code, 200)
        body = response.json()

        # The V3 keys keep their meaning and are still present.
        self.assertEqual(body["days"], 7)
        self.assertIn("conversation_volume", body)
        self.assertIn("top_topics", body)
        # The V4 additions validate against the schema and have the right shape.
        # A rolling 7×24h window touches seven whole days plus today's partial
        # one — eight rows unless the request lands exactly at midnight.
        self.assertIn(len(body["trend"]), (7, 8))
        self.assertEqual(
            [row["stage"] for row in body["funnel"]],
            list(analytics.FUNNEL_STAGES),
        )
        self.assertTrue(all("sessions" in row for row in body["funnel"]))
        self.assertIsInstance(body["top_questions"], list)

    def test_a_flag_off_summary_keeps_the_v4_1g_shape_byte_for_byte(self):
        with patch.object(analytics_api, "datetime", _FrozenDatetime):
            before = self.client.get("/api/analytics/summary", params={"days": 7})
            # Insight rows existing does not change a flag-off payload: the key is
            # absent, not null, so a V3 client reads exactly the V4-1G bytes.
            self._insight(
                self._conversation_row(self.site_b, "s2"),
                sentiment="positive",
                resolution="resolved",
            )
            after = self.client.get("/api/analytics/summary", params={"days": 7})

        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.text, after.text)
        self.assertEqual(set(after.json()), V4_1G_KEYS)
        self.assertNotIn("outcomes", after.json())

    def test_a_flag_on_summary_adds_the_outcomes_breakdown(self):
        self._setting("conversation_insights_enabled", "true")
        self._insight(
            self._conversation_row(self.site_b, "s2"),
            sentiment="positive",
            resolution="resolved",
        )
        self._insight(
            self._conversation_row(self.site_a, "s3"),
            sentiment="frustrated",
            resolution="unresolved",
        )

        with patch.object(analytics_api, "datetime", _FrozenDatetime):
            response = self.client.get("/api/analytics/summary", params={"days": 7})

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), V4_1G_KEYS | {"outcomes"})
        self.assertEqual(body["outcomes"]["classified"], 2)
        self.assertEqual(
            {
                item["value"]: item["count"]
                for item in body["outcomes"]["sentiment"]
            },
            {"positive": 1, "neutral": 0, "negative": 0, "frustrated": 1},
        )
        self.assertEqual(
            {
                item["value"]: item["count"]
                for item in body["outcomes"]["resolution"]
            },
            {"resolved": 1, "unresolved": 1, "escalated": 0, "unknown": 0},
        )
        # The V3/V4-1G keys keep their values alongside the new one.
        self.assertEqual(body["conversation_volume"], 3)
        self.assertEqual(body["days"], 7)


if __name__ == "__main__":
    unittest.main()
