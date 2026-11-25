"""V6-1G box 4: an error response must not hand back the credential it rejected.

Where this runs: the plain `unittest` suite
(`uv run python -m unittest discover -s tests`, or just this module with
`uv run python -m unittest tests.test_error_responses -v`). No database, no
network and no provider call: every case drives the real handler, route or
service with a stub one level below it.

The secret in each case is a distinctive value submitted by the caller; the
assertion is that the response body never contains it. Failure messages print
the rule and the status, never the secret.
"""

import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from site_gpt.app.api import upload as upload_api
from site_gpt.app.core import auth as core_auth
from site_gpt.app.core.auth import get_admin_user, get_db
from site_gpt.app.core.errors import request_validation_error_response
from site_gpt.app.services import session_tokens
from site_gpt.app.services.sources import SourceAuthError

SECRET = "sk_live_TESTSECRET_do_not_echo_0123456789"
TOKEN = "secret_ntn_TESTSECRET0123456789"
EMAIL = "person@example.com"


def _api_key_db():
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = None
    db = MagicMock()
    db.query.return_value = chain
    return db


class ErrorResponseTests(unittest.TestCase):
    def test_an_unhandled_exception_returns_no_message(self):
        app = FastAPI()

        @app.get("/boom")
        def boom():
            raise RuntimeError(f"provider rejected {SECRET} for {EMAIL}")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(SECRET, response.text)
        self.assertNotIn(EMAIL, response.text)
        self.assertEqual(response.text, "Internal Server Error")

    def test_a_validation_error_does_not_echo_the_submitted_body(self):
        # The real Notion route + the real sanitising handler. `url` is missing,
        # so FastAPI's default handler would echo the whole body — token
        # included — inside the error's `input`.
        app = FastAPI()
        app.add_exception_handler(
            RequestValidationError, request_validation_error_response
        )
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_admin_user] = lambda: MagicMock(
            id=uuid4(), role="admin"
        )
        client = TestClient(app)

        response = client.post("/api/uploads/notion", json={"token": TOKEN})

        self.assertEqual(response.status_code, 422)
        self.assertNotIn(TOKEN, response.text)
        errors = response.json()["detail"]
        self.assertEqual(errors[0]["loc"], ["body", "url"])
        self.assertEqual(errors[0]["msg"], "Field required")
        self.assertNotIn("input", errors[0])

    def test_the_real_app_registers_the_sanitising_handler(self):
        from site_gpt.app.main import app

        handlers = app.exception_handlers
        self.assertIs(
            handlers.get(RequestValidationError), request_validation_error_response
        )

    def test_a_session_token_refusal_does_not_echo_the_presented_token(self):
        app = FastAPI()
        app.add_exception_handler(session_tokens.SessionTokenError, session_tokens.error_response)

        @app.post("/mint")
        def mint(presented: str = Body(embed=True)):
            # The real service: a row exists whose digest is not this token, so
            # `mint` refuses with the claimed-session 403.
            with patch.object(
                session_tokens,
                "row_for",
                return_value=MagicMock(revoked_at=None, token_hash="another-digest"),
            ):
                session_tokens.mint(
                    MagicMock(), uuid4(), "session-1", presented_token=presented
                )
            return {}

        client = TestClient(app)
        response = client.post("/mint", json={"presented": SECRET})

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(SECRET, response.text)
        self.assertEqual(response.json()["reason"], session_tokens.REASON_CLAIMED)

    def test_an_api_key_refusal_does_not_echo_the_key(self):
        with self.assertRaises(HTTPException) as caught:
            core_auth.get_api_key(x_api_key=SECRET, db=_api_key_db())

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Invalid API key")
        self.assertNotIn(SECRET, str(caught.exception.detail))

    def test_a_jwt_refusal_does_not_echo_the_bearer_token(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=SECRET
        )

        with self.assertRaises(HTTPException) as caught:
            core_auth.get_current_user(credentials=credentials, db=MagicMock())

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Invalid token")
        self.assertNotIn(SECRET, str(caught.exception.detail))

    def test_a_provider_auth_failure_does_not_echo_the_token(self):
        # The real route maps `SourceAuthError` to a 401 with the provider's own
        # message; the submitted token must not be part of it.
        class RefusingNotion:
            async def acquire_many(self, ref, token=None):
                raise SourceAuthError(
                    "Notion rejected the integration token. Check the token and "
                    "that the page or database is shared with your integration."
                )

        app = FastAPI()
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_admin_user] = lambda: MagicMock(
            id=uuid4(), role="admin"
        )
        client = TestClient(app)

        with patch.object(upload_api, "get_provider", return_value=RefusingNotion()):
            response = client.post(
                "/api/uploads/notion",
                json={"url": "https://www.notion.so/x", "token": TOKEN},
            )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn(TOKEN, response.text)
        self.assertIn("Notion rejected the integration token", response.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
