"""Unit tests for company API keys (F8/ADR-6).

The stored row must never contain the raw key, and a revoked key must resolve
exactly like an unknown one.
"""

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from site_gpt.app import models
from site_gpt.app.services import api_keys


def _chain(**kwargs):
    """A query chain stub. `all_value=`/`first_value=`/`count_value=` set the
    terminal method's return value."""
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.join.return_value = chain
    chain.order_by.return_value = chain
    for name, value in kwargs.items():
        method = name[: -len("_value")] if name.endswith("_value") else name
        getattr(chain, method).return_value = value
    return chain


class KeyGenerationTests(unittest.TestCase):
    def test_raw_key_has_the_sk_prefix_and_real_entropy(self):
        key = api_keys.generate_api_key()
        self.assertTrue(key.startswith("sk_"))
        self.assertGreaterEqual(len(key), 40)
        self.assertNotEqual(key, api_keys.generate_api_key())

    def test_prefix_is_the_first_twelve_chars(self):
        key = api_keys.generate_api_key()
        self.assertEqual(len(api_keys.key_prefix(key)), 12)
        self.assertEqual(api_keys.key_prefix(key), key[:12])

    def test_hash_is_sha256_hex_of_pepper_plus_key(self):
        with patch.object(api_keys, "API_KEY_PEPPER", "pepper"):
            digest = api_keys.hash_api_key("sk_example")
        self.assertEqual(len(digest), 64)
        self.assertEqual(
            digest,
            # sha256("peppper" + key) — pinned by computing it independently.
            __import__("hashlib").sha256(b"peppersk_example").hexdigest(),
        )

    def test_pepper_changes_the_digest(self):
        with patch.object(api_keys, "API_KEY_PEPPER", ""):
            bare = api_keys.hash_api_key("sk_example")
        with patch.object(api_keys, "API_KEY_PEPPER", "pepper"):
            peppered = api_keys.hash_api_key("sk_example")
        self.assertNotEqual(bare, peppered)


class CreateKeyTests(unittest.TestCase):
    def test_only_the_hash_and_prefix_are_stored(self):
        db = MagicMock()
        key, raw = api_keys.create_api_key(
            db, company_id=uuid4(), name="CI", scopes=["read", "read", "chat:write"]
        )

        self.assertTrue(raw.startswith("sk_"))
        self.assertNotEqual(key.key_hash, raw)
        self.assertNotIn(raw, key.key_hash)
        self.assertEqual(key.key_hash, api_keys.hash_api_key(raw))
        self.assertEqual(key.key_prefix, raw[:12])
        self.assertEqual(json.loads(key.scopes), ["chat:write", "read"])
        db.add.assert_called_once_with(key)
        db.commit.assert_called_once()


class FindKeyTests(unittest.TestCase):
    def _db(self, key):
        db = MagicMock()
        db.query.return_value = _chain(first_value=key)
        return db

    def test_active_key_is_found(self):
        raw = api_keys.generate_api_key()
        key = models.ApiKey(
            id=uuid4(),
            company_id=uuid4(),
            name="ok",
            key_prefix=raw[:12],
            key_hash=api_keys.hash_api_key(raw),
            scopes='["read"]',
        )
        self.assertIs(api_keys.find_api_key(self._db(key), raw), key)

    def test_unknown_key_resolves_to_none(self):
        self.assertIsNone(api_keys.find_api_key(self._db(None), "sk_nope"))

    def test_revoked_key_resolves_like_an_unknown_one(self):
        raw = api_keys.generate_api_key()
        key = models.ApiKey(
            id=uuid4(),
            company_id=uuid4(),
            name="revoked",
            key_prefix=raw[:12],
            key_hash=api_keys.hash_api_key(raw),
            scopes='["read"]',
            revoked_at=datetime.now(UTC),
        )
        self.assertIsNone(api_keys.find_api_key(self._db(key), raw))

    def test_a_hash_that_does_not_match_the_digest_is_rejected(self):
        # Defends the compare_digest branch: the row must be the one we hashed.
        raw = api_keys.generate_api_key()
        key = models.ApiKey(
            id=uuid4(),
            company_id=uuid4(),
            name="wrong",
            key_prefix=raw[:12],
            key_hash=api_keys.hash_api_key("sk_something-else"),
            scopes='["read"]',
        )
        self.assertIsNone(api_keys.find_api_key(self._db(key), raw))


class ScopeParsingTests(unittest.TestCase):
    def test_valid_list_is_returned(self):
        self.assertEqual(api_keys.parse_scopes('["read", "chat:write"]'), ["read", "chat:write"])

    def test_malformed_input_is_empty(self):
        for raw in ("{", "null", '"read"', "3", "", None):
            self.assertEqual(api_keys.parse_scopes(raw), [])

    def test_non_strings_are_dropped(self):
        self.assertEqual(api_keys.parse_scopes('["read", 7, null, "ingest:write"]'), ["read", "ingest:write"])

    def test_allowed_scopes_are_the_documented_ones(self):
        self.assertEqual(
            set(api_keys.ALLOWED_SCOPES),
            {"read", "ingest:write", "settings:write", "chat:write"},
        )


if __name__ == "__main__":
    unittest.main()
