import asyncio
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api import routes
from site_gpt.app.core.auth import create_access_token
from site_gpt.app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from site_gpt.app.db.session import get_db
from site_gpt.app.services import embed_guard

WEBSITE_ID = str(uuid4())
WEBSITE_URL = "https://customer.example.com"


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result

    def all(self):
        return self._result if isinstance(self._result, list) else []


def website():
    site = MagicMock()
    site.id = uuid4()
    site.url = WEBSITE_URL
    site.company_id = uuid4()
    return site


class GuardUnitTests(unittest.TestCase):
    """The matching rules themselves, independent of HTTP."""

    def setUp(self):
        self.site = website()

    def check(self, headers):
        request = MagicMock()
        request.headers = headers
        return embed_guard.is_allowed_embed_request(request, self.site)

    def test_no_referrer_is_allowed(self):
        self.assertTrue(self.check({}))

    def test_origin_null_is_allowed(self):
        self.assertTrue(self.check({"origin": "null"}))

    def test_matching_origin_is_allowed(self):
        self.assertTrue(self.check({"origin": WEBSITE_URL}))

    def test_matching_origin_with_port_is_allowed(self):
        self.assertTrue(self.check({"origin": "https://customer.example.com:8443"}))

    def test_www_variant_is_allowed(self):
        self.assertTrue(self.check({"origin": "https://www.customer.example.com"}))

    def test_foreign_origin_is_refused(self):
        self.assertFalse(self.check({"origin": "https://attacker.example.net"}))
        self.assertFalse(
            self.check({"origin": "https://customer.example.com.attacker.net"})
        )
        self.assertFalse(self.check({"origin": "http://evilcustomer.example.com"}))

    def test_referer_is_used_when_origin_is_absent(self):
        self.assertTrue(
            self.check({"referer": f"{WEBSITE_URL}/pricing?utm=1"})
        )
        self.assertFalse(self.check({"referer": "https://attacker.example.net/x"}))

    def test_foreign_origin_wins_over_matching_referer(self):
        self.assertFalse(
            self.check(
                {
                    "origin": "https://attacker.example.net",
                    "referer": f"{WEBSITE_URL}/pricing",
                }
            )
        )

    def test_loopback_origins_are_allowed_for_local_demos(self):
        for origin in (
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://[::1]:3000",
        ):
            with self.subTest(origin=origin):
                self.assertTrue(self.check({"origin": origin}))

    def test_file_url_referer_is_allowed(self):
        self.assertTrue(self.check({"referer": "file:///Users/me/_widget-demo.html"}))

    def test_website_without_url_does_not_crash(self):
        site = website()
        site.url = None
        request = MagicMock()
        request.headers = {"origin": "https://attacker.example.net"}
        self.assertFalse(embed_guard.is_allowed_embed_request(request, site))


class EndpointOriginTests(unittest.TestCase):
    def setUp(self):
        self.site = website()
        self.contact = None

        def query(model):
            if model is routes.models.Website:
                return FakeQuery(self.site)
            if model is routes.models.User:
                return FakeQuery(self.user)
            if model is routes.models.Setting:
                return FakeQuery([])
            return FakeQuery(self.contact)

        self.db = MagicMock()
        self.db.query.side_effect = query
        self.user = MagicMock(id=uuid4())

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

        # Keep the shared in-memory rate limiter from bleeding into other tests.
        from site_gpt.app.services import ratelimit

        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

    def _chat_answer(self):
        return {"answer": "hi", "sources": []}

    # ---- widget-config -----------------------------------------------------
    def test_widget_config_allows_the_customer_site(self):
        response = self.client.get(
            "/api/widget-config",
            params={"website_id": WEBSITE_ID},
            headers={"Origin": WEBSITE_URL},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_widget_config_allows_a_missing_referrer(self):
        response = self.client.get(
            "/api/widget-config", params={"website_id": WEBSITE_ID}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_widget_config_refuses_a_foreign_origin(self):
        response = self.client.get(
            "/api/widget-config",
            params={"website_id": WEBSITE_ID},
            headers={"Origin": "https://attacker.example.net"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("not allowed", response.json()["detail"])

    # ---- chat --------------------------------------------------------------
    def test_chat_allows_the_customer_site(self):
        with patch.object(routes, "ask", return_value=self._chat_answer()) as ask:
            response = self.client.post(
                "/api/chat",
                json={
                    "website_id": WEBSITE_ID,
                    "session_id": "s1",
                    "question": "hi",
                },
                headers={"Origin": WEBSITE_URL},
            )
        self.assertEqual(response.status_code, 200, response.text)
        ask.assert_called_once()

    def test_chat_refuses_a_foreign_origin_before_answering(self):
        with patch.object(routes, "ask") as ask:
            response = self.client.post(
                "/api/chat",
                json={
                    "website_id": WEBSITE_ID,
                    "session_id": "s1",
                    "question": "hi",
                },
                headers={"Origin": "https://attacker.example.net"},
            )
        self.assertEqual(response.status_code, 403)
        ask.assert_not_called()

    def test_chat_stream_refuses_a_foreign_origin(self):
        with patch.object(routes, "ask_stream") as ask_stream:
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "website_id": WEBSITE_ID,
                    "session_id": "s1",
                    "question": "hi",
                },
                headers={"Referer": "https://attacker.example.net/page"},
            )
        self.assertEqual(response.status_code, 403)
        ask_stream.assert_not_called()

    def test_chat_allows_an_authenticated_playground_request(self):
        token = create_access_token(
            {"sub": str(self.user.id)}, JWT_SECRET_KEY, JWT_ALGORITHM
        )

        async def empty_stream(*args, **kwargs):
            yield b""

        with patch.object(routes, "ask_stream", empty_stream):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "website_id": WEBSITE_ID,
                    "session_id": "s1",
                    "question": "hi",
                },
                headers={
                    "Origin": "http://localhost:5173",
                    "Authorization": f"Bearer {token}",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)

    def test_chat_rejects_an_invalid_token_backed_by_a_foreign_origin(self):
        with patch.object(routes, "ask") as ask:
            response = self.client.post(
                "/api/chat",
                json={
                    "website_id": WEBSITE_ID,
                    "session_id": "s1",
                    "question": "hi",
                },
                headers={
                    "Origin": "https://attacker.example.net",
                    "Authorization": "Bearer not-a-real-token",
                },
            )
        self.assertEqual(response.status_code, 403)
        ask.assert_not_called()

    def test_chat_ignores_a_forged_authorization_from_an_unknown_user(self):
        token = create_access_token(
            {"sub": str(uuid4())}, JWT_SECRET_KEY, JWT_ALGORITHM
        )
        unknown_user_db = MagicMock()
        unknown_user_db.query.side_effect = lambda model: (
            FakeQuery(self.site)
            if model is routes.models.Website
            else FakeQuery(None)
        )
        self.client.app.dependency_overrides[get_db] = lambda: unknown_user_db

        with patch.object(routes, "ask") as ask:
            response = self.client.post(
                "/api/chat",
                json={
                    "website_id": WEBSITE_ID,
                    "session_id": "s1",
                    "question": "hi",
                },
                headers={
                    "Origin": "https://attacker.example.net",
                    "Authorization": f"Bearer {token}",
                },
            )
        self.assertEqual(response.status_code, 403)
        ask.assert_not_called()

    # ---- contacts ----------------------------------------------------------
    def _payload(self):
        return {
            "website_id": WEBSITE_ID,
            "session_id": "s1",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
        }

    def test_contact_create_refuses_a_foreign_origin(self):
        response = self.client.post(
            "/api/contacts",
            json=self._payload(),
            headers={"Origin": "https://attacker.example.net"},
        )
        self.assertEqual(response.status_code, 403)
        self.db.add.assert_not_called()

    def test_contact_create_allows_the_customer_site(self):
        response = self.client.post(
            "/api/contacts",
            json=self._payload(),
            headers={"Origin": WEBSITE_URL},
        )
        self.assertNotEqual(response.status_code, 403, response.text)
        self.db.add.assert_called()

    def test_contact_lookup_refuses_a_foreign_origin(self):
        response = self.client.get(
            "/api/contacts/s1",
            params={"website_id": WEBSITE_ID},
            headers={"Origin": "https://attacker.example.net"},
        )
        self.assertEqual(response.status_code, 403)

    def test_contact_lookup_allows_the_customer_site(self):
        response = self.client.get(
            "/api/contacts/s1",
            params={"website_id": WEBSITE_ID},
            headers={"Origin": WEBSITE_URL},
        )
        self.assertNotEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
