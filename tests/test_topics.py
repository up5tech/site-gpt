"""Topic clustering tests (V3-31).

The properties that matter here are the ones a provider change would quietly
break: the window is the company's digest week (not a rolling seven days), the same
input produces the same clusters twice, a truncated sample never reports itself as
the total, one tenant's questions never reach another's run, and a failed or
malformed LLM reply still leaves rows behind. Embeddings and the chat model are
stubbed — a test must not spend a provider call — but the query, the clustering,
the validation and the inserts are the real code, against a real SQLite database.
"""

import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.core.config import EMBEDDING_DIMENSIONS
from site_gpt.app.db.base import Base
from site_gpt.app.services import topics

WINDOW_START = datetime(2026, 11, 9, tzinfo=UTC)  # a Monday
WEEK = (WINDOW_START, WINDOW_START + timedelta(days=7))

TABLES = [
    models.Company.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Setting.__table__,
    models.TopicCluster.__table__,
    models.TopicClusterRun.__table__,
]

PRICING = (
    "How much does it cost?",
    "What are your prices and plans?",
    "Is the price monthly?",
)
REFUNDS = (
    "How do I get a refund?",
    "Can I return an item?",
    "What is your refund policy?",
)

GOOD_REPLY = json.dumps(
    [
        {"label": "Pricing and plans", "summary": "Visitors ask what it costs."},
        {"label": "Refunds and returns", "summary": "Visitors ask how to get a refund."},
    ]
)


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


def _message(db, website, text, created, role="user"):
    row = models.ChatMessage(
        website_id=website.id,
        session_id="s1",
        role=role,
        message=text,
        created_at=created,
        updated_at=created,
    )
    db.add(row)
    db.commit()
    return row


def _aware(moment: datetime) -> datetime:
    """SQLite hands timestamps back naive; compare them as UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _vector(axis: int) -> list[float]:
    """A one-hot embedding: same topic → similarity 1, different topic → 0."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[axis] = 1.0
    return vector


def _stub_embeddings(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        if "refund" in lowered or "return" in lowered:
            vectors.append(_vector(1))
        elif "price" in lowered or "cost" in lowered:
            vectors.append(_vector(0))
        else:
            vectors.append(_vector(2))
    return vectors


class _FakeLLM:
    """Stands in for `get_llm()`: records the prompt, returns or raises."""

    def __init__(self, reply=GOOD_REPLY, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.reply)


def _quadratic_assign(vectors):
    """The previous `_assign`, kept here as the reference implementation.

    It re-added every member of a cluster on every join. The running-sum version
    must produce the same members and the same centroids bit-for-bit, so a cheaper
    update can never quietly move a cluster.
    """
    members: list[list[int]] = []
    centroids: list[list[float]] = []
    for index, vector in enumerate(vectors):
        best, best_similarity = -1, -1.0
        for position, centroid in enumerate(centroids):
            similarity = topics._cosine(vector, centroid)
            if similarity > best_similarity:
                best, best_similarity = position, similarity
        joins = best >= 0 and (
            best_similarity >= topics.CLUSTER_SIMILARITY
            or len(centroids) >= topics.MAX_CLUSTERS
        )
        if joins:
            members[best].append(index)
            grouped = [vectors[i] for i in members[best]]
            # Plain left-to-right accumulation, exactly like the old `_mean`:
            # `sum()` on floats uses compensated summation since Python 3.12 and
            # would differ in the last bit, which is not what we are comparing.
            total = [0.0] * len(grouped[0])
            for item in grouped:
                for position, value in enumerate(item):
                    total[position] += value
            centroids[best] = [value / len(grouped) for value in total]
        else:
            members.append([index])
            centroids.append(topics._unit(vector))
    return members, centroids


class AssignmentEquivalenceTests(unittest.TestCase):
    def test_the_running_centroid_is_the_old_recomputed_mean(self):
        # A big near-identical cluster (the worst case the running sum exists for)
        # plus vectors that open new clusters until `MAX_CLUSTERS` forces a join,
        # so both branches of the update are compared.
        vectors = [
            [1.0 + ((index * (position + 1)) % 7) / 100.0 for position in range(16)]
            for index in range(24)
        ]
        vectors += [
            [1.0 if position == axis else 0.0 for position in range(16)]
            for axis in range(9)
        ]

        members, centroids = topics._assign(vectors)
        old_members, old_centroids = _quadratic_assign(vectors)

        self.assertGreater(len(members), 1)
        self.assertEqual(members, old_members)
        self.assertEqual(centroids, old_centroids)


class TopicClusteringTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.website = _website(self.db, self.company)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_week(self, website=None):
        website = website or self.website
        for position, question in enumerate(PRICING + REFUNDS):
            _message(
                self.db,
                website,
                question,
                WINDOW_START + timedelta(days=1, minutes=position),
            )

    def _run(self, llm=None, embeddings=_stub_embeddings, **kwargs):
        llm = llm or _FakeLLM()
        if "window" not in kwargs and "now" not in kwargs:
            kwargs["window"] = WEEK
        with patch.object(topics, "embed_texts", side_effect=embeddings), patch.object(
            topics, "get_llm", lambda **_: llm
        ):
            result = topics.cluster_topics(self.db, self.company.id, **kwargs)
        return llm, result

    def test_the_window_comes_from_the_companys_digest_day(self):
        # `digest_day = thursday` moves the week start, so a message before that
        # Thursday belongs to the previous window and must not be counted here.
        self.db.add(
            models.Setting(
                company_id=self.company.id, key="digest_day", value="thursday"
            )
        )
        self.db.commit()
        _message(self.db, self.website, "price inside", datetime(2026, 11, 13, tzinfo=UTC))
        _message(
            self.db, self.website, "price before the window", datetime(2026, 11, 10, tzinfo=UTC)
        )

        _, result = self._run(now=datetime(2026, 11, 18, 12, 0, tzinfo=UTC))

        self.assertEqual(result["period_start"], datetime(2026, 11, 12, tzinfo=UTC).isoformat())
        self.assertEqual(result["eligible_messages"], 1)
        self.assertEqual(
            [row.period_start.replace(tzinfo=UTC) for row in self.db.query(models.TopicCluster)],
            [datetime(2026, 11, 12, tzinfo=UTC)],
        )

    def test_an_embedding_failure_leaves_the_previous_clusters_in_place(self):
        # The worker records a failed run and commits; a `DELETE` left pending by
        # the failed attempt would then wipe a window nobody rebuilt.
        self.db.add(
            models.TopicCluster(
                company_id=self.company.id,
                period_start=WINDOW_START,
                cluster_key="c1",
                label="Pricing",
                sampled_messages=3,
                eligible_messages=3,
            )
        )
        self.db.commit()
        self._seed_week()

        def unavailable(texts):
            raise RuntimeError("embedding provider down")

        with self.assertRaises(RuntimeError):
            self._run(embeddings=unavailable)
        self.db.commit()

        rows = self.db.query(models.TopicCluster).all()
        self.assertEqual([row.label for row in rows], ["Pricing"])

    def test_two_runs_over_the_same_input_produce_the_same_clusters(self):
        self._seed_week()

        _, first = self._run()
        first_rows = self.db.query(models.TopicCluster).order_by(
            models.TopicCluster.cluster_key
        ).all()
        first_centroids = [list(map(float, row.centroid)) for row in first_rows]
        _, second = self._run()
        second_rows = self.db.query(models.TopicCluster).order_by(
            models.TopicCluster.cluster_key
        ).all()

        self.assertEqual(first["clusters"], second["clusters"])
        self.assertEqual(
            [row.cluster_key for row in second_rows], ["c1", "c2"]
        )
        self.assertEqual(
            [list(map(float, row.centroid)) for row in second_rows], first_centroids
        )
        # A rebuild replaces the window instead of adding a second set.
        self.assertEqual(len(second_rows), 2)
        self.assertEqual([row.label for row in second_rows], ["Pricing and plans", "Refunds and returns"])
        self.assertEqual(
            [cluster["message_count"] for cluster in second["clusters"]], [3, 3]
        )

    def test_a_failing_llm_still_writes_rows(self):
        self._seed_week()

        _, result = self._run(llm=_FakeLLM(error=RuntimeError("provider down")))

        rows = self.db.query(models.TopicCluster).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(result["clusters"]), 2)
        for row in rows:
            self.assertTrue(row.label)
            self.assertLessEqual(len(row.label), topics.MAX_LABEL_LENGTH)
            self.assertIsNone(row.summary)

    def test_a_malformed_reply_falls_back_to_the_clusters_own_terms(self):
        self._seed_week()

        _, result = self._run(llm=_FakeLLM(reply="Sorry, I cannot help with that."))

        labels = [cluster["label"] for cluster in result["clusters"]]
        self.assertEqual(len(labels), 2)
        self.assertIn("Price", labels[0])
        self.assertIn("Refund", labels[1])
        self.assertEqual(
            self.db.query(models.TopicCluster).filter(models.TopicCluster.summary.isnot(None)).count(),
            0,
        )

    def test_labels_and_summaries_are_validated_and_bounded(self):
        self._seed_week()
        reply = json.dumps(
            [
                {"label": "pricing " * 40, "summary": "line\nbreak " * 40},
                {"label": "Refunds", "summary": "Visitors want their money back."},
            ]
        )

        _, result = self._run(llm=_FakeLLM(reply=reply))

        first, second = result["clusters"]
        self.assertLessEqual(len(first["label"]), topics.MAX_LABEL_LENGTH)
        self.assertNotIn("\n", first["summary"])
        self.assertLessEqual(len(first["summary"]), topics.MAX_SUMMARY_LENGTH)
        self.assertEqual(second["summary"], "Visitors want their money back.")

    def test_another_companys_questions_never_enter_a_run(self):
        other = _company(self.db, "Other")
        other_site = _website(self.db, other, "theirs")
        _message(
            self.db,
            other_site,
            "SECRET other tenant question about refunds",
            WINDOW_START + timedelta(days=2),
        )
        self._seed_week()

        llm, result = self._run()

        self.assertEqual(result["eligible_messages"], 6)
        self.assertNotIn("SECRET", llm.calls[0][1].content)

    def test_a_truncated_sample_still_reports_the_eligible_total(self):
        self._seed_week()

        _, result = self._run(max_messages=2)

        self.assertEqual(result["sampled_messages"], 2)
        self.assertEqual(result["eligible_messages"], 6)
        self.assertTrue(result["truncated"])

    def test_only_visitor_questions_are_clustered(self):
        self._seed_week()
        _message(
            self.db,
            self.website,
            "The assistant's own reply",
            WINDOW_START + timedelta(days=2),
            role="assistant",
        )
        _message(
            self.db, self.website, "   ", WINDOW_START + timedelta(days=2, minutes=1)
        )

        _, result = self._run()

        self.assertEqual(result["eligible_messages"], 6)
        self.assertEqual(result["sampled_messages"], 6)

    def test_an_empty_window_clears_the_rows_it_used_to_have(self):
        self.db.add(
            models.TopicCluster(
                company_id=self.company.id,
                period_start=WINDOW_START,
                cluster_key="c1",
                label="Pricing",
                sampled_messages=3,
                eligible_messages=3,
            )
        )
        self.db.commit()

        _, result = self._run()

        self.assertEqual(result["clusters"], [])
        self.assertEqual(result["eligible_messages"], 0)
        self.assertEqual(self.db.query(models.TopicCluster).count(), 0)

    def test_naming_is_one_call_with_a_fixed_prompt_and_a_bounded_sample(self):
        for position, question in enumerate(PRICING * 2):
            _message(
                self.db,
                self.website,
                question,
                WINDOW_START + timedelta(days=1, minutes=position),
            )

        llm, _ = self._run()

        self.assertEqual(len(llm.calls), 1)
        system, human = llm.calls[0]
        self.assertEqual(system.content, topics.NAMING_SYSTEM_PROMPT)
        self.assertIn("Cluster 1:", human.content)
        # Six near-identical questions, one cluster: the prompt quotes only the
        # first `NAMING_SAMPLES` of them.
        self.assertEqual(human.content.count("\n- "), topics.NAMING_SAMPLES)


class TopicRunLifecycleTests(unittest.TestCase):
    """The durable claim that makes a window build once, and can be recovered."""

    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.website = _website(self.db, self.company)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_week(self):
        for position, question in enumerate(PRICING + REFUNDS):
            _message(
                self.db,
                self.website,
                question,
                WINDOW_START + timedelta(days=1, minutes=position),
            )

    def _setting(self, key, value):
        self.db.add(
            models.Setting(company_id=self.company.id, key=key, value=value)
        )
        self.db.commit()

    def test_a_completed_window_is_never_rebuilt(self):
        run = topics.claim_run(self.db, self.company.id, WINDOW_START)
        topics.complete_run(self.db, run)

        self.assertIsNone(topics.claim_run(self.db, self.company.id, WINDOW_START))
        self.assertTrue(topics.window_settled(self.db, self.company.id, WINDOW_START))

    def test_a_live_claim_is_not_taken_over(self):
        topics.claim_run(self.db, self.company.id, WINDOW_START)

        again = topics.claim_run(
            self.db,
            self.company.id,
            WINDOW_START,
            stale_before=datetime.now(UTC) - timedelta(minutes=5),
        )

        self.assertIsNone(again)
        self.assertEqual(self.db.query(models.TopicClusterRun).count(), 1)

    def test_a_stale_claim_is_taken_over_in_place(self):
        run = topics.claim_run(self.db, self.company.id, WINDOW_START)

        taken = topics.claim_run(
            self.db,
            self.company.id,
            WINDOW_START,
            stale_before=datetime.now(UTC) + timedelta(minutes=1),
        )

        self.assertIsNotNone(taken)
        self.assertEqual(taken.id, run.id)
        self.assertEqual(taken.status, "running")
        self.assertEqual(self.db.query(models.TopicClusterRun).count(), 1)

    def test_a_failed_run_can_be_retried(self):
        run = topics.claim_run(self.db, self.company.id, WINDOW_START)
        topics.fail_run(self.db, run, RuntimeError("provider down"))

        self.assertFalse(topics.window_settled(self.db, self.company.id, WINDOW_START))
        again = topics.claim_run(self.db, self.company.id, WINDOW_START)

        self.assertIsNotNone(again)
        self.assertEqual(again.status, "running")
        self.assertIsNone(again.error)
        self.assertEqual(self.db.query(models.TopicClusterRun).count(), 1)

    def test_recover_stale_runs_marks_only_dead_claims(self):
        dead = topics.claim_run(self.db, self.company.id, WINDOW_START)
        dead.claimed_at = datetime.now(UTC) - timedelta(hours=2)
        self.db.commit()
        live = topics.claim_run(
            self.db, self.company.id, WINDOW_START + timedelta(days=7)
        )

        recovered = topics.recover_stale_runs(self.db)

        self.assertEqual(
            [(company_id, _aware(period_start)) for company_id, period_start in recovered],
            [(self.company.id, WINDOW_START)],
        )
        self.assertEqual(dead.status, "failed")
        self.assertIn("stale", dead.error)
        self.assertEqual(live.status, "running")

    def test_the_scheduled_window_is_the_week_that_just_ended(self):
        start, end = topics.previous_window(datetime(2026, 11, 18, 12, 0, tzinfo=UTC))

        self.assertEqual(start, datetime(2026, 11, 9, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 11, 16, tzinfo=UTC))

    def test_run_window_commits_the_clusters_with_the_completion_status(self):
        self._seed_week()
        fake = _FakeLLM()
        with patch.object(
            topics, "embed_texts", side_effect=_stub_embeddings
        ) as embed, patch.object(topics, "get_llm", lambda **_: fake):
            result = topics.run_window(
                self.db, self.company.id, WINDOW_START, WINDOW_START + timedelta(days=7)
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["clusters"], 2)
        run = self.db.query(models.TopicClusterRun).one()
        self.assertEqual(run.status, "completed")
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(self.db.query(models.TopicCluster).count(), 2)

        # A duplicate job loses the claim and spends nothing.
        with patch.object(
            topics, "embed_texts", side_effect=AssertionError("no provider call")
        ):
            second = topics.run_window(
                self.db, self.company.id, WINDOW_START, WINDOW_START + timedelta(days=7)
            )
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(embed.call_count, 1)

    def test_a_failed_run_keeps_the_previous_clusters_and_is_retryable(self):
        self._seed_week()
        self.db.add(
            models.TopicCluster(
                company_id=self.company.id,
                period_start=WINDOW_START,
                cluster_key="c1",
                label="Pricing",
                sampled_messages=3,
                eligible_messages=3,
            )
        )
        self.db.commit()

        def unavailable(texts):
            raise RuntimeError("embedding provider down")

        with patch.object(topics, "embed_texts", side_effect=unavailable), patch.object(
            topics, "get_llm", lambda **_: _FakeLLM()
        ):
            with self.assertRaises(RuntimeError):
                topics.run_window(
                    self.db,
                    self.company.id,
                    WINDOW_START,
                    WINDOW_START + timedelta(days=7),
                )

        run = self.db.query(models.TopicClusterRun).one()
        self.assertEqual(run.status, "failed")
        self.assertIn("embedding provider down", run.error)
        self.assertEqual(
            [row.label for row in self.db.query(models.TopicCluster)], ["Pricing"]
        )

    def test_the_cluster_count_setting_bounds_the_run(self):
        self._setting("topic_cluster_count", "1")
        self._seed_week()

        with patch.object(
            topics, "embed_texts", side_effect=_stub_embeddings
        ), patch.object(topics, "get_llm", lambda **_: _FakeLLM()):
            result = topics.run_window(
                self.db, self.company.id, WINDOW_START, WINDOW_START + timedelta(days=7)
            )

        self.assertEqual(result["clusters"], 1)
        self.assertEqual(self.db.query(models.TopicCluster).count(), 1)

    def test_the_cluster_count_setting_is_clamped(self):
        self._setting("topic_cluster_count", "1")  # a row must exist to be updated
        for raw, expected in (
            ("0", 1),
            ("99", topics.MAX_CLUSTERS),
            ("abc", topics.DEFAULT_CLUSTER_COUNT),
            ("", topics.DEFAULT_CLUSTER_COUNT),
        ):
            with self.subTest(raw=raw):
                self.db.query(models.Setting).update(
                    {"value": raw}, synchronize_session=False
                )
                self.db.commit()
                self.assertEqual(
                    topics.cluster_count_for(self.db, self.company.id), expected
                )


class CompletedWindowsTests(unittest.TestCase):
    """The read side only sees intervals every window of which was built."""

    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.start = WINDOW_START
        self.end = WINDOW_START + timedelta(days=14)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _complete(self, period_start, label="Pricing"):
        self.db.add(
            models.TopicClusterRun(
                company_id=self.company.id,
                period_start=period_start,
                status="completed",
                claimed_at=period_start,
                completed_at=period_start,
            )
        )
        self.db.add(
            models.TopicCluster(
                company_id=self.company.id,
                period_start=period_start,
                cluster_key="c1",
                label=label,
                sampled_messages=1,
                eligible_messages=1,
            )
        )
        self.db.commit()

    def test_two_complete_weeks_come_back_in_order(self):
        self._complete(self.start, "First")
        self._complete(self.start + timedelta(days=7), "Second")

        windows = topics.completed_windows(
            self.db, self.company.id, self.start, self.end
        )

        self.assertEqual(
            [_aware(window_start) for window_start, _ in windows],
            [self.start, self.start + timedelta(days=7)],
        )
        self.assertEqual(
            [[row.label for row in clusters] for _, clusters in windows],
            [["First"], ["Second"]],
        )

    def test_a_missing_or_unfinished_window_returns_none(self):
        self._complete(self.start)
        self.assertIsNone(
            topics.completed_windows(self.db, self.company.id, self.start, self.end)
        )

        self.db.add(
            models.TopicClusterRun(
                company_id=self.company.id,
                period_start=self.start + timedelta(days=7),
                status="failed",
                claimed_at=self.start,
            )
        )
        self.db.commit()

        self.assertIsNone(
            topics.completed_windows(self.db, self.company.id, self.start, self.end)
        )

    def test_an_unaligned_partial_or_backwards_interval_returns_none(self):
        self._complete(self.start)
        self._complete(self.start + timedelta(days=7))

        self.assertIsNone(
            topics.completed_windows(
                self.db, self.company.id, self.start + timedelta(days=1), self.end
            )
        )
        self.assertIsNone(
            topics.completed_windows(
                self.db,
                self.company.id,
                self.start,
                self.start + timedelta(days=10),
            )
        )
        self.assertIsNone(
            topics.completed_windows(self.db, self.company.id, self.end, self.start)
        )


if __name__ == "__main__":
    unittest.main()
