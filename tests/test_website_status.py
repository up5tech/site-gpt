"""`websites.status` is the only way to disable a bot without deleting it.

It used to be written by the API and never read, so a disabled website kept
answering visitors, kept handing out widget config and kept accepting leads and
ingest jobs. These tests pin the disabled path on every public endpoint plus the
worker guard, and keep the active path working.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app import models, worker
from site_gpt.app.api import routes
from site_gpt.app.db.session import get_db
from site_gpt.app.services import ratelimit

WEBSITE_URL = "https://customer.example.com"


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        # A list result means "a collection was queried"; a single-row lookup
        # found nothing.
        return None if isinstance(self._result, list) else self._result

    def all(self):
        return self._result if isinstance(self._result, list) else []


def make_website(status):
    """A real Website row (no session needed) so `status` behaves like the DB."""
    return models.Website(
        id=uuid4(),
        url=WEBSITE_URL,
        name="Customer",
        description="",
        site_map_url="https://customer.example.com/sitemap.xml",
        company_id=uuid4(),
        status=status,
    )


class EndpointStatusTests(unittest.TestCase):
    def setUp(self):
        # Chat/ingest are rate limited; keep tests from spending the budget.
        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

        self.site = make_website("inactive")
        self.website_id = str(self.site.id)
        self.user = MagicMock(id=uuid4(), company_id=self.site.company_id)

        def query(model):
            if model is routes.models.Website:
                return FakeQuery(self.site)
            if model is routes.models.Contact:
                return FakeQuery(None)
            if model is routes.models.Setting:
                return FakeQuery([])
            return FakeQuery(self.user)

        self.db = MagicMock()
        self.db.query.side_effect = query

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[routes.get_manager_user] = lambda: self.user
        self.client = TestClient(app)

    def chat(self):
        return self.client.post(
            "/api/chat",
            json={
                "website_id": self.website_id,
                "session_id": "s-1",
                "question": "hello",
            },
        )

    # ---- disabled ----------------------------------------------------------
    def test_chat_is_refused_for_a_disabled_website(self):
        with patch.object(routes, "ask") as ask:
            response = self.chat()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("disabled", response.json()["detail"].lower())
        ask.assert_not_called()

    def test_streaming_chat_is_refused_for_a_disabled_website(self):
        with patch.object(routes, "ask_stream") as ask_stream:
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "website_id": self.website_id,
                    "session_id": "s-1",
                    "question": "hello",
                },
            )
        self.assertEqual(response.status_code, 403, response.text)
        ask_stream.assert_not_called()

    def test_widget_config_is_refused_for_a_disabled_website(self):
        response = self.client.get(
            "/api/widget-config",
            params={"website_id": self.website_id},
            headers={"Origin": WEBSITE_URL},
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_contacts_write_is_refused_for_a_disabled_website(self):
        response = self.client.post(
            "/api/contacts",
            json={
                "website_id": self.website_id,
                "session_id": "s-1",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
            },
            headers={"Origin": WEBSITE_URL},
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.db.add.assert_not_called()

    def test_contacts_read_is_refused_for_a_disabled_website(self):
        response = self.client.get(
            "/api/contacts/s-1",
            params={"website_id": self.website_id},
            headers={"Origin": WEBSITE_URL},
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_ingest_is_refused_for_a_disabled_website(self):
        with patch.object(routes, "enqueue_job", new=AsyncMock()) as enqueue:
            response = self.client.post(
                "/api/ingest", params={"website_id": self.website_id}
            )
        self.assertEqual(response.status_code, 403, response.text)
        enqueue.assert_not_called()
        self.assertNotEqual(self.site.ingest_status, "processing")

    def test_a_missing_status_does_not_disable_a_working_bot(self):
        # `websites.status` is nullable and predates the switch: NULL/empty
        # means "never set", not "disabled".
        for status in (None, "", "   "):
            with self.subTest(status=status):
                self.site.status = status
                with patch.object(
                    routes, "ask", return_value={"answer": "hi", "sources": []}
                ) as ask:
                    response = self.chat()
                self.assertEqual(response.status_code, 200, response.text)
                ask.assert_called_once()

    def test_every_non_active_status_is_refused(self):
        for status in ("paused", "disabled", "inactive", "Inactive", "ARCHIVED"):
            with self.subTest(status=status):
                self.site.status = status
                with patch.object(routes, "ask") as ask:
                    response = self.chat()
                self.assertEqual(response.status_code, 403, response.text)
                ask.assert_not_called()

    # ---- active ------------------------------------------------------------
    def test_an_active_website_still_answers(self):
        self.site.status = "active"
        with patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ) as ask:
            response = self.chat()
        self.assertEqual(response.status_code, 200, response.text)
        ask.assert_called_once()

    def test_active_ingest_still_queues_a_job(self):
        self.site.status = "active"
        with patch.object(routes, "enqueue_job", new=AsyncMock()) as enqueue:
            response = self.client.post(
                "/api/ingest", params={"website_id": self.website_id}
            )
        self.assertEqual(response.status_code, 200, response.text)
        enqueue.assert_awaited_once()


class WorkerStatusTests(unittest.TestCase):
    """A job queued before the website was disabled must not crawl or embed."""

    def run_ingest(self, status):
        site = make_website(status)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = site

        with patch.object(worker, "SessionLocal", return_value=db), patch.object(
            worker, "crawl_website", return_value=[]
        ) as crawl:
            asyncio.run(worker.handle_ingest({"website_id": str(site.id)}))

        return site, db, crawl

    def test_disabled_website_is_skipped(self):
        site, db, crawl = self.run_ingest("inactive")
        crawl.assert_not_called()
        self.assertNotEqual(site.ingest_status, "processing")
        db.commit.assert_not_called()

    def test_active_website_is_ingested(self):
        site, db, crawl = self.run_ingest("active")
        crawl.assert_called_once()


if __name__ == "__main__":
    unittest.main()
