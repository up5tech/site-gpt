"""V6-15 (D13): both token modes stay `compat`, and a production boot says so.

D13 keeps `SESSION_TOKEN_MODE=compat` and `EMBED_TOKEN_MODE=compat` for the
launch cohort, with the legacy tokenless session read (K4) and the embed without
`X-Embed-Token` (K18) recorded as accepted residuals. Flipping either to
`enforce` is a compatibility migration — every live embed must reload the
snippet first — so it is not a boot refusal and must not become one by accident.
What this module pins: which modes a production profile reports, that the report
names settings only, that development stays silent, and that the posture keeps
the production validator clean.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from site_gpt.app import main as main_module
from site_gpt.app.core import config

PRODUCTION_VALUES = {
    "JWT_SECRET_KEY": "x" * 40,
    "CORS_ORIGINS": "https://app.example.com",
    "SQL_ECHO": False,
    "RATE_LIMIT_BACKEND": "redis",
    "API_KEY_PEPPER": "pepper",
    "INTEGRATION_WEBHOOK_SECRET": "secret",
    "TRUSTED_PROXY_IPS": "10.0.0.0/8",
    "DOCS_ENABLED": False,
    "PLATFORM_CONSOLE_ENABLED": False,
}


class CompatModeReportTests(unittest.TestCase):
    def test_development_reports_nothing(self):
        # The posture only matters where real customers are served; a local run
        # does not need a warning it cannot act on.
        self.assertEqual(
            config.compat_token_modes_in_production(
                "development", session_mode="compat", embed_mode="compat"
            ),
            [],
        )

    def test_production_names_both_compat_modes(self):
        self.assertEqual(
            config.compat_token_modes_in_production(
                "production", session_mode="compat", embed_mode="compat"
            ),
            ["SESSION_TOKEN_MODE", "EMBED_TOKEN_MODE"],
        )

    def test_production_is_silent_once_both_are_enforced(self):
        self.assertEqual(
            config.compat_token_modes_in_production(
                "production", session_mode="enforce", embed_mode="enforce"
            ),
            [],
        )

    def test_only_the_mode_still_in_compat_is_named(self):
        self.assertEqual(
            config.compat_token_modes_in_production(
                "production", session_mode="enforce", embed_mode="compat"
            ),
            ["EMBED_TOKEN_MODE"],
        )

    def test_case_and_whitespace_do_not_change_the_answer(self):
        self.assertEqual(
            config.compat_token_modes_in_production(
                " PROD ", session_mode=" Compat ", embed_mode="ENFORCE"
            ),
            ["SESSION_TOKEN_MODE"],
        )

    def test_the_configured_defaults_are_read_when_no_override_is_given(self):
        with (
            patch.object(config, "SESSION_TOKEN_MODE", "compat"),
            patch.object(config, "EMBED_TOKEN_MODE", "enforce"),
        ):
            self.assertEqual(
                config.compat_token_modes_in_production("production"),
                ["SESSION_TOKEN_MODE"],
            )

    def test_the_posture_is_not_a_boot_error(self):
        # compat is the approved state; a boot refusal would take a working
        # deployment offline over a migration it has not done.
        self.assertEqual(config.production_config_errors(PRODUCTION_VALUES), [])

    def test_the_dev_defaults_are_both_compat(self):
        self.assertEqual(config.SESSION_TOKEN_MODE, "compat")
        self.assertEqual(config.EMBED_TOKEN_MODE, "compat")


class BootWarningTests(unittest.TestCase):
    def _run(self, modes):
        async def _scenario():
            async with main_module.lifespan(FastAPI()):
                pass

        log_event = MagicMock()
        with (
            patch.object(
                main_module, "compat_token_modes_in_production", lambda: modes
            ),
            patch.object(main_module, "log_event", log_event),
            patch.object(main_module, "close_client", AsyncMock(return_value=True)),
            patch.object(main_module, "dispose_engine", MagicMock(return_value=True)),
        ):
            asyncio.run(_scenario())
        return log_event

    def test_a_production_boot_logs_the_compat_modes_once(self):
        log_event = self._run(["SESSION_TOKEN_MODE", "EMBED_TOKEN_MODE"])

        calls = [
            call
            for call in log_event.call_args_list
            if call.args and call.args[0] == "config.token_modes_compat"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].kwargs["settings"],
            ["SESSION_TOKEN_MODE", "EMBED_TOKEN_MODE"],
        )
        self.assertEqual(calls[0].kwargs["level"], main_module.logging.WARNING)

    def test_an_enforced_profile_logs_no_such_warning(self):
        log_event = self._run([])

        self.assertNotIn(
            "config.token_modes_compat",
            [call.args[0] for call in log_event.call_args_list if call.args],
        )


if __name__ == "__main__":
    unittest.main()
