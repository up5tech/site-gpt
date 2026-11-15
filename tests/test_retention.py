"""Retention purge tests (F9).

The property under test is the one that matters for a delete: a row older than
the policy goes, and a row that is not goes nowhere. These run against a real
SQLite database holding only the tables the purge touches, so the filter and the
`DELETE` are the ones production builds — not a mock's opinion of them.
"""

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.db.base import Base
from site_gpt.app.services import retention

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
TABLES = [
    models.Company.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.ChatFeedback.__table__,
    models.HandoffRequest.__table__,
    models.Contact.__table__,
    models.DigestLog.__table__,
    models.Setting.__table__,
]


def _session():
    """An in-memory database with just the tables the purge touches."""
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


def _seed(db, website, company, created_at, session_id="s1"):
    """One row in every purged table, all with the same `created_at`."""
    db.add_all(
        [
            models.ChatMessage(
                website_id=website.id,
                session_id=session_id,
                role="user",
                message="hi",
                created_at=created_at,
                updated_at=created_at,
            ),
            models.ChatFeedback(
                website_id=website.id,
                session_id=session_id,
                rating="up",
                created_at=created_at,
                updated_at=created_at,
            ),
            models.HandoffRequest(
                website_id=website.id,
                session_id=session_id,
                status="pending",
                created_at=created_at,
                updated_at=created_at,
            ),
            models.Contact(
                website_id=website.id,
                session_id=session_id,
                first_name="A",
                last_name="B",
                email="a@b.test",
                created_at=created_at,
                updated_at=created_at,
            ),
        ]
    )
    db.add(
        models.DigestLog(
            company_id=company.id,
            period_start=created_at,
            period_end=created_at + timedelta(days=7),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    db.commit()


def _counts(db):
    return {
        "chat_messages": db.query(models.ChatMessage).count(),
        "chat_feedback": db.query(models.ChatFeedback).count(),
        "handoff_requests": db.query(models.HandoffRequest).count(),
        "contacts": db.query(models.Contact).count(),
        "digest_log": db.query(models.DigestLog).count(),
    }


class ParseTests(unittest.TestCase):
    def test_zero_and_junk_mean_keep_for_ever(self):
        for raw in (None, "", "0", "-5", "abc", "30 days"):
            self.assertEqual(retention.parse_retention_days(raw), 0, raw)

    def test_positive_values_are_read_and_clamped(self):
        self.assertEqual(retention.parse_retention_days("30"), 30)
        self.assertEqual(retention.parse_retention_days(" 7 "), 7)
        self.assertEqual(retention.parse_retention_days(14), 14)
        self.assertEqual(
            retention.parse_retention_days("999999"), retention.MAX_RETENTION_DAYS
        )

    def test_cutoff_matches_the_policy(self):
        self.assertIsNone(retention.cutoff_for(0, NOW))
        self.assertEqual(retention.cutoff_for(30, NOW), NOW - timedelta(days=30))

    def test_naive_now_is_treated_as_utc(self):
        cutoff = retention.cutoff_for(1, datetime(2026, 11, 15, 12, 0))
        self.assertEqual(cutoff, datetime(2026, 11, 14, 12, 0, tzinfo=UTC))


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = _session()
        self.company = _company(self.db)
        self.website = _website(self.db, self.company)
        self.other = _company(self.db, "Other")
        self.other_site = _website(self.db, self.other, "other")

        # 10 days old, 30 days old, and one row exactly at the cutoff.
        self.old = NOW - timedelta(days=10)
        self.older = NOW - timedelta(days=30)
        self.fresh = NOW - timedelta(hours=1)
        _seed(self.db, self.website, self.company, self.old)
        _seed(self.db, self.website, self.company, self.older, session_id="s2")
        _seed(self.db, self.website, self.company, self.fresh, session_id="s3")
        # Another tenant, same age: must never be touched.
        _seed(self.db, self.other_site, self.other, self.older)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_dry_run_counts_without_deleting(self):
        result = retention.purge_company(self.db, self.company.id, days=7, dry_run=True, now=NOW)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["retention_days"], 7)
        self.assertEqual(result["cutoff"], NOW - timedelta(days=7))
        self.assertEqual(
            result["deleted"],
            {
                "chat_messages": 2,
                "chat_feedback": 2,
                "handoff_requests": 2,
                "contacts": 2,
                "digest_log": 2,
            },
        )
        self.assertEqual(result["total"], 10)
        # Nothing was removed: 3 of ours (2 old + 1 fresh) still there.
        self.assertEqual(_counts(self.db)["chat_messages"], 4)

    def test_purge_deletes_only_rows_past_the_cutoff(self):
        result = retention.purge_company(self.db, self.company.id, days=7, dry_run=False, now=NOW)

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["total"], 10)
        self.assertEqual(
            _counts(self.db),
            {
                # one fresh message of ours + the other tenant's row
                "chat_messages": 2,
                "chat_feedback": 2,
                "handoff_requests": 2,
                "contacts": 2,
                "digest_log": 2,
            },
        )
        remaining = {
            row.session_id
            for row in self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.website.id)
            .all()
        }
        self.assertEqual(remaining, {"s3"})

    def test_the_cutoff_row_itself_survives(self):
        # A row created exactly at the cutoff is not older than it.
        _seed(self.db, self.website, self.company, NOW - timedelta(days=7), session_id="edge")
        retention.purge_company(self.db, self.company.id, days=7, dry_run=False, now=NOW)

        survivors = {
            row.session_id
            for row in self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.website.id)
            .all()
        }
        self.assertEqual(survivors, {"s3", "edge"})

    def test_zero_days_is_a_no_op(self):
        result = retention.purge_company(self.db, self.company.id, days=0, dry_run=False, now=NOW)
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["cutoff"])
        self.assertEqual(_counts(self.db)["chat_messages"], 4)

    def test_other_companies_are_never_deleted(self):
        retention.purge_company(self.db, self.other.id, days=7, dry_run=False, now=NOW)
        self.assertEqual(
            self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.website.id)
            .count(),
            3,
        )
        self.assertEqual(
            self.db.query(models.ChatMessage)
            .filter(models.ChatMessage.website_id == self.other_site.id)
            .count(),
            0,
        )

    def test_company_without_websites_reports_zeroes(self):
        lonely = _company(self.db, "Lonely")
        result = retention.purge_company(self.db, lonely.id, days=7, dry_run=False, now=NOW)
        self.assertEqual(result["total"], 0)

    def test_policy_is_read_from_the_setting(self):
        self.db.add(
            models.Setting(company_id=self.company.id, key="retention_days", value="7")
        )
        self.db.commit()

        result = retention.purge_company(self.db, self.company.id, dry_run=True, now=NOW)
        self.assertEqual(result["retention_days"], 7)
        self.assertEqual(result["total"], 10)

    def test_only_companies_with_a_policy_are_scheduled(self):
        self.db.add_all(
            [
                models.Setting(company_id=self.company.id, key="retention_days", value="30"),
                models.Setting(company_id=self.other.id, key="retention_days", value="0"),
            ]
        )
        self.db.commit()

        self.assertEqual(retention.companies_with_policy(self.db), [self.company.id])


if __name__ == "__main__":
    unittest.main()
