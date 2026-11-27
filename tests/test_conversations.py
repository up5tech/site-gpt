"""M9 conversation state: lazy creation, transitions, erasure and retention.

A conversation row is the inbox's durable state for one widget session. Three
properties are load-bearing and easy to break:

* creation is **lazy** and race-safe — one row per `(website_id, session_id)`,
  owned by `services/conversations.py`, never by a route;
* a session that predates M9 (or has no row for any reason) still lists, reads
  and deletes through the message helpers;
* erasure removes the whole session in one transaction and retention expires the
  inbox row on the newest message's clock, so metadata can neither half-survive
  an erasure nor outlive the transcript.
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import privacy as privacy_api
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import conversations, rag, retention

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.TenantAuditLog.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.ChatFeedback.__table__,
    models.HandoffRequest.__table__,
    models.Contact.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
    models.SessionToken.__table__,
    models.Setting.__table__,
    models.DigestLog.__table__,
    models.TopicCluster.__table__,
    models.TopicClusterRun.__table__,
    # The purge also sweeps uploads, so those tables must exist.
    models.ExtraDocument.__table__,
    models.Attachment.__table__,
    models.Document.__table__,
    models.Embedding.__table__,
]


def _sqlite_foreign_keys(connection, _record):
    """SQLite ignores FKs unless asked; Postgres always enforces them.

    The M10 insight FK carries `ON DELETE CASCADE`, which is the only erasure and
    retention path for those rows (V4-44). Without this pragma the cascade tests
    would pass while leaving the child row behind, i.e. they would prove nothing.
    """
    connection.execute("PRAGMA foreign_keys=ON")


class ConversationTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(self.engine, "connect", _sqlite_foreign_keys)
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()
        self.company = models.Company(name="Acme")
        self.other = models.Company(name="Other")
        self.db.add_all([self.company, self.other])
        self.db.commit()
        self.site = self._site(self.company, "mine")
        self.other_site = self._site(self.other, "theirs")
        self.user = models.User(
            company_id=self.company.id,
            email="agent@acme.test",
            password_hash="x",
            first_name="A",
            last_name="G",
            role="manager",
        )
        self.db.add(self.user)
        self.db.commit()

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

    def _message(self, site, session_id, body="hello?", role="user", when=None):
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

    def _conversation(self, site, session_id, state="bot", last=None):
        moment = last or NOW
        row = models.Conversation(
            website_id=site.id,
            session_id=session_id,
            state=state,
            last_message_at=moment,
            created_at=moment,
            updated_at=moment,
        )
        self.db.add(row)
        self.db.commit()
        return row


class CreationTests(ConversationTestCase):
    def test_the_first_message_creates_the_inbox_row(self):
        message = rag.save_message(self.db, self.site.id, "s1", "user", "what?")

        row = conversations.conversation_for(self.db, self.site.id, "s1")
        self.assertIsNotNone(row)
        self.assertEqual(row.state, conversations.STATE_BOT)
        self.assertEqual(row.assigned_user_id, None)
        # `last_message_at` is written in the same transaction as the message, so
        # it can differ from the row's server default only by the insert clock.
        self.assertLess(
            abs(
                row.last_message_at.replace(tzinfo=UTC)
                - message.created_at.replace(tzinfo=UTC)
            ),
            timedelta(seconds=5),
        )
        self.assertEqual(self.db.query(models.Conversation).count(), 1)

    def test_a_second_message_does_not_create_a_second_row(self):
        rag.save_message(self.db, self.site.id, "s1", "user", "one")
        rag.save_message(self.db, self.site.id, "s1", "assistant", "two")

        self.assertEqual(self.db.query(models.Conversation).count(), 1)

    def test_the_same_session_on_two_websites_is_two_conversations(self):
        self._conversation(self.site, "shared")
        self._conversation(self.other_site, "shared")

        self.assertEqual(
            conversations.conversation_for(self.db, self.site.id, "shared").website_id,
            self.site.id,
        )
        self.assertEqual(
            conversations.conversation_for(
                self.db, self.other_site.id, "shared"
            ).website_id,
            self.other_site.id,
        )

    def test_losing_the_insert_race_returns_the_winners_row(self):
        winner = self._conversation(self.site, "s-race")
        calls = {"n": 0}
        original = conversations.conversation_for

        def blind_once(db, website_id, session_id):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # both tabs saw "no row yet"
            return original(db, website_id, session_id)

        conversations.conversation_for = blind_once
        try:
            row = conversations.ensure_conversation(self.db, self.site.id, "s-race")
        finally:
            conversations.conversation_for = original

        self.assertEqual(row.id, winner.id)
        self.assertEqual(self.db.query(models.Conversation).count(), 1)


class LegacySessionTests(ConversationTestCase):
    """A session with no inbox row keeps working through the message helpers."""

    def test_it_still_lists(self):
        self._message(self.site, "old-session")

        summaries, total = conversations.list_conversations(self.db, self.site.id)

        self.assertEqual(total, 1)
        self.assertEqual(summaries[0]["session_id"], "old-session")
        self.assertIsNone(summaries[0]["conversation_id"])
        self.assertIsNone(summaries[0]["state"])

    def test_it_reports_the_inbox_state_when_a_row_exists(self):
        self._message(self.site, "queued")
        self._conversation(self.site, "queued", state="waiting")

        summaries, _ = conversations.list_conversations(self.db, self.site.id)

        self.assertEqual(summaries[0]["state"], "waiting")
        self.assertIsNotNone(summaries[0]["conversation_id"])

    def test_it_still_deletes(self):
        self._message(self.site, "old-session")
        self._message(self.site, "other-session")

        deleted = conversations.delete_conversation(self.db, self.site.id, "old-session")

        self.assertEqual(deleted, 1)
        self.assertEqual(
            [m.session_id for m in self.db.query(models.ChatMessage).all()],
            ["other-session"],
        )

    def test_deleting_also_removes_an_existing_inbox_row(self):
        self._message(self.site, "s1")
        self._conversation(self.site, "s1", state="human")

        conversations.delete_conversation(self.db, self.site.id, "s1")

        self.assertEqual(self.db.query(models.Conversation).count(), 0)


class TransitionTests(ConversationTestCase):
    def test_bot_waiting_human_release_close(self):
        row = conversations.mark_waiting(self.db, self.site.id, "s1")
        self.assertEqual(row.state, "waiting")
        self.db.commit()

        conversations.claim(self.db, row, self.user.id)
        self.assertEqual(row.state, "human")
        self.assertEqual(row.assigned_user_id, self.user.id)
        self.assertIsNotNone(row.claimed_at)
        self.db.commit()

        conversations.release(self.db, row)
        self.assertEqual(row.state, "waiting")
        self.assertIsNone(row.assigned_user_id)
        self.assertIsNone(row.claimed_at)
        self.db.commit()

        conversations.claim(self.db, row, self.user.id)
        conversations.close(self.db, row)
        self.db.commit()
        self.assertEqual(row.state, "closed")
        self.assertIsNone(row.assigned_user_id)
        self.assertIsNotNone(row.closed_at)

    def test_an_invalid_transition_raises(self):
        row = conversations.ensure_conversation(self.db, self.site.id, "s1")

        with self.assertRaises(conversations.ConversationStateError):
            conversations.claim(self.db, row, self.user.id)  # bot → human

        with self.assertRaises(conversations.ConversationStateError):
            conversations.set_state(self.db, row, "nonsense")

        self.assertEqual(row.state, "bot")

    def test_a_second_handoff_click_does_not_requeue_a_claimed_session(self):
        row = conversations.mark_waiting(self.db, self.site.id, "s1")
        conversations.claim(self.db, row, self.user.id)
        self.db.commit()

        again = conversations.mark_waiting(self.db, self.site.id, "s1")

        self.assertEqual(again.state, "human")
        self.assertEqual(again.assigned_user_id, self.user.id)

    def test_a_visitor_message_reopens_a_closed_session(self):
        row = self._conversation(self.site, "s1", state="closed")

        refreshed = conversations.note_message(self.db, self.site.id, "s1", "user")
        self.db.commit()

        self.assertEqual(refreshed.id, row.id)
        self.assertEqual(refreshed.state, "bot")
        self.assertIsNone(refreshed.closed_at)

    def test_an_agent_message_does_not_change_the_state(self):
        row = self._conversation(self.site, "s1", state="human")

        conversations.note_message(self.db, self.site.id, "s1", "agent")
        self.db.commit()

        self.assertEqual(row.state, "human")

    def test_note_message_advances_the_activity_clock(self):
        row = self._conversation(self.site, "s1", last=NOW - timedelta(days=2))

        conversations.note_message(self.db, self.site.id, "s1", "user", when=NOW)
        self.db.commit()

        self.assertGreater(row.last_message_at.replace(tzinfo=UTC), NOW - timedelta(days=1))


class ErasureTests(ConversationTestCase):
    def test_erase_session_removes_every_session_scoped_row(self):
        message = self._message(self.site, "s1")
        self._conversation(self.site, "s1", state="closed")
        self.db.add_all(
            [
                models.ChatFeedback(
                    website_id=self.site.id,
                    session_id="s1",
                    rating="up",
                    message_id=message.id,
                ),
                models.HandoffRequest(
                    website_id=self.site.id, session_id="s1", status="pending"
                ),
                models.SessionToken(
                    website_id=self.site.id,
                    session_id="s1",
                    token_hash="h" * 64,
                    expires_at=NOW + timedelta(days=1),
                ),
            ]
        )
        self.db.commit()
        # A neighbouring session on the same website stays.
        self._message(self.site, "s2")
        self._conversation(self.site, "s2", state="human")

        deleted = conversations.erase_session(self.db, self.site.id, "s1")

        self.assertEqual(
            deleted,
            {
                "chat_messages": 1,
                "chat_feedback": 1,
                "handoff_requests": 1,
                "session_tokens": 1,
                "conversations": 1,
            },
        )
        self.assertEqual(
            [m.session_id for m in self.db.query(models.ChatMessage).all()], ["s2"]
        )
        self.assertEqual(
            [c.session_id for c in self.db.query(models.Conversation).all()], ["s2"]
        )
        self.assertEqual(self.db.query(models.ChatFeedback).count(), 0)
        self.assertEqual(self.db.query(models.HandoffRequest).count(), 0)
        self.assertEqual(self.db.query(models.SessionToken).count(), 0)

    def test_the_route_reports_the_new_keys_and_keeps_the_contact(self):
        message = self._message(self.site, "s1")
        self._conversation(self.site, "s1", state="waiting")
        self.db.add(
            models.Contact(
                website_id=self.site.id,
                session_id="s1",
                first_name="V",
                last_name="P",
                email="v@example.test",
            )
        )
        self.db.add(
            models.SessionToken(
                website_id=self.site.id,
                session_id="s1",
                token_hash="h" * 64,
                expires_at=NOW + timedelta(days=1),
            )
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(privacy_api.router, prefix="/api/privacy")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=self.company.id
        )
        client = TestClient(app)

        response = client.delete(
            "/api/privacy/conversations/s1", params={"website_id": str(self.site.id)}
        )

        self.assertEqual(response.status_code, 200, response.text)
        deleted = response.json()["deleted"]
        self.assertEqual(deleted["chat_messages"], 1)
        self.assertEqual(deleted["conversations"], 1)
        self.assertEqual(deleted["session_tokens"], 1)
        self.assertEqual(self.db.query(models.Conversation).count(), 0)
        self.assertEqual(self.db.query(models.SessionToken).count(), 0)
        # The owner's lead record is kept by design.
        self.assertEqual(self.db.query(models.Contact).count(), 1)

    def test_the_export_does_not_need_an_insight_section(self):
        # V4-44 decision: insights are derived labels over the transcript the
        # export already contains, so the export gains no new section — and a
        # summary that is not source data must not become an exported record.
        self._message(self.site, "s1")
        row = self._conversation(self.site, "s1", state="human")
        self.db.add(
            models.ConversationInsight(
                conversation_id=row.id,
                status="completed",
                sentiment="frustrated",
                resolution="escalated",
                summary="Derived label marker",
            )
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(privacy_api.router, prefix="/api/privacy")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=self.company.id
        )
        client = TestClient(app)

        response = client.get(
            "/api/privacy/export", params={"website_id": str(self.site.id)}
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            set(response.json()),
            {
                "website_id",
                "website_name",
                "generated_at",
                "chat_messages",
                "contacts",
                "chat_feedback",
                "handoff_requests",
                "conversations",
            },
        )
        self.assertNotIn("Derived label marker", response.text)

    def test_export_lists_the_inbox_state(self):
        self._conversation(self.site, "s1", state="human")

        app = FastAPI()
        app.include_router(privacy_api.router, prefix="/api/privacy")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=self.company.id
        )
        client = TestClient(app)

        response = client.get(
            "/api/privacy/export", params={"website_id": str(self.site.id)}
        )

        self.assertEqual(response.status_code, 200, response.text)
        exported = response.json()["conversations"]
        self.assertEqual([row["session_id"] for row in exported], ["s1"])
        self.assertEqual(exported[0]["state"], "human")


class InsightCascadeTests(ConversationTestCase):
    """V4-44: the insight row dies with its conversation, and only with it.

    There is deliberately no second delete path: `conversation_insights` has a
    unique `conversation_id` FK with `ON DELETE CASCADE` (M10, invariant 14), so
    every existing erasure/retention route removes the derived row for free.
    These tests run with SQLite's `PRAGMA foreign_keys=ON` so they would fail if
    the cascade were dropped.
    """

    def _insight(self, conversation, summary="Visitor was charged twice."):
        row = models.ConversationInsight(
            conversation_id=conversation.id,
            status="completed",
            sentiment="frustrated",
            resolution="escalated",
            summary=summary,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _orphans(self):
        """Insight rows whose conversation no longer exists — must always be 0."""
        return (
            self.db.query(models.ConversationInsight)
            .filter(
                ~models.ConversationInsight.conversation_id.in_(
                    select(models.Conversation.id)
                )
            )
            .count()
        )

    def test_erase_session_leaves_no_orphan_insight(self):
        self._message(self.site, "s1")
        erased = self._conversation(self.site, "s1", state="closed")
        self._insight(erased)
        kept = self._conversation(self.site, "s2", state="human")
        self._insight(kept, summary="Shipping was answered from the help content.")

        conversations.erase_session(self.db, self.site.id, "s1")

        self.assertEqual(self.db.query(models.ConversationInsight).count(), 1)
        self.assertEqual(
            self.db.query(models.ConversationInsight).one().conversation_id,
            kept.id,
        )
        self.assertEqual(self._orphans(), 0)

    def test_delete_conversation_leaves_no_orphan_insight(self):
        self._message(self.site, "s1")
        row = self._conversation(self.site, "s1", state="closed")
        self._insight(row)

        conversations.delete_conversation(self.db, self.site.id, "s1")

        self.assertEqual(self.db.query(models.ConversationInsight).count(), 0)
        self.assertEqual(self._orphans(), 0)

    def test_retention_expiry_leaves_no_orphan_insight(self):
        self.db.add(
            models.Setting(
                company_id=self.company.id, key="retention_days", value="7"
            )
        )
        self.db.commit()
        self._message(self.site, "s1", when=NOW - timedelta(days=10))
        expired = self._conversation(self.site, "s1", last=NOW - timedelta(days=10))
        self._insight(expired)
        fresh = self._conversation(self.site, "s2", last=NOW - timedelta(hours=1))
        self._insight(fresh, summary="Shipping was answered from the help content.")

        result = retention.purge_company(
            self.db, self.company.id, dry_run=False, now=NOW
        )

        self.assertEqual(result["deleted"]["conversations"], 1)
        self.assertEqual(self.db.query(models.ConversationInsight).count(), 1)
        self.assertEqual(
            self.db.query(models.ConversationInsight).one().conversation_id,
            fresh.id,
        )
        self.assertEqual(self._orphans(), 0)


class RetentionMetadataTests(ConversationTestCase):
    def _policy(self, days):
        self.db.add(
            models.Setting(
                company_id=self.company.id, key="retention_days", value=str(days)
            )
        )
        self.db.commit()

    def test_an_expired_conversation_goes_with_its_messages(self):
        self._policy(7)
        self._message(self.site, "s1", when=NOW - timedelta(days=10))
        self._conversation(self.site, "s1", last=NOW - timedelta(days=10))

        result = retention.purge_company(self.db, self.company.id, dry_run=False, now=NOW)

        self.assertEqual(result["deleted"]["chat_messages"], 1)
        self.assertEqual(result["deleted"]["conversations"], 1)
        self.assertEqual(self.db.query(models.Conversation).count(), 0)

    def test_an_old_session_with_a_fresh_message_keeps_its_metadata(self):
        self._policy(7)
        self._message(self.site, "s1", when=NOW - timedelta(days=30))
        self._message(self.site, "s1", body="still here", when=NOW - timedelta(hours=1))
        # Created long ago, active now: the clock that matters is the message.
        self._conversation(
            self.site,
            "s1",
            state="waiting",
            last=NOW - timedelta(hours=1),
        )

        result = retention.purge_company(self.db, self.company.id, dry_run=False, now=NOW)

        self.assertEqual(result["deleted"]["chat_messages"], 1)
        self.assertEqual(result["deleted"]["conversations"], 0)
        self.assertEqual(self.db.query(models.Conversation).count(), 1)

    def test_another_tenants_conversation_is_never_touched(self):
        self._policy(7)
        self._message(self.other_site, "s1", when=NOW - timedelta(days=10))
        self._conversation(self.other_site, "s1", last=NOW - timedelta(days=10))

        result = retention.purge_company(self.db, self.company.id, dry_run=False, now=NOW)

        self.assertEqual(result["deleted"]["conversations"], 0)
        self.assertEqual(self.db.query(models.Conversation).count(), 1)

    def test_the_dry_run_counts_conversations_without_deleting(self):
        self._policy(7)
        self._conversation(self.site, "s1", last=NOW - timedelta(days=10))

        result = retention.purge_company(self.db, self.company.id, dry_run=True, now=NOW)

        self.assertEqual(result["deleted"]["conversations"], 1)
        self.assertEqual(self.db.query(models.Conversation).count(), 1)


if __name__ == "__main__":
    unittest.main()
