import unittest

from fastapi.testclient import TestClient

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
}


def _with(**overrides):
    values = dict(VALID_PRODUCTION)
    values.update(overrides)
    return values


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
        # The current process is not production, so the defaults keep docs on.
        self.assertTrue(config.DOCS_ENABLED)
        self.assertEqual(app.docs_url, "/docs")
        self.assertEqual(app.redoc_url, "/redoc")
        self.assertEqual(app.openapi_url, "/openapi.json")

    def test_development_startup_needs_no_production_configuration(self):
        with TestClient(app):
            pass


if __name__ == "__main__":
    unittest.main()
