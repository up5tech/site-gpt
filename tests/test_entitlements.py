"""Plan entitlements and their enforcement boundaries (V5 F3, V5-30/V5-31).

What is pinned here:

* the resolution table — billing off, no subscription, every Stripe status, an
  unpublished or unknown plan, and a plan whose limits are unusable;
* that a missing/stale subscription can only fall back to the V4 ceilings, never
  to a higher plan and never to a guessed free tier;
* `effective` is the stricter of the company's setting and the plan ceiling, so
  a plan can neither raise a deliberate cap nor disappear behind `0`;
* the two count boundaries (`POST /api/websites`, `POST /api/companies/users`)
  allow below the ceiling and refuse at it with a 403;
* every chat handler routes both caps through the resolver, which is the only
  way `/api/v1` cannot bypass them.

These are service/API tests against a real SQLite database; Stripe is never
called (the resolver reads only the mirrored row).
"""

import asyncio
import inspect
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import company as company_api
from site_gpt.app.api import routes as widget_routes
from site_gpt.app.api import v1 as v1_routes
from site_gpt.app.api import website as website_api
from site_gpt.app.core import config
from site_gpt.app.core.auth import get_manager_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.chat import ChatRequest
from site_gpt.app.services import entitlements, plan_catalog

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.Subscription.__table__,
    models.CatalogPlan.__table__,
    models.PlanPrice.__table__,
]

STARTER = plan_catalog.Plan(
    code="starter",
    name="Starter",
    description="One website.",
    price_minor=2900,
    currency="usd",
    interval="month",
    features=("One website",),
    limits={"websites": 1, "seats": 2, "daily_messages": 500},
    published=True,
)


def _find_route(router, method, path):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in (
            getattr(route, "methods", None) or set()
        ):
            return route
    raise AssertionError(f"route {method} {path} not found")


class EntitlementTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.db.add(self.company)
        self.db.commit()

        self.admin = self._user("admin@acme.test", "admin")
        self.member = self._user("member@acme.test", "user")

        for name, value in (("BILLING_ENABLED", True),):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        plans = patch.object(plan_catalog, "PLANS", (STARTER,))
        plans.start()
        self.addCleanup(plans.stop)

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

    def _website(self, name="Site", url="https://acme.test"):
        row = models.Website(
            name=name,
            url=url,
            site_map_url="",
            company_id=self.company.id,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _subscription(self, status="active", plan_code="starter", limits=None):
        row = models.Subscription(
            company_id=self.company.id,
            plan_code=plan_code,
            interval="month",
            status=status,
            stripe_customer_id="cus_test",
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _snapshot(self):
        return entitlements.resolve(self.db, self.company.id)


class ResolutionTests(EntitlementTestBase):
    def test_billing_off_enforces_nothing_and_reads_nothing(self):
        self._subscription(status="active")

        with patch.object(config, "BILLING_ENABLED", False):
            with patch.object(
                entitlements.billing,
                "company_subscription",
                side_effect=AssertionError("billing off must not read a row"),
            ):
                snapshot = self._snapshot()

        self.assertFalse(snapshot.billing_enabled)
        self.assertFalse(snapshot.enforced)
        self.assertEqual(dict(snapshot.limits), {})
        self.assertEqual(entitlements.effective(1000, snapshot.limit("websites")), 1000)

    def test_no_subscription_grants_no_limits(self):
        snapshot = self._snapshot()

        self.assertTrue(snapshot.billing_enabled)
        self.assertFalse(snapshot.enforced)
        self.assertIsNone(snapshot.plan_code)
        self.assertEqual(dict(snapshot.limits), {})

    def test_active_and_trialing_grant_the_published_plan(self):
        row = self._subscription(status="active")
        snapshot = self._snapshot()
        self.assertTrue(snapshot.enforced)
        self.assertEqual(snapshot.plan_code, "starter")
        self.assertEqual(snapshot.limit("websites"), 1)
        self.assertEqual(snapshot.limit("seats"), 2)
        self.assertEqual(snapshot.limit("daily_messages"), 500)

        row.status = "trialing"
        self.db.commit()
        self.assertTrue(self._snapshot().enforced)

    def test_every_other_status_grants_nothing(self):
        row = self._subscription(status="incomplete")
        for status in ("incomplete", "past_due", "unpaid", "paused", "canceled"):
            row.status = status
            self.db.commit()
            snapshot = self._snapshot()
            self.assertFalse(snapshot.enforced, status)
            self.assertEqual(dict(snapshot.limits), {}, status)
            self.assertEqual(snapshot.status, status)

    def test_an_unpublished_plan_stops_granting_its_limits(self):
        self._subscription(status="active")
        withdrawn = plan_catalog.Plan(
            code="starter",
            name="Starter",
            description="Withdrawn.",
            price_minor=2900,
            currency="usd",
            interval="month",
            limits={"websites": 5, "seats": 5},
            published=False,
        )
        with patch.object(plan_catalog, "PLANS", (withdrawn,)):
            snapshot = self._snapshot()

        self.assertFalse(snapshot.enforced)
        self.assertEqual(dict(snapshot.limits), {})

    def test_an_unknown_plan_code_grants_nothing(self):
        self._subscription(status="active", plan_code="ghost")

        snapshot = self._snapshot()

        self.assertFalse(snapshot.enforced)
        self.assertIsNone(snapshot.plan_code)

    def test_unknown_and_non_positive_limits_are_ignored(self):
        plan = plan_catalog.Plan(
            code="starter",
            name="Starter",
            description="Odd limits.",
            price_minor=0,
            currency="usd",
            interval="month",
            limits={
                "websites": 3,
                "seats": 0,  # not a ceiling: 0 is indistinguishable from unset
                "glitter": 99,  # display copy, not enforced
            },
            published=True,
        )
        self._subscription(status="active")
        with patch.object(plan_catalog, "PLANS", (plan,)):
            snapshot = self._snapshot()

        self.assertTrue(snapshot.enforced)
        self.assertEqual(dict(snapshot.limits), {"websites": 3})


class EffectiveLimitTests(unittest.TestCase):
    def test_the_stricter_of_setting_and_plan_wins(self):
        self.assertEqual(entitlements.effective(50, 1000), 50)
        self.assertEqual(entitlements.effective(1000, 50), 50)
        self.assertEqual(entitlements.effective(50, 50), 50)

    def test_an_uncapped_setting_becomes_the_plan_ceiling_not_infinity(self):
        self.assertEqual(entitlements.effective(0, 200), 200)
        self.assertEqual(entitlements.effective(-1, 200), 200)

    def test_no_plan_limit_leaves_the_setting_untouched(self):
        self.assertEqual(entitlements.effective(0, None), 0)
        self.assertEqual(entitlements.effective(1234, None), 1234)
        self.assertEqual(entitlements.effective(1234, 0), 1234)

    def test_a_plan_never_raises_a_configured_cap(self):
        for configured in (1, 7, 1000):
            for plan_limit in (None, 0, 1, 7, 1000):
                self.assertLessEqual(
                    entitlements.effective(configured, plan_limit),
                    configured,
                )


class UsageTests(EntitlementTestBase):
    def test_usage_counts_resources_and_reports_the_ceiling(self):
        self._subscription(status="active")
        self._website()

        payload = entitlements.usage(self.db, self.company.id)

        self.assertEqual(payload["plan_code"], "starter")
        self.assertTrue(payload["enforced"])
        self.assertEqual(
            payload["websites"], {"key": "websites", "used": 1, "limit": 1}
        )
        self.assertEqual(payload["seats"], {"key": "seats", "used": 2, "limit": 2})

    def test_usage_counts_only_users_that_hold_a_seat(self):
        self._subscription(status="active")
        self.member.status = "inactive"
        self.db.commit()

        payload = entitlements.usage(self.db, self.company.id)

        self.assertEqual(payload["seats"], {"key": "seats", "used": 1, "limit": 2})

    def test_usage_without_a_granted_plan_has_no_ceiling(self):
        self._website()

        payload = entitlements.usage(self.db, self.company.id)

        self.assertFalse(payload["enforced"])
        self.assertIsNone(payload["websites"]["limit"])
        self.assertIsNone(payload["seats"]["limit"])
        self.assertEqual(payload["websites"]["used"], 1)


class SiteAndSeatBoundaryTests(EntitlementTestBase):
    def setUp(self):
        super().setUp()
        self.app = FastAPI()
        self.app.include_router(website_api.router, prefix="/api/websites")
        self.app.include_router(company_api.router, prefix="/api/companies")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_manager_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def _create_website(self, name="Second"):
        return self.client.post(
            "/api/websites/",
            json={
                "name": name,
                "url": "https://second.test",
                "site_map_url": "",
                "description": "",
                "status": "active",
            },
        )

    def _create_user(self, email="third@acme.test"):
        return self.client.post(
            "/api/companies/users",
            json={
                "email": email,
                "password": "secret123",
                "first_name": "Third",
                "last_name": "User",
                "role": "user",
            },
        )

    def test_a_website_below_the_ceiling_is_created(self):
        self._subscription(status="active")  # websites: 1, none used yet

        response = self._create_website()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Second")

    def test_a_website_at_the_ceiling_is_refused(self):
        self._subscription(status="active")
        self._website()

        response = self._create_website()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Your plan's limit for websites is 1.")
        self.assertEqual(
            self.db.query(models.Website)
            .filter(models.Website.company_id == self.company.id)
            .count(),
            1,
        )

    def test_a_seat_at_the_ceiling_is_refused(self):
        self._subscription(status="active")  # seats: 2; admin + member already

        response = self._create_user()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"], "Your plan's limit for team members is 2."
        )

    def test_a_deactivated_user_frees_its_seat(self):
        self._subscription(status="active")  # seats: 2; admin + member active
        self.member.status = "inactive"
        self.db.commit()

        response = self._create_user()

        # One active user before the insert, so the ceiling is not reached.
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "active")

    def test_a_new_inactive_user_still_cannot_exceed_the_ceiling(self):
        self._subscription(status="active")  # seats: 2; admin + member active

        response = self.client.post(
            "/api/companies/users",
            json={
                "email": "fourth@acme.test",
                "password": "secret123",
                "first_name": "Fourth",
                "last_name": "User",
                "role": "user",
                "status": "inactive",
            },
        )

        # The row would not hold a seat, but the request already fills one, so
        # the ceiling is still the ceiling: at 2 of 2 it is refused.
        self.assertEqual(response.status_code, 403)

    def test_an_unpaid_subscription_leaves_v4_creation_unchanged(self):
        self._subscription(status="past_due")
        self._website()

        self.assertEqual(self._create_website().status_code, 200)
        self.assertEqual(self._create_user().status_code, 200)

    def test_billing_off_ignores_a_leftover_subscription_row(self):
        self._subscription(status="active")
        self._website()

        with patch.object(config, "BILLING_ENABLED", False):
            self.assertEqual(self._create_website().status_code, 200)


class ChatBoundaryTests(unittest.TestCase):
    """Every handler that spends the budget resolves both caps server-side."""

    def _source(self, router, path):
        return inspect.getsource(_find_route(router, "POST", path).endpoint)

    def test_both_caps_go_through_the_resolver_in_every_chat_handler(self):
        for router, path in (
            (widget_routes.router, "/api/chat"),
            (widget_routes.router, "/api/chat/stream"),
            (v1_routes.router, "/chat"),
        ):
            source = self._source(router, path)
            self.assertIn("entitlements.session_message_limit", source, path)
            self.assertIn("entitlements.daily_message_limit", source, path)
            # One resolution per request feeds both caps (no double DB read).
            self.assertEqual(source.count("entitlements.resolve"), 1, path)
            # V4 ordering is unchanged: session cap before the daily quota.
            self.assertLess(
                source.index("entitlements.session_message_limit"),
                source.index("entitlements.daily_message_limit"),
                path,
            )


class ChatSnapshotTests(EntitlementTestBase):
    """One snapshot per chat message, proved by driving the handlers (V5-31).

    `ChatBoundaryTests` only pins the call shape in source. These cases run the
    real handlers against a real subscription row, so a second resolution shows
    up as a second subscription read, and the limits handed to the session cap
    and the daily quota are checked against the plan's own numbers (2 and 5, so
    a mixed-up key or a duplicated read cannot pass).
    """

    PLAN = plan_catalog.Plan(
        code="starter",
        name="Starter",
        description="Chat ceilings.",
        price_minor=2900,
        currency="usd",
        interval="month",
        limits={"session_messages": 2, "daily_messages": 5},
        published=True,
    )

    def setUp(self):
        super().setUp()
        # The handlers read the company's own caps too; no row means the env
        # default (`0` for the session cap, 1000 daily), so the plan decides.
        Base.metadata.create_all(self.engine, tables=[models.Setting.__table__])
        self.site = self._website()
        self._subscription(status="active")
        plans = patch.object(plan_catalog, "PLANS", (self.PLAN,))
        plans.start()
        self.addCleanup(plans.stop)
        self.body = ChatRequest(
            website_id=self.site.id,
            session_id="s-1",
            question="What do you sell?",
        )
        self.request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/chat",
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
                "scheme": "http",
            }
        )
        self.api_key = models.ApiKey(
            company_id=self.company.id,
            name="snapshot-test",
            key_prefix="sk_test",
            scopes=json.dumps(["chat:write"]),
        )

    def _drive(self, module, call):
        """Run one handler and report the reads and the caps it passed."""
        session_limits: list[int] = []
        daily_limits: list[int] = []

        async def session_cap(website_id, session_id, *, limit):
            session_limits.append(limit)
            return True

        async def daily_quota(website_id, *, limit):
            daily_limits.append(limit)
            return True

        reads: list = []
        real_subscription = entitlements.billing.company_subscription

        def counted(db, company_id):
            reads.append(company_id)
            return real_subscription(db, company_id)

        with patch.object(
            entitlements.billing, "company_subscription", side_effect=counted
        ), patch.object(
            module, "consume_session_message", new=session_cap
        ), patch.object(module, "consume_message", new=daily_quota):
            result = call()

        return reads, session_limits, daily_limits, result

    def test_widget_chat_reads_the_subscription_once_and_uses_its_ceilings(self):
        with patch.object(
            widget_routes, "human_handling", return_value=False
        ), patch.object(
            widget_routes,
            "ask",
            return_value={"answer": "hi", "sources": []},
        ):
            reads, session_limits, daily_limits, result = self._drive(
                widget_routes,
                lambda: asyncio.run(
                    widget_routes.chat(self.body, self.request, self.db, None)
                ),
            )

        # One message, one subscription read — not one per cap helper.
        self.assertEqual(reads, [self.company.id])
        self.assertEqual(session_limits, [2])
        self.assertEqual(daily_limits, [5])
        self.assertEqual(result["answer"], "hi")

    def test_stream_chat_reads_the_subscription_once_and_uses_its_ceilings(self):
        with patch.object(
            widget_routes, "human_handling", return_value=False
        ), patch.object(widget_routes, "ask_stream", return_value=iter(())):
            reads, session_limits, daily_limits, response = self._drive(
                widget_routes,
                lambda: asyncio.run(
                    widget_routes.chat_stream(self.body, self.request, self.db, None)
                ),
            )

        self.assertEqual(reads, [self.company.id])
        self.assertEqual(session_limits, [2])
        self.assertEqual(daily_limits, [5])
        self.assertEqual(response.media_type, "text/event-stream")

    def test_v1_chat_reads_the_subscription_once_and_uses_its_ceilings(self):
        with patch.object(
            v1_routes,
            "ask",
            return_value={"answer": "hi", "sources": [], "message_id": None},
        ):
            reads, session_limits, daily_limits, result = self._drive(
                v1_routes,
                lambda: asyncio.run(
                    v1_routes.chat_v1(self.body, self.db, self.api_key)
                ),
            )

        self.assertEqual(reads, [self.company.id])
        self.assertEqual(session_limits, [2])
        self.assertEqual(daily_limits, [5])
        self.assertEqual(result["answer"], "hi")


class PlanLimitErrorTests(unittest.TestCase):
    def test_the_refusal_names_the_ceiling_not_the_plan(self):
        error = entitlements.PlanLimitError("seats", 3)

        self.assertEqual(error.key, "seats")
        self.assertEqual(error.limit, 3)
        self.assertEqual(error.detail, "Your plan's limit for team members is 3.")


if __name__ == "__main__":
    unittest.main()
