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
import time
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

    def __init__(self, values=None, depth=0, fail=False, incr_to=1, scan_fails=False):
        self.values = dict(values or {})
        self.depth = depth
        self.fail = fail
        self.incr_to = incr_to
        self.scan_fails = scan_fails
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

    async def mget(self, keys):
        if self.fail:
            raise RuntimeError("redis down")
        return [self.values.get(key) for key in keys]

    def pipeline(self):
        return _Pipeline(self)

    async def scan_iter(self, match=None):
        if self.fail or self.scan_fails:
            raise RuntimeError("redis down")
        prefix = (match or "").rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


class _Pipeline:
    """The queued subset of `redis.asyncio`'s pipeline the counters use."""

    def __init__(self, client):
        self.client = client
        self.ops = []

    def incr(self, key):
        self.ops.append(("incr", key))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        if self.client.fail:
            raise RuntimeError("redis down")
        for op in self.ops:
            if op[0] == "incr":
                self.client.values[op[1]] = int(self.client.values.get(op[1], 0)) + 1
            else:
                self.client.expires.append((op[1], op[2]))
        return [True] * len(self.ops)


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


class FleetWindowTests(unittest.TestCase):
    """V6-23: the 5xx rate is every replica's buckets, not one process."""

    def test_one_response_writes_a_bucket_pair_with_the_window_ttl(self):
        client = _Client()
        bucket = int(1000.0 // telemetry.BUCKET_SECONDS)
        requests_key = f"{telemetry.REQUESTS_BUCKET_PREFIX}{bucket}"
        errors_key = f"{telemetry.ERRORS_BUCKET_PREFIX}{bucket}"

        self.assertTrue(_shared(client, 500, 1000.0))

        self.assertEqual(client.values[requests_key], 1)
        self.assertEqual(client.values[errors_key], 1)
        ttls = dict(client.expires)
        self.assertEqual(ttls[requests_key], telemetry.BUCKET_TTL_SECONDS)
        self.assertEqual(ttls[errors_key], telemetry.BUCKET_TTL_SECONDS)

    def test_a_success_never_touches_the_error_bucket(self):
        client = _Client()
        bucket = int(1000.0 // telemetry.BUCKET_SECONDS)

        self.assertTrue(_shared(client, 200, 1000.0))

        self.assertEqual(client.values[f"{telemetry.REQUESTS_BUCKET_PREFIX}{bucket}"], 1)
        self.assertNotIn(f"{telemetry.ERRORS_BUCKET_PREFIX}{bucket}", client.values)

    def test_replicas_add_up_in_one_sum(self):
        client = _Client()
        for _ in range(3):
            _shared(client, 200, 1000.0)
        _shared(client, 500, 1000.0)

        window = _fleet(client, 1000.0)

        self.assertTrue(window["ok"])
        self.assertEqual(window["requests"], 4)
        self.assertEqual(window["errors_5xx"], 1)
        self.assertAlmostEqual(window["error_rate"], 0.25)

    def test_a_bucket_expires_out_of_the_window(self):
        client = _Client()
        _shared(client, 500, 1000.0)
        inside = 1000.0 + telemetry.API_ERROR_RATE_WINDOW_SECONDS
        outside = inside + telemetry.BUCKET_SECONDS + 1

        self.assertEqual(_fleet(client, inside)["errors_5xx"], 1)
        window = _fleet(client, outside)

        self.assertEqual(window["requests"], 0)
        self.assertEqual(window["errors_5xx"], 0)
        self.assertEqual(window["error_rate"], 0.0)

    def test_a_write_failure_is_reported_not_raised(self):
        self.assertFalse(_shared(_Client(fail=True), 500, 1000.0))

    def test_an_unreadable_window_is_missing_data_not_zero(self):
        window = _fleet(_Client(fail=True), 1000.0)

        self.assertFalse(window["ok"])
        self.assertIsNone(window["requests"])
        self.assertIsNone(window["errors_5xx"])

    def test_the_alert_reads_the_fleet_and_labels_it(self):
        with (
            patch.object(telemetry, "API_ERROR_RATE_MIN_REQUESTS", 20),
            patch.object(telemetry, "API_ERROR_RATE_ALERT", 0.02),
        ):
            alerts = telemetry.evaluate(
                _snapshot(
                    api={
                        "requests": 100,
                        "errors_5xx": 50,
                        "error_rate": 0.5,
                        "fleet": {
                            "ok": True,
                            "requests": 100,
                            "errors_5xx": 0,
                            "error_rate": 0.0,
                        },
                    }
                )
            )

        # One loud instance next to a clean fleet must not page.
        self.assertEqual(alerts, [])

    def test_a_failed_fleet_read_falls_back_to_the_instance_and_says_so(self):
        with (
            patch.object(telemetry, "API_ERROR_RATE_MIN_REQUESTS", 20),
            patch.object(telemetry, "API_ERROR_RATE_ALERT", 0.02),
        ):
            alerts = telemetry.evaluate(
                _snapshot(
                    api={
                        "requests": 100,
                        "errors_5xx": 5,
                        "error_rate": 0.05,
                        "fleet": {"ok": False},
                    }
                )
            )

        self.assertEqual(alerts[0]["code"], "api.error_rate")
        self.assertEqual(alerts[0]["evidence"]["source"], "instance")

    def test_min_requests_and_severity_apply_to_the_fleet_counts(self):
        with (
            patch.object(telemetry, "API_ERROR_RATE_MIN_REQUESTS", 20),
            patch.object(telemetry, "API_ERROR_RATE_ALERT", 0.02),
        ):

            def fleet(requests, errors):
                return {
                    "ok": True,
                    "requests": requests,
                    "errors_5xx": errors,
                    "error_rate": errors / requests if requests else 0.0,
                }

            tiny = telemetry.evaluate(_snapshot(api={"fleet": fleet(1, 1)}))
            at = telemetry.evaluate(_snapshot(api={"fleet": fleet(100, 2)}))
            double = telemetry.evaluate(_snapshot(api={"fleet": fleet(100, 4)}))

        self.assertEqual(tiny, [])
        self.assertEqual(at[0]["severity"], "warning")
        self.assertEqual(at[0]["evidence"]["source"], "fleet")
        self.assertEqual(double[0]["severity"], "critical")

    def test_the_middleware_writes_the_fleet_buckets(self):
        client = _Client()
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware, shared_client=client)

        @app.get("/boom")
        async def boom():
            return JSONResponse({"detail": "boom"}, status_code=500)

        TestClient(app).get("/boom")

        window = _fleet(client, time.time())
        self.assertTrue(window["ok"])
        self.assertEqual(window["errors_5xx"], 1)

    def test_the_snapshot_keeps_the_instance_detail_beside_the_fleet(self):
        snapshot = telemetry.build_snapshot(
            db_ok=True,
            redis={
                "ok": True,
                "heartbeat_age_seconds": 5.0,
                "heartbeat_loops": ["queue"],
                "queue_depth": 0,
                "queue_age_seconds": None,
                "job_failures": 0,
            },
            api={"requests": 5, "errors_5xx": 1, "error_rate": 0.2},
            fleet={"ok": True, "requests": 50, "errors_5xx": 1, "error_rate": 0.02},
            now=NOW,
        )

        self.assertEqual(snapshot["api"]["requests"], 5)
        self.assertEqual(snapshot["api"]["fleet"]["requests"], 50)


class PerWorkerHeartbeatTests(unittest.TestCase):
    """V6-23: one key per worker, so a dead peer cannot hide behind a live one."""

    def _worker_key(self, identity):
        return f"{telemetry.WORKER_HEARTBEAT_PREFIX}{identity}"

    def _payload(self, identity, age_seconds, loops=None):
        return json.dumps(
            {
                "at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
                "worker": identity,
                "loops": loops or ["queue"],
            }
        )

    def test_the_key_carries_the_host_and_the_pid(self):
        self.assertEqual(
            telemetry.worker_key(host="worker-a", pid=7),
            "ops:worker:heartbeat:worker-a:7",
        )

    def test_a_heartbeat_writes_the_worker_key_beside_the_legacy_one(self):
        client = _Client()

        with (
            patch.object(telemetry.socket, "gethostname", return_value="worker-a"),
            patch.object(telemetry.os, "getpid", return_value=7),
        ):
            self.assertTrue(_write(client))

        self.assertEqual(
            [key for key, _, _ in client.set_calls],
            [telemetry.HEARTBEAT_KEY, "ops:worker:heartbeat:worker-a:7"],
        )
        for _, value, ttl in client.set_calls:
            self.assertEqual(ttl, telemetry.HEARTBEAT_TTL_SECONDS)
            self.assertEqual(json.loads(value)["worker"], "worker-a:7")

    def test_two_workers_are_reported_separately(self):
        client = _Client(
            values={
                self._worker_key("worker-a:1"): self._payload("worker-a:1", 5),
                self._worker_key("worker-b:2"): self._payload(
                    "worker-b:2", 500, loops=["queue", "digest"]
                ),
            },
            depth=0,
        )

        snapshot = _snapshot_of(client)

        self.assertEqual(
            [worker["worker"] for worker in snapshot["workers"]],
            ["worker-a:1", "worker-b:2"],
        )
        self.assertAlmostEqual(snapshot["workers"][0]["age_seconds"], 5)
        self.assertAlmostEqual(snapshot["workers"][1]["age_seconds"], 500)
        self.assertEqual(snapshot["workers"][1]["loops"], ["queue", "digest"])

    def test_a_stale_worker_alerts_only_itself(self):
        client = _Client(
            values={
                self._worker_key("worker-a:1"): self._payload("worker-a:1", 5),
                self._worker_key("worker-b:2"): self._payload("worker-b:2", 500),
            },
            depth=0,
        )
        snapshot = _snapshot_of(client)

        with patch.object(telemetry, "WORKER_HEARTBEAT_STALE_SECONDS", 90):
            alerts = telemetry.evaluate(_snapshot(redis=snapshot))

        stale = [a for a in alerts if a["code"] == "worker.heartbeat_stale"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["evidence"]["worker"], "worker-b:2")
        self.assertNotIn("worker-a:1", json.dumps(stale))

    def test_a_key_without_a_timestamp_is_missing_for_that_worker(self):
        client = _Client(
            values={
                self._worker_key("worker-a:1"): json.dumps({"worker": "worker-a:1"}),
                telemetry.HEARTBEAT_KEY: json.dumps({"at": NOW.isoformat()}),
            },
            depth=0,
        )

        snapshot = _snapshot_of(client)
        missing = [
            alert
            for alert in telemetry.evaluate(_snapshot(redis=snapshot))
            if alert["code"] == "worker.heartbeat_missing"
        ]

        self.assertEqual([alert["evidence"]["worker"] for alert in missing], ["worker-a:1"])

    def test_a_scan_failure_keeps_the_legacy_view(self):
        client = _Client(
            values={
                telemetry.HEARTBEAT_KEY: json.dumps(
                    {"at": (NOW - timedelta(seconds=10)).isoformat()}
                )
            },
            depth=0,
            scan_fails=True,
        )

        snapshot = _snapshot_of(client)

        self.assertTrue(snapshot["ok"])
        self.assertAlmostEqual(snapshot["heartbeat_age_seconds"], 10)
        self.assertEqual(snapshot["workers"], [])

    def test_an_expired_worker_key_is_not_invented(self):
        # A dead worker's key expires; without a deployment-fed expected count
        # the snapshot cannot name it — a recorded limit, not a claim.
        client = _Client(
            values={
                telemetry.HEARTBEAT_KEY: json.dumps({"at": NOW.isoformat()}),
                self._worker_key("worker-a:1"): self._payload("worker-a:1", 0),
            },
            depth=0,
        )

        snapshot = _snapshot_of(client)

        self.assertEqual(
            [worker["worker"] for worker in snapshot["workers"]], ["worker-a:1"]
        )
        self.assertNotIn("worker.heartbeat_missing", _codes(_snapshot(redis=snapshot)))


def _shared(client, status_code, now):
    import asyncio

    return asyncio.run(telemetry.record_request_shared(client, status_code, now=now))


def _fleet(client, now):
    import asyncio

    return asyncio.run(telemetry.fleet_window(client, now=now))


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
