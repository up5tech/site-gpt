"""V6-21: request counters, worker/queue visibility and the D8 alert set.

What is pinned here:

* the in-process 5xx window counts, expires and needs a minimum sample before it
  can alert (so one failed request does not page anyone);
* the worker writes a self-expiring heartbeat, a queue-pop time and a
  windowed failure counter;
* `redis_snapshot` turns those keys plus `LLEN` into ages, and reports missing
  data instead of raising when Redis is down;
* every alert fires only *above* its configured threshold, with a stable code
  and aggregate evidence — never a tenant id, path or payload.
"""

import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from site_gpt.app.core import telemetry
from site_gpt.app.core.logging import RequestContextMiddleware

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


class _Client:
    """Just enough async Redis for the telemetry keys."""

    def __init__(self, values=None, depth=0, fail=False, incr_to=1):
        self.values = dict(values or {})
        self.depth = depth
        self.fail = fail
        self.incr_to = incr_to
        self.set_calls = []
        self.expires = []

    async def get(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        return self.values.get(key)

    async def llen(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        return self.depth

    async def set(self, key, value, ex=None):
        if self.fail:
            raise RuntimeError("redis down")
        self.set_calls.append((key, value, ex))
        self.values[key] = value
        return True

    async def incr(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        self.incr_to += 1
        return self.incr_to

    async def expire(self, key, ttl):
        self.expires.append((key, ttl))
        return True


def _snapshot(**overrides):
    redis = {
        "ok": True,
        "heartbeat_age_seconds": 5.0,
        "heartbeat_loops": ["queue"],
        "queue_depth": 0,
        "queue_age_seconds": None,
        "job_failures": 0,
    }
    redis.update(overrides.pop("redis", {}))
    snapshot = {"db": True, "redis": redis, "api": {"requests": 0, "errors_5xx": 0, "error_rate": 0.0}}
    snapshot.update(overrides)
    return snapshot


def _codes(snapshot):
    return [alert["code"] for alert in telemetry.evaluate(snapshot)]


class RequestWindowTests(unittest.TestCase):
    def setUp(self):
        telemetry.reset_request_window()

    def tearDown(self):
        telemetry.reset_request_window()

    def test_counts_and_rate(self):
        telemetry.record_request(200, now=1000.0)
        telemetry.record_request(404, now=1001.0)
        telemetry.record_request(500, now=1002.0)

        window = telemetry.request_window(now=1003.0)

        self.assertEqual(window["requests"], 3)
        self.assertEqual(window["errors_5xx"], 1)
        self.assertAlmostEqual(window["error_rate"], 1 / 3)

    def test_requests_age_out_of_the_window(self):
        telemetry.record_request(500, now=1000.0)
        telemetry.record_request(200, now=1000.0 + telemetry.API_ERROR_RATE_WINDOW_SECONDS + 1)

        window = telemetry.request_window(
            now=1000.0 + telemetry.API_ERROR_RATE_WINDOW_SECONDS + 1
        )

        self.assertEqual(window["requests"], 1)
        self.assertEqual(window["errors_5xx"], 0)

    def test_a_tiny_sample_cannot_alert(self):
        # 1 of 1 failed is a 100% rate, but D8 should not page on one request.
        with patch.object(telemetry, "API_ERROR_RATE_MIN_REQUESTS", 20):
            alerts = telemetry.evaluate(
                _snapshot(api={"requests": 1, "errors_5xx": 1, "error_rate": 1.0})
            )

        self.assertNotIn("api.error_rate", [alert["code"] for alert in alerts])

    def test_rate_above_threshold_warns_then_criticals(self):
        with (
            patch.object(telemetry, "API_ERROR_RATE_MIN_REQUESTS", 20),
            patch.object(telemetry, "API_ERROR_RATE_ALERT", 0.02),
        ):
            warning = telemetry.evaluate(
                _snapshot(api={"requests": 100, "errors_5xx": 2, "error_rate": 0.02})
            )
            critical = telemetry.evaluate(
                _snapshot(api={"requests": 100, "errors_5xx": 5, "error_rate": 0.05})
            )

        self.assertEqual(warning[0]["severity"], "warning")
        self.assertEqual(critical[0]["severity"], "critical")
        self.assertEqual(critical[0]["code"], "api.error_rate")

    def test_the_access_middleware_feeds_the_window(self):
        # The counters are only useful if the request path actually writes them.
        telemetry.reset_request_window()
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/boom")
        async def boom():
            return JSONResponse({"detail": "boom"}, status_code=500)

        TestClient(app).get("/boom")

        window = telemetry.request_window()
        self.assertEqual(window["requests"], 1)
        self.assertEqual(window["errors_5xx"], 1)


class WorkerHeartbeatTests(unittest.TestCase):
    def test_heartbeat_self_expires(self):
        client = _Client()

        self.assertTrue(_write(client))

        key, value, ttl = client.set_calls[0]
        self.assertEqual(key, telemetry.HEARTBEAT_KEY)
        self.assertEqual(ttl, telemetry.HEARTBEAT_TTL_SECONDS)
        payload = json.loads(value)
        self.assertIn("at", payload)
        self.assertEqual(payload["loops"], ["queue"])

    def test_a_failed_heartbeat_is_reported_not_raised(self):
        self.assertFalse(_write(_Client(fail=True)))

    def test_queue_pop_time_is_recorded(self):
        client = _Client()

        self.assertTrue(_note_pop(client, NOW))

        key, value, _ = client.set_calls[0]
        self.assertEqual(key, telemetry.LAST_POP_KEY)
        self.assertEqual(datetime.fromisoformat(value), NOW)

    def test_job_failure_counter_starts_its_window(self):
        client = _Client(incr_to=0)

        self.assertEqual(_note_failure(client), 1)
        self.assertEqual(client.expires[0][0], telemetry.JOB_FAILURES_KEY)
        self.assertEqual(client.expires[0][1], telemetry.JOB_FAILURE_WINDOW_SECONDS)

    def test_note_failure_returns_none_when_redis_is_down(self):
        self.assertIsNone(_note_failure(_Client(fail=True)))


class RedisSnapshotTests(unittest.TestCase):
    def test_reads_ages_depth_and_counters(self):
        client = _Client(
            values={
                telemetry.HEARTBEAT_KEY: json.dumps(
                    {"at": (NOW - timedelta(seconds=10)).isoformat(), "loops": ["queue", "digest"]}
                ),
                telemetry.LAST_POP_KEY: (NOW - timedelta(seconds=120)).isoformat(),
                telemetry.JOB_FAILURES_KEY: "4",
            },
            depth=7,
        )

        snapshot = _snapshot_of(client)

        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["queue_depth"], 7)
        self.assertAlmostEqual(snapshot["heartbeat_age_seconds"], 10)
        self.assertAlmostEqual(snapshot["queue_age_seconds"], 120)
        self.assertEqual(snapshot["heartbeat_loops"], ["queue", "digest"])
        self.assertEqual(snapshot["job_failures"], 4)

    def test_an_empty_queue_has_no_age(self):
        client = _Client(
            values={
                telemetry.HEARTBEAT_KEY: json.dumps({"at": NOW.isoformat()}),
                telemetry.LAST_POP_KEY: (NOW - timedelta(hours=3)).isoformat(),
            },
            depth=0,
        )

        snapshot = _snapshot_of(client)

        self.assertIsNone(snapshot["queue_age_seconds"])

    def test_a_dead_worker_has_no_heartbeat(self):
        snapshot = _snapshot_of(_Client(depth=0))

        self.assertIsNone(snapshot["heartbeat_age_seconds"])
        self.assertIn("worker.heartbeat_missing", _codes(_snapshot(redis=snapshot)))

    def test_redis_down_is_reported_not_raised(self):
        snapshot = _snapshot_of(_Client(fail=True))

        self.assertFalse(snapshot["ok"])
        self.assertIsNone(snapshot["queue_depth"])


class AlertRuleTests(unittest.TestCase):
    def test_healthy_snapshot_has_no_alerts(self):
        self.assertEqual(telemetry.evaluate(_snapshot()), [])

    def test_database_and_redis_outages(self):
        codes = _codes(_snapshot(db=False, redis={"ok": False}))

        self.assertIn("api.database_unreachable", codes)
        self.assertIn("api.redis_unreachable", codes)

    def test_stale_heartbeat_alerts_only_past_the_threshold(self):
        with patch.object(telemetry, "WORKER_HEARTBEAT_STALE_SECONDS", 90):
            at_threshold = _codes(_snapshot(redis={"heartbeat_age_seconds": 90.0}))
            past_threshold = _codes(_snapshot(redis={"heartbeat_age_seconds": 91.0}))

        self.assertNotIn("worker.heartbeat_stale", at_threshold)
        self.assertIn("worker.heartbeat_stale", past_threshold)

    def test_queue_depth_and_age_boundaries(self):
        with (
            patch.object(telemetry, "QUEUE_DEPTH_ALERT", 100),
            patch.object(telemetry, "QUEUE_AGE_ALERT_SECONDS", 900),
        ):
            at_threshold = _codes(
                _snapshot(redis={"queue_depth": 100, "queue_age_seconds": 900.0})
            )
            past_threshold = _codes(
                _snapshot(redis={"queue_depth": 101, "queue_age_seconds": 901.0})
            )

        self.assertNotIn("queue.depth_high", at_threshold)
        self.assertNotIn("queue.age_high", at_threshold)
        self.assertIn("queue.depth_high", past_threshold)
        self.assertIn("queue.age_high", past_threshold)

    def test_repeated_job_failures(self):
        with patch.object(telemetry, "JOB_FAILURE_ALERT_COUNT", 3):
            self.assertNotIn("worker.job_failures", _codes(_snapshot(redis={"job_failures": 2})))
            self.assertIn("worker.job_failures", _codes(_snapshot(redis={"job_failures": 3})))

    def test_alerts_carry_no_tenant_or_payload_data(self):
        snapshot = telemetry.build_snapshot(
            db_ok=False,
            redis={
                "ok": True,
                "heartbeat_age_seconds": None,
                "heartbeat_loops": [],
                "queue_depth": 400,
                "queue_age_seconds": 4000.0,
                "job_failures": 9,
            },
            api={"requests": 100, "errors_5xx": 40, "error_rate": 0.4},
            now=NOW,
        )

        line = json.dumps(snapshot)
        for forbidden in ("token", "password", "email", "payload", "uploads/"):
            self.assertNotIn(forbidden, line)
        self.assertEqual(snapshot["generated_at"], NOW.isoformat())
        self.assertTrue(snapshot["thresholds"])


def _write(client):
    import asyncio

    return asyncio.run(telemetry.write_heartbeat(client, loops=["queue"]))


def _note_pop(client, now):
    import asyncio

    return asyncio.run(telemetry.note_queue_pop(client, now=now))


def _note_failure(client):
    import asyncio

    return asyncio.run(telemetry.note_job_failure(client))


def _snapshot_of(client):
    import asyncio

    return asyncio.run(telemetry.redis_snapshot(client, now=NOW))


if __name__ == "__main__":
    unittest.main()
