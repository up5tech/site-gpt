"""The server-owned plan catalog and its public endpoint (V5-11).

`GET /api/plans` is unauthenticated and read-only; these tests pin the three
things that make it safe: an empty catalog is a valid state (nothing is guessed
before V5-01 approval), an unpublished or half-filled plan never reaches the
public, and the public payload carries no Stripe configuration.
"""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import plan as plan_api
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db
from site_gpt.app.services import plan_catalog

PUBLIC_KEYS = {
    "code",
    "name",
    "description",
    "price_minor",
    "currency",
    "interval",
    "features",
    "limits",
    "self_serve_checkout",
}


def make_plan(**overrides) -> plan_catalog.Plan:
    values = dict(
        code="starter",
        name="Starter",
        description="For one website.",
        price_minor=2900,
        currency="usd",
        interval="month",
        features=("One website",),
        limits={"websites": 1},
        self_serve_checkout=True,
        published=True,
    )
    values.update(overrides)
    return plan_catalog.Plan(**values)


class PlanCatalogTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.CatalogPlan.__table__,
                models.PlanPrice.__table__,
            ],
        )
        self.db = sessionmaker(bind=self.engine)()
        app = FastAPI()
        app.include_router(plan_api.router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_default_catalog_is_empty(self):
        self.assertEqual(plan_catalog.PLANS, ())
        self.assertEqual(plan_catalog.published_plans(), ())

    def test_endpoint_is_anonymous_and_empty_by_default(self):
        response = self.client.get("/api/plans")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"plans": []})

    def test_published_plan_is_listed(self):
        with patch.object(plan_catalog, "PLANS", (make_plan(),)):
            response = self.client.get("/api/plans")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "plans": [
                    {
                        "code": "starter",
                        "name": "Starter",
                        "description": "For one website.",
                        "price_minor": 2900,
                        "currency": "USD",
                        "interval": "month",
                        "features": ["One website"],
                        "limits": [{"key": "websites", "value": 1}],
                        "self_serve_checkout": True,
                    }
                ]
            },
        )

    def test_unpublished_plan_is_not_public(self):
        hidden = make_plan(code="secret", published=False)
        with patch.object(plan_catalog, "PLANS", (hidden,)):
            self.assertEqual(self.client.get("/api/plans").json(), {"plans": []})

    def test_invalid_plans_are_filtered_rather_than_rendered(self):
        broken = [
            make_plan(code="  "),
            make_plan(name=" "),
            make_plan(price_minor=-1),
            make_plan(interval="week"),
            make_plan(currency="us"),
            make_plan(currency=""),
            make_plan(limits={"websites": -1}),
        ]
        with patch.object(plan_catalog, "PLANS", tuple(broken)):
            self.assertEqual(self.client.get("/api/plans").json(), {"plans": []})

    def test_public_payload_exposes_no_stripe_configuration(self):
        with patch.object(plan_catalog, "PLANS", (make_plan(),)):
            plan = self.client.get("/api/plans").json()["plans"][0]
        self.assertEqual(set(plan), PUBLIC_KEYS)
        # The same guarantee for the service-level mapping the route uses.
        self.assertEqual(set(plan_catalog.public_payload(make_plan())), PUBLIC_KEYS)

    def test_find_plan_matches_case_insensitively_and_ignores_unpublished(self):
        with patch.object(
            plan_catalog,
            "PLANS",
            (make_plan(), make_plan(code="growth", published=False)),
        ):
            self.assertIsNotNone(plan_catalog.find_plan(" STARTER "))
            self.assertIsNone(plan_catalog.find_plan("growth"))
            self.assertIsNone(plan_catalog.find_plan("unknown"))
            self.assertIsNone(plan_catalog.find_plan(""))
            self.assertIsNone(plan_catalog.find_plan(None))


class DurableCatalogTests(PlanCatalogTests):
    """V5-42: once an owner publishes a durable row, it is authoritative."""

    def _published_plan(self, code="starter", **overrides):
        row = plan_catalog.create_plan(
            self.db,
            code=code,
            name="Starter",
            description="One website.",
            features=["One website"],
            limits={"websites": 1},
            currency="usd",
            price_minor=2900,
            **overrides,
        )
        plan_catalog.publish_plan(self.db, code)
        return row

    def test_a_published_durable_plan_is_public_without_stripe_ids(self):
        self._published_plan()

        response = self.client.get("/api/plans")

        self.assertEqual(response.status_code, 200)
        plan = response.json()["plans"][0]
        self.assertEqual(plan["code"], "starter")
        self.assertEqual(set(plan), PUBLIC_KEYS)

    def test_a_draft_never_replaces_the_static_fallback_silently(self):
        plan_catalog.create_plan(
            self.db,
            code="draft",
            name="Draft",
            currency="usd",
            price_minor=100,
        )

        self.assertEqual(self.client.get("/api/plans").json(), {"plans": []})

    def test_publishing_requires_an_active_price(self):
        plan_catalog.create_plan(
            self.db,
            code="starter",
            name="Starter",
            currency="usd",
            price_minor=2900,
        )
        row = plan_catalog.get_plan(self.db, "starter")
        for price in row.prices:
            price.active = False
        self.db.commit()

        with self.assertRaises(plan_catalog.CatalogError):
            plan_catalog.publish_plan(self.db, "starter")


if __name__ == "__main__":
    unittest.main()
