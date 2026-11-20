import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from site_gpt.app import models
from site_gpt.app.api.setting import (
    ALL_SETTINGS,
    DEFAULT_SETTINGS,
    INTERNAL_SETTINGS,
    WIDGET_PUBLIC_KEYS,
    _default_setting_rows,
    create_settings,
)
from site_gpt.app.core.config import DEFAULT_WIDGET_LANGUAGE, SESSION_MESSAGE_LIMIT

APPEARANCE_KEYS = {
    "assistant_name",
    "widget_header_color",
    "widget_footer_color",
    "widget_position",
    "greeting_message",
    "placeholder_text",
    "suggested_questions",
}

# V2 widget-facing keys (`plans/SPEC.md` §9). Public by decision: they describe
# how the visitor's own widget looks and behaves, never internal state.
PUBLIC_V2_KEYS = {
    "widget_language",
    "widget_ui_strings",
    "widget_logo_url",
    "handoff_enabled",
    "handoff_label",
    "require_consent",
    "privacy_policy_url",
}

# Pinned literal, duplicated here on purpose: the public widget config may only
# change as an explicit product decision, never because a key was added to a
# registry dict. Extend this tuple and `WIDGET_PUBLIC_KEYS` together.
PUBLIC_WIDGET_KEYS = (
    "assistant_name",
    "widget_header_color",
    "widget_footer_color",
    "widget_position",
    "greeting_message",
    "placeholder_text",
    "suggested_questions",
    "widget_language",
    "widget_ui_strings",
    "widget_logo_url",
    "handoff_enabled",
    "handoff_label",
    "require_consent",
    "privacy_policy_url",
)

# Server-side keys. They are seeded like the public ones but must never be
# readable through the public `GET /api/widget-config`.
INTERNAL_KEYS = {
    "daily_message_limit",
    "llm_provider",
    "llm_model",
    "handoff_email",
    "digest_enabled",
    "digest_hour",
    "digest_day",
    "digest_recipients",
    # Retention policy (F9): days of visitor data to keep, "0" = for ever.
    "retention_days",
    # V3-03: F2/F3 feature switches (off by default).
    "topic_clustering_enabled",
    "topic_cluster_count",
    "live_inbox_enabled",
    # V4-02: F4/F2 switches and the per-session cap (off by default).
    "session_message_limit",
    "sitemap_scan_enabled",
    "conversation_insights_enabled",
}


class SettingsRegistryTests(unittest.TestCase):
    def test_default_settings_are_the_public_widget_keys(self):
        self.assertEqual(set(DEFAULT_SETTINGS), APPEARANCE_KEYS | PUBLIC_V2_KEYS)

    def test_public_v2_keys_carry_their_spec_defaults(self):
        self.assertEqual(
            {key: DEFAULT_SETTINGS[key] for key in PUBLIC_V2_KEYS},
            {
                # Seeded from the env default (`auto` unless a deployment sets
                # DEFAULT_WIDGET_LANGUAGE), so the two can never drift.
                "widget_language": DEFAULT_WIDGET_LANGUAGE,
                "widget_ui_strings": "",
                "widget_logo_url": "",
                "handoff_enabled": "false",
                "handoff_label": "Talk to a human",
                "require_consent": "false",
                "privacy_policy_url": "",
            },
        )

    def test_internal_settings_are_exactly_the_internal_keys(self):
        self.assertEqual(set(INTERNAL_SETTINGS), INTERNAL_KEYS)

    def test_v3_internal_defaults_are_off(self):
        # V3-03: every new feature switch must default to V2.1 behaviour.
        self.assertEqual(INTERNAL_SETTINGS["topic_clustering_enabled"], "false")
        self.assertEqual(INTERNAL_SETTINGS["topic_cluster_count"], "5")
        self.assertEqual(INTERNAL_SETTINGS["live_inbox_enabled"], "false")

    def test_live_inbox_is_an_internal_switch_off_by_default(self):
        # V3-44/V3-45: the agent console is opt-in per company; Settings writes
        # it through the admin-only `PUT /api/settings`, and it must never reach
        # the public widget config (the widget has no consent to show a queue).
        self.assertIn("live_inbox_enabled", INTERNAL_SETTINGS)
        self.assertEqual(INTERNAL_SETTINGS["live_inbox_enabled"], "false")
        self.assertNotIn("live_inbox_enabled", WIDGET_PUBLIC_KEYS)
        self.assertNotIn("live_inbox_enabled", DEFAULT_SETTINGS)

    def test_v4_internal_defaults_are_off(self):
        # V4-02: every new switch defaults to the V3 behaviour, and the session
        # cap is seeded from the env default exactly like `daily_message_limit`
        # so the two can never drift.
        self.assertEqual(
            INTERNAL_SETTINGS["session_message_limit"], str(SESSION_MESSAGE_LIMIT)
        )
        self.assertEqual(SESSION_MESSAGE_LIMIT, 0)
        self.assertEqual(INTERNAL_SETTINGS["sitemap_scan_enabled"], "false")
        self.assertEqual(
            INTERNAL_SETTINGS["conversation_insights_enabled"], "false"
        )

    def test_no_v4_key_reaches_the_widget(self):
        # Invariant 8: `WIDGET_PUBLIC_KEYS` stays exactly 14 — no V4 key is
        # widget-facing, so a V3 snippet sees the same response.
        for key in (
            "session_message_limit",
            "sitemap_scan_enabled",
            "conversation_insights_enabled",
        ):
            self.assertIn(key, INTERNAL_SETTINGS)
            self.assertNotIn(key, DEFAULT_SETTINGS)
            self.assertNotIn(key, WIDGET_PUBLIC_KEYS)

    def test_widget_public_keys_are_the_pinned_literal(self):
        # An explicit tuple, not derived from a dict: order is part of the
        # contract the widget receives.
        self.assertIsInstance(WIDGET_PUBLIC_KEYS, tuple)
        self.assertEqual(tuple(WIDGET_PUBLIC_KEYS), PUBLIC_WIDGET_KEYS)
        self.assertEqual(len(WIDGET_PUBLIC_KEYS), 14)

    def test_no_internal_key_is_public(self):
        self.assertFalse(set(INTERNAL_SETTINGS) & set(WIDGET_PUBLIC_KEYS))
        for key in INTERNAL_KEYS:
            self.assertNotIn(key, WIDGET_PUBLIC_KEYS)

    def test_registry_is_the_public_and_internal_keys(self):
        self.assertEqual(
            set(ALL_SETTINGS), APPEARANCE_KEYS | PUBLIC_V2_KEYS | INTERNAL_KEYS
        )
        self.assertTrue(set(WIDGET_PUBLIC_KEYS) <= set(ALL_SETTINGS))

    def test_default_rows_are_scoped_to_the_company(self):
        company_id = uuid4()
        rows = _default_setting_rows(company_id)
        self.assertEqual(len(rows), len(ALL_SETTINGS))
        self.assertTrue(all(isinstance(row, models.Setting) for row in rows))
        self.assertTrue(all(row.company_id == company_id for row in rows))
        self.assertEqual({row.key: row.value for row in rows}, ALL_SETTINGS)
        # Every public key is seeded; the internal ones are seeded but private.
        self.assertTrue(set(WIDGET_PUBLIC_KEYS) <= set(ALL_SETTINGS))


class CreateSettingsIdempotencyTests(unittest.TestCase):
    def _db_with_keys(self, keys):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            (key,) for key in keys
        ]
        return db

    def test_empty_company_gets_all_defaults(self):
        db = self._db_with_keys([])
        result = create_settings(db=db, user=SimpleNamespace(company_id=uuid4()))

        self.assertEqual(result, {"created": len(ALL_SETTINGS), "skipped": 0})
        created = db.add_all.call_args.args[0]
        self.assertEqual({row.key for row in created}, set(ALL_SETTINGS))
        self.assertTrue(set(WIDGET_PUBLIC_KEYS) <= {row.key for row in created})
        db.commit.assert_called_once()

    def test_second_call_creates_nothing(self):
        db = self._db_with_keys(set(ALL_SETTINGS))
        result = create_settings(db=db, user=SimpleNamespace(company_id=uuid4()))

        self.assertEqual(result, {"created": 0, "skipped": len(ALL_SETTINGS)})
        db.add_all.assert_not_called()
        db.commit.assert_not_called()

    def test_partial_company_only_fills_missing_keys(self):
        existing = {"assistant_name", "greeting_message"}
        db = self._db_with_keys(existing)
        result = create_settings(db=db, user=SimpleNamespace(company_id=uuid4()))

        self.assertEqual(
            result, {"created": len(ALL_SETTINGS) - 2, "skipped": 2}
        )
        created = db.add_all.call_args.args[0]
        self.assertEqual({row.key for row in created}, set(ALL_SETTINGS) - existing)


if __name__ == "__main__":
    unittest.main()
