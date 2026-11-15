"""POST /api/v1/ingest: API-key auth on top of the shared helpers.

The route must not re-implement them, so these tests exercise the behaviour the
services own: the atomic claim (one enqueue, 409 for the loser), the disabled
website 403 and company scoping from the key.
"""

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import api_key as api_key_api
from site_gpt.app.api import v1 as v1_api
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import api_keys


class V1IngestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.Company.__table__,
                models.Website.__table__,
                models.ApiKey.__table__,
            ],
        )
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Customer", description="")
        self.db.add(self.company)
        self.db.commit()
        self.db.refresh(self.company)

        self.site = models.Website(
            url="https://customer.example.com",
            name="Customer",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=self.company.id,
            status="active",
            ingest_status="completed",
        )
        self.db.add(self.site)
        self.db.commit()
        self.db.refresh(self.site)

        app = FastAPI()
        app.include_router(v1_api.router, prefix="/api/v1")
        app.include_router(api_key_api.router, prefix="/api/api-keys")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_admin_user] = lambda: SimpleNamespace(
            id=uuid4(), company_id=self.company.id, role="admin"
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # ---- helpers -----------------------------------------------------------
    def make_key(self, scopes=("ingest:write",), revoked=False, company_id=None):
        raw = api_keys.generate_api_key()
        key = models.ApiKey(
            company_id=company_id or self.company.id,
            name="CI",
            key_prefix=api_keys.key_prefix(raw),
            key_hash=api_keys.hash_api_key(raw),
            scopes=json.dumps(list(scopes)),
            revoked_at=datetime.now(UTC) if revoked else None,
        )
        self.db.add(key)
        self.db.commit()
        self.db.refresh(key)
        return raw, key

    def ingest(self, raw_key, website_id=None):
        headers = {} if raw_key is None else {"X-API-Key": raw_key}
        with patch.object(v1_api, "enqueue_job", new=AsyncMock()) as enqueue:
            response = self.client.post(
                "/api/v1/ingest",
                params={"website_id": str(website_id or self.site.id)},
                headers=headers,
            )
        return response, enqueue

    def other_company_website(self):
        other = models.Company(name="Other", description="")
        self.db.add(other)
        self.db.commit()
        self.db.refresh(other)
        site = models.Website(
            url="https://other.example.com",
            name="Other",
            site_map_url="https://other.example.com/sitemap.xml",
            company_id=other.id,
            status="active",
            ingest_status="completed",
        )
        self.db.add(site)
        self.db.commit()
        self.db.refresh(site)
        return site

    # ---- the three required cases -----------------------------------------
    def test_success_claims_the_website_and_enqueues_one_job(self):
        raw_key, _ = self.make_key()

        response, enqueue = self.ingest(raw_key)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["website_id"], str(self.site.id))
        enqueue.assert_awaited_once_with(
            {"type": "ingest", "website_id": str(self.site.id)}
        )
        self.db.refresh(self.site)
        self.assertEqual(self.site.ingest_status, "processing")

    def test_a_second_call_gets_409_and_queues_nothing(self):
        raw_key, _ = self.make_key()

        first, enqueue_first = self.ingest(raw_key)
        second, enqueue_second = self.ingest(raw_key)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertIn("already running", second.json()["detail"])
        enqueue_first.assert_awaited_once()
        enqueue_second.assert_not_called()

    def test_a_disabled_website_is_refused_before_claiming(self):
        raw_key, _ = self.make_key()
        self.site.status = "inactive"
        self.db.commit()

        response, enqueue = self.ingest(raw_key)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("disabled", response.json()["detail"])
        enqueue.assert_not_called()
        # Nothing was claimed, so the row keeps its previous state.
        self.db.refresh(self.site)
        self.assertEqual(self.site.ingest_status, "completed")

    # ---- API-key auth ------------------------------------------------------
    def test_missing_key_is_401(self):
        response = self.client.post(
            "/api/v1/ingest", params={"website_id": str(self.site.id)}
        )

        self.assertEqual(response.status_code, 401, response.text)
        self.assertIn("Missing API key", response.json()["detail"])

    def test_unknown_key_is_401(self):
        response, enqueue = self.ingest(api_keys.generate_api_key())

        self.assertEqual(response.status_code, 401, response.text)
        self.assertIn("Invalid API key", response.json()["detail"])
        enqueue.assert_not_called()

    def test_revoked_key_is_401(self):
        raw_key, _ = self.make_key(revoked=True)

        response, enqueue = self.ingest(raw_key)

        self.assertEqual(response.status_code, 401, response.text)
        enqueue.assert_not_called()

    def test_key_without_the_ingest_scope_is_403(self):
        raw_key, _ = self.make_key(scopes=("read",))

        response, enqueue = self.ingest(raw_key)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("ingest:write", response.json()["detail"])
        enqueue.assert_not_called()

    def test_a_key_cannot_ingest_another_companys_website(self):
        raw_key, _ = self.make_key()
        foreign = self.other_company_website()

        response, enqueue = self.ingest(raw_key, website_id=foreign.id)

        self.assertEqual(response.status_code, 404, response.text)
        enqueue.assert_not_called()

    # ---- key lifecycle -----------------------------------------------------
    def test_created_key_authenticates_and_revoking_stops_it(self):
        created = self.client.post(
            "/api/api-keys", json={"name": "CI", "scopes": ["ingest:write"]}
        )

        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertTrue(body["key"].startswith("sk_"))
        self.assertEqual(body["key_prefix"], body["key"][:12])
        self.assertNotIn("key_hash", body)

        # Only a hash is stored.
        row = (
            self.db.query(models.ApiKey)
            .filter(models.ApiKey.id == UUID(body["id"]))
            .one()
        )
        self.assertNotEqual(row.key_hash, body["key"])
        self.assertEqual(len(row.key_hash), 64)

        # The list endpoint never returns the secret, only the prefix.
        listed = self.client.get("/api/api-keys")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertNotIn(body["key"], listed.text)
        self.assertIn(body["key_prefix"], listed.text)

        ok, enqueue = self.ingest(body["key"])
        self.assertEqual(ok.status_code, 200, ok.text)
        enqueue.assert_awaited_once()

        revoked = self.client.delete(f"/api/api-keys/{body['id']}")
        self.assertEqual(revoked.status_code, 200, revoked.text)

        denied, enqueue_after = self.ingest(body["key"])
        self.assertEqual(denied.status_code, 401, denied.text)
        enqueue_after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
