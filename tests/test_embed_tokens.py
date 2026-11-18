"""Embed-token service and routes (V3 F4, V3-21).

The token is public by design, so the properties worth pinning are the ones that
keep it *manageable* rather than secret:

- only `sha256(raw)` and a 12-character prefix are ever stored, and the raw value
  appears in exactly one response (mint/rotate);
- a website has at most one active token — minting twice is a 409, and rotation
  revokes the old row and inserts the new one in one transaction;
- a revoked prefix is dead, and revoked rows survive as history;
- the routes are admin-only and company-scoped, and a foreign website id is a
  404 rather than a 403.

These run against a real SQLite database (like `test_retention.py`) so the
partial unique index is actually enforced: the model carries the same
`revoked_at IS NULL` predicate for SQLite, so a test that accidentally allows two
active tokens fails here instead of in production.
"""

import hashlib
import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import website as website_api
from site_gpt.app.core.auth import get_admin_user, get_current_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import embed_tokens

TABLES = [
    models.Company.__table__,
    models.Website.__table__,
    models.EmbedToken.__table__,
]


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    return engine, sessionmaker(bind=engine)()


def _company(db, name="Acme"):
    company = models.Company(name=name)
    db.add(company)
    db.commit()
    return company


def _website(db, company, name="site"):
    site = models.Website(
        company_id=company.id,
        name=name,
        url=f"https://{name}.test",
        site_map_url="",
    )
    db.add(site)
    db.commit()
    return site


class TokenFormatTests(unittest.TestCase):
    def test_raw_token_is_prefixed_random_and_long(self):
        first = embed_tokens.generate_token()
        second = embed_tokens.generate_token()

        self.assertTrue(first.startswith("emb_"))
        self.assertGreaterEqual(len(first), 40)
        self.assertNotEqual(first, second)

    def test_prefix_is_the_first_twelve_characters(self):
        raw = embed_tokens.generate_token()

        self.assertEqual(len(embed_tokens.token_prefix(raw)), 12)
        self.assertEqual(embed_tokens.token_prefix(raw), raw[:12])

    def test_hash_is_plain_sha256_hex(self):
        # No pepper: a random 256-bit token needs none, and a pepper that changed
        # would invalidate every deployed snippet at once.
        raw = embed_tokens.generate_token()
        digest = embed_tokens.hash_token(raw)

        self.assertEqual(len(digest), 64)
        self.assertEqual(
            digest,
            hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn(raw, digest)


class MintTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = _session()
        self.site = _website(self.db, _company(self.db))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_mint_stores_only_hash_and_prefix(self):
        row, raw = embed_tokens.mint(self.db, self.site.id)

        self.assertEqual(row.token_hash, embed_tokens.hash_token(raw))
        self.assertEqual(row.token_prefix, raw[:12])
        self.assertNotEqual(row.token_hash, raw)
        self.assertIsNone(row.revoked_at)
        self.assertEqual(row.website_id, self.site.id)
        # Nothing in the row can be turned back into the token.
        for column in row.__table__.columns:
            value = getattr(row, column.name)
            if isinstance(value, str):
                self.assertNotIn(raw, value)

    def test_a_second_mint_is_refused(self):
        embed_tokens.mint(self.db, self.site.id)

        with self.assertRaises(embed_tokens.EmbedTokenExists):
            embed_tokens.mint(self.db, self.site.id)

        self.assertEqual(
            self.db.query(models.EmbedToken)
            .filter(models.EmbedToken.revoked_at.is_(None))
            .count(),
            1,
        )

    def test_the_database_itself_refuses_two_active_tokens(self):
        # Guards the index, not just the service: "read then insert" alone would
        # let two concurrent mints both pass the check.
        first_raw = embed_tokens.generate_token()
        self.db.add(
            models.EmbedToken(
                website_id=self.site.id,
                token_prefix=embed_tokens.token_prefix(first_raw),
                token_hash=embed_tokens.hash_token(first_raw),
            )
        )
        self.db.commit()

        with self.assertRaises(IntegrityError):
            self.db.add(
                models.EmbedToken(
                    website_id=self.site.id,
                    token_prefix="emb_other",
                    token_hash=embed_tokens.hash_token("emb_other"),
                )
            )
            self.db.commit()
        self.db.rollback()


class RotateAndRevokeTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = _session()
        self.site = _website(self.db, _company(self.db))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _active(self):
        return (
            self.db.query(models.EmbedToken)
            .filter(
                models.EmbedToken.website_id == self.site.id,
                models.EmbedToken.revoked_at.is_(None),
            )
            .all()
        )

    def test_rotate_revokes_the_old_token_and_activates_the_new_one(self):
        old_row, _ = embed_tokens.mint(self.db, self.site.id)

        new_row, raw = embed_tokens.rotate(self.db, self.site.id)

        self.db.refresh(old_row)
        self.assertIsNotNone(old_row.revoked_at)
        self.assertNotEqual(old_row.token_prefix, new_row.token_prefix)
        self.assertEqual(new_row.token_hash, embed_tokens.hash_token(raw))
        active = self._active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, new_row.id)

    def test_rotation_keeps_the_history_and_stays_single_active(self):
        embed_tokens.mint(self.db, self.site.id)
        embed_tokens.rotate(self.db, self.site.id)
        embed_tokens.rotate(self.db, self.site.id)

        rows = (
            self.db.query(models.EmbedToken)
            .filter(models.EmbedToken.website_id == self.site.id)
            .all()
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(self._active()), 1)

    def test_rotate_without_a_token_just_issues_one(self):
        row, _ = embed_tokens.rotate(self.db, self.site.id)

        self.assertIsNone(row.revoked_at)
        self.assertEqual(len(self._active()), 1)

    def test_revoke_marks_the_row_and_a_second_revoke_is_refused(self):
        row, _ = embed_tokens.mint(self.db, self.site.id)

        revoked = embed_tokens.revoke(self.db, self.site.id)

        self.assertEqual(revoked.id, row.id)
        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(self._active(), [])
        with self.assertRaises(embed_tokens.EmbedTokenMissing):
            embed_tokens.revoke(self.db, self.site.id)

    def test_latest_token_is_the_newest_row(self):
        embed_tokens.mint(self.db, self.site.id)
        new_row, _ = embed_tokens.rotate(self.db, self.site.id)

        latest = embed_tokens.latest_token(self.db, self.site.id)

        self.assertEqual(latest.id, new_row.id)

    def test_tokens_are_scoped_per_website(self):
        other = _website(self.db, _company(self.db, "Other"), "other")
        embed_tokens.mint(self.db, self.site.id)

        self.assertIsNone(embed_tokens.active_token(self.db, other.id))


class EmbedTokenEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()
        self.company = _company(self.db)
        self.other_company = _company(self.db, "Other")
        self.site = _website(self.db, self.company, "mine")
        self.other_site = _website(self.db, self.other_company, "theirs")
        self.admin = SimpleNamespace(
            id=uuid4(), company_id=self.company.id, role="admin"
        )

        app = FastAPI()
        app.include_router(website_api.router, prefix="/api/websites")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: self.admin
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _path(self, site=None, suffix=""):
        return f"/api/websites/{(site or self.site).id}/embed-token{suffix}"

    def test_mint_returns_the_raw_token_once_and_reads_never_do(self):
        created = self.client.post(self._path())

        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertTrue(body["token"].startswith("emb_"))
        self.assertEqual(body["token_prefix"], body["token"][:12])
        self.assertTrue(body["active"])

        read = self.client.get(self._path())

        self.assertEqual(read.status_code, 200, read.text)
        read_body = read.json()
        self.assertNotIn("token", read_body)
        self.assertEqual(read_body["token_prefix"], body["token_prefix"])

    def test_get_before_any_issuance_is_404(self):
        self.assertEqual(self.client.get(self._path()).status_code, 404)

    def test_a_second_mint_is_409(self):
        self.client.post(self._path())

        second = self.client.post(self._path())

        self.assertEqual(second.status_code, 409, second.text)

    def test_rotate_invalidates_the_previous_prefix(self):
        first = self.client.post(self._path()).json()

        rotated = self.client.post(self._path(suffix="/rotate"))

        self.assertEqual(rotated.status_code, 201, rotated.text)
        new_token = rotated.json()["token"]
        self.assertNotEqual(new_token, first["token"])

        old_row = (
            self.db.query(models.EmbedToken)
            .filter(models.EmbedToken.token_prefix == first["token_prefix"])
            .one()
        )
        self.assertIsNotNone(old_row.revoked_at)
        read = self.client.get(self._path()).json()
        self.assertTrue(read["active"])
        self.assertEqual(read["token_prefix"], new_token[:12])

    def test_delete_revokes_and_a_second_delete_is_404(self):
        self.client.post(self._path())

        revoked = self.client.delete(self._path())

        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json(), {"status": "revoked"})
        self.assertFalse(self.client.get(self._path()).json()["active"])
        self.assertEqual(self.client.delete(self._path()).status_code, 404)

    def test_another_companys_website_is_404_everywhere(self):
        calls = [
            ("post", self._path(self.other_site)),
            ("get", self._path(self.other_site)),
            ("post", self._path(self.other_site, suffix="/rotate")),
            ("delete", self._path(self.other_site)),
        ]

        for method, path in calls:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 404, response.text)

        self.assertEqual(
            self.db.query(models.EmbedToken)
            .filter(models.EmbedToken.website_id == self.other_site.id)
            .count(),
            0,
        )

    def test_the_routes_are_admin_only(self):
        app = FastAPI()
        app.include_router(website_api.router, prefix="/api/websites")
        manager = SimpleNamespace(id=uuid4(), company_id=self.company.id, role="manager")
        app.dependency_overrides[get_db] = lambda: self.db
        # Only the session auth is stubbed; `get_admin_user` is the real guard.
        app.dependency_overrides[get_current_user] = lambda: manager
        client = TestClient(app)

        for method, path in [
            ("post", self._path()),
            ("get", self._path()),
            ("post", self._path(suffix="/rotate")),
            ("delete", self._path()),
        ]:
            with self.subTest(method=method):
                response = getattr(client, method)(path)
                self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
