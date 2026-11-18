import asyncio
import ipaddress
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from site_gpt.app.services import ratelimit
from site_gpt.app.services.ratelimit import (
    RATE_LIMIT_POLICIES,
    _client_ip,
    _trusted_networks,
    allow,
    limiter_degraded,
    rate_limit,
    rate_limit_policy,
)


def make_request(headers=None, client=("127.0.0.1", 1234)):
    scope = {
        "type": "http",
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


class ClientIpTests(unittest.TestCase):
    def test_uses_first_x_forwarded_for_entry_from_local_proxy(self):
        request = make_request({"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_strips_surrounding_whitespace(self):
        request = make_request({"x-forwarded-for": "  1.1.1.1  "})
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_private_proxy_peer_is_trusted(self):
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("10.0.0.5", 5000)
        )
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_ipv6_loopback_proxy_is_trusted(self):
        request = make_request({"x-forwarded-for": "1.1.1.1"}, client=("::1", 5000))
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_public_peer_cannot_spoof_x_forwarded_for(self):
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("9.9.9.9", 5000)
        )
        self.assertEqual(_client_ip(request), "9.9.9.9")

    def test_malformed_forwarded_entry_falls_back_to_peer(self):
        request = make_request({"x-forwarded-for": "not-an-ip"})
        self.assertEqual(_client_ip(request), "127.0.0.1")

    def test_falls_back_to_socket_ip_without_header(self):
        request = make_request(client=("127.0.0.1", 4321))
        self.assertEqual(_client_ip(request), "127.0.0.1")

    def test_unknown_when_client_is_missing(self):
        request = make_request({"x-forwarded-for": "1.1.1.1"}, client=None)
        self.assertEqual(_client_ip(request), "unknown")


class TrustedProxyAllowlistTests(unittest.TestCase):
    """A public-address LB must be listed in TRUSTED_PROXY_IPS."""

    def test_listed_public_proxy_uses_forwarded_client_ip(self):
        networks = [ipaddress.ip_network("8.8.8.0/24")]
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("8.8.8.10", 5000)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_unlisted_public_proxy_keeps_socket_ip(self):
        networks = [ipaddress.ip_network("8.8.8.0/24")]
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("1.0.0.7", 5000)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "1.0.0.7")

    def test_single_ip_entry_matches_exactly(self):
        networks = _trusted_networks(["8.8.8.10"])
        trusted = make_request({"x-forwarded-for": "1.1.1.1"}, client=("8.8.8.10", 1))
        other = make_request({"x-forwarded-for": "1.1.1.1"}, client=("8.8.8.11", 1))

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(trusted), "1.1.1.1")
            self.assertEqual(_client_ip(other), "8.8.8.11")

    def test_ipv6_allowlist_entry(self):
        networks = _trusted_networks(["2001:db8::/32"])
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("2001:db8::5", 1)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_malformed_forwarded_entry_from_trusted_proxy_falls_back(self):
        networks = [ipaddress.ip_network("8.8.8.0/24")]
        request = make_request(
            {"x-forwarded-for": "definitely-not-an-ip"}, client=("8.8.8.10", 1)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "8.8.8.10")

    def test_parsing_skips_invalid_entries_and_handles_host_entries(self):
        networks = _trusted_networks(["nonsense", "10.0.0.0/8", "", "8.8.8.10"])

        self.assertEqual(
            [str(n) for n in networks], ["10.0.0.0/8", "8.8.8.10/32"]
        )

    def test_empty_configuration_trusts_nothing_public(self):
        self.assertEqual(_trusted_networks([]), [])


class MemoryBackendTests(unittest.TestCase):
    def test_memory_backend_is_the_default_and_limits(self):
        self.assertEqual(ratelimit.RATE_LIMIT_BACKEND, "memory")
        self.assertFalse(limiter_degraded())

        async def go():
            key = f"test:{id(self)}"
            self.assertTrue(await allow(key, 2, 60))
            self.assertTrue(await allow(key, 2, 60))
            self.assertFalse(await allow(key, 2, 60))

        asyncio.run(go())


class RedisBackendTests(unittest.TestCase):
    def _patch(self, fake_client):
        return patch.object(ratelimit, "RATE_LIMIT_BACKEND", "redis"), patch(
            "site_gpt.app.services.redis.redis_client", fake_client
        )

    def test_redis_backend_allows_and_denies_via_lua(self):
        fake = MagicMock()
        fake.eval = AsyncMock(side_effect=[1, 1, 0])
        p1, p2 = self._patch(fake)
        with p1, p2:
            async def go():
                self.assertTrue(await allow("k", 2, 60))
                self.assertTrue(await allow("k", 2, 60))
                self.assertFalse(await allow("k", 2, 60))
            asyncio.run(go())
        self.assertEqual(fake.eval.await_count, 3)
        # Lua script must prune + count + conditionally add atomically.
        script = fake.eval.call_args.args[0]
        for token in ("ZREMRANGEBYSCORE", "ZCOUNT", "ZADD", "PEXPIRE"):
            self.assertIn(token, script)

    def test_redis_error_falls_back_to_memory_and_marks_degraded(self):
        fake = MagicMock()
        fake.eval = AsyncMock(side_effect=ConnectionError("down"))
        p1, p2 = self._patch(fake)
        with p1, p2:
            async def go():
                key = f"fb:{id(self)}"
                # Memory fallback still enforces a per-process cap.
                self.assertTrue(await allow(key, 1, 60))
                self.assertFalse(await allow(key, 1, 60))
                self.assertTrue(limiter_degraded())
            asyncio.run(go())

    def test_successful_redis_call_clears_degraded(self):
        fake = MagicMock()
        fake.eval = AsyncMock(side_effect=[1])
        p1, p2 = self._patch(fake)
        with patch.object(ratelimit, "_redis_degraded", True), p1, p2:
            asyncio.run(allow("k", 5, 60))
            self.assertFalse(limiter_degraded())

    def test_fallback_is_per_process_not_shared(self):
        # Documents D5: two processes each get their own memory budget during
        # an outage, so combined traffic may exceed one shared budget.
        fake = MagicMock()
        fake.eval = AsyncMock(side_effect=ConnectionError("down"))
        p1, p2 = self._patch(fake)
        with p1, p2:
            async def go():
                # Same key, but each "process" has its own _hits deque.
                self.assertTrue(await allow("shared", 1, 60))
                ratelimit._hits.clear()  # simulate the other process
                self.assertTrue(await allow("shared", 1, 60))
            asyncio.run(go())


class PolicyTableTests(unittest.TestCase):
    def test_policy_table_matches_pre_v3_literals(self):
        expected = {
            "chat": ("chat", 20, 60),
            "stream": ("chat", 20, 60),
            "feedback": ("chat", 40, 60),
            "contacts": ("chat", 40, 60),
            "handoff": ("chat", 10, 60),
            "session-token": ("session", 30, 60),
            "ingest": ("ingest", 10, 60),
            "register": ("register", 3, 3600),
            "login": ("login", 10, 60),
            "reset": ("reset", 3, 3600),
            "reset-confirm": ("reset-confirm", 10, 300),
            "v1": ("v1", 60, 60),
        }
        self.assertEqual(RATE_LIMIT_POLICIES, expected)

    def test_rate_limit_policy_builds_a_dependency(self):
        dep = rate_limit_policy("chat")
        self.assertTrue(asyncio.iscoroutinefunction(dep))

    def test_429_carries_retry_after_and_unchanged_body(self):
        async def go():
            dep = rate_limit("chat", max_requests=1, window_seconds=7)
            request = make_request()
            await dep(request)
            with self.assertRaises(HTTPException) as ctx:
                await dep(request)
            exc = ctx.exception
            self.assertEqual(exc.status_code, 429)
            self.assertEqual(exc.headers["Retry-After"], "7")
            self.assertEqual(
                exc.detail,
                "Too many requests. Limit is 1 per 7s. Please slow down.",
            )

        asyncio.run(go())

if __name__ == "__main__":
    unittest.main()
