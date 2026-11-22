import unittest
from unittest.mock import patch

import stripe
from fastapi.testclient import TestClient

from site_gpt.app.core import config
from site_gpt.app.main import app


class BillingConfigTests(unittest.TestCase):
    def test_billing_is_disabled_by_default(self):
        # Billing is an opt-in backend feature; no Stripe credentials are needed
        # for the existing self-hosted and billing-off paths.
        self.assertFalse(config.BILLING_ENABLED)

    def test_disabled_billing_does_not_require_stripe_credentials(self):
        with (
            patch.object(config, "BILLING_ENABLED", False),
            patch.object(config, "STRIPE_SECRET_KEY", ""),
            patch.object(config, "STRIPE_WEBHOOK_SECRET", ""),
        ):
            config.validate_billing_config()

    def test_enabled_billing_reports_missing_configuration_names_only(self):
        with (
            patch.object(config, "BILLING_ENABLED", True),
            patch.object(config, "STRIPE_SECRET_KEY", ""),
            patch.object(config, "STRIPE_WEBHOOK_SECRET", ""),
            patch.object(config, "STRIPE_API_VERSION", ""),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_API_VERSION",
            ) as raised:
                config.validate_billing_config()

        self.assertNotIn("sk_", str(raised.exception))
        self.assertNotIn("whsec_", str(raised.exception))

    def test_enabled_billing_accepts_complete_configuration(self):
        with (
            patch.object(config, "BILLING_ENABLED", True),
            patch.object(config, "STRIPE_SECRET_KEY", "sk_test_example"),
            patch.object(config, "STRIPE_WEBHOOK_SECRET", "whsec_example"),
            patch.object(config, "STRIPE_API_VERSION", "2026-11-18.endive"),
        ):
            config.validate_billing_config()

    def test_stripe_values_are_backend_only_and_not_published(self):
        self.assertFalse(hasattr(config, "VITE_STRIPE_SECRET_KEY"))
        self.assertFalse(hasattr(config, "VITE_STRIPE_PRICE_ID"))

    def test_configured_api_version_matches_the_pinned_sdk_version(self):
        self.assertEqual(config.STRIPE_API_VERSION, stripe.api_version)

    def test_billing_off_app_startup_needs_no_stripe_secrets(self):
        with (
            patch.object(config, "BILLING_ENABLED", False),
            patch.object(config, "STRIPE_SECRET_KEY", ""),
            patch.object(config, "STRIPE_WEBHOOK_SECRET", ""),
            TestClient(app) as client,
        ):
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)

    def test_billing_on_app_startup_fails_fast_without_secrets(self):
        with (
            patch.object(config, "BILLING_ENABLED", True),
            patch.object(config, "STRIPE_SECRET_KEY", ""),
            patch.object(config, "STRIPE_WEBHOOK_SECRET", ""),
            self.assertRaisesRegex(RuntimeError, "STRIPE_SECRET_KEY"),
        ):
            with TestClient(app):
                self.fail("app startup should refuse incomplete billing config")


if __name__ == "__main__":
    unittest.main()
