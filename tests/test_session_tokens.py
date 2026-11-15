"""Unit tests for per-session tokens (K4).

The guard is the only thing standing between a leaked session id and a
transcript, so the negative paths matter more than the happy one: a right id with
a wrong token must be refused in *both* modes, and `compat` must never turn a
forged token into "no token, therefore allowed".
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from site_gpt.app import models
from site_gpt.app.services import session_tokens


def _row(raw_token: str | None = None, **overrides) -> models.SessionToken:
    row = models.SessionToken(
        website_id=uuid4(),
        session_id="sid-1",
        token_hash=session_tokens.hash_token(raw_token or session_tokens.generate_token()),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _website() -> models.Website:
    return models.Website(
        id=uuid4(), company_id=uuid4(), name="site", url="https://x.test", site_map_url=""
    )


def _db(row):
    db = MagicMock()
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = row
    db.query.return_value = chain
    return db


class TokenGenerationTests(unittest.TestCase):
    def test_tokens_are_prefixed_random_and_unique(self):
        first = session_tokens.generate_token()
        second = session_tokens.generate_token()
        self.assertTrue(first.startswith("sst_"))
        self.assertGreaterEqual(len(first), 40)
        self.assertNotEqual(first, second)

    def test_hash_is_sha256_hex(self):
        digest = session_tokens.hash_token("sst_example")
        self.assertEqual(len(digest), 64)
        self.assertEqual(
            digest,
            __import__("hashlib").sha256(b"sst_example").hexdigest(),
        )
        self.assertNotIn("sst_example", digest)


class MatchesAndVerifyTests(unittest.TestCase):
    def setUp(self):
        self.raw = session_tokens.generate_token()
        self.row = _row(self.raw)

    def test_correct_token_matches(self):
        self.assertTrue(session_tokens.matches(self.row, self.raw))
        self.assertTrue(session_tokens.verify(self.row, self.raw))

    def test_wrong_token_does_not_match(self):
        other = session_tokens.generate_token()
        self.assertFalse(session_tokens.matches(self.row, other))
        self.assertFalse(session_tokens.verify(self.row, other))

    def test_missing_token_or_row_does_not_match(self):
        self.assertFalse(session_tokens.matches(self.row, None))
        self.assertFalse(session_tokens.matches(self.row, ""))
        self.assertFalse(session_tokens.matches(None, self.raw))

    def test_expired_token_matches_but_does_not_verify(self):
        # Rotation relies on this split: the holder of an expired token can renew
        # it, but the expired value grants no read.
        self.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        self.assertTrue(session_tokens.matches(self.row, self.raw))
        self.assertFalse(session_tokens.verify(self.row, self.raw))

    def test_naive_expiry_is_read_as_utc(self):
        self.row.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        self.assertTrue(session_tokens.verify(self.row, self.raw))
        self.row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        self.assertFalse(session_tokens.verify(self.row, self.raw))

    def test_revoked_token_never_verifies(self):
        self.row.revoked_at = datetime.now(UTC)
        self.assertFalse(session_tokens.verify(self.row, self.raw))


class MintTests(unittest.TestCase):
    def test_new_session_inserts_a_row(self):
        db = _db(None)
        raw, row = session_tokens.mint(db, uuid4(), "sid-new", ttl_seconds=60)
        self.assertIsInstance(row, models.SessionToken)
        self.assertEqual(row.session_id, "sid-new")
        self.assertEqual(row.token_hash, session_tokens.hash_token(raw))
        self.assertGreater(row.expires_at, datetime.now(UTC))
        db.add.assert_called_once_with(row)

    def test_rotation_replaces_the_hash_and_extends_expiry(self):
        db = _db(None)
        current = session_tokens.generate_token()
        row = _row(current)
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.query.return_value.first.return_value = row

        # Rotation is the holder's move: no token, no rotation.
        raw, returned = session_tokens.mint(
            db, row.website_id, row.session_id, presented_token=current
        )

        self.assertIs(returned, row)
        self.assertEqual(row.token_hash, session_tokens.hash_token(raw))
        self.assertGreater(row.expires_at, datetime.now(UTC))
        db.add.assert_not_called()

    def test_ttl_is_honoured(self):
        db = _db(None)
        _, row = session_tokens.mint(db, uuid4(), "sid", ttl_seconds=0)
        self.assertLessEqual(row.expires_at, datetime.now(UTC) + timedelta(seconds=1))


class _RaceSession:
    """A session whose INSERT loses the race: commit raises, then the winner
    row is visible. `first()` returns None until the rollback, which is exactly
    the window the bug lived in."""

    def __init__(self, winner_row):
        self.winner_row = winner_row
        self.rolled_back = False
        self.commits = 0
        self.rollbacks = 0
        self.added = []

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.winner_row if self.rolled_back else None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1
        raise IntegrityError("INSERT INTO session_tokens", {}, Exception("duplicate key"))

    def rollback(self):
        self.rollbacks += 1
        self.rolled_back = True

    def refresh(self, row):  # pragma: no cover - never reached on this path
        raise AssertionError("refresh must not run after a failed insert")


class _OkSession:
    """No race: the insert succeeds."""

    def __init__(self):
        self.added = []
        self.commits = 0

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        raise AssertionError("rollback must not run on a clean insert")

    def refresh(self, row):
        return None


class MintRaceTests(unittest.TestCase):
    """Two first loads of the same new session must not 500 the loser."""

    def test_lost_insert_race_answers_the_already_claimed_403(self):
        winner = _row(session_tokens.generate_token())
        winner.session_id = "sid-race"
        db = _RaceSession(winner)

        with self.assertRaises(HTTPException) as caught:
            session_tokens.mint(db, winner.website_id, "sid-race")

        self.assertEqual(caught.exception.status_code, 403)
        # The same message the "row already existed" path returns, so the caller
        # cannot tell the race from the ordinary case.
        self.assertEqual(caught.exception.detail, session_tokens.ALREADY_CLAIMED_DETAIL)
        self.assertEqual(db.rollbacks, 1)
        self.assertEqual(db.commits, 1)

    def test_an_integrity_error_that_is_not_a_race_is_not_disguised(self):
        # A deleted website raises an FK violation too; answering 403 "already has
        # a token" there would be a lie, so the original error propagates.
        db = _RaceSession(winner_row=None)

        with self.assertRaises(IntegrityError):
            session_tokens.mint(db, uuid4(), "sid-race")
        self.assertEqual(db.rollbacks, 1)

    def test_a_row_that_appears_after_the_route_check_is_not_rotated(self):
        # The route saw no row and called mint; another request claimed the
        # session first. Without presenting the token this must not become a
        # rotation, or winning the race would be a way to get the credential.
        winner = _row(session_tokens.generate_token())
        db = _db(None)
        db.query.return_value.first.return_value = winner

        with self.assertRaises(HTTPException) as caught:
            session_tokens.mint(db, winner.website_id, winner.session_id)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, session_tokens.ALREADY_CLAIMED_DETAIL)

    def test_a_clean_insert_still_mints(self):
        db = _OkSession()
        raw, row = session_tokens.mint(db, uuid4(), "sid-new", ttl_seconds=60)

        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.commits, 1)
        self.assertEqual(row.token_hash, session_tokens.hash_token(raw))
        self.assertGreater(row.expires_at, datetime.now(UTC))


class SessionHasDataTests(unittest.TestCase):
    def test_message_presence_counts_as_data(self):
        db = _db(None)
        db.query.return_value.first.return_value = uuid4()
        self.assertTrue(session_tokens.session_has_data(db, uuid4(), "sid"))

    def test_contact_presence_counts_as_data(self):
        db = MagicMock()
        first = MagicMock()
        first.filter.return_value = first
        first.first.return_value = None
        second = MagicMock()
        second.filter.return_value = second
        second.first.return_value = uuid4()
        db.query.side_effect = [first, second]
        self.assertTrue(session_tokens.session_has_data(db, uuid4(), "sid"))

    def test_empty_session_has_no_data(self):
        db = _db(None)
        self.assertFalse(session_tokens.session_has_data(db, uuid4(), "sid"))


class AuthorizeTests(unittest.TestCase):
    """The route-level guard. Every refusal below is a test on purpose."""

    def setUp(self):
        self.website = _website()
        self.raw = session_tokens.generate_token()
        self.row = _row(self.raw, website_id=self.website.id)
        self.row.session_id = "sid-1"

    def _authorize(self, db, token, mode="compat"):
        with patch.object(session_tokens, "SESSION_TOKEN_MODE", mode):
            session_tokens.authorize(db, self.website, "sid-1", token)

    def test_valid_token_is_allowed_and_touches_last_seen(self):
        db = _db(self.row)
        self._authorize(db, self.raw)
        self.assertIsNotNone(self.row.last_seen_at)
        db.commit.assert_called_once()

    def test_right_session_with_wrong_token_is_refused(self):
        db = _db(self.row)
        with self.assertRaises(HTTPException) as caught:
            self._authorize(db, session_tokens.generate_token())
        self.assertEqual(caught.exception.status_code, 403)

    def test_wrong_token_is_refused_even_in_compat(self):
        # The dangerous regression: falling back to "no token, therefore open".
        db = _db(self.row)
        with self.assertRaises(HTTPException) as caught:
            self._authorize(db, "sst_forged", mode="compat")
        self.assertEqual(caught.exception.status_code, 403)

    def test_expired_token_is_refused(self):
        self.row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        with self.assertRaises(HTTPException) as caught:
            self._authorize(_db(self.row), self.raw)
        self.assertEqual(caught.exception.status_code, 403)

    def test_revoked_token_is_refused(self):
        self.row.revoked_at = datetime.now(UTC)
        with self.assertRaises(HTTPException) as caught:
            self._authorize(_db(self.row), self.raw)
        self.assertEqual(caught.exception.status_code, 403)

    def test_token_of_another_session_is_refused(self):
        other = _row(session_tokens.generate_token(), website_id=self.website.id)
        other.session_id = "sid-2"
        # The id in the request resolves row sid-1, whose hash is not this token.
        with self.assertRaises(HTTPException) as caught:
            self._authorize(_db(self.row), session_tokens.generate_token())
        self.assertEqual(caught.exception.status_code, 403)

    def test_compat_allows_a_tokenless_read_of_an_unclaimed_session(self):
        self._authorize(_db(None), None)

    def test_compat_refuses_a_tokenless_read_of_a_claimed_session(self):
        with self.assertRaises(HTTPException) as caught:
            self._authorize(_db(self.row), None)
        self.assertEqual(caught.exception.status_code, 403)

    def test_enforce_requires_a_token_even_for_an_unclaimed_session(self):
        with self.assertRaises(HTTPException) as caught:
            self._authorize(_db(None), None, mode="enforce")
        self.assertEqual(caught.exception.status_code, 401)

    def test_enforce_accepts_a_valid_token(self):
        self._authorize(_db(self.row), self.raw, mode="enforce")


class TokenRequiredTests(unittest.TestCase):
    def test_mode_parsing(self):
        self.assertTrue(session_tokens.token_required("enforce"))
        self.assertTrue(session_tokens.token_required(" ENFORCE "))
        self.assertFalse(session_tokens.token_required("compat"))


if __name__ == "__main__":
    unittest.main()
