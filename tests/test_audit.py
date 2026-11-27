"""V6-14 — the tenant-admin audit trail.

The task's minimum action set is pinned through the real routes: user
create/role-status update/delete/password change, API-key create/revoke, settings
(and therefore model) changes, data export and erasure. Every case also checks
what must *not* be stored — a password, the raw API key, a submitted secret, a
transcript — because "metadata only" is the whole point of the trail.
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api.api_key import router as api_key_router
from site_gpt.app.api.audit import router as audit_router
from site_gpt.app.api.company import router as company_router
from site_gpt.app.api.privacy import router as privacy_router
from site_gpt.app.api.setting import router as setting_router
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import audit

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Setting.__table__,
    models.ApiKey.__table__,
    models.Website.__table__,
    models.ChatMessage.__table__,
    models.Contact.__table__,
    models.ChatFeedback.__table__,
    models.HandoffRequest.__table__,
    models.Conversation.__table__,
    models.TenantAuditLog.__table__,
]


class AuditTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _foreign_keys_on(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.other = models.Company(name="Other")
        self.db.add_all([self.company, self.other])
        self.db.commit()

        self.admin = self._user(self.company.id, "admin@acme.test", "admin")
        self.member = self._user(self.company.id, "member@acme.test", "user")
        self.foreign_admin = self._user(self.other.id, "admin@other.test", "admin")
        self.website = models.Website(
            company_id=self.company.id,
            name="Acme site",
            url="https://acme.test",
            site_map_url="https://acme.test/sitemap.xml",
        )
        self.db.add(self.website)
        self.db.commit()

        self.acting = self.admin
        self.app = FastAPI()
        for router, prefix in (
            (company_router, "/api/companies"),
            (setting_router, "/api/settings"),
            (api_key_router, "/api/api-keys"),
            (audit_router, "/api/audit"),
            (privacy_router, "/api/privacy"),
        ):
            self.app.include_router(router, prefix=prefix)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.acting
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _user(self, company_id, email, role):
        user = models.User(
            company_id=company_id,
            email=email,
            password_hash="x",
            first_name="Test",
            last_name="User",
            role=role,
            status="active",
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _rows(self, company_id=None):
        """Oldest-first, so a test can pick one event without relying on ties."""
        query = self.db.query(models.TenantAuditLog)
        if company_id is not None:
            query = query.filter(models.TenantAuditLog.company_id == company_id)
        return query.order_by(
            models.TenantAuditLog.created_at.asc(),
            models.TenantAuditLog.id.asc(),
        ).all()

    def _last(self, action):
        rows = [row for row in self._rows() if row.action == action]
        self.assertTrue(rows, f"no {action} audit row")
        return rows[-1]


class UserAuditTests(AuditTestBase):
    def test_creating_a_user_records_actor_role_and_no_password(self):
        response = self.client.post(
            "/api/companies/users",
            json={
                "email": "new@acme.test",
                "first_name": "New",
                "last_name": "Member",
                "password": "super-secret-password",
                "role": "manager",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        row = self._last("user.create")
        self.assertEqual(row.action, "user.create")
        self.assertEqual(row.actor_user_id, self.admin.id)
        self.assertEqual(row.actor_label, "admin@acme.test")
        self.assertEqual(row.target_id, response.json()["id"])
        self.assertEqual(row.detail, {"role": "manager", "status": "active"})
        self.assertNotIn("super-secret-password", str(row.detail))

    def test_a_role_and_status_change_is_recorded_without_profile_values(self):
        target = self._user(self.company.id, "target@acme.test", "user")
        response = self.client.put(
            f"/api/companies/users/{target.id}",
            json={
                "email": "renamed@acme.test",
                "phone": "+84900000000",
                "role": "manager",
                "status": "inactive",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        row = self._last("user.update")
        self.assertEqual(row.action, "user.update")
        self.assertEqual(row.target_id, str(target.id))
        self.assertEqual(
            row.detail,
            {
                "fields": ["email", "phone", "role", "status"],
                "role": "manager",
                "status": "inactive",
            },
        )
        # The trail keeps field names and the two security-relevant values, not
        # the new email or phone number.
        self.assertNotIn("renamed@acme.test", str(row.detail))
        self.assertNotIn("84900000000", str(row.detail))

    def test_deleting_a_user_leaves_an_audit_row(self):
        target = self._user(self.company.id, "gone@acme.test", "user")
        response = self.client.delete(f"/api/companies/users/{target.id}")

        self.assertEqual(response.status_code, 200, response.text)
        row = self._last("user.delete")
        self.assertEqual(row.action, "user.delete")
        self.assertEqual(row.target_id, str(target.id))
        self.assertEqual(row.actor_label, "admin@acme.test")

    def test_a_password_change_records_no_hash_or_password(self):
        target = self._user(self.company.id, "pw@acme.test", "user")
        response = self.client.post(
            f"/api/companies/users/{target.id}/change-password",
            params={"password": "another-secret-password"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        row = self._last("user.password.change")
        self.assertEqual(row.action, "user.password.change")
        self.assertIsNone(row.detail)
        self.assertNotIn("another-secret-password", str(row.detail))


class ApiKeyAndSettingsAuditTests(AuditTestBase):
    def test_key_creation_keeps_the_prefix_not_the_key(self):
        response = self.client.post(
            "/api/api-keys/", json={"name": "integration", "scopes": ["read"]}
        )

        self.assertEqual(response.status_code, 201, response.text)
        raw = response.json()["key"]
        self.assertTrue(raw)
        row = self._last("api_key.create")
        self.assertEqual(row.action, "api_key.create")
        self.assertEqual(row.target_id, response.json()["id"])
        self.assertNotIn(raw, str(row.detail))
        self.assertIn("integration", row.detail["name"])

    def test_key_revocation_is_recorded(self):
        created = self.client.post(
            "/api/api-keys/", json={"name": "temp", "scopes": ["read"]}
        )
        key_id = created.json()["id"]

        response = self.client.delete(f"/api/api-keys/{key_id}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._last("api_key.revoke").action, "api_key.revoke")

    def test_settings_record_key_names_and_never_values(self):
        response = self.client.put(
            "/api/settings/",
            json=[{"key": "assistant_name", "value": "sk-live-not-a-secret"}],
        )

        self.assertEqual(response.status_code, 200, response.text)
        row = self._last("settings.update")
        self.assertEqual(row.action, "settings.update")
        self.assertEqual(row.detail, {"keys": ["assistant_name"]})
        self.assertNotIn("sk-live-not-a-secret", str(row.detail))

    def test_a_model_change_is_the_same_settings_event(self):
        response = self.client.put(
            "/api/settings/",
            json=[
                {"key": "llm_provider", "value": "openai"},
                {"key": "llm_model", "value": "gpt-4o-mini"},
            ],
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self._last("settings.update").detail,
            {"keys": ["llm_model", "llm_provider"]},
        )


class PrivacyAuditTests(AuditTestBase):
    def test_an_export_is_audited_without_the_exported_rows(self):
        self.db.add(
            models.ChatMessage(
                website_id=self.website.id,
                session_id="s1",
                role="user",
                message="my private question",
            )
        )
        self.db.commit()

        response = self.client.get(
            "/api/privacy/export", params={"website_id": str(self.website.id)}
        )

        self.assertEqual(response.status_code, 200, response.text)
        row = self._last("data.export")
        self.assertEqual(row.action, "data.export")
        self.assertEqual(row.target_id, str(self.website.id))
        self.assertNotIn("my private question", str(row.detail))

    def test_a_retention_preview_is_not_an_erasure(self):
        # The purge itself is covered by the retention suite; this pins only the
        # audit question — a preview is not an erasure, an applied purge is.
        def fake_purge(_db, _company_id, days=None, dry_run=True):
            return {
                "retention_days": 30,
                "cutoff": None,
                "dry_run": dry_run,
                "deleted": {},
                "total": 4,
            }

        with patch(
            "site_gpt.app.api.privacy.retention.purge_company",
            side_effect=fake_purge,
        ):
            dry = self.client.post(
                "/api/privacy/retention",
                json={"dry_run": True, "retention_days": 30},
            )
            self.assertEqual(dry.status_code, 200, dry.text)
            self.assertEqual(
                [
                    row
                    for row in self._rows()
                    if row.action == "data.retention.apply"
                ],
                [],
            )

            applied = self.client.post(
                "/api/privacy/retention",
                json={"dry_run": False, "retention_days": 30},
            )

        self.assertEqual(applied.status_code, 200, applied.text)
        row = self._last("data.retention.apply")
        self.assertEqual(row.detail, {"retention_days": 30, "rows": 4})


class AuditReadTests(AuditTestBase):
    def test_the_read_is_company_scoped_and_bounded(self):
        self.client.put(
            "/api/settings/", json=[{"key": "assistant_name", "value": "Acme"}]
        )
        audit.record(
            self.db,
            company_id=self.other.id,
            action="user.create",
            target_type="user",
            actor=self.foreign_admin,
            commit=True,
        )

        response = self.client.get("/api/audit/", params={"limit": 10})

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["events"][0]["action"], "settings.update")
        self.assertEqual(payload["events"][0]["actor_label"], "admin@acme.test")

        too_big = self.client.get("/api/audit/", params={"limit": 101})
        self.assertEqual(too_big.status_code, 422)

    def test_only_an_admin_may_read_the_trail(self):
        self.acting = self.member
        self.assertEqual(self.client.get("/api/audit/").status_code, 403)

    def test_an_action_filter_is_exact(self):
        for key in ("assistant_name", "handoff_email"):
            self.client.put(
                "/api/settings/", json=[{"key": key, "value": "x"}]
            )
        audit.record(
            self.db,
            company_id=self.company.id,
            action="data.export",
            target_type="website",
            actor=self.admin,
            commit=True,
        )

        response = self.client.get("/api/audit/", params={"action": "data.export"})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["events"][0]["action"], "data.export")


class AuditServiceTests(AuditTestBase):
    def test_secret_shaped_detail_is_redacted_before_storage(self):
        row = audit.record(
            self.db,
            company_id=self.company.id,
            action="settings.update",
            target_type="company",
            actor=self.admin,
            detail={"password": "hunter2", "api_key": "sk-123", "webhook_token": "t"},
            commit=True,
        )

        self.assertEqual(
            row.detail,
            {
                "password": "[redacted]",
                "api_key": "[redacted]",
                "webhook_token": "[redacted]",
            },
        )

    def test_the_one_year_purge_dry_runs_then_deletes(self):
        old = audit.record(
            self.db,
            company_id=self.company.id,
            action="user.create",
            target_type="user",
            actor=self.admin,
        )
        fresh = audit.record(
            self.db,
            company_id=self.company.id,
            action="user.create",
            target_type="user",
            actor=self.admin,
        )
        self.db.commit()
        old.created_at = datetime.now(UTC) - timedelta(days=400)
        fresh.created_at = datetime.now(UTC) - timedelta(days=10)
        self.db.commit()

        self.assertEqual(audit.purge_expired(self.db, dry_run=True), 1)
        self.assertEqual(len(self._rows()), 2)

        self.assertEqual(audit.purge_expired(self.db), 1)
        remaining = self._rows()
        self.assertEqual([row.id for row in remaining], [fresh.id])

    def test_zero_days_keeps_the_trail_for_ever(self):
        audit.record(
            self.db,
            company_id=self.company.id,
            action="user.create",
            target_type="user",
            actor=self.admin,
            commit=True,
        )
        self.assertEqual(audit.purge_expired(self.db, days=0), 0)
        self.assertEqual(len(self._rows()), 1)


if __name__ == "__main__":
    unittest.main()
