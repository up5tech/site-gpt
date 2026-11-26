"""V3-02: one Redis access module — helpers stub the client, no live Redis."""

import asyncio
import importlib
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from site_gpt.app.services import redis as redis_mod


class ImportTests(unittest.TestCase):
    def test_import_works_with_redis_down(self):
        # Construction must not connect: building the client issues no
        # command (no ping), so import never touches the network.
        with patch.object(redis_mod.aioredis, "Redis") as mock:
            client = redis_mod.create_client()
        self.assertIs(client, mock.return_value)
        mock.return_value.ping.assert_not_called()
        self.assertIsNotNone(redis_mod.redis_client)

    def test_create_client_uses_config(self):
        with patch.object(redis_mod.aioredis, "Redis") as mock:
            redis_mod.create_client()
        kwargs = mock.call_args.kwargs
        self.assertEqual(kwargs["decode_responses"], True)
        self.assertIn("host", kwargs)


class PingTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_ping_true(self):
        fake = MagicMock()
        fake.ping = AsyncMock(return_value=True)
        with patch.object(redis_mod, "redis_client", fake):
            self.assertTrue(self._run(redis_mod.ping()))

    def test_ping_false_on_error(self):
        fake = MagicMock()
        fake.ping = AsyncMock(side_effect=ConnectionError("down"))
        with patch.object(redis_mod, "redis_client", fake):
            self.assertFalse(self._run(redis_mod.ping()))


class EnqueueTests(unittest.TestCase):
    def test_enqueue_payload_is_additive(self):
        # V6-20's envelope adds `job_id`/`attempt` and changes nothing else: the
        # producer's fields and the top-level `type` reach `queue:jobs` verbatim,
        # which is what every handler and the gate's redis-cli recipes read.
        fake = MagicMock()
        fake.lpush = AsyncMock()
        with patch.object(redis_mod, "redis_client", fake):
            asyncio.run(redis_mod.enqueue_job({"type": "ingest", "website_id": "w1"}))
        fake.lpush.assert_awaited_once()
        key, payload = fake.lpush.call_args.args
        self.assertEqual(key, "queue:jobs")
        body = json.loads(payload)
        self.assertEqual(body["type"], "ingest")
        self.assertEqual(body["website_id"], "w1")
        self.assertEqual(body["attempt"], 0)
        self.assertEqual(set(body), {"type", "website_id", "job_id", "attempt"})


class PublishSubscribeTests(unittest.TestCase):
    def test_publish_event_dict_serialises_json(self):
        fake = MagicMock()
        fake.publish = AsyncMock()
        with patch.object(redis_mod, "redis_client", fake):
            ok = asyncio.run(redis_mod.publish_event("inbox:1", {"id": "m1"}))
        self.assertTrue(ok)
        fake.publish.assert_awaited_once_with("inbox:1", json.dumps({"id": "m1"}))

    def test_publish_event_false_on_error(self):
        fake = MagicMock()
        fake.publish = AsyncMock(side_effect=ConnectionError("down"))
        with patch.object(redis_mod, "redis_client", fake):
            self.assertFalse(asyncio.run(redis_mod.publish_event("c", "x")))

    def test_subscribe_cleans_up_on_exit(self):
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        fake = MagicMock()
        fake.pubsub.return_value = pubsub

        async def go():
            with patch.object(redis_mod, "redis_client", fake):
                async with redis_mod.subscribe("chan") as ps:
                    self.assertIs(ps, pubsub)
            # exited cleanly -> unsubscribe + aclose ran
            pubsub.unsubscribe.assert_awaited_once_with("chan")
            pubsub.aclose.assert_awaited_once()

        asyncio.run(go())

    def test_subscribe_cleans_up_on_exception(self):
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        fake = MagicMock()
        fake.pubsub.return_value = pubsub

        async def go():
            with patch.object(redis_mod, "redis_client", fake):
                with self.assertRaises(ValueError):
                    async with redis_mod.subscribe("chan"):
                        raise ValueError("consumer gone")
            pubsub.unsubscribe.assert_awaited_once_with("chan")
            pubsub.aclose.assert_awaited_once()

        asyncio.run(go())


class IncrementTests(unittest.TestCase):
    def test_increment_sets_ttl_on_first_use(self):
        fake = MagicMock()
        fake.incr = AsyncMock(return_value=1)
        fake.expire = AsyncMock()
        with patch.object(redis_mod, "redis_client", fake):
            value = asyncio.run(redis_mod.increment("rl:x", 60))
        self.assertEqual(value, 1)
        fake.expire.assert_awaited_once_with("rl:x", 60)

    def test_increment_no_ttl_after_first(self):
        fake = MagicMock()
        fake.incr = AsyncMock(return_value=3)
        fake.expire = AsyncMock()
        with patch.object(redis_mod, "redis_client", fake):
            value = asyncio.run(redis_mod.increment("rl:x", 60))
        self.assertEqual(value, 3)
        fake.expire.assert_not_awaited()

    def test_increment_none_on_error(self):
        fake = MagicMock()
        fake.incr = AsyncMock(side_effect=ConnectionError("down"))
        with patch.object(redis_mod, "redis_client", fake):
            self.assertIsNone(asyncio.run(redis_mod.increment("rl:x", 60)))


class LeaseKeyTests(unittest.TestCase):
    """Presence leases are read with `SCAN`, never with the blocking `KEYS`."""

    def test_lease_keys_scans_the_pattern(self):
        seen = []
        wanted = ["inbox:presence:c:u:1", "inbox:presence:c:u:2"]

        async def pages():
            for key in wanted:
                yield key

        def scan_iter(match=None):
            seen.append(match)
            return pages()

        fake = MagicMock()
        fake.scan_iter = scan_iter
        fake.keys = AsyncMock()
        with patch.object(redis_mod, "redis_client", fake):
            keys = asyncio.run(redis_mod.lease_keys("inbox:presence:c:*"))

        self.assertEqual(keys, wanted)
        self.assertEqual(seen, ["inbox:presence:c:*"])
        # `KEYS` holds the server for the whole keyspace; presence must not use it.
        fake.keys.assert_not_awaited()

    def test_lease_keys_is_empty_on_error(self):
        async def failing():
            yield "inbox:presence:c:u:1"
            raise ConnectionError("down")

        fake = MagicMock()
        fake.scan_iter = lambda match=None: failing()
        with patch.object(redis_mod, "redis_client", fake):
            self.assertEqual(
                asyncio.run(redis_mod.lease_keys("inbox:presence:c:*")), []
            )


if __name__ == "__main__":
    unittest.main()
