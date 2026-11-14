import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api.user import router as user_router
from site_gpt.app.db.session import get_db
from site_gpt.app.services import ratelimit


class AuthRateLimitTests(unittest.TestCase):
    """Exercise the real routes with a stubbed DB (no Postgres needed)."""

    def setUp(self):
        ratelimit._hits.clear()
        app = FastAPI()
        app.include_router(user_router, prefix="/api/users")

        db = MagicMock()
        # No user matches, so reset-password answers 400 and forgot-password
        # sends nothing while still being counted.
        db.query.return_value.filter.return_value.first.return_value = None
        app.dependency_overrides[get_db] = lambda: db

        self.client = TestClient(app)

    def tearDown(self):
        ratelimit._hits.clear()

    def reset(self, headers=None):
        return self.client.post(
            "/api/users/reset-password",
            json={"email": "nobody@example.com", "token": "guess", "password": "x"},
            headers=headers,
        )

    def forgot(self, headers=None):
        return self.client.post(
            "/api/users/forgot-password",
            json={"email": "nobody@example.com"},
            headers=headers,
        )

    def test_reset_password_attempts_are_capped(self):
        codes = [self.reset().status_code for _ in range(11)]

        self.assertEqual(codes[:10], [400] * 10)
        self.assertEqual(codes[10], 429)

    def test_reset_password_limit_is_independent_of_forgot_password(self):
        codes = [self.forgot().status_code for _ in range(4)]
        self.assertEqual(codes[:3], [200] * 3)
        self.assertEqual(codes[3], 429)

        # The reset bucket is untouched by the reset-request bucket.
        self.assertEqual(self.reset().status_code, 400)

    def test_spoofed_forwarded_for_does_not_reset_the_window(self):
        codes = [
            self.reset({"X-Forwarded-For": f"5.5.5.{i}"}).status_code
            for i in range(11)
        ]

        self.assertEqual(codes[:10], [400] * 10)
        self.assertEqual(codes[10], 429)


if __name__ == "__main__":
    unittest.main()
