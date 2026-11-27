"""V6-11 — the operator console's network allowlist.

D5 was reopened by the owner on 2026-11-27 with this control: an operator
network allowlist (`OPERATOR_ALLOWED_NETWORKS`) enforced on every
`/api/platform` request, so the boundary does not depend on a hostname, an
alternate API origin or a proxy header. These cases pin the matching rules, the
production requirement, and the refusal itself — including that a spoofed
`X-Forwarded-For` from an untrusted peer buys nothing, and that a private peer
(a neighbouring container or a plain process on the same host or VPC) cannot
buy an allowed address either unless it is listed in `TRUSTED_PROXY_IPS`.
"""

import unittest
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

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.PlatformOwner.__table__,
    models.PlatformAuditLog.__table__,
    models.Subscription.__table__,
]


class AllowlistRulesTests(unittest.TestCase):
    def test_an_address_inside_a_listed_network_is_allowed(self):
        networks = ("10.20.0.0/16", "203.0.113.10")
        self.assertTrue(config.operator_network_allows("10.20.4.5", networks))
        self.assertTrue(config.operator_network_allows("203.0.113.10", networks))
        self.assertFalse(config.operator_network_allows("203.0.113.11", networks))
        self.assertFalse(config.operator_network_allows("10.21.0.1", networks))

    def test_an_unknown_or_unparsable_address_is_refused(self):
        networks = ("10.20.0.0/16",)
        for value in (None, "", "unknown", "not-an-ip", "10.20.0.999"):
            with self.subTest(value=value):
                self.assertFalse(config.operator_network_allows(value, networks))

    def test_an_empty_list_means_no_restriction(self):
        # Development posture only: production refuses the console switch
        # without a real list, which the next cases pin.
        self.assertTrue(config.operator_network_allows("203.0.113.9", ()))
        self.assertTrue(config.operator_network_allows("203.0.113.9", ""))

    def test_a_malformed_entry_can_never_widen_access(self):
        networks = ("not-a-network", "10.20.0.0/16")
        self.assertTrue(config.operator_network_allows("10.20.1.1", networks))
        self.assertFalse(config.operator_network_allows("203.0.113.9", networks))

    def test_only_a_non_blanket_list_is_a_control(self):
        for networks in (
            "",
            (),
            "0.0.0.0/0",
            "::/0",
            "10.0.0.0/8,0.0.0.0/0",
            "not-a-network",
            ("10.0.0.0/8", "bad"),
        ):
            with self.subTest(networks=networks):
                self.assertFalse(config.valid_operator_networks(networks))
        for networks in ("10.20.0.0/16", "203.0.113.10,::1", ("10.0.0.5",)):
            with self.subTest(networks=networks):
                self.assertTrue(config.valid_operator_networks(networks))


class OperatorNetworkRequestTests(unittest.TestCase):
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
        self.db.add(self.company)
        self.db.commit()

        self.owner = models.User(
            company_id=self.company.id,
            email="ops@acme.test",
            password_hash="x",
            first_name="Ops",
            last_name="Test",
            role="admin",
            status="active",
        )
        self.db.add(self.owner)
        self.db.commit()
        platform.grant_owner(self.db, self.owner.id, actor_label="test")

        self.app = FastAPI()
        self.app.include_router(platform_api.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.owner

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _client(self, host):
        return TestClient(self.app, client=(host, 50000))

    def test_an_allowed_address_reaches_the_console(self):
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ):
            response = self._client("10.20.1.7").get("/api/platform/session")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "ops@acme.test")

    def test_any_other_address_gets_the_same_403_as_a_missing_grant(self):
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ):
            # 1.1.1.1 is globally routed; TEST-NET addresses (203.0.113.0/24)
            # count as private in Python, so they are trusted peers here.
            refused = self._client("1.1.1.1").get("/api/platform/session")

        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json(), {"detail": "Not enough permissions"})

    def test_a_spoofed_forwarded_header_from_an_untrusted_peer_is_ignored(self):
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ):
            # The socket peer is public, so the header is attacker-controlled.
            response = self._client("1.1.1.1").get(
                "/api/platform/session",
                headers={"X-Forwarded-For": "10.20.1.7"},
            )

        self.assertEqual(response.status_code, 403)

    def test_a_listed_proxy_may_forward_an_allowed_address(self):
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ), patch.object(config, "TRUSTED_PROXY_IPS", ("127.0.0.1",)):
            response = self._client("127.0.0.1").get(
                "/api/platform/session",
                headers={"X-Forwarded-For": "10.20.1.7"},
            )

        self.assertEqual(response.status_code, 200)

    def test_a_private_peer_cannot_forge_an_allowed_address(self):
        # A neighbouring container or a shell on the same host shares the
        # private network. It may not claim an operator address with a header:
        # only a peer listed in TRUSTED_PROXY_IPS may forward here, even
        # though the limiter would trust the same private peer.
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ), patch.object(config, "TRUSTED_PROXY_IPS", ()):
            forged = self._client("10.99.0.5").get(
                "/api/platform/session",
                headers={"X-Forwarded-For": "10.20.1.7"},
            )
            loopback_forged = self._client("127.0.0.1").get(
                "/api/platform/session",
                headers={"X-Forwarded-For": "10.20.1.7"},
            )

        for response in (forged, loopback_forged):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json(), {"detail": "Not enough permissions"}
            )

    def test_a_private_peer_is_judged_by_its_socket_address(self):
        # Not a proxy, so its own address is the operator address — the header
        # is ignored rather than consulted.
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ), patch.object(config, "TRUSTED_PROXY_IPS", ()):
            response = self._client("10.20.1.7").get(
                "/api/platform/session",
                headers={"X-Forwarded-For": "1.1.1.1"},
            )

        self.assertEqual(response.status_code, 200)

    def test_the_switch_is_checked_before_the_network(self):
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", False), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ):
            response = self._client("10.20.1.7").get("/api/platform/session")

        self.assertEqual(response.status_code, 404)

    def test_every_platform_route_refuses_an_outside_address(self):
        routes = [
            route
            for route in platform_api.router.routes
            if getattr(route, "path", "").startswith("/api/platform")
        ]
        self.assertTrue(routes)
        with patch.object(config, "PLATFORM_CONSOLE_ENABLED", True), patch.object(
            config, "OPERATOR_ALLOWED_NETWORKS", ("10.20.0.0/16",)
        ):
            client = self._client("1.1.1.1")
            for route in routes:
                path = route.path
                method = "GET" if "GET" in route.methods else sorted(route.methods)[0]
                concrete = path.replace("{code}", "starter").replace(
                    "{company_id}", str(self.company.id)
                ).replace("{key}", "public_status_message")
                with self.subTest(path=path):
                    response = client.request(method, concrete, json={})
                    self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
