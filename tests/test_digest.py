"""Unit tests for the weekly digest (F6).

Covers the pure parts — the week window, the HTML and the claim-before-send
insert — because those are what a wrong edit would silently break: a shifted
period start makes the unique constraint stop matching, and a claim taken after
the send lets two workers mail the same week.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from site_gpt.app import models
from site_gpt.app.api import digest as digest_api
from site_gpt.app.services import digest, topics


def _chain(**kwargs):
    """A query chain stub. `all_value=`/`first_value=`/`count_value=` set the
    terminal method's return value."""
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.join.return_value = chain
    chain.order_by.return_value = chain
    for name, value in kwargs.items():
        method = name[: -len("_value")] if name.endswith("_value") else name
        getattr(chain, method).return_value = value
    return chain


class NormalizePeriodTests(unittest.TestCase):
    def test_monday_week_containing_now(self):
        # Wednesday 2026-11-18 → the week starts Monday 2026-11-16.
        start, end = digest.normalize_period(datetime(2026, 11, 18, 15, 30, tzinfo=UTC))
        self.assertEqual(start, datetime(2026, 11, 16, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 11, 23, tzinfo=UTC))
        self.assertEqual(end - start, timedelta(days=7))

    def test_same_week_always_yields_the_same_start(self):
        # digest_log's unique constraint depends on this, not on the clock time.
        monday = digest.normalize_period(datetime(2026, 11, 16, 0, 0, tzinfo=UTC))
        sunday = digest.normalize_period(datetime(2026, 11, 22, 23, 59, tzinfo=UTC))
        self.assertEqual(monday, sunday)

    def test_naive_input_is_treated_as_utc(self):
        start, end = digest.normalize_period(datetime(2026, 11, 18, 12, 0))
        self.assertEqual(start.tzinfo, UTC)
        self.assertEqual(start, datetime(2026, 11, 16, tzinfo=UTC))

    def test_custom_day_moves_the_start(self):
        start, _ = digest.normalize_period(
            datetime(2026, 11, 18, 12, 0, tzinfo=UTC), "friday"
        )
        self.assertEqual(start.weekday(), 4)  # Friday
        self.assertEqual(start, datetime(2026, 11, 13, tzinfo=UTC))

    def test_unknown_day_falls_back_to_monday(self):
        start, _ = digest.normalize_period(
            datetime(2026, 11, 18, 12, 0, tzinfo=UTC), "notaday"
        )
        self.assertEqual(start, datetime(2026, 11, 16, tzinfo=UTC))


class PreviousPeriodTests(unittest.TestCase):
    """The digest reports a finished week — the one the topic worker builds."""

    def test_it_is_the_week_before_the_one_containing_now(self):
        start, end = digest.previous_period(
            datetime(2026, 11, 18, 15, 30, tzinfo=UTC)
        )
        self.assertEqual(start, datetime(2026, 11, 9, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 11, 16, tzinfo=UTC))
        self.assertEqual(end - start, timedelta(days=7))

    def test_every_moment_of_a_week_reports_the_same_window(self):
        monday = digest.previous_period(datetime(2026, 11, 16, 0, 0, tzinfo=UTC))
        sunday = digest.previous_period(datetime(2026, 11, 22, 23, 59, tzinfo=UTC))
        self.assertEqual(monday, sunday)

    def test_a_custom_digest_day_shifts_both_edges(self):
        start, end = digest.previous_period(
            datetime(2026, 11, 18, 12, 0, tzinfo=UTC), "friday"
        )
        self.assertEqual(start, datetime(2026, 11, 6, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 11, 13, tzinfo=UTC))

    def test_the_topic_window_uses_the_same_definition(self):
        now = datetime(2026, 11, 18, 15, 30, tzinfo=UTC)
        for day in ("monday", "friday", "sunday", "notaday"):
            with self.subTest(day=day):
                self.assertEqual(
                    topics.previous_window(now, day), digest.previous_period(now, day)
                )


class DigestEndpointPeriodTests(unittest.TestCase):
    def test_preview_and_send_now_use_the_last_complete_week(self):
        db = MagicMock()
        moment = datetime(2026, 11, 18, 15, 30, tzinfo=UTC)

        with patch.object(
            digest_api.company_settings, "value", return_value="monday"
        ), patch.object(
            digest_api, "datetime", SimpleNamespace(now=lambda tz=None: moment)
        ):
            period = digest_api._period(db, uuid4())

        self.assertEqual(period, digest.previous_period(moment, "monday"))
        self.assertEqual(period[0], datetime(2026, 11, 9, tzinfo=UTC))


class RenderDigestHtmlTests(unittest.TestCase):
    def _data(self, **overrides):
        data = {
            "company_id": str(uuid4()),
            "period_start": "2026-11-16T00:00:00+00:00",
            "period_end": "2026-11-23T00:00:00+00:00",
            "conversation_volume": 3,
            "message_count": 12,
            "new_contacts": 2,
            "feedback_up": 4,
            "feedback_down": 1,
            "top_topics": [{"term": "pricing", "count": 5}],
            "unanswered_questions": [
                {
                    "question": "Do you ship to Mars?",
                    "website_id": "w1",
                    "website_name": "Acme",
                    "session_id": "s1",
                    "asked_at": "2026-11-17T10:00:00+00:00",
                    "link": "http://app.test/?website=w1&focus=s1",
                }
            ],
        }
        data.update(overrides)
        return data

    def test_counts_and_period_dates_are_rendered(self):
        html = digest.render_digest_html(self._data(), "Acme Co")
        self.assertIn("Acme Co", html)
        self.assertIn("2026-11-16", html)
        self.assertIn("2026-11-23", html)
        self.assertIn("<strong>12</strong>", html)
        self.assertIn("👍 4 / 👎 1", html)

    def test_company_name_and_topics_are_escaped(self):
        html = digest.render_digest_html(
            self._data(top_topics=[{"term": "<script>x</script>", "count": 1}]),
            "<b>Bad & Co</b>",
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;Bad &amp; Co&lt;/b&gt;", html)

    def test_empty_state_is_stated_in_words(self):
        html = digest.render_digest_html(
            self._data(top_topics=[], unanswered_questions=[])
        )
        self.assertIn("No topics yet", html)
        self.assertIn("Every question was answered", html)

    def test_unanswered_question_links_into_the_transcript(self):
        html = digest.render_digest_html(self._data())
        self.assertIn('href="http://app.test/?website=w1&amp;focus=s1"', html)
        self.assertIn("Do you ship to Mars?", html)
        self.assertIn("(Acme)", html)

    def test_default_title_when_no_company_name(self):
        self.assertIn("Weekly digest", digest.render_digest_html(self._data()))

    def test_without_groups_the_term_list_is_unchanged(self):
        # Clustering off (the default) must render exactly what V2.1 rendered.
        self.assertIn(
            "<h3>Top topics</h3><ul><li>pricing — 5</li></ul>"
            "<h3>Questions your content could not answer</h3>",
            digest.render_digest_html(self._data()),
        )

    def test_groups_replace_the_terms_and_disclose_the_sample(self):
        html = digest.render_digest_html(
            self._data(
                topic_groups=[
                    {
                        "label": "Pricing and plans",
                        "summary": "Visitors ask what it costs.",
                        "sampled_messages": 40,
                        "eligible_messages": 50,
                    }
                ]
            )
        )
        self.assertIn("<h3>Topic groups</h3>", html)
        self.assertIn("<strong>Pricing and plans</strong>", html)
        self.assertIn("Visitors ask what it costs.", html)
        self.assertIn("Named from 40 of 50 visitor questions", html)
        self.assertNotIn("<h3>Top topics</h3>", html)

    def test_group_labels_and_summaries_are_escaped(self):
        html = digest.render_digest_html(
            self._data(
                topic_groups=[
                    {
                        "label": "<b>Prices</b>",
                        "summary": "<script>x</script>",
                        "sampled_messages": 1,
                        "eligible_messages": 1,
                    }
                ]
            )
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;Prices&lt;/b&gt;", html)


class BuildDigestTests(unittest.TestCase):
    def test_counts_topics_and_unanswered_questions(self):
        website_id = uuid4()
        asked_at = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
        messages = [
            SimpleNamespace(
                role="user",
                message="what is the pricing model?",
                session_id="s1",
                website_id=website_id,
                answered=None,
                created_at=asked_at,
            ),
            SimpleNamespace(
                role="assistant",
                message="no idea",
                session_id="s1",
                website_id=website_id,
                answered=False,
                created_at=asked_at + timedelta(seconds=5),
            ),
            SimpleNamespace(
                role="user",
                message="hello",
                session_id="s2",
                website_id=website_id,
                answered=None,
                created_at=asked_at,
            ),
        ]
        db = MagicMock()
        db.query.side_effect = [
            _chain(all_value=[(website_id, "Acme")]),
            _chain(count_value=2),  # new contacts
            _chain(count_value=3),  # feedback up
            _chain(count_value=1),  # feedback down
            # No `topic_clustering_enabled` row: the off default, so no cluster read.
            _chain(all_value=[]),
        ]

        with patch.object(digest, "_period_messages", return_value=messages):
            data = digest.build_digest(
                db,
                uuid4(),
                datetime(2026, 11, 16, tzinfo=UTC),
                datetime(2026, 11, 23, tzinfo=UTC),
            )

        self.assertEqual(data["message_count"], 3)
        self.assertEqual(data["conversation_volume"], 2)
        self.assertEqual(data["new_contacts"], 2)
        self.assertEqual(data["feedback_up"], 3)
        self.assertEqual(data["feedback_down"], 1)
        self.assertEqual([topic["term"] for topic in data["top_topics"]][0], "pricing")
        self.assertEqual(len(data["unanswered_questions"]), 1)
        self.assertEqual(
            data["unanswered_questions"][0]["question"],
            "what is the pricing model?",
        )
        self.assertEqual(data["unanswered_questions"][0]["website_name"], "Acme")


class TopicGroupTests(unittest.TestCase):
    """Named groups are an opt-in read of stored rows, never a computed topic list."""

    START = datetime(2026, 11, 9, tzinfo=UTC)  # a Monday
    END = START + timedelta(days=7)

    def _db(self, clustering: str):
        """`build_digest`'s queries in order: sites, contacts, votes, flag."""
        db = MagicMock()
        db.query.side_effect = [
            _chain(all_value=[]),  # websites
            _chain(count_value=0),  # new contacts
            _chain(count_value=0),  # feedback up
            _chain(count_value=0),  # feedback down
            _chain(all_value=[("topic_clustering_enabled", clustering)]),
        ]
        return db

    def test_flag_off_keeps_the_v21_payload(self):
        db = self._db("false")
        with patch.object(digest, "_period_messages", return_value=[]), patch.object(
            topics,
            "completed_windows",
            side_effect=AssertionError("clusters must not be read with the flag off"),
        ):
            data = digest.build_digest(db, uuid4(), self.START, self.END)

        self.assertEqual(
            list(data),
            [
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
            ],
        )

    def test_flag_on_reports_the_stored_groups(self):
        company_id = uuid4()
        db = self._db("true")
        cluster = SimpleNamespace(
            label="Pricing",
            summary="Visitors ask what it costs.",
            sampled_messages=40,
            eligible_messages=50,
        )
        with patch.object(digest, "_period_messages", return_value=[]), patch.object(
            topics, "completed_windows", return_value=[(self.START, [cluster])]
        ) as windows:
            data = digest.build_digest(db, company_id, self.START, self.END)

        # The gate gets the digest's own interval: no widening to whole weeks.
        windows.assert_called_once_with(db, company_id, self.START, self.END)
        self.assertEqual(
            data["topic_groups"],
            [
                {
                    "label": "Pricing",
                    "summary": "Visitors ask what it costs.",
                    "sampled_messages": 40,
                    "eligible_messages": 50,
                }
            ],
        )
        # The old field survives, so existing clients keep reading it.
        self.assertEqual(data["top_topics"], [])

    def test_flag_on_keeps_terms_unless_one_week_is_complete(self):
        cluster = SimpleNamespace(
            label="Pricing", summary=None, sampled_messages=1, eligible_messages=1
        )
        # A digest period is one week: an unaligned/missing interval and a set of
        # completed weeks both keep the term list rather than invent an aggregate.
        for windows in (None, [], [(self.START, [cluster]), (self.END, [cluster])]):
            with self.subTest(windows=windows):
                with patch.object(
                    digest, "_period_messages", return_value=[]
                ), patch.object(topics, "completed_windows", return_value=windows):
                    data = digest.build_digest(
                        self._db("true"), uuid4(), self.START, self.END
                    )

                self.assertNotIn("topic_groups", data)


class ClaimPeriodTests(unittest.TestCase):
    """The row must exist before the email goes out, so a crash cannot resend."""

    def test_first_claim_inserts_an_unsent_row(self):
        db = MagicMock()
        db.query.return_value = _chain(first_value=None)
        start = datetime(2026, 11, 16, tzinfo=UTC)
        end = datetime(2026, 11, 23, tzinfo=UTC)

        row = digest.claim_period(
            db, uuid4(), start, end, datetime.now(UTC) - timedelta(hours=1)
        )

        self.assertIsInstance(row, models.DigestLog)
        self.assertIsNone(row.sent_at)
        self.assertEqual(row.period_start, start)
        self.assertEqual(row.period_end, end)
        db.add.assert_called_once_with(row)
        db.commit.assert_called_once()

    def test_a_sent_period_is_never_claimed_again(self):
        db = MagicMock()
        db.query.return_value = _chain(
            first_value=SimpleNamespace(
                sent_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        self.assertIsNone(
            digest.claim_period(
                db,
                uuid4(),
                datetime(2026, 11, 16, tzinfo=UTC),
                datetime(2026, 11, 23, tzinfo=UTC),
                datetime.now(UTC) - timedelta(hours=1),
            )
        )
        db.add.assert_not_called()

    def test_a_live_claim_belongs_to_its_worker(self):
        db = MagicMock()
        db.query.return_value = _chain(
            first_value=SimpleNamespace(
                sent_at=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        self.assertIsNone(
            digest.claim_period(
                db,
                uuid4(),
                datetime(2026, 11, 16, tzinfo=UTC),
                datetime(2026, 11, 23, tzinfo=UTC),
                datetime.now(UTC) - timedelta(hours=1),
            )
        )

    def test_a_dead_workers_claim_is_taken_over(self):
        stale = SimpleNamespace(
            sent_at=None,
            created_at=datetime.now(UTC) - timedelta(hours=5),
            updated_at=datetime.now(UTC) - timedelta(hours=5),
        )
        db = MagicMock()
        db.query.return_value = _chain(first_value=stale)

        row = digest.claim_period(
            db,
            uuid4(),
            datetime(2026, 11, 16, tzinfo=UTC),
            datetime(2026, 11, 23, tzinfo=UTC),
            datetime.now(UTC) - timedelta(hours=1),
        )

        self.assertIs(row, stale)
        self.assertGreater(stale.updated_at, datetime.now(UTC) - timedelta(minutes=1))
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
