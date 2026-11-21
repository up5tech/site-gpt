"""V3-43: an agent's reply reaches the visitor, and the bot stays quiet.

Three properties carry this task, and each one is a way the feature could lie to
someone:

* an agent reply is a stored `role='agent'` row with its author, persisted
  before either notification goes out, so a console or widget never shows a
  message the database would roll back;
* the public message endpoints are gated by the K4 session token — the embed
  token is public in the page, so it alone can never read a transcript;
* while a session is `human`, `/api/chat` stores the visitor's message and
  answers "handed over" without calling the LLM; a queued (`waiting`) session is
  still unattended and keeps getting bot answers.
"""

import asyncio
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import inbox as inbox_api
from site_gpt.app.api import privacy as privacy_api
from site_gpt.app.api import routes
from site_gpt.app.core.auth import get_admin_user, get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import conversations, inbox, rag, session_tokens

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
WEBSITE_URL = "https://customer.example.com"

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Conversation.__table__,
    models.ConversationInsight.__table__,
    models.Contact.__table__,
    models.ChatFeedback.__table__,
    models.HandoffRequest.__table__,
    models.Setting.__table__,
    models.SessionToken.__table__,
]


class ReplyTestCase(unittest.TestCase):
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

        self.site = self._site(self.company, "mine", WEBSITE_URL)
        self.other_site = self._site(self.other_company, "theirs", "https://x.test")

        self.agent = self._user(self.company, "agent@acme.test", "manager")
        self.teammate = self._user(self.company, "mate@acme.test", "manager")
        self.admin = self._user(self.company, "boss@acme.test", "admin")
        self.viewer = self._user(self.company, "viewer@acme.test", "user")

        self._setting("live_inbox_enabled", "true")
        self.actor = self.agent

        # Both notifications leave the request thread; unit tests stub them so
        # no Redis connection is opened. Tests that assert on them patch again.
        for target, name in (
            (inbox, "publish_after_commit"),
            (rag, "publish_agent_reply"),
            (rag, "publish_widget_state"),
        ):
            patcher = patch.object(target, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # -- fixtures ---------------------------------------------------------

    def _site(self, company, name, url):
        site = models.Website(
            company_id=company.id, name=name, url=url, site_map_url=""
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
        self, site=None, session_id="s1", state="human", assigned=None, last=None
    ):
        site = site or self.site
        moment = last or NOW
        row = models.Conversation(
            website_id=site.id,
            session_id=session_id,
            state=state,
            assigned_user_id=assigned.id if assigned is not None else None,
            claimed_at=moment if assigned is not None else None,
            last_message_at=moment,
            created_at=moment,
            updated_at=moment,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _message(self, role="user", body="hello", when=None, site=None, session="s1"):
        site = site or self.site
        moment = when or NOW
        row = models.ChatMessage(
            website_id=site.id,
            session_id=session,
            role=role,
            message=body,
            created_at=moment,
            updated_at=moment,
        )
        self.db.add(row)
        self.db.commit()
        return row


class AgentReplyTests(ReplyTestCase):
    def setUp(self):
        super().setUp()
        self.row = self._conversation(assigned=self.agent)
        self.app = FastAPI()
        self.app.include_router(inbox_api.router, prefix="/api/inbox")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_manager_user] = lambda: self.actor
        self.client = TestClient(self.app)

    def reply(self, text="Hi, I can help with that.", conversation=None):
        return self.client.post(
            f"/api/inbox/conversations/{(conversation or self.row).id}/messages",
            json={"message": text},
        )

    def stored(self):
        return self.db.query(models.ChatMessage).all()

    def test_an_agent_reply_is_stored_as_agent_with_its_author(self):
        response = self.reply("We ship on Fridays.")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["role"], "agent")
        self.assertEqual(body["message"], "We ship on Fridays.")
        self.assertEqual(body["author_user_id"], str(self.agent.id))
        self.assertEqual(body["author_name"], "agent Test")

        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].role, "agent")
        self.assertEqual(rows[0].author_user_id, self.agent.id)
        self.assertEqual(rows[0].session_id, "s1")
        self.db.refresh(self.row)
        self.assertEqual(self.row.state, "human")

    def test_the_reply_is_persisted_before_either_notification(self):
        order = []
        states = []

        def capture_inbox(company_id, payload):
            order.append("inbox")
            states.append(len(self.stored()))

        def capture_widget(website_id, session_id, message):
            order.append("widget")
            states.append(len(self.stored()))

        with patch.object(
            inbox, "publish_after_commit", side_effect=capture_inbox
        ), patch.object(
            rag, "publish_agent_reply", side_effect=capture_widget
        ):
            response = self.reply()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(order, ["inbox", "widget"])
        # The row existed (and was committed) by the time both were queued.
        self.assertEqual(states, [1, 1])

    def test_the_inbox_notification_names_the_new_message(self):
        captured = []

        with patch.object(
            inbox, "publish_after_commit", side_effect=lambda c, p: captured.append(p)
        ):
            self.reply()

        self.assertEqual(captured[0]["event"], "message")
        self.assertEqual(captured[0]["conversation_id"], str(self.row.id))
        self.assertEqual(captured[0]["state"], "human")

    def test_the_widget_notification_carries_the_session_and_message(self):
        captured = []

        with patch.object(
            rag,
            "publish_agent_reply",
            side_effect=lambda site, session, message: captured.append(
                (site, session, message)
            ),
        ):
            self.reply("Shipping now.")

        site_id, session_id, message = captured[0]
        self.assertEqual(site_id, self.site.id)
        self.assertEqual(session_id, "s1")
        self.assertEqual(message.role, "agent")
        self.assertEqual(message.message, "Shipping now.")

    def test_a_reply_to_a_queued_conversation_is_refused(self):
        waiting = self._conversation(session_id="s2", state="waiting")

        response = self.reply(conversation=waiting)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.stored(), [])

    def test_a_reply_from_a_non_holder_is_refused(self):
        self.row.assigned_user_id = self.teammate.id
        self.db.commit()

        response = self.reply()

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.stored(), [])

    def test_an_admin_can_reply_in_place_of_the_assignee(self):
        self.row.assigned_user_id = self.teammate.id
        self.db.commit()
        self.app.dependency_overrides[get_manager_user] = lambda: self.admin
        self.actor = self.admin

        response = self.reply("Taking over for a moment.")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stored()[0].author_user_id, self.admin.id)

    def test_a_foreign_conversation_is_a_404(self):
        foreign = self._conversation(site=self.other_site, session_id="s3")

        response = self.reply(conversation=foreign)

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.stored(), [])

    def test_the_route_is_a_404_when_the_inbox_is_off(self):
        self._setting("live_inbox_enabled", "false")

        response = self.reply()

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.stored(), [])

    def test_an_empty_reply_is_a_400(self):
        for text in ("", "   \n "):
            with self.subTest(text=text):
                response = self.reply(text)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.stored(), [])

    def test_claiming_wakes_the_visitors_widget(self):
        waiting = self._conversation(session_id="s9", state="waiting")

        with patch.object(rag, "publish_widget_state") as publish:
            response = self.client.post(
                f"/api/inbox/conversations/{waiting.id}/claim"
            )

        self.assertEqual(response.status_code, 200, response.text)
        publish.assert_called_once_with(self.site.id, "s9", "human")

    def test_closing_stops_the_visitors_widget(self):
        with patch.object(rag, "publish_widget_state") as publish:
            response = self.client.post(
                f"/api/inbox/conversations/{self.row.id}/close"
            )

        self.assertEqual(response.status_code, 200, response.text)
        publish.assert_called_once_with(self.site.id, "s1", "closed")

    def test_the_inbox_transcript_shows_the_agent_and_its_author(self):
        self._message(body="can someone help?")
        self.reply("Sure — what's the order number?")

        detail = inbox.detail(self.db, self.company.id, self.row.id)

        agent_rows = [m for m in detail["messages"] if m["role"] == "agent"]
        self.assertEqual(len(agent_rows), 1)
        self.assertEqual(agent_rows[0]["author_user_id"], self.agent.id)
        self.assertEqual(agent_rows[0]["author_name"], "agent Test")

    def test_the_privacy_export_keeps_the_agent_author(self):
        self.reply("Stored for the export.")
        app = FastAPI()
        app.include_router(privacy_api.router, prefix="/api/privacy")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: self.admin
        client = TestClient(app)

        response = client.get(f"/api/privacy/export?website_id={self.site.id}")

        self.assertEqual(response.status_code, 200, response.text)
        exported = response.json()["chat_messages"][0]
        self.assertEqual(exported["role"], "agent")
        self.assertEqual(exported["author_user_id"], str(self.agent.id))


class WidgetMessageTests(ReplyTestCase):
    def setUp(self):
        super().setUp()
        self.app = FastAPI()
        # `main.app` registers this; a bare test app needs it to keep the
        # `reason` code that the widget branches on.
        self.app.add_exception_handler(
            session_tokens.SessionTokenError, session_tokens.error_response
        )
        self.app.include_router(routes.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)
        self.token, _ = session_tokens.mint(
            self.db, self.site.id, "s1"
        )

    def send(self, path="/api/chat/messages", **params):
        query = {"website_id": str(self.site.id), "session_id": "s1"}
        query.update(params)
        headers = {"Origin": WEBSITE_URL}
        token = params.pop("token", self.token)
        if token:
            headers["X-Session-Token"] = token
        return self.client.get(path, params=query, headers=headers)

    def test_the_cursor_returns_the_session_messages_in_order(self):
        first = self._message(body="hello", when=NOW)
        second = self._message(role="assistant", body="hi", when=NOW.replace(minute=1))
        agent = self._message(
            role="agent", body="agent here", when=NOW.replace(minute=2)
        )

        response = self.send()

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            [item["id"] for item in body["items"]],
            [str(first.id), str(second.id), str(agent.id)],
        )
        self.assertEqual(body["next_cursor"], rag.message_cursor(agent))

    def test_the_cursor_resumes_after_the_last_seen_message(self):
        first = self._message(body="one", when=NOW)
        later = self._message(role="agent", body="two", when=NOW.replace(minute=1))

        response = self.send(after=rag.message_cursor(first))

        self.assertEqual(
            [item["id"] for item in response.json()["items"]], [str(later.id)]
        )

    def test_a_garbage_cursor_replays_instead_of_failing(self):
        self._message(body="one", when=NOW)

        response = self.send(after="not-a-cursor")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 1)

    def test_the_session_token_is_required_once_the_session_is_claimed(self):
        self._message(body="one", when=NOW)

        response = self.send(token="")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["reason"], "session_claimed")

    def test_a_wrong_token_reads_nothing(self):
        self._message(body="one", when=NOW)

        response = self.send(token="sst_forged")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["reason"], "invalid_token")

    def test_another_websites_token_cannot_read_this_session(self):
        self._message(body="one", when=NOW)
        other_token, _ = session_tokens.mint(self.db, self.other_site.id, "s1")

        response = self.send(token=other_token)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["reason"], "invalid_token")

    def test_a_disabled_website_serves_no_messages(self):
        self._message(body="one", when=NOW)
        self.site.status = "inactive"
        self.db.commit()

        response = self.send()

        self.assertEqual(response.status_code, 403, response.text)

    def test_the_read_reports_whether_an_agent_handles_the_session(self):
        self._message(body="one", when=NOW)
        self.assertEqual(self.send().json()["state"], "bot")

        self._conversation(assigned=self.agent)

        self.assertEqual(self.send().json()["state"], "human")

    def test_the_stream_is_refused_while_nobody_handles_the_session(self):
        self._message(body="one", when=NOW)

        with patch.object(routes, "redis_ping", AsyncMock(return_value=True)):
            response = self.send(path="/api/chat/messages/stream")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], routes.WIDGET_STREAM_IDLE)

    def test_the_stream_is_503_before_streaming_when_redis_is_down(self):
        # A queued session: the stream is only offered once an agent (or the
        # handoff queue) is involved, which is checked before Redis.
        self._conversation(state="waiting")

        with patch.object(routes, "redis_ping", AsyncMock(return_value=False)):
            response = self.send(path="/api/chat/messages/stream")

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["detail"], routes.WIDGET_STREAM_UNAVAILABLE)

    def test_the_stream_replays_from_the_cursor_before_going_live(self):
        self._conversation(state="waiting")
        message = self._message(role="agent", body="live", when=NOW)
        seen = {}

        async def finite(website_id, session_id, replay, *, disconnect=None):
            seen["replay"] = replay
            yield "retry: 3000\n\n"
            for item in replay:
                yield rag.message_frame(item)

        with patch.object(routes, "redis_ping", AsyncMock(return_value=True)), patch.object(
            routes.rag, "message_stream", finite
        ):
            response = self.send(path="/api/chat/messages/stream")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream")
        )
        self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertEqual(
            [item["id"] for item in seen["replay"]], [str(message.id)]
        )
        self.assertIn(f"id: {message.id}", response.text)


    def test_the_stream_follows_a_handoff_then_stops_when_it_closes(self):
        waiting = self._conversation(state="waiting")
        opened = []

        async def finite(website_id, session_id, replay, *, disconnect=None):
            opened.append(session_id)
            yield "retry: 3000\n\n"

        with patch.object(routes, "redis_ping", AsyncMock(return_value=True)), patch.object(
            routes.rag, "message_stream", finite
        ):
            response = self.send(path="/api/chat/messages/stream")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(opened, ["s1"])

        conversations.close(self.db, waiting)
        self.db.commit()

        with patch.object(routes, "redis_ping", AsyncMock(return_value=True)):
            response = self.send(path="/api/chat/messages/stream")

        self.assertEqual(response.status_code, 409, response.text)

    def test_history_reports_a_live_handoff_after_a_reload(self):
        self._message(body="hello", when=NOW)
        self._conversation(assigned=self.agent)

        response = self.client.get(
            "/api/conversations/s1",
            params={"website_id": str(self.site.id)},
            headers={"Origin": WEBSITE_URL, "X-Session-Token": self.token},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "human")


class FakePubSub:
    def __init__(self, messages=None, error=None):
        self.messages = list(messages or [])
        self.error = error

    async def get_message(self, ignore_subscribe_messages=True):
        if self.error is not None:
            raise self.error
        if self.messages:
            return self.messages.pop(0)
        await asyncio.Event().wait()


class FakeSubscribe:
    def __init__(self, pubsub):
        self.pubsub = pubsub
        self.channels = []

    def __call__(self, channel):
        self.channels.append(channel)
        return self

    async def __aenter__(self):
        return self.pubsub

    async def __aexit__(self, *exc):
        return False


class MessageStreamBodyTests(ReplyTestCase):
    def _collect(self, pubsub, count=4):
        chunks = []

        async def run():
            gen = rag.message_stream(
                self.site.id,
                "s1",
                [rag.widget_message(self._message(role="agent", body="history"))],
                heartbeat_seconds=1,
            )
            try:
                async for chunk in gen:
                    chunks.append(chunk)
                    if len(chunks) >= count:
                        break
            finally:
                await gen.aclose()
            return chunks

        with patch.object(rag.redis_service, "subscribe", FakeSubscribe(pubsub)):
            asyncio.run(run())
        return chunks

    def test_it_starts_with_retry_then_the_replayed_rows(self):
        chunks = self._collect(FakePubSub(), count=2)

        self.assertEqual(chunks[0], "retry: 3000\n\n")
        self.assertIn("event: message", chunks[1])
        self.assertIn('"body": "history"'.replace("body", "message"), chunks[1])

    def test_a_live_reply_arrives_after_the_replay(self):
        payload = {
            "id": str(uuid4()),
            "role": "agent",
            "message": "live reply",
            "created_at": NOW.isoformat(),
        }
        pubsub = FakePubSub(
            messages=[{"type": "message", "data": json.dumps(payload)}]
        )

        chunks = self._collect(pubsub, count=3)

        self.assertIn(f"id: {payload['id']}", chunks[2])
        self.assertIn("live reply", chunks[2])

    def test_a_quiet_session_gets_heartbeat_comments(self):
        chunks = self._collect(FakePubSub(), count=3)

        self.assertTrue(chunks[2].startswith(": heartbeat "), chunks[2])

    def test_a_reader_error_ends_the_stream_with_an_error_frame(self):
        chunks = self._collect(FakePubSub(error=ConnectionError("gone")), count=3)

        self.assertIn("event: error", chunks[2])
        self.assertIn("stream_interrupted", chunks[2])


    def test_a_state_frame_is_forwarded_as_state_not_a_message(self):
        pubsub = FakePubSub(
            messages=[
                {
                    "type": "message",
                    "data": json.dumps({"event": "state", "state": "closed"}),
                }
            ]
        )

        chunks = self._collect(pubsub, count=3)

        self.assertEqual(chunks[2], rag.widget_state_frame("closed"))
        self.assertIn("event: state", chunks[2])
        self.assertIn('"state": "closed"', chunks[2])


class ChatWhileHumanTests(ReplyTestCase):
    def setUp(self):
        super().setUp()
        self._setting("daily_message_limit", "100")
        self.row = self._conversation(assigned=self.agent)
        self.app = FastAPI()
        self.app.include_router(routes.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

    def chat(self, session_id="s1", question="anyone there?"):
        return self.client.post(
            "/api/chat",
            json={
                "website_id": str(self.site.id),
                "session_id": session_id,
                "question": question,
            },
            headers={"Origin": WEBSITE_URL},
        )

    def stream(self, session_id="s1", question="anyone there?"):
        return self.client.post(
            "/api/chat/stream",
            json={
                "website_id": str(self.site.id),
                "session_id": session_id,
                "question": question,
            },
            headers={"Origin": WEBSITE_URL},
        )

    def stored_roles(self):
        return [m.role for m in self.db.query(models.ChatMessage).all()]

    def test_a_human_held_session_stores_the_message_and_queues_it(self):
        with patch.object(routes, "ask") as ask, patch.object(
            routes, "consume_message", AsyncMock(return_value=True)
        ) as consume:
            response = self.chat()

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["queued"])
        self.assertEqual(body["answer"], rag.QUEUED_MESSAGE)
        self.assertIsNotNone(body["message_id"])
        ask.assert_not_called()
        # Nothing was generated, so the daily ceiling is not charged.
        consume.assert_not_awaited()
        self.assertEqual(self.stored_roles(), ["user"])
        self.db.refresh(self.row)
        self.assertEqual(self.row.state, "human")

    def test_the_streaming_handler_queues_the_same_way(self):
        with patch.object(routes, "ask_stream") as ask_stream:
            response = self.stream()

        self.assertEqual(response.status_code, 200, response.text)
        ask_stream.assert_not_called()
        frames = [
            json.loads(part.removeprefix("data: ").strip())
            for part in response.text.split("\n\n")
            if part.strip().startswith("data: ")
        ]
        self.assertEqual(frames[0]["chunk"], rag.QUEUED_MESSAGE)
        self.assertTrue(frames[-1]["queued"])
        self.assertEqual(self.stored_roles(), ["user"])

    def test_a_waiting_session_still_gets_the_bot(self):
        self._conversation(session_id="s2", state="waiting")
        answer = {"answer": "bot answer", "sources": [], "message_id": str(uuid4())}

        with patch.object(routes, "ask", return_value=answer) as ask, patch.object(
            routes, "consume_message", AsyncMock(return_value=True)
        ):
            response = self.chat(session_id="s2")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "bot answer")
        ask.assert_called_once()

    def test_a_closed_session_is_reopened_for_the_bot(self):
        closed = self._conversation(session_id="s3", state="closed")

        def fake_ask(db, website_id, session_id, question):
            # The real handler persists the exchange; that write is what reopens
            # the closed session in `note_message`.
            rag.save_message(db, website_id, session_id, "user", question)
            answer = rag.save_message(
                db, website_id, session_id, "assistant", "bot again"
            )
            return {"answer": "bot again", "sources": [], "message_id": answer.id}

        with patch.object(routes, "ask", side_effect=fake_ask) as ask, patch.object(
            routes, "consume_message", AsyncMock(return_value=True)
        ):
            response = self.chat(session_id="s3")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "bot again")
        ask.assert_called_once()
        self.db.expire_all()
        row = conversations.conversation_for(self.db, self.site.id, "s3")
        self.assertEqual(row.id, closed.id)
        self.assertEqual(row.state, conversations.STATE_BOT)

    def test_human_handling_only_matches_a_human_held_session(self):
        self.assertTrue(conversations.human_handling(self.db, self.site.id, "s1"))
        self.assertFalse(conversations.human_handling(self.db, self.site.id, "nope"))
        self._conversation(session_id="s4", state="waiting")
        self.assertFalse(conversations.human_handling(self.db, self.site.id, "s4"))


class WidgetGatingTests(ReplyTestCase):
    def test_only_a_queued_or_agent_held_session_is_engaged(self):
        for state, expected in (
            ("bot", False),
            ("waiting", True),
            ("human", True),
            ("closed", False),
        ):
            with self.subTest(state=state):
                self.assertIs(conversations.agent_engaged(state), expected)

    def test_a_session_without_an_inbox_row_reads_as_bot(self):
        self.assertEqual(
            conversations.widget_state(self.db, self.site.id, "never-seen"),
            "bot",
        )


class HistoryRoleTests(unittest.TestCase):
    def test_an_agent_row_is_labelled_as_a_person_in_the_prompt(self):
        rows = [
            MagicMock(role="user", message="where is my order?"),
            MagicMock(role="agent", message="checking now"),
            MagicMock(role="assistant", message="it ships today"),
        ]

        history = rag.format_history(rows)

        self.assertIn("User: where is my order?", history)
        self.assertIn("Agent: checking now", history)
        self.assertIn("Assistant: it ships today", history)

    def test_a_cursor_round_trips_and_rejects_garbage(self):
        message = MagicMock(
            id=uuid4(), created_at=NOW
        )

        cursor = rag.message_cursor(message)

        self.assertEqual(rag.parse_cursor(cursor), (NOW, message.id))
        for raw in (None, "", "|", "nope", f"{NOW.isoformat()}|not-a-uuid"):
            with self.subTest(raw=raw):
                self.assertIsNone(rag.parse_cursor(raw))


if __name__ == "__main__":
    unittest.main()
