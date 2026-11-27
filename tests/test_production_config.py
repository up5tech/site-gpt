import unittest
from unittest import mock

from fastapi.testclient import TestClient

from site_gpt.app import main as main_module
from site_gpt.app.core import config
from site_gpt.app.main import app

VALID_PRODUCTION = {
    "JWT_SECRET_KEY": "4f3c" * 16,
    "CORS_ORIGINS": "https://app.example.com",
    "SQL_ECHO": False,
    "RATE_LIMIT_BACKEND": "redis",
    "API_KEY_PEPPER": "pepper-value",
    "INTEGRATION_WEBHOOK_SECRET": "webhook-secret-value",
    "TRUSTED_PROXY_IPS": ("203.0.113.10",),
    "DOCS_ENABLED": False,
    "PLATFORM_CONSOLE_ENABLED": False,
}


def _with(**overrides):
    values = dict(VALID_PRODUCTION)
    values.update(overrides)
    return values


class OpsStatusTokenTests(unittest.TestCase):
    """An unset ops token is a 404 by design, not a production boot failure."""

    def test_only_a_production_boot_without_the_token_is_flagged(self):
        self.assertTrue(
            config.ops_status_disabled_in_production(env="production", token="")
        )
        self.assertTrue(
            config.ops_status_disabled_in_production(env="prod", token="   ")
        )
        self.assertFalse(
            config.ops_status_disabled_in_production(env="production", token="s3cret")
        )
        self.assertFalse(
            config.ops_status_disabled_in_production(env="development", token="")
        )

    def test_the_validator_does_not_require_it(self):
        # The route is fail-closed by absence. Refusing to boot would take a
        # working API offline over a monitoring gap, not an exposure.
        self.assertEqual(config.production_config_errors(_with()), [])
        self.assertNotIn("OPS_STATUS_TOKEN", config.production_config_errors(_with()))

    def test_a_production_boot_warns_once_and_still_serves(self):
        with mock.patch.object(
            main_module, "ops_status_disabled_in_production", return_value=True
        ):
            with self.assertLogs("site_gpt.app", level="WARNING") as captured:
                with TestClient(app) as client:
                    response = client.get("/api/ops/status")

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            "config.ops_status_disabled",
            [record.getMessage() for record in captured.records],
        )


class ProductionConfigTests(unittest.TestCase):
    def test_development_defaults_need_no_production_secrets(self):
        defaults = {
            "JWT_SECRET_KEY": config.DEV_JWT_SECRET,
            "CORS_ORIGINS": "*",
            "SQL_ECHO": False,
            "RATE_LIMIT_BACKEND": "memory",
            "API_KEY_PEPPER": "",
            "INTEGRATION_WEBHOOK_SECRET": None,
            "TRUSTED_PROXY_IPS": (),
            "DOCS_ENABLED": True,
        }
        for env in ("development", "test", "local"):
            with self.subTest(env=env):
                config.ensure_production_config(env=env, values=defaults)

    def test_production_defaults_fail_with_setting_names(self):
        self.assertEqual(
            config.production_config_errors(
                {
                    "JWT_SECRET_KEY": config.DEV_JWT_SECRET,
                    "CORS_ORIGINS": "*",
                    "SQL_ECHO": False,
                    "RATE_LIMIT_BACKEND": "memory",
                    "API_KEY_PEPPER": "",
                    "INTEGRATION_WEBHOOK_SECRET": None,
                    "TRUSTED_PROXY_IPS": (),
                    "DOCS_ENABLED": True,
                }
            ),
            [
                "JWT_SECRET_KEY",
                "CORS_ORIGINS",
                "RATE_LIMIT_BACKEND",
                "API_KEY_PEPPER",
                "INTEGRATION_WEBHOOK_SECRET",
                "TRUSTED_PROXY_IPS",
                "DOCS_ENABLED",
            ],
        )

    def test_complete_production_profile_is_accepted(self):
        self.assertEqual(config.production_config_errors(VALID_PRODUCTION), [])

    def test_cors_must_be_an_exact_origin_list(self):
        for origins in (
            "",
            "*",
            "https://app.example.com,*",
            "app.example.com",
            "ftp://app.example.com",
            "https://app.example.com/app",
        ):
            with self.subTest(origins=origins):
                self.assertIn(
                    "CORS_ORIGINS",
                    config.production_config_errors(
                        _with(CORS_ORIGINS=origins)
                    ),
                )

    def test_sql_echo_must_be_off(self):
        for value in (True, "true", "1"):
            with self.subTest(value=value):
                self.assertIn(
                    "SQL_ECHO",
                    config.production_config_errors(_with(SQL_ECHO=value)),
                )

    def test_webhook_secret_is_required_even_without_tenant_integrations(self):
        # There is no enablement flag to gate on: /api/integrations is always
        # mounted and any tenant admin can enable a webhook after boot, so the
        # secret cannot depend on rows that may appear later. "when
        # integrations are enabled" therefore means "whenever production is on".
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertEqual(
                    config.production_config_errors(
                        _with(INTEGRATION_WEBHOOK_SECRET=value)
                    ),
                    ["INTEGRATION_WEBHOOK_SECRET"],
                )

    def test_rate_limit_backend_must_be_shared(self):
        self.assertIn(
            "RATE_LIMIT_BACKEND",
            config.production_config_errors(_with(RATE_LIMIT_BACKEND="memory")),
        )

    def test_docs_must_be_hidden(self):
        self.assertIn(
            "DOCS_ENABLED",
            config.production_config_errors(_with(DOCS_ENABLED=True)),
        )

    def test_trusted_proxies_must_be_valid_networks(self):
        for proxies in ((), "", "not-an-ip", ("203.0.113.10", "bad")):
            with self.subTest(proxies=proxies):
                self.assertIn(
                    "TRUSTED_PROXY_IPS",
                    config.production_config_errors(
                        _with(TRUSTED_PROXY_IPS=proxies)
                    ),
                )
        self.assertEqual(
            config.production_config_errors(
                _with(TRUSTED_PROXY_IPS="203.0.113.0/24,10.0.0.5")
            ),
            [],
        )

    def test_startup_error_names_settings_without_values(self):
        with self.assertRaises(RuntimeError) as raised:
            config.ensure_production_config(env="production", values={})

        message = str(raised.exception)
        for name in (
            "JWT_SECRET_KEY",
            "CORS_ORIGINS",
            "SQL_ECHO",
            "RATE_LIMIT_BACKEND",
            "API_KEY_PEPPER",
            "INTEGRATION_WEBHOOK_SECRET",
            "TRUSTED_PROXY_IPS",
            "DOCS_ENABLED",
        ):
            self.assertIn(name, message)
        self.assertNotIn("pepper-value", message)
        self.assertNotIn("webhook-secret-value", message)

    def test_production_startup_accepts_a_valid_profile(self):
        config.ensure_production_config(
            env="production", values=VALID_PRODUCTION
        )

    def test_docs_surface_follows_the_flag(self):
        # `main.py` reads DOCS_ENABLED when it is imported, so compare the app
        # against the value this process actually loaded instead of assuming a
        # developer's .env leaves docs on.
        self.assertEqual(app.docs_url, "/docs" if config.DOCS_ENABLED else None)
        self.assertEqual(app.redoc_url, "/redoc" if config.DOCS_ENABLED else None)
        self.assertEqual(
            app.openapi_url, "/openapi.json" if config.DOCS_ENABLED else None
        )

    def test_production_requires_hidden_docs_and_accepts_them(self):
        self.assertIn(
            "DOCS_ENABLED",
            config.production_config_errors(_with(DOCS_ENABLED=True)),
        )
        self.assertNotIn(
            "DOCS_ENABLED",
            config.production_config_errors(_with(DOCS_ENABLED=False)),
        )

    def test_platform_console_needs_the_operator_allowlist(self):
        # V6-11 / D5 (reopened 2026-11-27): the console may be on in production
        # only behind the approved control — an operator network allowlist
        # enforced on every /api/platform request. A tenant JWT plus a grant is
        # not a control, and neither is "everyone".
        for value in (True, "true", "1", "on"):
            with self.subTest(value=value):
                self.assertEqual(
                    config.production_config_errors(
                        _with(PLATFORM_CONSOLE_ENABLED=value)
                    ),
                    ["OPERATOR_ALLOWED_NETWORKS"],
                )
                self.assertEqual(
                    config.production_config_errors(
                        _with(
                            PLATFORM_CONSOLE_ENABLED=value,
                            OPERATOR_ALLOWED_NETWORKS="",
                        )
                    ),
                    ["OPERATOR_ALLOWED_NETWORKS"],
                )

    def test_platform_console_is_accepted_with_a_real_allowlist(self):
        self.assertEqual(
            config.production_config_errors(
                _with(
                    PLATFORM_CONSOLE_ENABLED=True,
                    OPERATOR_ALLOWED_NETWORKS="10.20.0.0/16,203.0.113.10",
                )
            ),
            [],
        )

    def test_a_blanket_operator_allowlist_is_not_a_control(self):
        for networks in (
            "0.0.0.0/0",
            "::/0",
            "10.0.0.0/8,0.0.0.0/0",
            "not-a-network",
            (),
        ):
            with self.subTest(networks=networks):
                self.assertIn(
                    "OPERATOR_ALLOWED_NETWORKS",
                    config.production_config_errors(
                        _with(
                            PLATFORM_CONSOLE_ENABLED=True,
                            OPERATOR_ALLOWED_NETWORKS=networks,
                        )
                    ),
                )

    def test_platform_console_off_or_absent_is_accepted(self):
        # Absent means the default (off), so a profile written before V6-11 must
        # not start failing.
        for value in (False, "false", "0", None):
            with self.subTest(value=value):
                self.assertEqual(
                    config.production_config_errors(
                        _with(PLATFORM_CONSOLE_ENABLED=value)
                    ),
                    [],
                )

    def test_production_startup_names_the_missing_allowlist(self):
        with self.assertRaises(RuntimeError) as raised:
            config.ensure_production_config(
                env="production", values=_with(PLATFORM_CONSOLE_ENABLED=True)
            )

        self.assertIn("OPERATOR_ALLOWED_NETWORKS", str(raised.exception))

    def test_development_startup_needs_no_production_configuration(self):
        # Pin the profile: an APP_ENV=production shell must not turn this
        # development-path test into a startup failure.
        with mock.patch.object(config, "APP_ENV", "development"):
            with TestClient(app):
                pass


if __name__ == "__main__":
    unittest.main()
