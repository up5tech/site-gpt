"""V3-42 agent inbox stream: notifications, SSE framing and presence leases.

The stream is a `fetch()` body, so the properties that matter are about what a
browser can and cannot trust:

* auth and `live_inbox_enabled` are checked before the first byte, and Redis
  being down is a 503 rather than a stream that never delivers;
* every notification carries an id derived from the row, so the console can
  dedupe the same state change after a reconnect;
* the notification is published only after the service committed;
* presence is one lease per connection with a TTL, so one tab closing cannot
  clear another tab's presence.

Nothing here needs a live Redis: the pub/sub subscriber, the leases and the
publisher are patched, and the stream body is driven by `event_stream` directly
so the framing is inspected without an HTTP response that never ends.
"""

import asyncio
import json
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
from site_gpt.app.api import inbox as inbox_api
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import inbox

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.Conversation.__table__,
    models.ChatMessage.__table__,
    models.Contact.__table__,
    models.Setting.__table__,
]


class FakePubSub:
    """A subscriber that hands back queued messages, then blocks like a socket."""

    def __init__(self, messages=None, error=None):
        self.messages = list(messages or [])
        self.error = error
        self.reads = 0

    async def get_message(self, ignore_subscribe_messages=True):
        self.reads += 1
        if self.error is not None:
            raise self.error
        if self.messages:
            return self.messages.pop(0)
        await asyncio.Event().wait()  # a quiet subscription never returns


class FakeSubscribe:
    """`redis.subscribe` as an async context manager around a fake pubsub."""

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


def message(payload):
    return {"type": "message", "channel": "c", "data": json.dumps(payload)}


class StreamTestCase(unittest.TestCase):
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
        self.agent = self._user(self.company, "agent@acme.test", "manager")
        self.teammate = self._user(self.company, "mate@acme.test", "manager")
        self.viewer = self._user(self.company, "viewer@acme.test", "user")
        self.outsider = self._user(self.other_company, "spy@other.test", "manager")

        self._setting("live_inbox_enabled", "true")
        self.actor = self.agent

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

    def _conversation(self, site=None, session_id="s1", state="waiting", last=None):
        site = site or self.site
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

    def _client(self, actor=None):
        app = FastAPI()
        app.include_router(inbox_api.router, prefix="/api/inbox")
        self.actor = actor or self.agent
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_manager_user] = lambda: self.actor
        return TestClient(app)

    # -- stream driving ---------------------------------------------------

    def _patches(self, pubsub, *, leased=True):
        """Patch the Redis surface the stream touches, with async fakes."""
        return (
            patch.object(
                inbox.redis_service,
                "set_lease",
                AsyncMock(return_value=leased),
            ),
            patch.object(
                inbox.redis_service, "renew_lease", AsyncMock(return_value=True)
            ),
            patch.object(
                inbox.redis_service, "delete_lease", AsyncMock(return_value=True)
            ),
            patch.object(
                inbox.redis_service,
                "publish_event",
                AsyncMock(return_value=True),
            ),
            patch.object(inbox.redis_service, "subscribe", FakeSubscribe(pubsub)),
        )

    def _collect(self, count, pubsub, *, leased=True, user=None, **kwargs):
        """Read `count` frames from the stream, then close it like a browser."""
        set_lease, renew, delete, publish, subscribe = self._patches(
            pubsub, leased=leased
        )
        chunks = []

        async def run():
            gen = inbox.event_stream(
                self.company.id,
                (user or self.agent).id,
                heartbeat_seconds=1,
                **kwargs,
            )
            try:
                async for chunk in gen:
                    chunks.append(chunk)
                    if len(chunks) >= count:
                        break
            finally:
                await gen.aclose()
            return chunks

        with set_lease as set_mock, renew as renew_mock, delete as delete_mock:
            with publish as publish_mock, subscribe as subscribe_mock:
                asyncio.run(run())

        self.set_lease = set_mock
        self.renew_lease = renew_mock
        self.delete_lease = delete_mock
        self.publish_event = publish_mock
        self.subscribe = subscribe_mock
        return chunks


def frame(chunk):
    """Split one SSE frame into its `event`/`id`/`data` parts."""
    lines = chunk.strip().splitlines()
    event = next((line[7:] for line in lines if line.startswith("event: ")), None)
    frame_id = next((line[4:] for line in lines if line.startswith("id: ")), None)
    data = next((line[6:] for line in lines if line.startswith("data: ")), None)
    return event, frame_id, json.loads(data) if data else None


class StreamFramingTests(StreamTestCase):
    def test_the_stream_opens_with_a_retry_hint_and_a_ready_event(self):
        chunks = self._collect(2, FakePubSub())

        self.assertEqual(chunks[0], "retry: 3000\n\n")
        event, _, data = frame(chunks[1])
        self.assertEqual(event, "ready")
        self.assertTrue(data["resync"])
        self.assertEqual(data["heartbeat_seconds"], 1)

    def test_a_quiet_stream_sends_heartbeat_comments(self):
        chunks = self._collect(3, FakePubSub())

        self.assertTrue(chunks[2].startswith(": heartbeat "), chunks[2])

    def test_a_notification_is_forwarded_with_its_stable_id(self):
        payload = {
            "id": "conv:2026-11-19T12:00:00+00:00",
            "type": "conversation",
            "event": "claimed",
            "conversation_id": str(uuid4()),
            "state": "human",
        }
        chunks = self._collect(3, FakePubSub(messages=[message(payload)]))

        event, frame_id, data = frame(chunks[2])
        self.assertEqual(event, "conversation")
        self.assertEqual(frame_id, payload["id"])
        self.assertEqual(data, payload)

    def test_a_presence_notification_keeps_its_own_event_name(self):
        payload = {"id": "presence:u:1", "type": "presence", "event": "online"}
        chunks = self._collect(3, FakePubSub(messages=[message(payload)]))

        event, _, data = frame(chunks[2])
        self.assertEqual(event, "presence")
        self.assertEqual(data["event"], "online")

    def test_a_reader_error_ends_the_stream_with_an_error_frame(self):
        chunks = self._collect(3, FakePubSub(error=ConnectionError("gone")))

        event, _, data = frame(chunks[2])
        self.assertEqual(event, "error")
        self.assertEqual(data["event"], "stream_interrupted")
        self.assertIn("gone", data["detail"])

    def test_a_stream_that_cannot_lease_reports_it_instead_of_hanging(self):
        chunks = self._collect(1, FakePubSub(), leased=False)

        event, _, data = frame(chunks[0])
        self.assertEqual(event, "error")
        self.assertEqual(data["event"], "redis_unavailable")
        self.delete_lease.assert_not_awaited()
        self.publish_event.assert_not_awaited()


class StreamLeaseTests(StreamTestCase):
    def test_the_lease_is_unique_per_connection_and_removed_on_close(self):
        self._collect(2, FakePubSub())
        first_key = self.set_lease.await_args.args[0]

        self._collect(2, FakePubSub())
        second_key = self.set_lease.await_args.args[0]

        self.assertNotEqual(first_key, second_key)
        self.assertIn(str(self.agent.id), first_key)
        self.assertIn(str(self.company.id), first_key)
        self.delete_lease.assert_awaited_once_with(second_key)

    def test_the_lease_is_renewed_on_every_quiet_tick(self):
        self._collect(4, FakePubSub())

        # Two heartbeats, so the second tick renewed once more: the TTL only has
        # to outlive one missed tick, not the whole session.
        self.assertEqual(self.renew_lease.await_count, 2)
        key, ttl = self.renew_lease.await_args.args
        self.assertIn(str(self.agent.id), key)
        self.assertGreaterEqual(ttl, 2)

    def test_presence_online_and_offline_are_published_on_the_company_channel(self):
        self._collect(2, FakePubSub())

        channel = self.publish_event.await_args_list[0].args[0]
        self.assertEqual(channel, f"inbox:{self.company.id}")
        events = [
            json.loads(call.args[1]) if isinstance(call.args[1], str) else call.args[1]
            for call in self.publish_event.await_args_list
        ]
        self.assertEqual(
            [(e["type"], e["event"], e["user_id"]) for e in events],
            [
                ("presence", "online", str(self.agent.id)),
                ("presence", "offline", str(self.agent.id)),
            ],
        )


class EventIdTests(StreamTestCase):
    def test_the_same_state_change_keeps_the_same_id(self):
        row = self._conversation()

        first = inbox.conversation_event(row, "claimed")
        second = inbox.conversation_event(row, "claimed")

        self.assertEqual(first["id"], second["id"])

    def test_a_later_change_gets_a_new_id(self):
        row = self._conversation()
        before = inbox.conversation_event(row, "claimed")

        row.state = "human"
        row.updated_at = NOW.replace(minute=5)
        after = inbox.conversation_event(row, "released")

        self.assertNotEqual(before["id"], after["id"])
        self.assertEqual(after["state"], "human")

    def test_the_payload_names_the_conversation_and_its_assignee(self):
        row = self._conversation()
        row.assigned_user_id = self.agent.id
        row.updated_at = NOW

        payload = inbox.conversation_event(row, "assigned")

        self.assertEqual(payload["conversation_id"], str(row.id))
        self.assertEqual(payload["website_id"], str(self.site.id))
        self.assertEqual(payload["assigned_user_id"], str(self.agent.id))
        self.assertEqual(payload["event"], "assigned")


class PresenceTests(StreamTestCase):
    def _keys(self, *specs):
        return [
            f"inbox:presence:{company_id}:{user_id}:{index}"
            for company_id, user_id, index in specs
        ]

    def test_connections_of_the_same_agent_are_counted_together(self):
        keys = self._keys(
            (self.company.id, self.agent.id, 1),
            (self.company.id, self.agent.id, 2),
            (self.company.id, self.teammate.id, 3),
        )

        with patch.object(
            inbox.redis_service, "lease_keys", AsyncMock(return_value=keys)
        ) as lease_keys:
            rows = asyncio.run(inbox.presence(self.db, self.company.id))

        self.assertEqual(
            [(row["user_id"], row["connections"]) for row in rows],
            sorted(
                [(self.agent.id, 2), (self.teammate.id, 1)],
                key=lambda item: str(item[0]),
            ),
        )
        names = {row["user_id"]: row["name"] for row in rows}
        self.assertEqual(names[self.agent.id], "agent Test")
        self.assertEqual(names[self.teammate.id], "mate Test")
        lease_keys.assert_awaited_once_with(f"inbox:presence:{self.company.id}:*")

    def test_foreign_and_malformed_keys_are_ignored(self):
        keys = self._keys((self.company.id, self.agent.id, 1)) + [
            f"inbox:presence:{self.company.id}:not-a-uuid:2",
            "unrelated:key",
        ]

        with patch.object(
            inbox.redis_service, "lease_keys", AsyncMock(return_value=keys)
        ):
            rows = asyncio.run(inbox.presence(self.db, self.company.id))

        self.assertEqual([row["user_id"] for row in rows], [self.agent.id])

    def test_a_key_seen_twice_by_scan_is_one_connection(self):
        # `SCAN` may repeat a key while the keyspace changes; counting the list
        # instead of the set would show one tab as two connections.
        keys = self._keys((self.company.id, self.agent.id, 1)) * 2

        with patch.object(
            inbox.redis_service, "lease_keys", AsyncMock(return_value=keys)
        ):
            rows = asyncio.run(inbox.presence(self.db, self.company.id))

        self.assertEqual([row["connections"] for row in rows], [1])

    def test_a_redis_outage_reads_as_nobody_online(self):
        with patch.object(
            inbox.redis_service, "lease_keys", AsyncMock(return_value=[])
        ):
            self.assertEqual(
                asyncio.run(inbox.presence(self.db, self.company.id)), []
            )


class StreamRouteTests(StreamTestCase):
    def test_events_is_a_404_when_the_inbox_is_off(self):
        self._setting("live_inbox_enabled", "false")
        client = self._client()

        with patch.object(
            inbox_api.redis_service, "ping", AsyncMock(return_value=True)
        ) as ping:
            response = client.get("/api/inbox/events")

        self.assertEqual(response.status_code, 404, response.text)
        ping.assert_not_awaited()

    def test_events_is_503_before_streaming_when_redis_is_down(self):
        client = self._client()

        with patch.object(
            inbox_api.redis_service, "ping", AsyncMock(return_value=False)
        ):
            response = client.get("/api/inbox/events")

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["detail"], inbox_api.STREAM_UNAVAILABLE)

    def test_events_streams_sse_without_proxy_buffering(self):
        client = self._client()
        calls = []

        async def finite(company_id, user_id, *, disconnect=None):
            calls.append((company_id, user_id, disconnect))
            yield "retry: 3000\n\n"

        with patch.object(
            inbox_api.redis_service, "ping", AsyncMock(return_value=True)
        ), patch.object(inbox_api.inbox, "event_stream", finite):
            response = client.get("/api/inbox/events")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream")
        )
        self.assertEqual(
            response.headers["cache-control"], "no-cache, no-transform"
        )
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertEqual(response.text, "retry: 3000\n\n")
        self.assertEqual(calls[0][0], self.company.id)
        self.assertEqual(calls[0][1], self.agent.id)
        self.assertIsNotNone(calls[0][2])

    def test_presence_lists_the_callers_company_only(self):
        client = self._client()
        keys = [f"inbox:presence:{self.company.id}:{self.agent.id}:1"]

        with patch.object(
            inbox.redis_service, "lease_keys", AsyncMock(return_value=keys)
        ) as lease_keys:
            response = client.get("/api/inbox/presence")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {
                    "user_id": str(self.agent.id),
                    "name": "agent Test",
                    "connections": 1,
                }
            ],
        )
        lease_keys.assert_awaited_once_with(f"inbox:presence:{self.company.id}:*")

    def test_presence_is_a_404_when_the_inbox_is_off(self):
        self._setting("live_inbox_enabled", "false")
        client = self._client()

        response = client.get("/api/inbox/presence")

        self.assertEqual(response.status_code, 404, response.text)


class PublishingTests(StreamTestCase):
    def test_claim_publishes_only_after_the_commit(self):
        row = self._conversation()
        client = self._client()
        captured = []
        states = []

        async def capture(company_id, payload):
            captured.append((company_id, payload))
            self.db.expire_all()
            stored = self.db.get(models.Conversation, row.id)
            states.append(stored.state)
            return True

        with patch.object(inbox, "publish", side_effect=capture):
            response = client.post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(response.status_code, 200, response.text)
        company_id, payload = captured[0]
        self.assertEqual(company_id, self.company.id)
        self.assertEqual(payload["event"], "claimed")
        self.assertEqual(payload["state"], "human")
        self.assertEqual(payload["conversation_id"], str(row.id))
        # The row was already `human` when the notification went out.
        self.assertEqual(states, ["human"])

    def test_assign_publishes_the_new_assignee(self):
        row = self._conversation()
        client = self._client()
        captured = []

        async def capture(company_id, payload):
            captured.append(payload)
            return True

        with patch.object(inbox, "publish", side_effect=capture):
            response = client.post(
                f"/api/inbox/conversations/{row.id}/assign",
                json={"user_id": str(self.teammate.id)},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(captured[0]["event"], "assigned")
        self.assertEqual(captured[0]["assigned_user_id"], str(self.teammate.id))

    def test_release_and_close_publish_their_own_events(self):
        row = self._conversation(state="human", last=NOW)
        row.assigned_user_id = self.agent.id
        self.db.commit()
        client = self._client()
        events = []

        async def capture(company_id, payload):
            events.append(payload["event"])
            return True

        with patch.object(inbox, "publish", side_effect=capture):
            released = client.post(
                f"/api/inbox/conversations/{row.id}/release"
            )
            closed = client.post(f"/api/inbox/conversations/{row.id}/close")

        self.assertEqual(released.status_code, 200, released.text)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(events, ["released", "closed"])

    def test_a_refused_action_publishes_nothing(self):
        row = self._conversation(state="human")
        row.assigned_user_id = self.teammate.id
        self.db.commit()
        client = self._client()

        with patch.object(inbox, "publish", AsyncMock(return_value=True)) as publish:
            response = client.post(
                f"/api/inbox/conversations/{row.id}/release"
            )

        self.assertEqual(response.status_code, 409, response.text)
        publish.assert_not_awaited()

    def test_the_service_never_publishes_on_its_own(self):
        row = self._conversation()

        with patch.object(inbox, "publish", AsyncMock(return_value=True)) as publish:
            inbox.claim(self.db, self.company.id, row.id, self.agent)

        publish.assert_not_awaited()
        self.db.expire_all()
        self.assertEqual(
            self.db.get(models.Conversation, row.id).state, "human"
        )

    def test_an_idempotent_retry_publishes_the_same_event_id(self):
        row = self._conversation()
        client = self._client()
        ids = []

        async def capture(company_id, payload):
            ids.append(payload["id"])
            return True

        with patch.object(inbox, "publish", side_effect=capture):
            first = client.post(f"/api/inbox/conversations/{row.id}/claim")
            second = client.post(f"/api/inbox/conversations/{row.id}/claim")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], ids[1])


if __name__ == "__main__":
    unittest.main()
