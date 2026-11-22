"""Stripe billing routes and webhook processing (V5 F2, V5-21 … V5-24).

No live Stripe account is involved: the SDK calls are mocked and the events are
plain dicts, but the properties under test are the ones that make paid billing
safe:

* a browser sends only a plan code — the price, customer, mode and return URLs
  are resolved server-side;
* an unknown plan, a contact-sales plan or a plan without a private Stripe Price
  mapping fails closed with no provider call;
* only a signature-verified webhook changes state; the Checkout return URL is
  never read;
* one event id is applied once, and a delayed older event cannot restore a
  state Stripe has moved past; a failed apply rolls its receipt back so the
  Stripe retry is not mistaken for a duplicate;
* another tenant's customer id, or a mismatched metadata company, changes
  nothing;
* with billing off, no route but `status` exists and no Stripe call is made.

These run against a real SQLite database so the uniqueness constraints (one
subscription per company, one receipt per event id) are enforced, not just
declared.
"""

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import billing as billing_api
from site_gpt.app.core import config
from site_gpt.app.core.auth import get_admin_user, get_current_user
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import billing, plan_catalog

TABLES = [
    models.Company.__table__,
    models.User.__table__,
    models.Website.__table__,
    models.Subscription.__table__,
    models.BillingEvent.__table__,
]

PLAN = plan_catalog.Plan(
    code="starter",
    name="Starter",
    description="One website.",
    price_minor=2900,
    currency="usd",
    interval="month",
    features=("One website",),
    limits={"websites": 1},
    self_serve_checkout=True,
    published=True,
)

#: Stripe `created` timestamps are epoch seconds; these are far enough apart to
#: order events without relying on wall-clock time.
FRESH = 1_800_000_000
OLDER = 1_700_000_000


def _moment(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


class BillingTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.db = sessionmaker(bind=self.engine)()

        self.company = models.Company(name="Acme")
        self.other_company = models.Company(name="Other")
        self.db.add_all([self.company, self.other_company])
        self.db.commit()

        self.admin = self._user(self.company, "admin@acme.test", "admin")
        self.other_admin = self._user(self.other_company, "admin@other.test", "admin")
        self.member = self._user(self.company, "member@acme.test", "user")
        self.actor = self.admin

        self.app = FastAPI()
        self.app.include_router(billing_api.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.actor
        self.app.dependency_overrides[get_admin_user] = lambda: self.actor
        self.client = TestClient(self.app)

        # Enabled billing with one configured plan, and no real secret is ever
        # used: every provider call in these tests is mocked.
        for name, value in (
            ("BILLING_ENABLED", True),
            ("STRIPE_SECRET_KEY", "sk_test_example"),
            ("STRIPE_WEBHOOK_SECRET", "whsec_example"),
            ("FRONTEND_URL", "https://app.example.com"),
            ("STRIPE_PRICE_IDS", "starter:month=price_starter_month"),
        ):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        plans = patch.object(plan_catalog, "PLANS", (PLAN,))
        plans.start()
        self.addCleanup(plans.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # -- fixtures ---------------------------------------------------------

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

    def _subscription(
        self,
        company=None,
        customer="cus_1",
        status="active",
        plan_code="starter",
        last_event_at=None,
    ):
        row = models.Subscription(
            company_id=(company or self.company).id,
            plan_code=plan_code,
            interval="month",
            status=status,
            stripe_customer_id=customer,
            last_event_at=last_event_at,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _row(self, company=None):
        self.db.expire_all()
        return billing.company_subscription(
            self.db, (company or self.company).id
        )

    def _receipts(self):
        return self.db.query(models.BillingEvent).count()


class CheckoutTests(BillingTestCase):
    def _start(self, plan_code="starter", **extra):
        customer = SimpleNamespace(id="cus_123")
        session = SimpleNamespace(url="https://checkout.stripe.test/c/session")
        with (
            patch.object(
                billing.stripe.Customer, "create", return_value=customer
            ) as customer_create,
            patch.object(
                billing.stripe.checkout.Session, "create", return_value=session
            ) as session_create,
        ):
            response = self.client.post(
                "/api/billing/checkout", json={"plan_code": plan_code, **extra}
            )
        return response, customer_create, session_create

    def test_checkout_pins_the_server_resolved_plan_customer_and_urls(self):
        response, customer_create, session_create = self._start(
            price_id="price_evil",
            amount=1,
            success_url="https://evil.test/paid",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"url": "https://checkout.stripe.test/c/session"}
        )

        customer_kwargs = customer_create.call_args.kwargs
        self.assertEqual(
            customer_kwargs["metadata"], {"company_id": str(self.company.id)}
        )
        self.assertEqual(
            customer_kwargs["idempotency_key"],
            f"sitegpt-customer-{self.company.id}",
        )

        kwargs = session_create.call_args.kwargs
        self.assertEqual(kwargs["mode"], "subscription")
        self.assertEqual(kwargs["customer"], "cus_123")
        self.assertEqual(
            kwargs["line_items"], [{"price": "price_starter_month", "quantity": 1}]
        )
        self.assertEqual(
            kwargs["success_url"],
            "https://app.example.com/app/billing?checkout=success",
        )
        self.assertEqual(
            kwargs["cancel_url"],
            "https://app.example.com/app/billing?checkout=cancelled",
        )
        self.assertEqual(kwargs["client_reference_id"], str(self.company.id))
        self.assertEqual(
            kwargs["metadata"],
            {
                "company_id": str(self.company.id),
                "plan_code": "starter",
                "plan_interval": "month",
            },
        )
        self.assertEqual(
            kwargs["subscription_data"], {"metadata": kwargs["metadata"]}
        )
        self.assertEqual(
            kwargs["idempotency_key"],
            f"sitegpt-checkout-{self.company.id}-starter-month",
        )
        # A posted amount, URL or Price ID never reaches the provider request.
        rendered = json.dumps(kwargs)
        self.assertNotIn("price_evil", rendered)
        self.assertNotIn("evil.test", rendered)
        self.assertNotIn("amount", kwargs)

        row = self._row()
        self.assertEqual(row.status, "incomplete")
        self.assertEqual(row.plan_code, "starter")
        self.assertEqual(row.interval, "month")
        self.assertEqual(row.stripe_customer_id, "cus_123")

    def test_unknown_plan_is_refused_before_any_provider_call(self):
        response, customer_create, session_create = self._start("growth")

        self.assertEqual(response.status_code, 400)
        customer_create.assert_not_called()
        session_create.assert_not_called()
        self.assertIsNone(self._row())

    def test_plan_without_a_private_price_mapping_fails_closed(self):
        with patch.object(config, "STRIPE_PRICE_IDS", ""):
            response, customer_create, session_create = self._start()

        self.assertEqual(response.status_code, 409)
        customer_create.assert_not_called()
        session_create.assert_not_called()
        self.assertIsNone(self._row())

    def test_contact_sales_plan_cannot_be_bought_self_serve(self):
        contact = plan_catalog.Plan(
            code="enterprise",
            name="Enterprise",
            description="Talk to sales.",
            price_minor=0,
            currency="usd",
            interval="month",
            published=True,
            self_serve_checkout=False,
        )
        with patch.object(plan_catalog, "PLANS", (contact,)):
            response, _, session_create = self._start("enterprise")

        self.assertEqual(response.status_code, 409)
        session_create.assert_not_called()

    def test_existing_customer_is_reused_instead_of_duplicated(self):
        self._subscription(customer="cus_existing")
        customer_create = patch.object(billing.stripe.Customer, "create")
        session_create = patch.object(
            billing.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/c/2"),
        )
        with customer_create as customer_mock, session_create as session_mock:
            response = self.client.post(
                "/api/billing/checkout", json={"plan_code": "starter"}
            )

        self.assertEqual(response.status_code, 200)
        customer_mock.assert_not_called()
        self.assertEqual(session_mock.call_args.kwargs["customer"], "cus_existing")

    def test_switching_plan_updates_the_stored_code_before_checkout(self):
        self._subscription(customer="cus_existing", plan_code="legacy")
        with (
            patch.object(billing.stripe.Customer, "create") as customer_create,
            patch.object(
                billing.stripe.checkout.Session,
                "create",
                return_value=SimpleNamespace(url="https://checkout.stripe.test/c/3"),
            ),
        ):
            response = self.client.post(
                "/api/billing/checkout", json={"plan_code": "starter"}
            )

        self.assertEqual(response.status_code, 200)
        customer_create.assert_not_called()
        self.assertEqual(self._row().plan_code, "starter")

    def test_checkout_belongs_to_the_signed_in_company(self):
        self.actor = self.other_admin
        response, _, _ = self._start()

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self._row(self.other_company))
        self.assertIsNone(self._row(self.company))

    def test_a_member_cannot_start_checkout(self):
        app = FastAPI()
        app.include_router(billing_api.router)
        app.dependency_overrides[get_db] = lambda: self.db

        def forbidden():
            raise HTTPException(status_code=403, detail="Not enough permissions")

        app.dependency_overrides[get_admin_user] = forbidden
        client = TestClient(app)

        response = client.post(
            "/api/billing/checkout", json={"plan_code": "starter"}
        )

        self.assertEqual(response.status_code, 403)


class PortalAndSummaryTests(BillingTestCase):
    def test_a_company_without_a_billing_account_has_no_portal(self):
        response = self.client.post("/api/billing/portal")

        self.assertEqual(response.status_code, 404)

    def test_portal_uses_the_company_customer_and_fixed_return_url(self):
        self._subscription(customer="cus_acme")
        self._subscription(customer="cus_other", company=self.other_company)

        with patch.object(
            billing.stripe.billing_portal.Session,
            "create",
            return_value=SimpleNamespace(url="https://billing.stripe.test/p/1"),
        ) as portal_create:
            response = self.client.post("/api/billing/portal")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"url": "https://billing.stripe.test/p/1"}
        )
        kwargs = portal_create.call_args.kwargs
        self.assertEqual(kwargs["customer"], "cus_acme")
        self.assertEqual(
            kwargs["return_url"], "https://app.example.com/app/billing"
        )

    def test_portal_is_scoped_to_the_signed_in_company(self):
        self._subscription(customer="cus_acme")
        self._subscription(customer="cus_other", company=self.other_company)
        self.actor = self.other_admin

        with patch.object(
            billing.stripe.billing_portal.Session,
            "create",
            return_value=SimpleNamespace(url="https://billing.stripe.test/p/2"),
        ) as portal_create:
            response = self.client.post("/api/billing/portal")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(portal_create.call_args.kwargs["customer"], "cus_other")

    def test_a_member_cannot_open_the_portal(self):
        app = FastAPI()
        app.include_router(billing_api.router)
        app.dependency_overrides[get_db] = lambda: self.db

        def forbidden():
            raise HTTPException(status_code=403, detail="Not enough permissions")

        app.dependency_overrides[get_admin_user] = forbidden

        self.assertEqual(
            TestClient(app).post("/api/billing/portal").status_code, 403
        )

    def test_summary_is_empty_before_checkout(self):
        response = self.client.get("/api/billing/subscription")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "has_billing_account": False,
                "plan_code": None,
                "interval": None,
                "status": None,
                "active": False,
                "cancel_at_period_end": False,
                "current_period_end": None,
            },
        )

    def test_summary_exposes_only_the_mirrored_state(self):
        row = self._subscription(customer="cus_acme", status="active")
        row.current_period_end = _moment(FRESH)
        row.cancel_at_period_end = True
        self.db.commit()

        payload = self.client.get("/api/billing/subscription").json()

        self.assertEqual(
            set(payload),
            {
                "has_billing_account",
                "plan_code",
                "interval",
                "status",
                "active",
                "cancel_at_period_end",
                "current_period_end",
            },
        )
        self.assertTrue(payload["has_billing_account"])
        self.assertEqual(payload["plan_code"], "starter")
        self.assertEqual(payload["status"], "active")
        self.assertTrue(payload["active"])
        self.assertTrue(payload["cancel_at_period_end"])
        self.assertIsNotNone(payload["current_period_end"])
        self.assertNotIn("cus_acme", json.dumps(payload))

    def test_usage_reports_counts_and_the_granted_ceiling(self):
        self._subscription(customer="cus_acme", status="active")
        self.db.add(
            models.Website(
                name="Site",
                url="https://acme.test",
                site_map_url="",
                company_id=self.company.id,
            )
        )
        self.db.commit()

        payload = self.client.get("/api/billing/usage").json()

        self.assertEqual(payload["plan_code"], "starter")
        self.assertTrue(payload["enforced"])
        self.assertEqual(
            payload["websites"], {"key": "websites", "used": 1, "limit": 1}
        )
        # Acme has its admin and its member; the other company's admin is not a
        # seat here.
        self.assertEqual(payload["seats"], {"key": "seats", "used": 2, "limit": None})

    def test_usage_has_no_ceiling_before_a_subscription_is_confirmed(self):
        payload = self.client.get("/api/billing/usage").json()

        self.assertIsNone(payload["plan_code"])
        self.assertFalse(payload["enforced"])
        self.assertIsNone(payload["websites"]["limit"])

    def test_summary_is_scoped_to_the_signed_in_company(self):
        self._subscription(customer="cus_acme", plan_code="starter")
        self._subscription(
            customer="cus_other", company=self.other_company, plan_code="growth"
        )
        self.actor = self.other_admin

        payload = self.client.get("/api/billing/subscription").json()

        self.assertEqual(payload["plan_code"], "growth")


class WebhookTests(BillingTestCase):
    def _event(self, event_id, event_type, obj, created=FRESH):
        return {
            "id": event_id,
            "type": event_type,
            "created": created,
            "data": {"object": obj},
        }

    def _deliver(self, event, signature="t=1,v1=signature", client=None):
        with patch.object(
            billing.stripe.Webhook, "construct_event", return_value=event
        ):
            return (client or self.client).post(
                "/api/billing/webhook",
                content=json.dumps(event),
                headers={"stripe-signature": signature},
            )

    def test_an_invalid_signature_changes_no_rows(self):
        self._subscription(customer="cus_1", status="active")

        with patch.object(
            billing.stripe.Webhook,
            "construct_event",
            side_effect=ValueError("bad signature"),
        ):
            response = self.client.post(
                "/api/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "t=1,v1=bad"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._receipts(), 0)
        self.assertEqual(self._row().status, "active")

    def test_a_missing_signature_header_is_rejected(self):
        response = self.client.post("/api/billing/webhook", content=b"{}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._receipts(), 0)

    def test_checkout_completed_links_the_subscription_and_paid_state(self):
        self._subscription(customer="cus_1", status="incomplete")

        response = self._deliver(
            self._event(
                "evt_checkout",
                "checkout.session.completed",
                {
                    "customer": "cus_1",
                    "subscription": "sub_1",
                    "payment_status": "paid",
                    "metadata": {"company_id": str(self.company.id)},
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        row = self._row()
        self.assertEqual(row.stripe_subscription_id, "sub_1")
        self.assertEqual(row.status, "active")
        self.assertEqual(self._receipts(), 1)

    def test_a_browser_return_alone_grants_nothing(self):
        # No webhook has been delivered: starting Checkout leaves the company
        # `incomplete`, so a `?checkout=success` visit cannot be an entitlement.
        self._subscription(customer="cus_1", status="incomplete")

        payload = self.client.get("/api/billing/subscription").json()

        self.assertFalse(payload["active"])
        self.assertEqual(payload["status"], "incomplete")

    def test_a_duplicate_event_is_acknowledged_and_applied_once(self):
        self._subscription(customer="cus_1", status="incomplete")
        event = self._event(
            "evt_duplicate",
            "customer.subscription.updated",
            {"id": "sub_1", "customer": "cus_1", "status": "active"},
        )

        first = self._deliver(event)
        second = self._deliver(event)

        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["duplicate"])
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(self._receipts(), 1)
        self.assertEqual(self._row().status, "active")

    def test_a_failed_apply_leaves_no_receipt_so_the_retry_applies_once(self):
        # V5-22: a receipt that survived a failed apply would make Stripe's
        # retry look like a duplicate, so the paid state would never land.
        self._subscription(customer="cus_1", status="incomplete")
        event = self._event(
            "evt_retry",
            "customer.subscription.updated",
            {"id": "sub_1", "customer": "cus_1", "status": "active"},
        )

        # The event is verified and receipted, then the apply step fails.
        # Stripe sees 500 and will redeliver the same event id.
        failing = TestClient(self.app, raise_server_exceptions=False)
        with patch.object(
            billing, "_apply", side_effect=RuntimeError("apply failed")
        ):
            failed = self._deliver(event, client=failing)

        self.assertEqual(failed.status_code, 500)
        self.assertEqual(self._receipts(), 0)
        self.assertEqual(self._row().status, "incomplete")

        retried = self._deliver(event)

        self.assertEqual(retried.status_code, 200)
        self.assertFalse(retried.json()["duplicate"])
        self.assertEqual(self._row().status, "active")
        self.assertEqual(self._receipts(), 1)

        # The retry was the apply; a further delivery is the duplicate no-op.
        self.assertTrue(self._deliver(event).json()["duplicate"])
        self.assertEqual(self._receipts(), 1)

    def test_a_delayed_older_event_cannot_restore_stale_state(self):
        self._subscription(
            customer="cus_1", status="active", last_event_at=_moment(FRESH)
        )

        response = self._deliver(
            self._event(
                "evt_stale",
                "customer.subscription.updated",
                {"id": "sub_1", "customer": "cus_1", "status": "past_due"},
                created=OLDER,
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._row().status, "active")

    def test_an_unknown_customer_is_receipted_but_changes_nothing(self):
        self._subscription(customer="cus_1", status="active")

        response = self._deliver(
            self._event(
                "evt_unknown",
                "customer.subscription.updated",
                {"id": "sub_x", "customer": "cus_unknown", "status": "canceled"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._row().status, "active")
        self.assertEqual(self._receipts(), 1)

    def test_metadata_cannot_move_another_tenants_subscription(self):
        self._subscription(customer="cus_1", status="active")

        response = self._deliver(
            self._event(
                "evt_foreign",
                "customer.subscription.updated",
                {
                    "id": "sub_1",
                    "customer": "cus_1",
                    "status": "canceled",
                    "metadata": {"company_id": str(self.other_company.id)},
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._row().status, "active")

    def test_subscription_updated_mirrors_status_period_and_cancellation(self):
        self._subscription(customer="cus_1", status="incomplete")

        response = self._deliver(
            self._event(
                "evt_updated",
                "customer.subscription.updated",
                {
                    "id": "sub_1",
                    "customer": "cus_1",
                    "status": "active",
                    "current_period_start": OLDER,
                    "current_period_end": FRESH,
                    "cancel_at_period_end": True,
                    "metadata": {
                        "company_id": str(self.company.id),
                        "plan_code": "starter",
                        "plan_interval": "year",
                    },
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        row = self._row()
        self.assertEqual(row.status, "active")
        self.assertEqual(row.stripe_subscription_id, "sub_1")
        # SQLite hands back a naive value; the column is timezone-aware in
        # Postgres and the service always stores UTC.
        self.assertEqual(
            row.current_period_end.replace(tzinfo=UTC), _moment(FRESH)
        )
        self.assertTrue(row.cancel_at_period_end)
        self.assertEqual(row.interval, "year")
        self.assertEqual(row.last_event_at.replace(tzinfo=UTC), _moment(FRESH))

    def test_deleted_does_not_get_revived_by_a_later_invoice_paid(self):
        self._subscription(customer="cus_1", status="active")

        self._deliver(
            self._event(
                "evt_deleted",
                "customer.subscription.deleted",
                {"id": "sub_1", "customer": "cus_1", "status": "canceled"},
            )
        )
        row = self._row()
        self.assertEqual(row.status, "canceled")
        self.assertIsNotNone(row.canceled_at)
        self.assertTrue(row.cancel_at_period_end)

        self._deliver(
            self._event(
                "evt_invoice_late",
                "invoice.paid",
                {"customer": "cus_1", "subscription": "sub_1"},
                created=FRESH + 1,
            )
        )

        self.assertEqual(self._row().status, "canceled")

    def test_invoice_payment_failure_marks_past_due(self):
        self._subscription(customer="cus_1", status="active")

        response = self._deliver(
            self._event(
                "evt_failed",
                "invoice.payment_failed",
                {"customer": "cus_1", "subscription": "sub_1"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._row().status, "past_due")

    def test_invoice_paid_activates_a_pending_subscription(self):
        self._subscription(customer="cus_1", status="incomplete")

        self._deliver(
            self._event(
                "evt_paid",
                "invoice.paid",
                {"customer": "cus_1", "subscription": "sub_1"},
            )
        )

        self.assertEqual(self._row().status, "active")

    def test_an_unhandled_event_is_receipted_without_touching_state(self):
        self._subscription(customer="cus_1", status="incomplete")

        response = self._deliver(
            self._event(
                "evt_other",
                "customer.created",
                {"id": "cus_1"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._row().status, "incomplete")
        self.assertEqual(self._receipts(), 1)

    def test_no_raw_event_payload_or_card_data_is_stored(self):
        columns = set(models.BillingEvent.__table__.columns.keys())

        self.assertEqual(
            columns,
            {
                "stripe_event_id",
                "type",
                "stripe_created_at",
                "processed_at",
                "id",
                "created_at",
                "updated_at",
            },
        )

        self._deliver(
            self._event(
                "evt_privacy",
                "customer.subscription.updated",
                {"id": "sub_1", "customer": "cus_1", "status": "active"},
                created=FRESH,
            )
        )
        receipt = self.db.query(models.BillingEvent).one()
        self.assertIsNotNone(receipt.processed_at)
        self.assertNotIn("customer", json.dumps(receipt.stripe_event_id))


class BillingDisabledTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(config, "BILLING_ENABLED", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_reports_off_and_the_rest_of_the_surface_is_404(self):
        self.assertEqual(
            self.client.get("/api/billing/status").json(), {"enabled": False}
        )
        self.assertEqual(
            self.client.get("/api/billing/subscription").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                "/api/billing/checkout", json={"plan_code": "starter"}
            ).status_code,
            404,
        )
        self.assertEqual(self.client.post("/api/billing/portal").status_code, 404)
        self.assertEqual(self.client.get("/api/billing/usage").status_code, 404)
        self.assertEqual(
            self.client.post(
                "/api/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "t=1,v1=x"},
            ).status_code,
            404,
        )

    def test_disabled_billing_makes_no_provider_call(self):
        with (
            patch.object(billing.stripe.Customer, "create") as customer_create,
            patch.object(billing.stripe.checkout.Session, "create") as session_create,
            patch.object(billing.stripe.Webhook, "construct_event") as construct,
        ):
            self.client.post("/api/billing/checkout", json={"plan_code": "starter"})
            self.client.post("/api/billing/portal")
            self.client.post(
                "/api/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "t=1,v1=x"},
            )

        customer_create.assert_not_called()
        session_create.assert_not_called()
        construct.assert_not_called()
        self.assertEqual(self._receipts(), 0)


class PriceMappingTests(unittest.TestCase):
    def test_json_and_comma_forms_resolve_to_the_same_mapping(self):
        expected = {"starter:month": "price_123"}

        self.assertEqual(
            billing.price_ids('{"Starter:Month": "price_123"}'), expected
        )
        self.assertEqual(
            billing.price_ids("starter:month=price_123"), expected
        )

    def test_junk_is_dropped_rather_than_sent_to_stripe(self):
        self.assertEqual(billing.price_ids(""), {})
        self.assertEqual(billing.price_ids("starter:month=29.00"), {})
        self.assertEqual(billing.price_ids("{not json"), {})
        self.assertEqual(billing.price_ids("starter:month="), {})


if __name__ == "__main__":
    unittest.main()
