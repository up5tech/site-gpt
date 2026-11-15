import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from site_gpt.app import models
from site_gpt.app.api.setting import (
    ALL_SETTINGS,
    DEFAULT_SETTINGS,
    WIDGET_PUBLIC_KEYS,
    _default_setting_rows,
    create_settings,
)

APPEARANCE_KEYS = {
    "assistant_name",
    "widget_header_color",
    "widget_footer_color",
    "widget_position",
    "greeting_message",
    "placeholder_text",
    "suggested_questions",
}

# Keys that exist (or will exist) for internal use and must never be public.
INTERNAL_KEYS = {
    "llm_model",
    "llm_provider",
    "handoff_email",
    "digest_recipients",
    "daily_message_limit",
}


class SettingsRegistryTests(unittest.TestCase):
    def test_default_settings_are_exactly_the_appearance_keys(self):
        self.assertEqual(set(DEFAULT_SETTINGS), APPEARANCE_KEYS)

    def test_widget_public_keys_match_default_settings(self):
        self.assertEqual(list(WIDGET_PUBLIC_KEYS), list(DEFAULT_SETTINGS))
        self.assertEqual(set(WIDGET_PUBLIC_KEYS), APPEARANCE_KEYS)

    def test_internal_keys_are_not_public(self):
        for key in INTERNAL_KEYS:
            self.assertNotIn(key, WIDGET_PUBLIC_KEYS)

    def test_default_rows_are_scoped_to_the_company(self):
        company_id = uuid4()
        rows = _default_setting_rows(company_id)
        self.assertEqual(len(rows), len(ALL_SETTINGS))
        self.assertTrue(all(isinstance(row, models.Setting) for row in rows))
        self.assertTrue(all(row.company_id == company_id for row in rows))
        self.assertEqual({row.key: row.value for row in rows}, ALL_SETTINGS)
        # Appearance keys stay a subset: the internal ones are private.
        self.assertTrue(set(DEFAULT_SETTINGS) <= set(ALL_SETTINGS))


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
        self.assertTrue(APPEARANCE_KEYS <= {row.key for row in created})
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
