"""V6-23: bounded Redis I/O and the durability settings that can drop jobs.

What is pinned here:

* every client this module builds carries the socket timeouts and the health
  check from configuration, so a hung Redis fails a command instead of pinning a
  request or the worker's whole job loop;
* the durability classifier names the two settings that can delete `queue:jobs`
  (an eviction policy other than `noeviction`, and a restart with no
  persistence), and treats an unreadable `CONFIG GET` as unknown rather than
  safe;
* `evaluate` raises `redis.durability_unsafe` only when the settings were read
  and one of them is bad;
* the production validator refuses a socket timeout at or below the inbox
  stream heartbeat, which would cut every SSE read before its own heartbeat.
"""

import asyncio
import unittest
from unittest.mock import patch

from site_gpt.app.core import config, telemetry
from site_gpt.app.services import redis as redis_mod


class _DurabilityClient:
    """Just enough async Redis for `config_get`."""

    def __init__(self, values=None, fail=False):
        self.values = values
        self.fail = fail
        self.params = None

    async def config_get(self, *names):
        self.params = names
        if self.fail:
            raise RuntimeError("CONFIG is disabled")
        return dict(self.values or {})


class ClientBoundsTests(unittest.TestCase):
    def test_the_shared_client_carries_every_bound(self):
        client = redis_mod.create_client()
        kwargs = client.connection_pool.connection_kwargs

        self.assertEqual(
            kwargs["socket_connect_timeout"],
            config.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
        self.assertEqual(kwargs["socket_timeout"], config.REDIS_SOCKET_TIMEOUT_SECONDS)
        self.assertEqual(
            kwargs["health_check_interval"],
            config.REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
        )
        self.assertTrue(kwargs["decode_responses"])

    def test_overrides_win_so_a_caller_can_tighten_one_command(self):
        client = redis_mod.create_client(socket_timeout=1.5)

        self.assertEqual(client.connection_pool.connection_kwargs["socket_timeout"], 1.5)

    def test_the_default_socket_timeout_outlives_the_stream_heartbeat(self):
        # An SSE read waits the heartbeat's worth of silence; a shorter socket
        # timeout would turn every idle console into a reconnect loop.
        self.assertGreater(
            config.REDIS_SOCKET_TIMEOUT_SECONDS, config.INBOX_STREAM_HEARTBEAT_SECONDS
        )
        self.assertNotIn(
            "REDIS_SOCKET_TIMEOUT_SECONDS",
            config.production_config_errors(
                {
                    "JWT_SECRET_KEY": "x" * 40,
                    "CORS_ORIGINS": "https://app.example.com",
                    "SQL_ECHO": False,
                    "RATE_LIMIT_BACKEND": "redis",
                    "API_KEY_PEPPER": "pepper",
                    "INTEGRATION_WEBHOOK_SECRET": "secret",
                    "TRUSTED_PROXY_IPS": "10.0.0.0/8",
                    "DOCS_ENABLED": False,
                    "PLATFORM_CONSOLE_ENABLED": False,
                    "REDIS_SOCKET_TIMEOUT_SECONDS": 30,
                    "INBOX_STREAM_HEARTBEAT_SECONDS": 15,
                }
            ),
        )


class ProductionSocketTimeoutTests(unittest.TestCase):
    VALUES = {
        "JWT_SECRET_KEY": "x" * 40,
        "CORS_ORIGINS": "https://app.example.com",
        "SQL_ECHO": False,
        "RATE_LIMIT_BACKEND": "redis",
        "API_KEY_PEPPER": "pepper",
        "INTEGRATION_WEBHOOK_SECRET": "secret",
        "TRUSTED_PROXY_IPS": "10.0.0.0/8",
        "DOCS_ENABLED": False,
        "PLATFORM_CONSOLE_ENABLED": False,
    }

    def _errors(self, socket_timeout, heartbeat):
        values = dict(self.VALUES)
        values["REDIS_SOCKET_TIMEOUT_SECONDS"] = socket_timeout
        values["INBOX_STREAM_HEARTBEAT_SECONDS"] = heartbeat
        return config.production_config_errors(values)

    def test_a_timeout_below_the_heartbeat_is_refused(self):
        self.assertIn("REDIS_SOCKET_TIMEOUT_SECONDS", self._errors(10, 15))

    def test_exactly_the_heartbeat_is_refused(self):
        # The read and the stream timer would race at the same instant.
        self.assertIn("REDIS_SOCKET_TIMEOUT_SECONDS", self._errors(15, 15))

    def test_a_timeout_above_the_heartbeat_passes(self):
        self.assertNotIn("REDIS_SOCKET_TIMEOUT_SECONDS", self._errors(16, 15))

    def test_a_partial_mapping_skips_the_relation(self):
        self.assertEqual(config.production_config_errors(self.VALUES), [])


class DurabilityProblemsTests(unittest.TestCase):
    def test_a_durable_instance_has_no_problems(self):
        self.assertEqual(
            redis_mod.durability_problems(
                {"maxmemory-policy": "noeviction", "appendonly": "yes"}
            ),
            [],
        )

    def test_an_eviction_policy_is_named(self):
        # Any allkeys/volatile policy can free the queue when maxmemory is hit.
        for policy in ("allkeys-lru", "allkeys-random", "volatile-ttl"):
            with self.subTest(policy=policy):
                self.assertEqual(
                    redis_mod.durability_problems(
                        {"maxmemory-policy": policy, "appendonly": "yes"}
                    ),
                    ["maxmemory-policy"],
                )

    def test_no_persistence_at_all_is_named(self):
        self.assertEqual(
            redis_mod.durability_problems(
                {"maxmemory-policy": "noeviction", "appendonly": "no", "save": ""}
            ),
            ["appendonly"],
        )

    def test_a_save_schedule_is_enough_without_appendonly(self):
        self.assertEqual(
            redis_mod.durability_problems(
                {
                    "maxmemory-policy": "noeviction",
                    "appendonly": "no",
                    "save": "3600 1 300 100",
                }
            ),
            [],
        )

    def test_both_problems_are_reported_together(self):
        self.assertEqual(
            redis_mod.durability_problems({"maxmemory-policy": "allkeys-lru"}),
            ["maxmemory-policy", "appendonly"],
        )


class DurabilityReadTests(unittest.TestCase):
    def test_the_three_settings_are_read(self):
        client = _DurabilityClient(
            {"maxmemory-policy": "noeviction", "appendonly": "yes", "save": ""}
        )
        with patch.object(redis_mod, "get_client", lambda: client):
            report = asyncio.run(redis_mod.durability())

        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(
            client.params, ("maxmemory-policy", "appendonly", "save")
        )

    def test_a_bad_policy_is_reported_with_its_setting_name(self):
        client = _DurabilityClient(
            {"maxmemory-policy": "allkeys-lru", "appendonly": "yes", "save": ""}
        )
        with patch.object(redis_mod, "get_client", lambda: client):
            report = asyncio.run(redis_mod.durability())

        self.assertEqual(report["problems"], ["maxmemory-policy"])

    def test_an_unreadable_config_is_unknown_not_safe(self):
        client = _DurabilityClient(fail=True)
        with patch.object(redis_mod, "get_client", lambda: client):
            report = asyncio.run(redis_mod.durability())

        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["settings"], {})


def _snapshot(**durability):
    redis = {
        "ok": True,
        "heartbeat_age_seconds": 5.0,
        "heartbeat_loops": ["queue"],
        "queue_depth": 0,
        "queue_age_seconds": None,
        "job_failures": 0,
        "workers": [],
    }
    if durability:
        redis["durability"] = durability
    return {
        "db": True,
        "redis": redis,
        "api": {
            "requests": 0,
            "errors_5xx": 0,
            "error_rate": 0.0,
            "window_seconds": 300,
        },
    }


class DurabilityAlertTests(unittest.TestCase):
    def _codes(self, snapshot):
        return [alert["code"] for alert in telemetry.evaluate(snapshot)]

    def test_an_unsafe_policy_raises_a_critical_alert(self):
        alerts = telemetry.evaluate(
            _snapshot(ok=True, problems=["maxmemory-policy"], settings={})
        )

        self.assertIn("redis.durability_unsafe", [a["code"] for a in alerts])
        alert = next(a for a in alerts if a["code"] == "redis.durability_unsafe")
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["evidence"]["problems"], ["maxmemory-policy"])

    def test_durable_settings_raise_nothing(self):
        self.assertNotIn(
            "redis.durability_unsafe",
            self._codes(_snapshot(ok=True, problems=[], settings={})),
        )

    def test_unreadable_settings_raise_nothing(self):
        # Unknown is not a pass, but it is also not evidence of a bad policy.
        self.assertNotIn(
            "redis.durability_unsafe", self._codes(_snapshot(ok=False, problems=[]))
        )

    def test_a_snapshot_without_the_field_still_evaluates(self):
        self.assertNotIn("redis.durability_unsafe", self._codes(_snapshot()))


if __name__ == "__main__":
    unittest.main()
