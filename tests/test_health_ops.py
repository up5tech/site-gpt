"""V6-21: liveness/readiness split and the token-gated operator snapshot.

`/health` keeps its V2 contract (pinned in tests/test_health.py). These tests add
the two properties the task's Done-when depends on: a dependency-degraded
process stays live and keeps serving, while a database-less process reports
itself not ready; and the operator snapshot is invisible unless the host set its
token, cannot be read with a wrong one, and never echoes the token back.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api import ops
from site_gpt.app.api.routes import router as routes_router
from site_gpt.app.core import telemetry
from site_gpt.app.db.session import get_db


def _app(db_error=False):
    app = FastAPI()
    app.include_router(routes_router)
    app.include_router(ops.router)
    db = MagicMock()
    if db_error:
        db.execute.side_effect = RuntimeError("database is gone")
    else:
        db.execute.return_value = 1
    app.dependency_overrides[get_db] = lambda: db
    return app


class LivenessTests(unittest.TestCase):
    def test_live_answers_with_dependencies_down(self):
        # Liveness must not consult the database or Redis: a degraded process
        # that can still serve must never be restarted in a crash loop (D8).
        client = TestClient(_app(db_error=True))
        with patch.object(ops, "redis_ping", AsyncMock(return_value=False)):
            response = client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive"})


class ReadinessTests(unittest.TestCase):
    def test_ready_when_db_and_redis_answer(self):
        client = TestClient(_app())
        with patch.object(ops, "redis_ping", AsyncMock(return_value=True)):
            response = client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "ready", "db": True, "redis": True}
        )

    def test_redis_down_is_degraded_but_still_ready(self):
        # The API degrades rather than stops without Redis (limiter fails open,
        # chat still answers), so taking it out of rotation would be worse.
        client = TestClient(_app())
        with patch.object(ops, "redis_ping", AsyncMock(return_value=False)):
            response = client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertFalse(response.json()["redis"])

    def test_database_down_is_not_ready(self):
        client = TestClient(_app(db_error=True))
        with patch.object(ops, "redis_ping", AsyncMock(return_value=True)):
            response = client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertFalse(response.json()["db"])

    def test_a_raising_ping_does_not_500_the_probe(self):
        client = TestClient(_app())
        with patch.object(
            ops, "redis_ping", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            response = client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["redis"])

    def test_health_keeps_its_contract_next_to_the_new_probes(self):
        client = TestClient(_app())
        with (
            patch("site_gpt.app.api.routes.redis_ping", AsyncMock(return_value=True)),
            patch("site_gpt.app.api.routes.limiter_degraded", lambda: False),
        ):
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "db": True,
                "redis": True,
                "rate_limiter": {"backend": "memory", "degraded": False},
            },
        )


class OpsStatusTests(unittest.TestCase):
    def setUp(self):
        telemetry.reset_request_window()
        self.redis = {
            "ok": True,
            "heartbeat_age_seconds": None,
            "heartbeat_loops": [],
            "queue_depth": 0,
            "queue_age_seconds": None,
            "job_failures": 0,
        }

    def tearDown(self):
        telemetry.reset_request_window()

    def test_disabled_without_a_token(self):
        client = TestClient(_app())
        with patch.object(ops, "OPS_STATUS_TOKEN", ""):
            response = client.get("/api/ops/status")

        self.assertEqual(response.status_code, 404)

    def test_a_wrong_token_is_refused(self):
        client = TestClient(_app())
        with patch.object(ops, "OPS_STATUS_TOKEN", "right-token"):
            response = client.get(
                "/api/ops/status", headers={"X-Ops-Token": "wrong-token"}
            )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("right-token", response.text)

    def test_a_missing_header_is_refused(self):
        client = TestClient(_app())
        with patch.object(ops, "OPS_STATUS_TOKEN", "right-token"):
            response = client.get("/api/ops/status")

        self.assertEqual(response.status_code, 401)

    def test_the_snapshot_is_returned_with_its_alerts(self):
        client = TestClient(_app())
        with (
            patch.object(ops, "OPS_STATUS_TOKEN", "right-token"),
            patch.object(
                ops.telemetry, "redis_snapshot", AsyncMock(return_value=self.redis)
            ),
        ):
            response = client.get(
                "/api/ops/status", headers={"X-Ops-Token": "right-token"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(body["alerts"][0]["code"], "worker.heartbeat_missing")
        self.assertEqual(body["thresholds"]["worker_heartbeat_stale_seconds"], 90)
        self.assertNotIn("right-token", json.dumps(body))

    def test_a_failing_database_appears_as_an_alert(self):
        client = TestClient(_app(db_error=True))
        with (
            patch.object(ops, "OPS_STATUS_TOKEN", "right-token"),
            patch.object(
                ops.telemetry, "redis_snapshot", AsyncMock(return_value=self.redis)
            ),
        ):
            response = client.get(
                "/api/ops/status", headers={"X-Ops-Token": "right-token"}
            )

        self.assertEqual(response.status_code, 200)
        codes = [alert["code"] for alert in response.json()["alerts"]]
        self.assertIn("api.database_unreachable", codes)


if __name__ == "__main__":
    unittest.main()
