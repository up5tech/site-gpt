"""DELETE /api/privacy/conversations/{sid} — derived topic windows go with it.

The conversation's messages are the input the clusters were built from, so
erasing the messages while keeping "Pricing questions" (and its summary) would
leave a readable trace of the text this endpoint promises to delete, and a
`completed` run would tell the worker never to rebuild that week. These tests
drive the real route against a real SQLite database, so the invalidation is
executed rather than asserted from a mock.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import privacy as privacy_api
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db

WINDOW = datetime(2026, 11, 9, tzinfo=UTC)  # Monday, aligned with normalize_period


class EraseConversationTopicsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.User.__table__,
                models.Website.__table__,
                models.ChatMessage.__table__,
                models.ChatFeedback.__table__,
                models.HandoffRequest.__table__,
                models.Contact.__table__,
                models.TopicCluster.__table__,
                models.TopicClusterRun.__table__,
                # M9: the erasure is transactional over the whole session, so
                # the inbox row and the K4 token must go with the messages.
                models.Conversation.__table__,
                models.SessionToken.__table__,
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

    def _message(self, site, session_id, created):
        row = models.ChatMessage(
            website_id=site.id,
            session_id=session_id,
            role="user",
            message="how much does it cost?",
            created_at=created,
            updated_at=created,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _cluster(self, company, period_start, key):
        row = models.TopicCluster(
            company_id=company.id,
            period_start=period_start,
            cluster_key=key,
            label="Pricing",
            sampled_messages=1,
            eligible_messages=1,
            created_at=period_start,
            updated_at=period_start,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _run(self, company, period_start):
        row = models.TopicClusterRun(
            company_id=company.id,
            period_start=period_start,
            status="completed",
            created_at=period_start,
            updated_at=period_start,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _erase(self, session_id, site):
        return self.client.delete(
            f"/api/privacy/conversations/{session_id}",
            params={"website_id": str(site.id)},
        )

    def test_the_erased_weeks_clusters_and_run_are_deleted(self):
        session_id = "s-topics"
        self._message(self.site, session_id, WINDOW + timedelta(days=1))
        self._cluster(self.company, WINDOW, "this-week")
        self._run(self.company, WINDOW)
        # A window the conversation never touched stays.
        self._cluster(self.company, WINDOW - timedelta(days=21), "older")
        self._run(self.company, WINDOW - timedelta(days=21))
        # Another tenant's identical window is never touched.
        self._cluster(self.other, WINDOW, "theirs")

        response = self._erase(session_id, self.site)

        self.assertEqual(response.status_code, 200, response.text)
        deleted = response.json()["deleted"]
        self.assertEqual(deleted["chat_messages"], 1)
        self.assertEqual(deleted["topic_clusters"], 1)
        self.assertEqual(deleted["topic_cluster_runs"], 1)
        self.assertEqual(
            sorted((row.company_id == self.company.id, row.cluster_key) for row in self.db.query(models.TopicCluster)),
            [(False, "theirs"), (True, "older")],
        )
        # The run for the erased week is gone, so the worker may rebuild it; the
        # untouched week keeps its `completed` row.
        self.assertEqual(
            [
                row.period_start.replace(tzinfo=UTC)
                if row.period_start.tzinfo is None
                else row.period_start
                for row in self.db.query(models.TopicClusterRun)
            ],
            [WINDOW - timedelta(days=21)],
        )

    def test_an_already_empty_conversation_invalidates_nothing(self):
        self._cluster(self.company, WINDOW, "this-week")

        response = self._erase("never-existed", self.site)

        self.assertEqual(response.status_code, 200, response.text)
        deleted = response.json()["deleted"]
        self.assertEqual(deleted["chat_messages"], 0)
        self.assertEqual(deleted["topic_clusters"], 0)
        self.assertEqual(self.db.query(models.TopicCluster).count(), 1)

    def test_the_other_tenants_conversation_is_a_404(self):
        session_id = "s-foreign"
        self._message(self.other_site, session_id, WINDOW + timedelta(days=1))
        self._cluster(self.other, WINDOW, "theirs")

        response = self._erase(session_id, self.other_site)

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.db.query(models.TopicCluster).count(), 1)


if __name__ == "__main__":
    unittest.main()
