"""V3-41 agent inbox: scoping, the claim race, transitions and the queue read.

The inbox is addressed by conversation UUID, so three properties carry the
feature and are easy to regress:

* a conversation is only reachable through its own company's website — a foreign
  UUID is a 404, and the same `session_id` on two websites stays two entries;
* a claim is exclusive — `FOR UPDATE SKIP LOCKED` means one agent wins and the
  other is answered with a 409, never with the same session;
* every state move goes through `services/inbox.py` → `services/conversations.py`;
  a route cannot write a state, and an invalid move is a 409 rather than a
  corrupted queue.

SQLite ignores `FOR UPDATE`, so the statement shape is pinned against the
Postgres dialect here and the real two-connection race is verified on Postgres.
"""

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import handoff as handoff_api
from site_gpt.app.api import inbox as inbox_api
from site_gpt.app.api import setting as setting_api
from site_gpt.app.core.auth import get_admin_user, get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import conversations, inbox

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.TenantAuditLog.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
    models.Contact.__table__,
    models.HandoffRequest.__table__,
    models.Setting.__table__,
]

INBOX_SOURCE = (
    Path(__file__).resolve().parents[1] / "src/site_gpt/app/api/inbox.py"
)


class InboxTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.other_company = models.Company(name="Other")
        self.db.add_all([self.company, self.other_company])
        self.db.commit()

        self.site = self._site(self.company, "mine")
        self.other_site = self._site(self.other_company, "theirs")

        self.agent = self._user(self.company, "agent@acme.test", "manager")
        self.teammate = self._user(self.company, "mate@acme.test", "manager")
        self.viewer = self._user(self.company, "viewer@acme.test", "user")
        self.admin = self._user(self.company, "boss@acme.test", "admin")
        self.outsider = self._user(self.other_company, "spy@other.test", "manager")

        self._setting("live_inbox_enabled", "true")
        self._setting("handoff_enabled", "true")
        self.actor = self.agent

        # Action routes hand their notification to a daemon publisher thread;
        # unit tests must not open a Redis connection for it.
        publisher = patch.object(inbox, "publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # -- fixtures ---------------------------------------------------------

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

    def _user(self, company, email, role):
        user = models.User(
            company_id=company.id,
            email=email,
            password_hash="x",
            first_name=email.split("@")[0],
            last_name="Test",
            role=role,
            status="active",
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _setting(self, key, value, company=None):
        self.db.add(
            models.Setting(
                company_id=(company or self.company).id, key=key, value=value
            )
        )
        self.db.commit()

    def _conversation(
        self, site=None, session_id="s1", state="waiting", last=None, assigned=None
    ):
        site = site or self.site
        moment = last or NOW
        row = models.Conversation(
            website_id=site.id,
            session_id=session_id,
            state=state,
            assigned_user_id=assigned.id if assigned is not None else None,
            claimed_at=moment if assigned is not None else None,
            closed_at=moment if state == "closed" else None,
            last_message_at=moment,
            created_at=moment,
            updated_at=moment,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _message(self, site=None, session_id="s1", body="what?", role="user", when=None):
        site = site or self.site
        moment = when or NOW
        row = models.ChatMessage(
            website_id=site.id,
            session_id=session_id,
            role=role,
            message=body,
            created_at=moment,
            updated_at=moment,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _client(self, actor=None):
        app = FastAPI()
        app.include_router(inbox_api.router, prefix="/api/inbox")
        self.actor = actor or self.agent
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_manager_user] = lambda: self.actor
        return TestClient(app)


class DisabledInboxTests(InboxTestCase):
    """With `live_inbox_enabled=false` the agent surface does not exist."""

    def setUp(self):
        super().setUp()
        self._setting("live_inbox_enabled", "false")
        self.row = self._conversation()
        self.client = self._client()

    def test_the_queue_is_a_404(self):
        response = self.client.get("/api/inbox/conversations")

        self.assertEqual(response.status_code, 404, response.text)

    def test_a_detail_read_is_a_404(self):
        response = self.client.get(f"/api/inbox/conversations/{self.row.id}")

        self.assertEqual(response.status_code, 404, response.text)

    def test_an_action_is_a_404_and_changes_nothing(self):
        response = self.client.post(
            f"/api/inbox/conversations/{self.row.id}/claim"
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.db.refresh(self.row)
        self.assertEqual(self.row.state, "waiting")

    def test_the_public_handoff_still_works(self):
        # The inbox is off, but the visitor's "talk to a human" click must keep
        # producing its V2.1 handoff row — and no queue entry for a queue this
        # company does not run (`s9` is a fresh session; `s1` is this fixture's).
        app = FastAPI()
        app.include_router(handoff_api.router)
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)

        with patch.object(handoff_api, "send_email_async", new=AsyncMock()), patch.object(
            handoff_api, "emit_event_async", new=AsyncMock()
        ):
            response = client.post(
                "/api/handoff",
                json={"website_id": str(self.site.id), "session_id": "s9"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(models.HandoffRequest).count(), 1)
        self.db.expire_all()
        self.assertIsNone(
            conversations.conversation_for(self.db, self.site.id, "s9")
        )


class StatusTests(InboxTestCase):
    """The console's navigation reads the flag without hitting a 404 surface."""

    def test_a_manager_reads_the_flag(self):
        response = self._client().get("/api/inbox/status")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"enabled": True})

    def test_off_answers_false_instead_of_404(self):
        self._setting("live_inbox_enabled", "false")

        response = self._client().get("/api/inbox/status")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])


class LiveInboxToggleTests(InboxTestCase):
    """Settings is where the console is switched on, for an admin only."""

    def setUp(self):
        super().setUp()
        row = (
            self.db.query(models.Setting)
            .filter(
                models.Setting.company_id == self.company.id,
                models.Setting.key == "live_inbox_enabled",
            )
            .first()
        )
        row.value = "false"
        self.db.commit()

        app = FastAPI()
        app.include_router(inbox_api.router, prefix="/api/inbox")
        app.include_router(setting_api.router, prefix="/api/settings")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_manager_user] = lambda: self.agent
        app.dependency_overrides[get_admin_user] = lambda: self.admin
        self.client = TestClient(app)

    def put(self, value):
        return self.client.put(
            "/api/settings/",
            json=[{"key": "live_inbox_enabled", "value": value}],
        )

    def test_an_admin_turns_the_console_on_and_the_status_follows(self):
        self.assertFalse(self.client.get("/api/inbox/status").json()["enabled"])

        response = self.put("true")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.client.get("/api/inbox/status").json()["enabled"])
        self.assertTrue(inbox.enabled(self.db, self.company.id))
        # Upsert, not a second row: the status read must stay unambiguous.
        self.assertEqual(
            self.db.query(models.Setting)
            .filter_by(company_id=self.company.id, key="live_inbox_enabled")
            .count(),
            1,
        )

    def test_turning_it_off_hides_the_surface_again(self):
        self.assertEqual(self.put("true").status_code, 200)

        response = self.put("false")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.client.get("/api/inbox/status").json()["enabled"])
        self.assertEqual(
            self.client.get("/api/inbox/conversations").status_code, 404
        )


class InsightBadgeTests(InboxTestCase):
    """V4-43: the queue and the detail read the stored insight labels."""

    def _insight(self, conversation, sentiment=None, resolution=None, summary=None):
        row = models.ConversationInsight(
            conversation_id=conversation.id,
            status="completed",
            sentiment=sentiment,
            resolution=resolution,
            summary=summary,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_the_queue_and_the_detail_carry_the_insight(self):
        row = self._conversation()
        self._insight(
            row,
            sentiment="frustrated",
            resolution="escalated",
            summary="Visitor waited for a human.",
        )
        client = self._client()

        item = client.get("/api/inbox/conversations").json()["items"][0]
        self.assertEqual(item["sentiment"], "frustrated")
        self.assertEqual(item["resolution"], "escalated")
        self.assertEqual(item["summary"], "Visitor waited for a human.")

        detail = client.get(f"/api/inbox/conversations/{row.id}").json()
        self.assertEqual(detail["sentiment"], "frustrated")
        self.assertEqual(detail["resolution"], "escalated")
        self.assertEqual(detail["summary"], "Visitor waited for a human.")

    def test_a_conversation_without_an_insight_reports_nulls(self):
        self._conversation()

        item = self._client().get("/api/inbox/conversations").json()["items"][0]

        self.assertIsNone(item["sentiment"])
        self.assertIsNone(item["resolution"])
        self.assertIsNone(item["summary"])

    def test_insight_labels_never_leak_across_companies(self):
        mine = self._conversation()
        theirs = self._conversation(site=self.other_site, session_id="s2")
        self._insight(
            theirs, sentiment="positive", resolution="resolved"
        )
        client = self._client()

        body = client.get("/api/inbox/conversations").json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["id"], str(mine.id))
        self.assertIsNone(body["items"][0]["sentiment"])
        # The foreign conversation id stays a 404, as it did before V4-43.
        response = client.get(f"/api/inbox/conversations/{theirs.id}")
        self.assertEqual(response.status_code, 404, response.text)


class ClaimTests(InboxTestCase):
    def test_an_agent_claims_a_waiting_conversation(self):
        row = self._conversation()
        client = self._client()

        response = client.post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "human")
        self.assertEqual(body["assigned_user_id"], str(self.agent.id))
        self.assertIsNotNone(body["claimed_at"])
        self.db.refresh(row)
        self.assertEqual(row.state, "human")

    def test_the_loser_of_a_claim_race_is_a_409(self):
        row = self._conversation()
        self._client().post(f"/api/inbox/conversations/{row.id}/claim")

        response = self._client(self.teammate).post(
            f"/api/inbox/conversations/{row.id}/claim"
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(row)
        self.assertEqual(row.assigned_user_id, self.agent.id)

    def test_a_row_locked_by_another_claim_is_a_409(self):
        # `SKIP LOCKED` returns nothing while another transaction holds the row;
        # the route must not fall back to a plain read and claim it anyway.
        row = self._conversation()
        client = self._client()
        locked = SimpleNamespace(first=lambda: None)

        with patch.object(inbox, "waiting_claim_query", lambda *a, **k: locked):
            response = client.post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(row)
        self.assertEqual(row.state, "waiting")
        self.assertIsNone(row.assigned_user_id)

    def test_claiming_the_same_conversation_twice_is_idempotent(self):
        row = self._conversation()
        client = self._client()
        client.post(f"/api/inbox/conversations/{row.id}/claim")

        response = client.post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "human")

    def test_a_bot_conversation_cannot_be_claimed(self):
        row = self._conversation(state="bot")

        response = self._client().post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(row)
        self.assertEqual(row.state, "bot")

    def test_a_closed_conversation_cannot_be_claimed(self):
        row = self._conversation(state="closed")

        response = self._client().post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(response.status_code, 409, response.text)


class ScopeTests(InboxTestCase):
    def test_a_foreign_conversation_uuid_is_a_404(self):
        row = self._conversation(site=self.other_site, session_id="s1")
        client = self._client()

        for method, path in (
            ("get", f"/api/inbox/conversations/{row.id}"),
            ("post", f"/api/inbox/conversations/{row.id}/claim"),
            ("post", f"/api/inbox/conversations/{row.id}/release"),
            ("post", f"/api/inbox/conversations/{row.id}/close"),
            ("post", f"/api/inbox/conversations/{row.id}/assign"),
        ):
            kwargs = {"json": {"user_id": str(self.agent.id)}} if path.endswith(
                "assign"
            ) else {}
            response = getattr(client, method)(path, **kwargs)
            self.assertEqual(response.status_code, 404, f"{path}: {response.text}")

        self.db.refresh(row)
        self.assertEqual(row.state, "waiting")

    def test_the_list_only_contains_the_callers_company(self):
        self._conversation(site=self.site, session_id="mine")
        self._conversation(site=self.other_site, session_id="theirs")

        response = self._client().get("/api/inbox/conversations")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["session_id"], "mine")

    def test_one_session_id_on_two_websites_resolves_by_uuid(self):
        # Two websites of the same company: the session id is not the identity,
        # the conversation UUID is.
        second_site = self._site(self.company, "second")
        mine = self._conversation(site=self.site, session_id="shared")
        other = self._conversation(site=second_site, session_id="shared")

        self.assertNotEqual(mine.id, other.id)
        response = self._client().post(f"/api/inbox/conversations/{other.id}/claim")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["website_id"], str(second_site.id))
        self.db.refresh(mine)
        self.assertEqual(mine.state, "waiting")
        self.db.refresh(other)
        self.assertEqual(other.state, "human")

    def test_filtering_by_a_foreign_website_is_a_404(self):
        response = self._client().get(
            "/api/inbox/conversations", params={"website_id": str(self.other_site.id)}
        )

        self.assertEqual(response.status_code, 404, response.text)


class ReleaseTests(InboxTestCase):
    def test_the_holder_releases_the_conversation(self):
        row = self._conversation(state="human", assigned=self.agent)

        response = self._client().post(f"/api/inbox/conversations/{row.id}/release")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "waiting")
        self.assertIsNone(body["assigned_user_id"])
        self.assertIsNone(body["claimed_at"])

    def test_another_manager_cannot_release_someone_elses_claim(self):
        row = self._conversation(state="human", assigned=self.agent)

        response = self._client(self.teammate).post(
            f"/api/inbox/conversations/{row.id}/release"
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(row)
        self.assertEqual(row.assigned_user_id, self.agent.id)

    def test_an_admin_can_override_the_holder(self):
        row = self._conversation(state="human", assigned=self.agent)

        response = self._client(self.admin).post(
            f"/api/inbox/conversations/{row.id}/release"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "waiting")

    def test_a_waiting_conversation_cannot_be_released(self):
        row = self._conversation()

        response = self._client().post(f"/api/inbox/conversations/{row.id}/release")

        self.assertEqual(response.status_code, 409, response.text)


class AssignTests(InboxTestCase):
    def test_a_waiting_conversation_can_be_assigned_to_a_teammate(self):
        row = self._conversation()

        response = self._client().post(
            f"/api/inbox/conversations/{row.id}/assign",
            json={"user_id": str(self.teammate.id)},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "human")
        self.assertEqual(body["assigned_user_id"], str(self.teammate.id))
        self.db.refresh(row)
        self.assertEqual(row.assigned_user_id, self.teammate.id)

    def test_assigning_to_a_non_agent_is_a_404(self):
        row = self._conversation()

        response = self._client().post(
            f"/api/inbox/conversations/{row.id}/assign",
            json={"user_id": str(self.viewer.id)},
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.db.refresh(row)
        self.assertEqual(row.state, "waiting")

    def test_assigning_to_a_foreign_user_is_a_404(self):
        row = self._conversation()

        response = self._client().post(
            f"/api/inbox/conversations/{row.id}/assign",
            json={"user_id": str(self.outsider.id)},
        )

        self.assertEqual(response.status_code, 404, response.text)

    def test_a_closed_conversation_cannot_be_assigned(self):
        row = self._conversation(state="closed")

        response = self._client().post(
            f"/api/inbox/conversations/{row.id}/assign",
            json={"user_id": str(self.teammate.id)},
        )

        self.assertEqual(response.status_code, 409, response.text)


class CloseTests(InboxTestCase):
    def test_the_holder_closes_the_conversation(self):
        row = self._conversation(state="human", assigned=self.agent)

        response = self._client().post(f"/api/inbox/conversations/{row.id}/close")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "closed")
        self.assertIsNotNone(body["closed_at"])
        self.assertIsNone(body["assigned_user_id"])

    def test_a_waiting_conversation_can_be_closed(self):
        row = self._conversation()

        response = self._client().post(f"/api/inbox/conversations/{row.id}/close")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "closed")

    def test_a_bot_conversation_cannot_be_closed(self):
        row = self._conversation(state="bot")

        response = self._client().post(f"/api/inbox/conversations/{row.id}/close")

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(row)
        self.assertEqual(row.state, "bot")

    def test_another_manager_cannot_close_someone_elses_claim(self):
        row = self._conversation(state="human", assigned=self.agent)

        response = self._client(self.teammate).post(
            f"/api/inbox/conversations/{row.id}/close"
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(row)
        self.assertEqual(row.state, "human")

    def test_closing_twice_is_idempotent(self):
        row = self._conversation()
        client = self._client()
        client.post(f"/api/inbox/conversations/{row.id}/close")

        response = client.post(f"/api/inbox/conversations/{row.id}/close")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "closed")


class QueueListTests(InboxTestCase):
    def test_a_state_filter_returns_only_that_queue(self):
        self._conversation(session_id="waiting", state="waiting")
        self._conversation(session_id="human", state="human", assigned=self.agent)

        response = self._client().get(
            "/api/inbox/conversations", params={"state": "waiting"}
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["session_id"], "waiting")

    def test_an_unknown_state_is_a_400(self):
        response = self._client().get(
            "/api/inbox/conversations", params={"state": "open"}
        )

        self.assertEqual(response.status_code, 400, response.text)

    def test_pages_report_the_matching_total(self):
        for index in range(3):
            self._conversation(
                session_id=f"s{index}",
                last=NOW - timedelta(minutes=index),
            )

        first = self._client().get(
            "/api/inbox/conversations", params={"limit": 2, "page": 1}
        )
        second = self._client().get(
            "/api/inbox/conversations", params={"limit": 2, "page": 2}
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["total"], 3)
        self.assertEqual(len(first.json()["items"]), 2)
        self.assertEqual(len(second.json()["items"]), 1)
        # Newest activity first: the page 2 tail is the oldest conversation.
        self.assertEqual(second.json()["items"][0]["session_id"], "s2")

    def test_the_row_carries_the_title_count_and_assignee(self):
        self._conversation(
            session_id="with-history", state="human", assigned=self.agent
        )
        self._message(session_id="with-history", body="Where is my order?")
        self._message(session_id="with-history", body="One moment", role="assistant")
        self.db.add(
            models.Contact(
                website_id=self.site.id,
                session_id="with-history",
                first_name="Vera",
                last_name="P",
                email="vera@example.test",
            )
        )
        self.db.commit()

        response = self._client().get("/api/inbox/conversations")

        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertEqual(item["title"], "Where is my order?")
        self.assertEqual(item["message_count"], 2)
        self.assertEqual(item["assigned_user_name"], "agent Test")
        self.assertEqual(item["contact_name"], "Vera P")
        self.assertEqual(item["contact_email"], "vera@example.test")

    def test_a_long_question_is_truncated(self):
        self._conversation(session_id="long")
        self._message(session_id="long", body="x" * 200)

        item = self._client().get("/api/inbox/conversations").json()["items"][0]

        self.assertEqual(len(item["title"]), conversations.TITLE_MAX_LEN + 1)
        self.assertTrue(item["title"].endswith("…"))


class DetailTests(InboxTestCase):
    def test_the_transcript_is_oldest_first_with_the_author(self):
        row = self._conversation(session_id="s1", state="human", assigned=self.agent)
        self._message(
            session_id="s1", body="help me", when=NOW - timedelta(minutes=5)
        )
        agent_message = models.ChatMessage(
            website_id=self.site.id,
            session_id="s1",
            role="agent",
            message="on it",
            author_user_id=self.agent.id,
            created_at=NOW,
            updated_at=NOW,
        )
        self.db.add(agent_message)
        self.db.commit()
        self.db.add(
            models.Contact(
                website_id=self.site.id,
                session_id="s1",
                first_name="Vera",
                last_name="P",
                email="vera@example.test",
            )
        )
        self.db.commit()

        response = self._client().get(f"/api/inbox/conversations/{row.id}")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "agent"])
        self.assertEqual(body["messages"][1]["author_name"], "agent Test")
        self.assertEqual(body["contact"]["email"], "vera@example.test")
        self.assertEqual(body["id"], str(row.id))

    def test_a_conversation_without_messages_still_reads(self):
        row = self._conversation(session_id="empty", state="waiting")

        response = self._client().get(f"/api/inbox/conversations/{row.id}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["messages"], [])
        self.assertIsNone(response.json()["contact"])


class ClaimSqlTests(InboxTestCase):
    def test_the_claim_locks_the_row_and_skips_a_locked_one(self):
        query = inbox.waiting_claim_query(self.db, self.company.id, uuid4())
        sql = str(query.statement.compile(dialect=postgresql.dialect()))

        self.assertIn("FOR UPDATE", sql)
        self.assertIn("SKIP LOCKED", sql)
        self.assertIn("conversations.state IN", sql)
        self.assertIn("websites.company_id", sql)


class RouteOwnershipTests(unittest.TestCase):
    def test_the_routes_only_call_the_service(self):
        source = INBOX_SOURCE.read_text()

        for action in ("claim", "assign", "release", "close"):
            self.assertIn(f"inbox.{action}(", source)
        # No route writes a row itself: state moves live behind the service.
        self.assertNotIn(".update(", source)
        self.assertNotIn(".delete(", source)
        self.assertNotIn("models.Conversation(", source)


if __name__ == "__main__":
    unittest.main()
