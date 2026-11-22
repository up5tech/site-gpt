"""The platform-owner operations console (V5-41 … V5-44).

What is pinned here:

* cross-company reads are owner-only, paginated and searchable, and include only
  the mirrored state plus opaque Stripe references;
* the two subscription actions require a reason, a destructive one requires
  confirmation, and `cancel_at_period_end` asks Stripe without writing the local
  mirror — a verified webhook remains the only state authority. There is no
  "mark paid" action;
* the durable catalog starts as a draft, is invisible publicly until published,
  needs a Stripe mapping to publish with billing on, keeps every price record as
  immutable history, and archives instead of deleting;
* the global-settings allowlist rejects unknown keys and invalid values, preview
  writes nothing, and every accepted change is audited with the actor;
* every platform route is owner-only — a tenant admin, member or anonymous
  caller is refused — and no route can mint or revoke an operator grant.

Service/API tests against a real SQLite schema; Stripe is mocked and no live
account or credential is used.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import plan as plan_api
from site_gpt.app.api import platform as platform_api
from site_gpt.app.api import public_config as public_config_api
from site_gpt.app.core import config
from site_gpt.app.core.auth import get_current_user, require_platform_owner
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import billing, plan_catalog, platform

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.Subscription.__table__,
    models.PlatformOwner.__table__,
    models.PlatformAuditLog.__table__,
    models.CatalogPlan.__table__,
    models.PlanPrice.__table__,
    models.PlatformSetting.__table__,
]


class PlatformConsoleTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.other = models.Company(name="Beta")
        self.db.add_all([self.company, self.other])
        self.db.commit()

        self.owner = self._user(self.company, "ops@acme.test", "admin")
        self.admin = self._user(self.company, "admin@acme.test", "admin")
        self.member = self._user(self.company, "member@acme.test", "user")
        self.db.add(
            models.Website(
                url="https://acme.test",
                name="Acme site",
                company_id=self.company.id,
                site_map_url="https://acme.test/sitemap.xml",
            )
        )
        self.db.commit()
        platform.grant_owner(self.db, self.owner.id, actor_label="setup")

        patcher = patch.object(config, "PLATFORM_CONSOLE_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.acting_user = self.owner
        self.app = FastAPI()
        self.app.include_router(platform_api.router)
        self.app.include_router(public_config_api.router)
        self.app.include_router(plan_api.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.acting_user
        self.client = TestClient(self.app)

        # Real auth path: anonymous callers never reach a route.
        self.anon_app = FastAPI()
        self.anon_app.include_router(platform_api.router)
        self.anon_app.dependency_overrides[get_db] = lambda: self.db
        self.anon_client = TestClient(self.anon_app)

        self.public_client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _user(self, company, email, role):
        user = models.User(
            company_id=company.id,
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

    def _subscription(self, company=None, **values):
        company = company or self.company
        row = models.Subscription(
            company_id=company.id,
            plan_code=values.pop("plan_code", "starter"),
            interval=values.pop("interval", "month"),
            status=values.pop("status", "active"),
            stripe_customer_id=values.pop("stripe_customer_id", "cus_test"),
            stripe_subscription_id=values.pop(
                "stripe_subscription_id", "sub_test"
            ),
            **values,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _plan_payload(self, code="starter", **overrides):
        payload = {
            "code": code,
            "name": "Starter",
            "description": "One website.",
            "features": ["One website"],
            "limits": {"websites": 1},
            "self_serve_checkout": True,
            "interval": "month",
            "currency": "usd",
            "price_minor": 2900,
            "stripe_price_id": None,
            "reason": "initial catalog",
        }
        payload.update(overrides)
        return payload

    def _create_plan(self, code="starter", **overrides):
        return self.client.post(
            "/api/platform/plans", json=self._plan_payload(code, **overrides)
        )

    def _audit(self, action=None):
        query = self.db.query(models.PlatformAuditLog)
        if action:
            query = query.filter(models.PlatformAuditLog.action == action)
        return query.order_by(
            models.PlatformAuditLog.created_at, models.PlatformAuditLog.id
        ).all()


class OverviewAndListsTests(PlatformConsoleTestCase):
    def test_overview_counts_companies_websites_users_and_subscriptions(self):
        self._subscription()
        response = self.client.get("/api/platform/overview")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["companies"], 2)
        self.assertEqual(body["websites"], 1)
        self.assertEqual(body["active_users"], 3)
        self.assertEqual(body["subscriptions"], {"active": 1})
        self.assertEqual(body["published_plans"], 0)

    def test_companies_are_searchable_and_paginated(self):
        self._subscription()
        response = self.client.get(
            "/api/platform/companies?search=acm&page=1&page_size=10"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["name"], "Acme")
        self.assertEqual(body["items"][0]["websites"], 1)
        self.assertEqual(body["items"][0]["active_users"], 3)
        self.assertEqual(body["items"][0]["plan_code"], "starter")
        self.assertEqual(body["items"][0]["status"], "active")

    def test_subscriptions_list_filters_and_carries_stripe_references(self):
        self._subscription(status="past_due", stripe_customer_id="cus_pd")

        response = self.client.get("/api/platform/subscriptions?status=past_due")

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["company_name"], "Acme")
        self.assertEqual(item["status"], "past_due")
        self.assertEqual(item["stripe_customer_id"], "cus_pd")
        self.assertEqual(item["stripe_subscription_id"], "sub_test")

        empty = self.client.get("/api/platform/subscriptions?status=active")
        self.assertEqual(empty.json()["items"], [])

    def test_page_size_is_bounded(self):
        self.assertEqual(
            self.client.get("/api/platform/companies?page_size=500").status_code,
            422,
        )

    def test_list_reads_are_refused_to_a_tenant_admin(self):
        self.acting_user = self.admin
        for path in (
            "/api/platform/overview",
            "/api/platform/companies",
            "/api/platform/subscriptions",
            "/api/platform/plans",
            "/api/platform/settings",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)


class SubscriptionActionTests(PlatformConsoleTestCase):
    def test_a_reason_and_confirmation_are_required_for_cancellation(self):
        self._subscription()

        missing_reason = self.client.post(
            f"/api/platform/subscriptions/{self.company.id}/actions",
            json={"action": "request_reconciliation", "reason": "x"},
        )
        unconfirmed = self.client.post(
            f"/api/platform/subscriptions/{self.company.id}/actions",
            json={
                "action": "cancel_at_period_end",
                "reason": "customer asked",
                "confirm": False,
            },
        )

        self.assertEqual(missing_reason.status_code, 422)
        self.assertEqual(unconfirmed.status_code, 400)

    def test_there_is_no_mark_paid_action(self):
        self._subscription()

        response = self.client.post(
            f"/api/platform/subscriptions/{self.company.id}/actions",
            json={"action": "mark_paid", "reason": "support", "confirm": True},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._audit("platform.subscription.mark_paid"), [])

    def test_reconciliation_is_an_audit_record_not_a_state_change(self):
        row = self._subscription()

        response = self.client.post(
            f"/api/platform/subscriptions/{self.company.id}/actions",
            json={
                "action": "request_reconciliation",
                "reason": "invoice mismatch reported",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(row)
        self.assertEqual(row.status, "active")
        audit = self._audit("platform.subscription.reconciliation_requested")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0].actor_user_id, self.owner.id)
        self.assertEqual(audit[0].detail["reason"], "invoice mismatch reported")

    def test_cancel_at_period_end_asks_stripe_and_never_writes_the_mirror(self):
        row = self._subscription()
        for name, value in (
            ("BILLING_ENABLED", True),
            ("STRIPE_SECRET_KEY", "sk_test_example"),
        ):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        with patch(
            "site_gpt.app.services.platform_ops.stripe.Subscription.modify",
            return_value=SimpleNamespace(id="sub_test"),
        ) as modify:
            response = self.client.post(
                f"/api/platform/subscriptions/{self.company.id}/actions",
                json={
                    "action": "cancel_at_period_end",
                    "reason": "requested by customer",
                    "confirm": True,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        modify.assert_called_once()
        args, kwargs = modify.call_args
        self.assertEqual(args[0], "sub_test")
        self.assertTrue(kwargs["cancel_at_period_end"])
        self.db.refresh(row)
        self.assertFalse(row.cancel_at_period_end)
        audit = self._audit("platform.subscription.cancel_at_period_end")
        self.assertEqual(audit[-1].detail["outcome"], "requested")

    def test_cancellation_is_refused_while_billing_is_off(self):
        row = self._subscription()

        response = self.client.post(
            f"/api/platform/subscriptions/{self.company.id}/actions",
            json={
                "action": "cancel_at_period_end",
                "reason": "requested by customer",
                "confirm": True,
            },
        )

        self.assertEqual(response.status_code, 409)
        self.db.refresh(row)
        self.assertEqual(row.status, "active")
        audit = self._audit("platform.subscription.cancel_at_period_end")
        self.assertEqual(audit[-1].detail["outcome"], "refused_billing_disabled")

    def test_a_stripe_failure_is_audited_without_provider_detail(self):
        self._subscription()
        for name, value in (
            ("BILLING_ENABLED", True),
            ("STRIPE_SECRET_KEY", "sk_test_example"),
        ):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        with patch(
            "site_gpt.app.services.platform_ops.stripe.Subscription.modify",
            side_effect=RuntimeError("secret-ish provider detail"),
        ):
            response = self.client.post(
                f"/api/platform/subscriptions/{self.company.id}/actions",
                json={
                    "action": "cancel_at_period_end",
                    "reason": "requested by customer",
                    "confirm": True,
                },
            )

        self.assertEqual(response.status_code, 502)
        detail = self._audit("platform.subscription.cancel_at_period_end")[-1].detail
        self.assertEqual(detail["outcome"], "provider_error")
        self.assertEqual(detail["error"], "RuntimeError")
        self.assertNotIn("secret-ish", str(detail))

    def test_a_tenant_admin_cannot_act_on_a_subscription(self):
        self._subscription()
        self.acting_user = self.admin

        response = self.client.post(
            f"/api/platform/subscriptions/{self.company.id}/actions",
            json={
                "action": "request_reconciliation",
                "reason": "support request",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_an_unknown_company_is_a_404(self):
        response = self.client.post(
            f"/api/platform/subscriptions/{uuid4()}/actions",
            json={
                "action": "request_reconciliation",
                "reason": "support request",
            },
        )

        self.assertEqual(response.status_code, 404)


class CatalogTests(PlatformConsoleTestCase):
    def test_a_new_plan_is_a_draft_invisible_to_the_public(self):
        response = self._create_plan()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")
        self.assertEqual(self.public_client.get("/api/plans").json(), {"plans": []})
        audit = self._audit("platform.plan.create")
        self.assertEqual(audit[-1].target_id, "starter")
        self.assertEqual(audit[-1].actor_user_id, self.owner.id)

    def test_publishing_needs_confirmation_and_a_stripe_mapping_when_billing_is_on(self):
        self._create_plan()
        with patch.object(config, "BILLING_ENABLED", True):
            unconfirmed = self.client.post(
                "/api/platform/plans/starter/publish",
                json={"reason": "approved", "confirm": False},
            )
            unmapped = self.client.post(
                "/api/platform/plans/starter/publish",
                json={"reason": "approved", "confirm": True},
            )

        self.assertEqual(unconfirmed.status_code, 400)
        self.assertEqual(unmapped.status_code, 409)

    def test_a_published_plan_reaches_the_public_payload_without_stripe_ids(self):
        self._create_plan(stripe_price_id="price_starter")
        published = self.client.post(
            "/api/platform/plans/starter/publish",
            json={"reason": "approved", "confirm": True},
        )

        self.assertEqual(published.status_code, 200, published.text)
        public = self.public_client.get("/api/plans").json()["plans"]
        self.assertEqual([plan["code"] for plan in public], ["starter"])
        self.assertNotIn("price_starter", str(public))
        self.assertNotIn("stripe_price_id", public[0])
        self.assertEqual(self.public_client.get("/api/platform/session").status_code, 200)
        self.assertEqual(self.public_client.get("/api/public/config").status_code, 200)

    def test_a_price_change_creates_a_new_record_and_keeps_history(self):
        self._create_plan(stripe_price_id="price_first")

        response = self.client.post(
            "/api/platform/plans/starter/prices",
            json={
                "interval": "month",
                "currency": "usd",
                "price_minor": 3900,
                "stripe_price_id": "price_second",
                "reason": "price increase",
                "confirm": True,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        prices = response.json()["prices"]
        self.assertEqual({price["stripe_price_id"] for price in prices}, {
            "price_first",
            "price_second",
        })
        active = [price for price in prices if price["active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["price_minor"], 3900)
        audit = self._audit("platform.plan.price")
        self.assertEqual(audit[-1].detail["price_minor"], 3900)

    def test_the_durable_price_mapping_wins_over_the_env_fallback(self):
        self._create_plan(stripe_price_id="price_catalog")
        self.client.post(
            "/api/platform/plans/starter/publish",
            json={"reason": "approved", "confirm": True},
        )
        plan = plan_catalog.find_plan("starter", self.db)
        with patch.object(
            config, "STRIPE_PRICE_IDS", "starter:month=price_env"
        ):
            self.assertEqual(
                billing.price_id_for(plan, self.db), "price_catalog"
            )
            self.assertEqual(billing.price_id_for(plan), "price_env")

    def test_archiving_removes_the_plan_from_the_public_and_freezes_it(self):
        self._create_plan()
        self.client.post(
            "/api/platform/plans/starter/publish",
            json={"reason": "approved", "confirm": True},
        )

        archived = self.client.post(
            "/api/platform/plans/starter/archive",
            json={"reason": "retired", "confirm": True},
        )

        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(self.public_client.get("/api/plans").json(), {"plans": []})
        edit = self.client.put(
            "/api/platform/plans/starter",
            json={"name": "New name", "reason": "typo", "confirm": True},
        )
        self.assertEqual(edit.status_code, 409)

    def test_edits_and_price_changes_need_confirmation(self):
        self._create_plan()

        edit = self.client.put(
            "/api/platform/plans/starter",
            json={"name": "Renamed", "reason": "typo"},
        )
        price = self.client.post(
            "/api/platform/plans/starter/prices",
            json={
                "interval": "month",
                "currency": "usd",
                "price_minor": 1000,
                "reason": "promo",
            },
        )

        self.assertEqual(edit.status_code, 400)
        self.assertEqual(price.status_code, 400)
        self.assertEqual(
            self.client.get("/api/platform/plans").json()["plans"][0]["name"],
            "Starter",
        )

    def test_invalid_codes_and_duplicates_are_refused(self):
        self.assertEqual(
            self._create_plan(code="Not Valid").status_code, 400
        )
        self.assertEqual(self._create_plan().status_code, 200)
        self.assertEqual(self._create_plan().status_code, 409)

    def test_catalog_writes_are_refused_to_a_tenant_admin(self):
        self.acting_user = self.admin

        self.assertEqual(self._create_plan().status_code, 403)
        self.assertEqual(
            self.client.put(
                "/api/platform/plans/starter",
                json={"name": "Nope", "reason": "attempt", "confirm": True},
            ).status_code,
            403,
        )


class SettingsTests(PlatformConsoleTestCase):
    def test_the_allowlist_exposes_only_display_keys(self):
        response = self.client.get("/api/platform/settings")

        self.assertEqual(response.status_code, 200)
        keys = {item["key"] for item in response.json()["settings"]}
        self.assertEqual(
            keys, {"public_status_message", "support_contact_email"}
        )

    def test_unknown_keys_are_rejected(self):
        response = self.client.put(
            "/api/platform/settings/secret_key",
            json={"value": "x", "reason": "attempt"},
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_values_are_rejected(self):
        invalid_email = self.client.put(
            "/api/platform/settings/support_contact_email",
            json={"value": "not-an-email", "reason": "support"},
        )
        too_long = self.client.put(
            "/api/platform/settings/public_status_message",
            json={"value": "x" * 281, "reason": "notice"},
        )
        self.assertEqual(invalid_email.status_code, 400)
        self.assertEqual(too_long.status_code, 400)

    def test_preview_writes_nothing_and_audits_nothing(self):
        response = self.client.post(
            "/api/platform/settings/public_status_message/preview",
            json={"value": "Planned maintenance Sunday"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        self.assertEqual(
            self.db.query(models.PlatformSetting).count(), 0
        )
        self.assertEqual(self._audit("platform.setting.update"), [])

    def test_an_accepted_change_is_audited_and_public(self):
        response = self.client.put(
            "/api/platform/settings/public_status_message",
            json={
                "value": "Read-only mode tonight",
                "reason": "maintenance window",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["is_override"])
        self.assertEqual(
            self.public_client.get("/api/public/config").json()["status_message"],
            "Read-only mode tonight",
        )
        audit = self._audit("platform.setting.update")
        self.assertEqual(audit[-1].actor_user_id, self.owner.id)
        self.assertEqual(audit[-1].detail["reason"], "maintenance window")
        self.assertEqual(audit[-1].detail["value"], "Read-only mode tonight")

    def test_settings_writes_are_refused_to_a_tenant_admin(self):
        self.acting_user = self.admin

        response = self.client.put(
            "/api/platform/settings/public_status_message",
            json={"value": "x", "reason": "attempt"},
        )

        self.assertEqual(response.status_code, 403)


class BoundaryTests(PlatformConsoleTestCase):
    def _route_has_owner_dependency(self, route):
        seen = set()

        def walk(dependant):
            for dependency in dependant.dependencies:
                if dependency.call is require_platform_owner:
                    return True
                if id(dependency) not in seen:
                    seen.add(id(dependency))
                    if walk(dependency):
                        return True
            return False

        return walk(route.dependant)

    def test_every_platform_route_requires_an_owner_grant(self):
        for route in platform_api.router.routes:
            if getattr(route, "path", "").startswith("/api/platform"):
                with self.subTest(path=route.path):
                    self.assertTrue(self._route_has_owner_dependency(route))

    def test_anonymous_callers_are_refused(self):
        self.assertEqual(
            self.anon_client.get("/api/platform/overview").status_code, 401
        )

    def test_the_audit_trail_is_read_only_over_http(self):
        self.assertEqual(
            self.client.put("/api/platform/audit", json={}).status_code, 405
        )
        self.assertEqual(
            self.client.delete("/api/platform/audit").status_code, 405
        )

    def test_no_route_can_mint_an_owner_grant(self):
        for route in platform_api.router.routes:
            path = getattr(route, "path", "").lower()
            self.assertNotIn("grant", path)
            self.assertNotIn("revoke", path)
            self.assertNotIn("impersonat", path)


if __name__ == "__main__":
    unittest.main()
