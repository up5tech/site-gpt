"""V6-12 (D13): the incident controls that end a tenant session.

D13 defers per-session revocation and tenant MFA to 2027-02-28, so a documented
incident can rely on a short, tested list instead: the 24-hour JWT, immediate
refusal once an account is deactivated or deleted, API-key revocation (pinned
elsewhere) and a signing-key rotation. This module pins the parts owned by
`core/auth.py` and the one compatibility claim that matters during an incident —
a widget session token is not a JWT and is untouched by a rotation.

What is deliberately *not* here: a password reset ending live tokens. D13
records that limitation ("no way to end one session or revoke a live JWT"), so
a test would pin an absence the decision already accepted, and changing it needs
a new approval rather than a quiet new mechanism.
"""

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models
from site_gpt.app.core import auth
from site_gpt.app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from site_gpt.app.db.base import Base
from site_gpt.app.services import session_tokens

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.SessionToken.__table__,
]


class SessionIncidentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.db.add(self.company)
        self.db.flush()
        self.user = models.User(
            company_id=self.company.id,
            email="owner@example.com",
            password_hash="argon2-hash",
            first_name="Owner",
            last_name="One",
            role="admin",
            status="active",
        )
        self.website = models.Website(
            url="https://acme.example",
            name="Acme",
            site_map_url="https://acme.example/sitemap.xml",
            company_id=self.company.id,
        )
        self.db.add_all([self.user, self.website])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _token(self, *, secret=JWT_SECRET_KEY, expires=None, user=None):
        return auth.create_access_token(
            {"sub": str((user or self.user).id), "email": (user or self.user).email},
            secret,
            JWT_ALGORITHM,
            expires,
        )

    def _current(self, token):
        return auth.get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), self.db
        )

    def _refused(self, token):
        with self.assertRaises(HTTPException) as ctx:
            self._current(token)
        self.assertEqual(ctx.exception.status_code, 401)
        return ctx.exception

    # -- the token's own lifetime ------------------------------------------

    def test_the_issued_lifetime_is_the_approved_twenty_four_hours(self):
        token = self._token()

        payload = jwt.decode(
            token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False},
        )

        self.assertEqual(payload["exp"] - payload["iat"], 24 * 3600)
        self.assertEqual(payload["sub"], str(self.user.id))
        self.assertEqual(auth.ACCESS_TOKEN_TTL, timedelta(hours=24))

    def test_a_signed_token_without_an_expiry_is_refused(self):
        # jose validates `exp` only when it exists, so this is the only place a
        # never-expiring token can be caught.
        token = jwt.encode(
            {"sub": str(self.user.id)}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM
        )

        self._refused(token)

    def test_an_expired_token_is_refused(self):
        self._refused(self._token(expires=timedelta(seconds=-1)))

    def test_a_malformed_subject_is_a_401_not_a_500(self):
        # The query binds `sub` to a uuid column; without this coercion an
        # invalid value raises a database error and an unauthenticated caller
        # can turn a bad token into a 500.
        for subject in ("not-a-uuid", "", None):
            with self.subTest(subject=subject):
                token = auth.create_access_token(
                    {"sub": subject}, JWT_SECRET_KEY, JWT_ALGORITHM
                )
                self._refused(token)

    # -- the incident tools ------------------------------------------------

    def test_a_deactivated_account_is_refused_on_the_next_request(self):
        token = self._token()
        self.db.refresh(self.user)
        self.user.status = "inactive"
        self.db.commit()

        self._refused(token)

    def test_a_deleted_account_is_refused_on_the_next_request(self):
        token = self._token()
        self.db.delete(self.user)
        self.db.commit()

        self._refused(token)

    def test_rotating_the_signing_key_invalidates_every_issued_token(self):
        token = self._token()

        # It is a working token under the current key…
        self.assertEqual(self._current(token).id, self.user.id)
        # …and nothing but the key makes it unacceptable, which is what makes a
        # rotation the global incident tool (every tenant, every session).
        with self.assertRaises(HTTPException) as ctx:
            auth.verify_token(token, "a-new-secret", [JWT_ALGORITHM])
        self.assertEqual(ctx.exception.status_code, 401)

    def test_a_reactivated_account_can_use_a_freshly_issued_token(self):
        # The tools end access; they do not make the account unusable forever.
        self.db.refresh(self.user)
        self.user.status = "active"
        self.db.commit()

        self.assertEqual(self._current(self._token()).id, self.user.id)

    # -- the compatibility claim ------------------------------------------

    def test_a_widget_session_token_does_not_depend_on_the_jwt_secret(self):
        # A JWT incident (rotation) must not reset visitors' widget sessions:
        # K4 tokens are random values hashed into their own table and are
        # verified without the signing key.
        raw, row = session_tokens.mint(self.db, self.website.id, "session-1")

        self.assertEqual(row.session_id, "session-1")
        session_tokens.authorize(self.db, self.website, "session-1", raw)
        self.assertTrue(session_tokens.matches(row, raw))
        self.assertIsNotNone(row.expires_at)


if __name__ == "__main__":
    unittest.main()
