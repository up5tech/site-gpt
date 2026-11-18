import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api import routes
from site_gpt.app.db.session import get_db


class HealthTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(routes.router)
        db = MagicMock()
        db.execute.return_value = 1
        app.dependency_overrides[get_db] = lambda: db
        self.client = TestClient(app)

    def _redis(self, ping_result):
        return AsyncMock(return_value=ping_result)

    def test_ok_when_db_and_redis_answer(self):
        with patch.object(routes, "redis_ping", self._redis(True)):
            response = self.client.get("/health")
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

    def test_degraded_rate_limiter_marks_status_degraded(self):
        with (
            patch.object(routes, "redis_ping", self._redis(True)),
            patch.object(routes, "limiter_degraded", lambda: True),
        ):
            response = self.client.get("/health")
        self.assertEqual(response.json()["status"], "degraded")
        self.assertTrue(response.json()["rate_limiter"]["degraded"])

    def test_degraded_when_redis_does_not_answer(self):
        with patch.object(routes, "redis_ping", self._redis(False)):
            response = self.client.get("/health")
        self.assertEqual(response.json()["status"], "degraded")
        self.assertFalse(response.json()["redis"])

    def test_degraded_when_redis_raises(self):
        # ping() itself never raises, but health must still degrade (not
        # 500) if it ever does.
        with patch.object(routes, "redis_ping", AsyncMock(side_effect=RuntimeError("boom"))):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["redis"])

    def test_health_is_async_so_it_uses_the_apps_event_loop(self):
        # It used to run the ping on a private loop and close it, which left the
        # shared redis client attached to a dead loop: the following enqueue
        # raised "got Future attached to a different loop" (500 on POST /api/ingest).
        self.assertTrue(asyncio.iscoroutinefunction(routes.health))


if __name__ == "__main__":
    unittest.main()
