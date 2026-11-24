"""The platform-owner boundary (V5-40, Wave 4, D10).

What is pinned here:

* the surface is invisible while `PLATFORM_CONSOLE_ENABLED` is false — a 404,
  even to a signed-in operator — and the flag itself defaults to off;
* tenant roles do not cross the boundary: an ordinary user, a manager and even a
  company `admin` are refused, as are anonymous callers and API-key callers;
* a provisioned grant (only `services.platform.grant_owner`, i.e. the out-of-band
  CLI) is allowed, and a revoke takes effect on the very next request while the
  revoked row stays as history;
* re-granting after a revoke works (the partial unique index covers active rows
  only) and a repeated grant is idempotent;
* every grant/revoke writes one append-only audit row with actor, action,
  target and time, and the writer redacts secret-looking detail before storage.

Two clients are used on purpose: `anon_client` keeps the real JWT dependency so
anonymous and `X-API-Key`-only callers are genuinely refused, while `client`
overrides `get_current_user` to switch identity (the JWT path itself is covered
by the auth/console suites). These are service/API tests over a real SQLite
schema; no Stripe, Redis or provider call is involved.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import platform as platform_api
from site_gpt.app.core import config
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import platform

ROOT = Path(__file__).resolve().parent.parent

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.PlatformOwner.__table__,
    models.PlatformAuditLog.__table__,
    models.Subscription.__table__,
]


class PlatformTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # SQLite ignores foreign keys unless asked, and the grant's CASCADE is
        # the only thing that removes it with a deleted user.
        @event.listens_for(self.engine, "connect")
        def _foreign_keys_on(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.db.add(self.company)
        self.db.commit()

        self.owner = self._user("ops@acme.test", "admin")
        self.admin = self._user("admin@acme.test", "admin")
        self.manager = self._user("manager@acme.test", "manager")
        self.member = self._user("member@acme.test", "user")

        patcher = patch.object(config, "PLATFORM_CONSOLE_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Real auth: proves anonymous and API-key callers never reach the route.
        self.anon_app = FastAPI()
        self.anon_app.include_router(platform_api.router)
        self.anon_app.dependency_overrides[get_db] = lambda: self.db
        self.anon_client = TestClient(self.anon_app)

        # Switchable identity for the role matrix.
        self.acting_user = None
        self.app = FastAPI()
        self.app.include_router(platform_api.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.acting_user
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _user(self, email, role):
        user = models.User(
            company_id=self.company.id,
            email=email,
            password_hash="x",
            first_name=email.split("@")[0],
            last_name="Test",
            role=role,
            status="active",
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _get(self, path, user=None, **kwargs):
        self.acting_user = user
        return self.client.get(path, **kwargs)

    def _grant(self, user=None, actor="test-operator"):
        user = user or self.owner
        platform.grant_owner(self.db, user.id, actor_label=actor)
        return user


class ConsoleFlagTests(PlatformTestBase):
    def test_the_flag_defaults_to_off(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "PLATFORM_CONSOLE_ENABLED"
        }
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from site_gpt.app.core.config import PLATFORM_CONSOLE_ENABLED;"
                "print(PLATFORM_CONSOLE_ENABLED)",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_the_surface_is_a_404_while_the_console_is_off(self):
        self._grant()
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False):
            self.assertEqual(self._get("/api/platform/session", self.owner).status_code, 404)
            # Anonymous callers cannot tell the surface exists either.
            self.assertEqual(
                self.anon_client.get("/api/platform/session").status_code, 404
            )


class ConsoleOffAtTheIngressTests(PlatformTestBase):
    """V6-11: the switch is process configuration, not a host or proxy header.

    D5 keeps the console off for this launch. These cases pin both halves of
    that answer: the switch hides every route from every caller — a granted
    operator included — and no `Host`, `X-Forwarded-*` or `Origin` header can
    stand in for the ingress-level control a re-opened console would need.
    """

    ALT_ORIGIN_HEADERS = {
        "Host": "platform.internal.example",
        "X-Forwarded-Host": "platform.internal.example",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "203.0.113.10",
        "Origin": "https://platform.internal.example",
    }

    def _routes(self):
        routes = [
            route
            for route in platform_api.router.routes
            if getattr(route, "path", "").startswith("/api/platform")
        ]
        self.assertTrue(routes, "the platform router should expose routes")
        return routes

    def _call(self, route, user, headers=None):
        path = route.path
        while "{" in path:
            start = path.index("{")
            end = path.index("}", start)
            path = f"{path[:start]}{self.company.id}{path[end + 1:]}"
        method = "GET" if "GET" in route.methods else sorted(route.methods)[0]
        self.acting_user = user
        if method == "GET":
            return self.client.request(method, path, headers=headers or {})
        return self.client.request(method, path, json={}, headers=headers or {})

    def _carries_console_gate(self, dependant, seen=None):
        seen = seen if seen is not None else set()
        for dependency in dependant.dependencies:
            if dependency.call is platform_api.platform_console_enabled:
                return True
            if id(dependency) not in seen:
                seen.add(id(dependency))
                if self._carries_console_gate(dependency, seen):
                    return True
        return False

    def test_every_route_hides_behind_the_switch_for_every_caller(self):
        self._grant()
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False):
            for route in self._routes():
                for label, user in (
                    ("owner", self.owner),
                    ("tenant admin", self.admin),
                ):
                    with self.subTest(path=route.path, caller=label):
                        response = self._call(route, user)
                        self.assertEqual(response.status_code, 404)
                        self.assertEqual(response.json(), {"detail": "Not found"})

    def test_the_switch_is_not_derived_from_host_or_proxy_headers(self):
        self._grant()
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False):
            for path in (
                "/api/platform/session",
                "/api/platform/overview",
                "/api/platform/audit",
            ):
                with self.subTest(path=path):
                    response = self._get(
                        path, self.owner, headers=self.ALT_ORIGIN_HEADERS
                    )
                    self.assertEqual(response.status_code, 404)

    def test_an_alternate_hostname_does_not_replace_the_owner_check(self):
        # With the switch on, the same headers buy a tenant admin nothing.
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True):
            response = self._get(
                "/api/platform/session",
                self.admin,
                headers=self.ALT_ORIGIN_HEADERS,
            )

        self.assertEqual(response.status_code, 403)

    def test_every_route_carries_the_console_gate(self):
        # A route added later without the dependency would answer 401/403 and
        # so reveal the surface; this is the structural half of the switch.
        for route in self._routes():
            with self.subTest(path=route.path):
                self.assertTrue(self._carries_console_gate(route.dependant))

    def test_disabling_and_re_enabling_the_switch_keeps_grants(self):
        self._grant()
        audit_before = self.db.query(models.PlatformAuditLog).count()
        self.assertEqual(self._get("/api/platform/session", self.owner).status_code, 200)

        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False):
            self.assertEqual(self._get("/api/platform/session", self.owner).status_code, 404)

        self.assertEqual(self._get("/api/platform/session", self.owner).status_code, 200)
        self.assertEqual(
            self.db.query(models.PlatformAuditLog).count(), audit_before
        )


class AuthorizationTests(PlatformTestBase):
    def test_anonymous_callers_are_refused(self):
        self.assertIn(
            self.anon_client.get("/api/platform/session").status_code, (401, 403)
        )

    def test_an_api_key_is_not_a_platform_session(self):
        response = self.anon_client.get(
            "/api/platform/session", headers={"X-API-Key": "sk_not_a_session"}
        )

        self.assertIn(response.status_code, (401, 403))

    def test_every_tenant_role_is_refused_including_admin(self):
        for user in (self.member, self.manager, self.admin):
            with self.subTest(role=user.role):
                self.assertEqual(
                    self._get("/api/platform/session", user).status_code, 403
                )
                self.assertEqual(
                    self._get("/api/platform/audit", user).status_code, 403
                )

    def test_a_tenant_admin_is_refused_even_with_a_subscription(self):
        self.db.add(
            models.Subscription(
                company_id=self.company.id,
                plan_code="starter",
                interval="month",
                status="active",
                stripe_customer_id="cus_test",
            )
        )
        self.db.commit()

        self.assertEqual(self._get("/api/platform/session", self.admin).status_code, 403)

    def test_a_provisioned_operator_is_allowed(self):
        self._grant()
        response = self._get("/api/platform/session", self.owner)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["email"], "ops@acme.test")
        self.assertEqual(body["user_id"], str(self.owner.id))
        self.assertTrue(body["granted_at"])

    def test_revocation_takes_effect_on_the_next_request(self):
        self._grant()
        self.assertEqual(self._get("/api/platform/session", self.owner).status_code, 200)

        self.assertTrue(
            platform.revoke_owner(self.db, self.owner.id, actor_label="test-operator")
        )
        self.assertEqual(self._get("/api/platform/session", self.owner).status_code, 403)

    def test_no_platform_route_can_grant_or_revoke_ownership(self):
        # Catalog and settings mutations exist, but no route can mint the
        # operator grant itself: provisioning is the out-of-band CLI's job.
        for route in platform_api.router.routes:
            self.assertNotIn("owner", getattr(route, "path", "").lower())
            self.assertNotIn("grant", getattr(route, "path", "").lower())
            self.assertNotIn("revoke", getattr(route, "path", "").lower())


class GrantLifecycleTests(PlatformTestBase):
    def test_granting_twice_is_idempotent(self):
        first, created = platform.grant_owner(
            self.db, self.owner.id, actor_label="test-operator"
        )
        second, created_again = platform.grant_owner(
            self.db, self.owner.id, actor_label="test-operator"
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            self.db.query(models.PlatformOwner)
            .filter(models.PlatformOwner.user_id == self.owner.id)
            .count(),
            1,
        )

    def test_a_revoked_grant_stays_as_history_and_can_be_regranted(self):
        grant, _ = platform.grant_owner(
            self.db, self.owner.id, actor_label="test-operator"
        )
        platform.revoke_owner(self.db, self.owner.id, actor_label="test-operator")
        fresh, created = platform.grant_owner(
            self.db, self.owner.id, actor_label="test-operator"
        )

        self.assertTrue(created)
        self.assertNotEqual(grant.id, fresh.id)
        rows = (
            self.db.query(models.PlatformOwner)
            .filter(models.PlatformOwner.user_id == self.owner.id)
            .all()
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.revoked_at is None for row in rows].count(True), 1)

    def test_revoking_without_a_grant_reports_false_and_audits_nothing(self):
        self.assertFalse(
            platform.revoke_owner(self.db, self.owner.id, actor_label="test-operator")
        )
        self.assertEqual(self.db.query(models.PlatformAuditLog).count(), 0)

    def test_deleting_the_user_removes_the_grant(self):
        grant, _ = platform.grant_owner(
            self.db, self.owner.id, actor_label="test-operator"
        )
        grant_id = grant.id  # the ORM row expires once the cascade removes it
        self.db.execute(
            models.User.__table__.delete().where(models.User.id == self.owner.id)
        )
        self.db.commit()

        self.assertIsNone(
            self.db.query(models.PlatformOwner)
            .filter(models.PlatformOwner.id == grant_id)
            .first()
        )


class AuditTests(PlatformTestBase):
    def test_grant_and_revoke_are_audited_with_actor_target_and_time(self):
        platform.grant_owner(
            self.db, self.owner.id, actor_label="on-call SRE", note="primary"
        )
        platform.revoke_owner(self.db, self.owner.id, actor_label="on-call SRE")

        rows = (
            self.db.query(models.PlatformAuditLog)
            .order_by(models.PlatformAuditLog.created_at)
            .all()
        )
        self.assertEqual(
            [row.action for row in rows],
            ["platform_owner.grant", "platform_owner.revoke"],
        )
        for row in rows:
            self.assertEqual(row.target_type, "user")
            self.assertEqual(row.target_id, str(self.owner.id))
            self.assertEqual(row.actor_label, "on-call SRE")
            self.assertIsNone(row.actor_user_id)
            self.assertIsNotNone(row.created_at)

    def test_secret_shaped_detail_is_redacted(self):
        row = platform.record_audit(
            self.db,
            action="test.action",
            target_type="company",
            target_id=str(self.company.id),
            detail={
                "plan": "starter",
                "password": "hunter2",
                "api_key": "sk_live_123",
                "nested": {"stripe_secret_key": "sk_test_x", "label": "ok"},
                "counts": [1, 2],
                "raw": b"bytes",
            },
        )

        self.assertEqual(
            row.detail,
            {
                "plan": "starter",
                "password": platform.REDACTED,
                "api_key": platform.REDACTED,
                "nested": {
                    "stripe_secret_key": platform.REDACTED,
                    "label": "ok",
                },
                "counts": [1, 2],
                "raw": platform.REDACTED,
            },
        )

    def test_the_audit_route_is_owner_only_and_returns_the_rows(self):
        self._grant()
        platform.record_audit(
            self.db,
            action="test.action",
            target_type="user",
            target_id=str(self.owner.id),
            actor_user_id=self.owner.id,
            detail={"token": "abc"},
        )

        response = self._get("/api/platform/audit", self.owner)

        self.assertEqual(response.status_code, 200)
        events = response.json()["events"]
        # Both rows come back — the explicit one and the grant that set the
        # operator up. SQLite's CURRENT_TIMESTAMP has second precision, so the
        # two share an instant and the order is not asserted here.
        self.assertEqual(
            sorted(event["action"] for event in events),
            ["platform_owner.grant", "test.action"],
        )
        explicit = next(
            event for event in events if event["action"] == "test.action"
        )
        self.assertEqual(explicit["actor_user_id"], str(self.owner.id))
        self.assertEqual(explicit["detail"], {"token": platform.REDACTED})

    def test_the_audit_read_is_bounded(self):
        self._grant()

        self.assertEqual(
            self._get("/api/platform/audit?limit=0", self.owner).status_code, 422
        )
        self.assertEqual(
            self._get("/api/platform/audit?limit=500", self.owner).status_code, 422
        )
        self.assertEqual(
            self._get("/api/platform/audit?limit=10", self.owner).status_code, 200
        )


if __name__ == "__main__":
    unittest.main()
