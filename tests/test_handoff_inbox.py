"""V3-45: a handoff click becomes a queue entry only when the inbox is on.

Three properties carry the task, and each is a way the two features could
disagree with each other:

* a company with `live_inbox_enabled=true` gets one waiting conversation (created
  or reused) from the same click that stores the handoff row — one row, one
  email, one event, and the event names the queue entry additively;
* a company with the flag off keeps the V2.1 path exactly: the row, the email
  and the event, and **no** `conversations` row for a queue it does not run;
* an agent claiming or closing the conversation moves the `/handoffs` row with
  it, so the callback list cannot ask the team to answer someone twice.
"""

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import handoff as handoff_api
from site_gpt.app.api import inbox as inbox_api
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import conversations, ratelimit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
    models.Contact.__table__,
    models.HandoffRequest.__table__,
    models.Setting.__table__,
]


class HandoffInboxTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.db.add(self.company)
        self.db.commit()

        self.site = models.Website(
            company_id=self.company.id,
            name="mine",
            url="https://mine.test",
            site_map_url="",
        )
        self.db.add(self.site)
        self.db.commit()

        self.agent = models.User(
            company_id=self.company.id,
            email="agent@acme.test",
            password_hash="x",
            first_name="agent",
            last_name="Test",
            role="manager",
            status="active",
        )
        self.db.add(self.agent)
        self.db.commit()

        self._setting("handoff_enabled", "true")
        self._live_inbox("true")

        self.emails = []
        self.events = []

        async def fake_email(recipient, subject, body):
            self.emails.append((recipient, subject, body))

        async def fake_event(db, company_id, event, payload):
            self.events.append((str(company_id), event, payload))

        for target, name, replacement in (
            (handoff_api, "send_email_async", fake_email),
            (handoff_api, "emit_event_async", fake_event),
        ):
            patcher = patch.object(target, name, new=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        # The public click is rate-limited per IP in a process-wide window; these
        # tests are about the queue entry, and one file must not spend the budget
        # other handoff tests in the same run rely on.
        limiter = patch.object(ratelimit, "allow", new=AsyncMock(return_value=True))
        limiter.start()
        self.addCleanup(limiter.stop)

        self.app = FastAPI()
        self.app.include_router(handoff_api.router)
        self.app.include_router(inbox_api.router, prefix="/api/inbox")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_manager_user] = lambda: self.agent
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # -- fixtures ---------------------------------------------------------

    def _setting(self, key, value):
        self.db.add(
            models.Setting(company_id=self.company.id, key=key, value=value)
        )
        self.db.commit()

    def _live_inbox(self, value):
        """Only one row per key: replace it when a test flips the flag."""
        row = (
            self.db.query(models.Setting)
            .filter(
                models.Setting.company_id == self.company.id,
                models.Setting.key == "live_inbox_enabled",
            )
            .first()
        )
        if row is None:
            self.db.add(
                models.Setting(
                    company_id=self.company.id,
                    key="live_inbox_enabled",
                    value=value,
                )
            )
        else:
            row.value = value
        self.db.commit()

    def handoff(self, session_id="s1", message=None):
        body = {"website_id": str(self.site.id), "session_id": session_id}
        if message:
            body["message"] = message
        return self.client.post("/api/handoff", json=body)

    def conversation(self, session_id="s1"):
        self.db.expire_all()
        return conversations.conversation_for(self.db, self.site.id, session_id)

    def handoff_row(self, session_id="s1"):
        self.db.expire_all()
        return (
            self.db.query(models.HandoffRequest)
            .filter_by(website_id=self.site.id, session_id=session_id)
            .first()
        )


class InboxEnabledTests(HandoffInboxTestCase):
    def test_one_click_stores_the_row_and_queues_the_session(self):
        response = self.handoff(message="please call me")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(models.HandoffRequest).count(), 1)
        row = self.conversation()
        self.assertIsNotNone(row)
        self.assertEqual(row.state, "waiting")
        self.assertEqual(len(self.emails), 1)
        self.assertEqual([event[1] for event in self.events], ["handoff.requested"])

    def test_the_event_names_the_queue_entry(self):
        response = self.handoff()

        self.assertEqual(response.status_code, 200, response.text)
        _, event, payload = self.events[0]
        self.assertEqual(event, "handoff.requested")
        self.assertEqual(payload["handoff_id"], response.json()["id"])
        self.assertEqual(payload["website_id"], str(self.site.id))
        self.assertEqual(payload["session_id"], "s1")
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["conversation_id"], str(self.conversation().id))
        self.assertEqual(payload["conversation_state"], "waiting")

    def test_a_second_click_reuses_the_row_and_the_session(self):
        first = self.handoff()
        second = self.handoff()

        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(self.db.query(models.HandoffRequest).count(), 1)
        self.assertEqual(self.db.query(models.Conversation).count(), 1)
        # A pending request is not re-emailed or re-emitted on every click.
        self.assertEqual(len(self.emails), 1)
        self.assertEqual(len(self.events), 1)

    def test_an_existing_bot_session_is_reused_not_duplicated(self):
        existing = conversations.ensure_conversation(self.db, self.site.id, "s1")
        self.db.commit()

        response = self.handoff()

        self.assertEqual(response.status_code, 200, response.text)
        row = self.conversation()
        self.assertEqual(row.id, existing.id)
        self.assertEqual(row.state, "waiting")
        self.assertEqual(self.db.query(models.Conversation).count(), 1)

    def test_an_agent_claim_moves_the_handoff_row_to_accepted(self):
        self.handoff()
        conversation = self.conversation()

        response = self.client.post(
            f"/api/inbox/conversations/{conversation.id}/claim"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.handoff_row().status, "accepted")

    def test_closing_the_session_closes_the_handoff_row(self):
        self.handoff()
        conversation = self.conversation()
        self.client.post(f"/api/inbox/conversations/{conversation.id}/claim")

        response = self.client.post(
            f"/api/inbox/conversations/{conversation.id}/close"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.handoff_row().status, "closed")

    def test_releasing_puts_the_handoff_row_back_to_pending(self):
        self.handoff()
        conversation = self.conversation()
        self.client.post(f"/api/inbox/conversations/{conversation.id}/claim")

        response = self.client.post(
            f"/api/inbox/conversations/{conversation.id}/release"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.handoff_row().status, "pending")


class InboxDisabledTests(HandoffInboxTestCase):
    """With the flag off the click is the V2.1 path, unchanged."""

    def setUp(self):
        super().setUp()
        self._live_inbox("false")

    def test_the_row_and_the_email_still_happen(self):
        response = self.handoff(message="call me")

        self.assertEqual(response.status_code, 200, response.text)
        row = self.handoff_row()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.message, "call me")
        self.assertEqual(len(self.emails), 1)

    def test_no_queue_entry_is_created(self):
        self.handoff()

        self.assertIsNone(self.conversation())
        self.assertEqual(self.db.query(models.Conversation).count(), 0)

    def test_the_event_keeps_its_v2_1_shape(self):
        self.handoff()

        _, event, payload = self.events[0]
        self.assertEqual(event, "handoff.requested")
        self.assertEqual(
            set(payload),
            {"handoff_id", "website_id", "session_id", "status"},
        )


class HandoffDisabledTests(HandoffInboxTestCase):
    def test_the_public_endpoint_still_answers_404(self):
        self.db.query(models.Setting).filter_by(key="handoff_enabled").delete()
        self.db.commit()
        self._setting("handoff_enabled", "false")

        response = self.handoff()

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.db.query(models.HandoffRequest).count(), 0)
        self.assertEqual(self.db.query(models.Conversation).count(), 0)
        self.assertEqual(self.emails, [])
        self.assertEqual(self.events, [])
