"""POST /api/privacy/retention — the path the Settings → Privacy buttons use.

The service is covered in `test_retention.py`; this checks the route itself:
`dry_run` defaults to a preview, `dry_run: false` really deletes, the purge is
scoped to the caller's company, and the negative-days guard holds.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import privacy as privacy_api
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db

NOW = datetime.now(UTC)


def _sqlite_foreign_keys(connection, _record):
    """SQLite ignores FKs unless asked; Postgres always enforces them.

    The M10 insight FK's `ON DELETE CASCADE` is what removes the derived row when
    retention expires its conversation (V4-44), so the test turns the same
    enforcement on.
    """
    connection.execute("PRAGMA foreign_keys=ON")


class RetentionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(self.engine, "connect", _sqlite_foreign_keys)
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.User.__table__,
                models.Website.__table__,
                models.ExtraDocument.__table__,
                models.Attachment.__table__,
                models.ChatMessage.__table__,
                models.ChatFeedback.__table__,
                models.HandoffRequest.__table__,
                models.Contact.__table__,
                models.DigestLog.__table__,
                models.Setting.__table__,
                # M8: the purge sweeps derived topic rows with everything else.
                models.TopicCluster.__table__,
                models.TopicClusterRun.__table__,
                # M9: inbox metadata and the K4 token the erasure path removes.
                models.Conversation.__table__,
                models.SessionToken.__table__,
                # M10: the derived insight row cascades with its conversation.
                models.ConversationInsight.__table__,
            ],
        )
        self.db = sessionmaker(bind=self.engine)()
        self.company = models.Company(name="Acme")
        self.other = models.Company(name="Other")
        self.db.add_all([self.company, self.other])
        self.db.commit()
        self.site = self._site(self.company, "mine")
        self.other_site = self._site(self.other, "theirs")
        self.user = SimpleNamespace(id=uuid4(), company_id=self.company.id)

        app = FastAPI()
        app.include_router(privacy_api.router, prefix="/api/privacy")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _site(self, company, name):
        site = models.Website(
            company_id=company.id,
            name=name,
            url=f"https://{name}.test",
            site_map_url="",
        )
        self.db.add(site)
        self.db.commit()
        return site

    def _message(self, site, age_days):
        created = NOW - timedelta(days=age_days)
        row = models.ChatMessage(
            website_id=site.id,
            session_id=f"s-{uuid4().hex[:6]}",
            role="user",
            message="hi",
            created_at=created,
            updated_at=created,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _post(self, **body):
        return self.client.post("/api/privacy/retention", json=body)

    def test_the_default_is_a_preview_that_deletes_nothing(self):
        self._message(self.site, 40)

        response = self._post(retention_days=30)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["deleted"]["chat_messages"], 1)
        self.assertEqual(self.db.query(models.ChatMessage).count(), 1)

    def test_dry_run_false_deletes_and_reports_the_counts(self):
        self._message(self.site, 40)
        kept = self._message(self.site, 1)

        response = self._post(dry_run=False, retention_days=30)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["dry_run"])
        self.assertEqual(body["deleted"]["chat_messages"], 1)
        self.assertEqual(body["total"], 1)
        self.assertEqual(
            [row.id for row in self.db.query(models.ChatMessage).all()], [kept.id]
        )

    def test_the_apply_only_touches_the_callers_company(self):
        self._message(self.site, 40)
        theirs = self._message(self.other_site, 40)

        response = self._post(dry_run=False, retention_days=30)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [row.id for row in self.db.query(models.ChatMessage).all()], [theirs.id]
        )

    def test_a_zero_policy_applies_nothing(self):
        self._message(self.site, 400)

        body = self._post(dry_run=False, retention_days=0).json()

        self.assertEqual(body["total"], 0)
        self.assertIsNone(body["cutoff"])
        self.assertEqual(self.db.query(models.ChatMessage).count(), 1)

    def test_the_apply_cascades_to_an_expired_conversations_insight(self):
        expired = models.Conversation(
            website_id=self.site.id,
            session_id="s-expired",
            state="closed",
            last_message_at=NOW - timedelta(days=40),
            created_at=NOW - timedelta(days=40),
            updated_at=NOW - timedelta(days=40),
        )
        self.db.add(expired)
        self.db.commit()
        self.db.add(
            models.ConversationInsight(
                conversation_id=expired.id,
                status="completed",
                sentiment="negative",
                resolution="unresolved",
                summary="Visitor never got an answer.",
            )
        )
        self.db.commit()

        response = self._post(dry_run=False, retention_days=30)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted"]["conversations"], 1)
        self.assertEqual(self.db.query(models.Conversation).count(), 0)
        self.assertEqual(self.db.query(models.ConversationInsight).count(), 0)

    def test_negative_days_are_rejected(self):
        response = self._post(dry_run=False, retention_days=-1)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("negative", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
