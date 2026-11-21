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
from site_gpt.app.services import embed_guard, embed_tokens

WEBSITE_ID = str(uuid4())
WEBSITE_URL = "https://customer.example.com"


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        # A list result means "a collection was queried"; a single-row lookup
        # found nothing.
        return None if isinstance(self._result, list) else self._result

    def all(self):
        return self._result if isinstance(self._result, list) else []


def website():
    site = MagicMock()
    site.id = uuid4()
    site.url = WEBSITE_URL
    site.company_id = uuid4()
    # These tests are about origin matching, so the site must be served at all.
    site.status = "active"
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

    # ---- V4 F5: the hosted page's own origin ------------------------------
    def check_from(self, base_url, headers):
        request = MagicMock()
        request.headers = headers
        request.base_url = base_url
        return embed_guard.is_allowed_embed_request(request, self.site)

    def test_the_apis_own_origin_is_first_party(self):
        # The hosted page is served by this API, so its own origin is allowed
        # even though it is not the website's URL.
        self.assertTrue(
            self.check_from(
                "https://api.customer.example.com/",
                {"origin": "https://api.customer.example.com"},
            )
        )

    def test_a_referer_on_the_apis_own_origin_is_first_party(self):
        self.assertTrue(
            self.check_from(
                "https://api.customer.example.com/",
                {"referer": "https://api.customer.example.com/chat/abc?x=1"},
            )
        )

    def test_the_default_port_is_the_same_origin(self):
        self.assertTrue(
            self.check_from(
                "https://api.customer.example.com:443",
                {"origin": "https://api.customer.example.com"},
            )
        )
        self.assertTrue(
            self.check_from(
                "http://api.customer.example.com:80",
                {"origin": "http://api.customer.example.com"},
            )
        )

    def test_a_lookalike_first_party_origin_is_refused(self):
        for origin in (
            # suffix and prefix lookalikes
            "https://api.customer.example.com.evil",
            "https://evil-api.customer.example.com",
            "https://api.customer.example.com.evil/chat",
            # port mismatch
            "https://api.customer.example.com:8443",
            # scheme mismatch (a downgrade is not the same origin)
            "http://api.customer.example.com",
        ):
            with self.subTest(origin=origin):
                self.assertFalse(
                    self.check_from(
                        "https://api.customer.example.com", {"origin": origin}
                    ),
                    origin,
                )

    def test_the_website_url_is_still_checked_on_its_own(self):
        # A first-party request does not make the website's own domain the only
        # allowed one, nor the page's origin allowed for a different host.
        self.assertFalse(
            self.check_from(
                "https://api.customer.example.com",
                {"origin": "https://attacker.example.net"},
            )
        )

    def test_a_request_without_a_usable_origin_is_never_first_party(self):
        self.assertFalse(
            self.check_from("not-an-origin", {"origin": "not-an-origin"})
        )
        # A stub request (no usable base_url) must never become first-party.
        self.assertFalse(self.check({"origin": "https://attacker.example.net"}))

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


class EmbedTokenMatrixTests(unittest.TestCase):
    """V3 F4: `compat` vs `enforce`, and the reason the widget branches on.

    Two things matter more than the happy path: a deployed V2.1 snippet keeps
    working in `compat` even after the owner issued a token (otherwise the
    rollout would break every customer at once), and a refusal is never
    mistakable for a K4 session refusal.
    """

    def setUp(self):
        self.site = website()

    def guard(self, headers, *, mode="compat", row=None, authenticated=False):
        request = MagicMock()
        request.headers = {"origin": WEBSITE_URL, **headers}
        with patch.object(embed_guard, "EMBED_TOKEN_MODE", mode), patch.object(
            embed_tokens, "find_active_token", return_value=row
        ) as find, patch.object(embed_tokens, "record_use") as use, patch.object(
            embed_guard, "is_authenticated", return_value=authenticated
        ):
            refusal = None
            try:
                embed_guard.ensure_embed_allowed(
                    request, MagicMock(), self.site, allow_authenticated=True
                )
            except embed_guard.EmbedTokenRefused as exc:
                refusal = exc
        return refusal, find, use

    def test_compat_allows_a_tokenless_snippet(self):
        # Whether or not a token was issued: the old snippet cannot know it.
        refusal, find, use = self.guard({})

        self.assertIsNone(refusal)
        find.assert_not_called()
        use.assert_not_called()

    def test_compat_allows_a_valid_token_and_stamps_the_use(self):
        row = MagicMock()

        refusal, find, use = self.guard({"x-embed-token": "emb_ok"}, row=row)

        self.assertIsNone(refusal)
        self.assertEqual(find.call_args.kwargs["website_id"], self.site.id)
        self.assertIs(use.call_args.args[1], row)

    def test_a_wrong_revoked_or_foreign_token_is_refused_in_both_modes(self):
        # The service returns None for all three, so the guard has one answer.
        for mode in ("compat", "enforce"):
            with self.subTest(mode=mode):
                refusal, _, use = self.guard({"x-embed-token": "emb_nope"}, mode=mode)

                self.assertIsNotNone(refusal)
                self.assertEqual(refusal.status_code, 403)
                self.assertEqual(refusal.reason, "invalid_embed_token")
                use.assert_not_called()

    def test_enforce_requires_a_token(self):
        refusal, find, _ = self.guard({}, mode="enforce")

        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.reason, "embed_token_required")
        find.assert_not_called()

    def test_enforce_accepts_a_valid_token(self):
        refusal, _, use = self.guard(
            {"x-embed-token": "emb_ok"}, mode="enforce", row=MagicMock()
        )

        self.assertIsNone(refusal)
        use.assert_called_once()

    def test_reasons_are_not_the_session_ones(self):
        # The widget resets a session only for `session_expired`; an embed reason
        # must be unusable as a session reason, and vice versa.
        session_reasons = {
            "session_expired",
            "session_claimed",
            "invalid_token",
            "token_required",
        }

        self.assertNotIn(embed_guard.INVALID_EMBED_TOKEN, session_reasons)
        self.assertNotIn(embed_guard.EMBED_TOKEN_REQUIRED, session_reasons)

    def test_a_refusal_never_echoes_the_token(self):
        refusal, _, _ = self.guard(
            {"x-embed-token": "emb_super_secret"}, mode="enforce"
        )

        self.assertNotIn("emb_super_secret", refusal.detail)

    def test_an_authenticated_request_skips_the_token_gate(self):
        # The dashboard playground is not a browser embed.
        refusal, find, _ = self.guard({}, mode="enforce", authenticated=True)

        self.assertIsNone(refusal)
        find.assert_not_called()

    def test_api_key_callers_can_skip_the_token_gate(self):
        request = MagicMock()
        request.headers = {"origin": WEBSITE_URL}
        with patch.object(embed_guard, "EMBED_TOKEN_MODE", "enforce"), patch.object(
            embed_tokens, "find_active_token"
        ) as find:
            embed_guard.ensure_embed_allowed(
                request, MagicMock(), self.site, require_embed_token=False
            )
        find.assert_not_called()


class EmbedTokenEndpointTests(unittest.TestCase):
    """The shape the widget actually receives when the gate refuses."""

    def setUp(self):
        self.site = website()

        def query(model):
            if model is routes.models.Website:
                return FakeQuery(self.site)
            return FakeQuery(None) if model is routes.models.User else FakeQuery([])

        self.db = MagicMock()
        self.db.query.side_effect = query

        app = FastAPI()
        app.include_router(routes.router)
        app.add_exception_handler(
            embed_guard.EmbedTokenRefused, embed_guard.embed_token_error_response
        )
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def test_an_invalid_token_is_403_with_a_reason_beside_the_detail(self):
        with patch.object(embed_tokens, "find_active_token", return_value=None):
            response = self.client.post(
                "/api/session-token",
                json={"website_id": WEBSITE_ID, "session_id": "s1"},
                headers={"Origin": WEBSITE_URL, "X-Embed-Token": "emb_wrong"},
            )

        self.assertEqual(response.status_code, 403, response.text)
        body = response.json()
        self.assertEqual(body["reason"], "invalid_embed_token")
        self.assertIn("not valid", body["detail"])
        self.assertNotIn("emb_wrong", response.text)

    def test_enforce_refuses_a_tokenless_widget_config_read(self):
        with patch.object(embed_guard, "EMBED_TOKEN_MODE", "enforce"):
            response = self.client.get(
                "/api/widget-config",
                params={"website_id": WEBSITE_ID},
                headers={"Origin": WEBSITE_URL},
            )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["reason"], "embed_token_required")

    def test_a_valid_token_is_allowed_and_its_use_is_recorded(self):
        row = MagicMock()
        row.last_used_at = None

        with patch.object(
            embed_tokens, "find_active_token", return_value=row
        ), patch.object(embed_guard, "EMBED_TOKEN_MODE", "enforce"):
            response = self.client.get(
                "/api/widget-config",
                params={"website_id": WEBSITE_ID},
                headers={"Origin": WEBSITE_URL, "X-Embed-Token": "emb_ok"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.db.commit.assert_called()
        self.assertIsNotNone(row.last_used_at)


class HostedPageOriginTests(unittest.TestCase):
    """V4 F5: `GET /chat/{website_id}` may chat from the API's own origin.

    The page is served by this API, so a browser on it sends that origin; every
    third-party origin keeps the V3 rules, lookalikes included.
    """

    API_ORIGIN = "https://api.customer.example.com"

    def setUp(self):
        self.site = website()

        def query(model):
            if model is routes.models.Website:
                return FakeQuery(self.site)
            if model is routes.models.Setting:
                return FakeQuery([])
            return FakeQuery(None)

        self.db = MagicMock()
        self.db.query.side_effect = query

        app = FastAPI()
        app.include_router(routes.router)
        app.add_exception_handler(
            embed_guard.EmbedTokenRefused, embed_guard.embed_token_error_response
        )
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app, base_url=self.API_ORIGIN)

        from site_gpt.app.services import ratelimit

        hits = getattr(ratelimit, "_hits", None)
        if isinstance(hits, dict):
            hits.clear()

    def chat(self, origin):
        with patch.object(
            routes, "ask", return_value={"answer": "hi", "sources": []}
        ) as ask:
            response = self.client.post(
                "/api/chat",
                json={"website_id": WEBSITE_ID, "session_id": "s1", "question": "hi"},
                headers={"Origin": origin},
            )
        return response, ask

    def test_a_chat_from_the_hosted_page_is_allowed(self):
        response, ask = self.chat(self.API_ORIGIN)

        self.assertEqual(response.status_code, 200, response.text)
        ask.assert_called_once()

    def test_widget_config_from_the_hosted_page_is_allowed(self):
        response = self.client.get(
            "/api/widget-config",
            params={"website_id": WEBSITE_ID},
            headers={"Origin": self.API_ORIGIN},
        )

        self.assertEqual(response.status_code, 200, response.text)

    def test_a_lookalike_origin_is_still_refused_on_the_endpoint(self):
        for origin in (
            "https://api.customer.example.com.evil",
            "https://api.customer.example.com:8443",
            "http://api.customer.example.com",
        ):
            with self.subTest(origin=origin):
                response, ask = self.chat(origin)
                self.assertEqual(response.status_code, 403, response.text)
                ask.assert_not_called()

    def test_the_embed_token_rules_apply_to_the_hosted_page(self):
        # D8: the hosted page is an embed for the token gate, not an exemption.
        with patch.object(embed_guard, "EMBED_TOKEN_MODE", "enforce"):
            response = self.client.get(
                "/api/widget-config",
                params={"website_id": WEBSITE_ID},
                headers={"Origin": self.API_ORIGIN},
            )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["reason"], "embed_token_required")


class CorsPreflightTests(unittest.TestCase):
    def test_a_preflight_carrying_the_embed_token_header_is_allowed(self):
        from site_gpt.app.main import app

        response = TestClient(app).options(
            "/api/chat/stream",
            headers={
                "Origin": WEBSITE_URL,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-embed-token,x-session-token",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        allowed = (response.headers.get("access-control-allow-headers") or "").lower()
        self.assertTrue(
            allowed == "*" or "x-embed-token" in allowed,
            f"preflight did not allow X-Embed-Token: {allowed!r}",
        )


if __name__ == "__main__":
    unittest.main()
