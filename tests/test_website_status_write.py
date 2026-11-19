"""The enabled/disabled switch must survive the write paths.

Browsers send whatever the form holds, so the create/edit endpoints normalise
`status` and the chat guard accepts a NULL/empty status as enabled. Otherwise a
working bot could be silently disabled by a form payload or by a row that
predates the switch.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import routes
from site_gpt.app.api import website as website_api
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db

# Exactly what the Websites modal sends for an enabled site (Websites.tsx:
# Select with initialValue='active').
FORM_PAYLOAD = {
    "name": "Customer",
    "url": "https://example.com",
    "description": "Docs site",
    "site_map_url": "https://example.com/sitemap.xml",
    "status": "active",
}


class WebsiteStatusWriteTests(unittest.TestCase):
    def setUp(self):
        # StaticPool: the endpoints run in a threadpool and must see the same
        # in-memory database the tables were created in.
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Website.__table__,
                models.WebsitePage.__table__,
                models.Setting.__table__,
                # The chat handlers read the inbox state (V3-43).
                models.Conversation.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.company = models.Company(name="Customer", description="")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

        app = FastAPI()
        app.include_router(website_api.router, prefix="/api/websites")
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_manager_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=self.company.id
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create(self, payload=None):
        return self.client.post(
            "/api/websites/", json=dict(FORM_PAYLOAD if payload is None else payload)
        )

    def chat(self, website_id):
        with patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ) as ask:
            response = self.client.post(
                "/api/chat",
                json={
                    "website_id": str(website_id),
                    "session_id": "s-1",
                    "question": "hello",
                },
            )
        return response, ask

    # ---- create path -------------------------------------------------------
    def test_the_form_payload_creates_an_enabled_website(self):
        response = self.create()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "active")

        # And the guard actually serves it.
        chat, ask = self.chat(response.json()["id"])
        self.assertEqual(chat.status_code, 200, chat.text)
        ask.assert_called_once()

    def test_a_payload_without_status_defaults_to_enabled(self):
        payload = {k: v for k, v in FORM_PAYLOAD.items() if k != "status"}

        created = self.create(payload)

        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["status"], "active")
        chat, _ = self.chat(created.json()["id"])
        self.assertEqual(chat.status_code, 200, chat.text)

    def test_status_is_normalised_on_create(self):
        for sent in ("ACTIVE", " Active ", "Active"):
            with self.subTest(sent=sent):
                response = self.create({**FORM_PAYLOAD, "status": sent})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "active")
                chat, _ = self.chat(response.json()["id"])
                self.assertEqual(chat.status_code, 200, chat.text)

    def test_an_inactive_payload_creates_a_disabled_website(self):
        response = self.create({**FORM_PAYLOAD, "status": "inactive"})

        self.assertEqual(response.json()["status"], "inactive")
        chat, ask = self.chat(response.json()["id"])
        self.assertEqual(chat.status_code, 403, chat.text)
        ask.assert_not_called()

    # ---- edit path ---------------------------------------------------------
    def test_editing_status_to_inactive_disables_the_bot(self):
        website_id = self.create().json()["id"]

        updated = self.client.put(
            f"/api/websites/{website_id}", json={"status": "Inactive"}
        )

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "inactive")
        chat, _ = self.chat(website_id)
        self.assertEqual(chat.status_code, 403, chat.text)

        # ... and editing it back re-enables the same site.
        self.client.put(f"/api/websites/{website_id}", json={"status": "active"})
        chat, _ = self.chat(website_id)
        self.assertEqual(chat.status_code, 200, chat.text)

    def test_an_edit_without_status_keeps_the_current_one(self):
        website_id = self.create().json()["id"]

        updated = self.client.put(
            f"/api/websites/{website_id}", json={"description": "new description"}
        )

        self.assertEqual(updated.json()["status"], "active")
        chat, _ = self.chat(website_id)
        self.assertEqual(chat.status_code, 200, chat.text)

    # ---- rows that predate the switch --------------------------------------
    def test_a_legacy_row_without_status_still_serves(self):
        legacy = models.Website(
            url="https://old.example.com",
            name="Legacy",
            site_map_url="https://old.example.com/sitemap.xml",
            company_id=self.company.id,
            status=None,
        )
        self.db.add(legacy)
        self.db.commit()
        self.db.refresh(legacy)

        chat, ask = self.chat(legacy.id)

        self.assertEqual(chat.status_code, 200, chat.text)
        ask.assert_called_once()


if __name__ == "__main__":
    unittest.main()
