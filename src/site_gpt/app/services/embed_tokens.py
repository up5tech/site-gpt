"""Mint, rotate and revoke the per-website embed token (V3 F4).

The token is **public**: it ends up in a customer's HTML page, so anyone can read
and replay it. It exists to let an operator revoke the snippets they no longer
deploy and to support `EMBED_TOKEN_MODE=enforce`; it cannot prove browser origin
(K18 stays an accepted residual, see `README.md` §4).

Rules this module keeps in one place:

- **The raw value is returned once and never stored.** Only `sha256(raw)` and a
  12-character prefix (for the dashboard) are persisted, exactly like an API key.
  There is deliberately no pepper: the pepper protects a *guessable* secret
  against offline guessing, while this token carries 256 bits of entropy, and a
  pepper that changed would invalidate every issued snippet at once.
- **One active token per website**, enforced by the partial unique index in M7
  rather than by a read-then-write check. Rotation therefore revokes the old row
  and inserts the new one inside a single transaction: if the insert loses a race
  the whole thing rolls back and the old token stays valid, so a website is never
  left with two live tokens (or none).
- **Revoked rows stay** as history (`revoked_at`), so the UI can show what was
  replaced. A revoked token is refused the same way an unknown one is (V3-23).

Callers are routes; this module never decides tenancy. The website is resolved
by the caller under the caller's `company_id`, and a foreign id is a 404 before
any of this runs.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from site_gpt.app import models

# Raw tokens look like `emb_<43 url-safe chars>`; the dashboard shows the first
# 12 characters, the same convention as `ApiKey.key_prefix`.
RAW_TOKEN_PREFIX = "emb_"
TOKEN_PREFIX_LEN = 12


# How often `last_used_at` may be written for one token. One minute is enough to
# show activity in the dashboard without an UPDATE per chat message.
LAST_USED_THROTTLE_SECONDS = 60


class EmbedTokenExists(Exception):
    """The website already has an active token: rotate instead of minting."""


class EmbedTokenMissing(Exception):
    """There is no active token to revoke."""


def generate_token() -> str:
    """A fresh raw token. Store `hash_token(raw)` and show `raw` once."""
    return RAW_TOKEN_PREFIX + secrets.token_urlsafe(32)


def token_prefix(raw_token: str) -> str:
    """The non-secret prefix stored for display (`emb_abc1234`)."""
    return raw_token[:TOKEN_PREFIX_LEN]


def hash_token(raw_token: str) -> str:
    """SHA-256 of the raw token, hex encoded (64 chars).

    No pepper, on purpose — see the module docstring. A random 256-bit value
    needs no key stretching either.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _to_row(website_id, raw_token: str, created_at: datetime | None = None):
    return models.EmbedToken(
        website_id=website_id,
        token_prefix=token_prefix(raw_token),
        token_hash=hash_token(raw_token),
        # Written explicitly rather than left to the column's `now()` default:
        # SQLite's CURRENT_TIMESTAMP is second-precision, so a mint and the very
        # next rotation would tie and `latest_token` could return the old row.
        created_at=created_at or datetime.now(UTC),
    )


def find_active_token(
    db: Session, raw_token: str, *, website_id=None
) -> models.EmbedToken | None:
    """The live token matching `raw_token` for `website_id`, or None (V3-23).

    A revoked token, a token of another website and an unknown value all resolve
    to the same None, so a refusal cannot be used to probe whether a token ever
    existed. Compare with `hmac.compare_digest`, like the API-key lookup.
    """
    if not raw_token:
        return None
    digest = hash_token(raw_token)
    query = db.query(models.EmbedToken).filter(
        models.EmbedToken.token_hash == digest
    )
    if website_id is not None:
        query = query.filter(models.EmbedToken.website_id == website_id)
    row = query.first()
    if row is None or row.revoked_at is not None:
        return None
    if not hmac.compare_digest(row.token_hash, digest):
        return None
    return row


def record_use(
    db: Session,
    row: models.EmbedToken,
    *,
    now: datetime | None = None,
    throttle_seconds: int = LAST_USED_THROTTLE_SECONDS,
) -> bool:
    """Stamp `last_used_at`, at most once per `throttle_seconds` (V3-23).

    The throttle lives in the row rather than in a process-local map: an
    unbounded dict keyed by token would grow with the number of tokens ever
    seen, and would be wrong the moment a second worker handles the request.
    A busy widget therefore costs at most one `UPDATE` a minute per website.
    """
    current = now or datetime.now(UTC)
    previous = row.last_used_at
    if previous is not None:
        # SQLite hands back a naive value; Postgres returns it aware.
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
        if current - previous < timedelta(seconds=throttle_seconds):
            return False
    row.last_used_at = current
    db.commit()
    return True


def active_token(db: Session, website_id) -> models.EmbedToken | None:
    """This website's live token, or None."""
    return (
        db.query(models.EmbedToken)
        .filter(
            models.EmbedToken.website_id == website_id,
            models.EmbedToken.revoked_at.is_(None),
        )
        .first()
    )


def latest_token(db: Session, website_id) -> models.EmbedToken | None:
    """The most recently created row, revoked or not — what the UI shows."""
    return (
        db.query(models.EmbedToken)
        .filter(models.EmbedToken.website_id == website_id)
        .order_by(models.EmbedToken.created_at.desc())
        .first()
    )


def mint(db: Session, website_id) -> tuple[models.EmbedToken, str]:
    """Issue the website's first token; returns `(row, raw_token)`.

    Refuses when one is already active: a second live token would defeat
    revocation, and the partial unique index would reject it anyway. The check
    here only produces a clear 409 instead of a constraint error, so the insert
    still has to survive the race (hence the `IntegrityError` branch).
    """
    if active_token(db, website_id) is not None:
        raise EmbedTokenExists(
            "This website already has an active embed token; rotate it instead."
        )

    raw_token = generate_token()
    row = _to_row(website_id, raw_token)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Another request minted between the check and the insert.
        db.rollback()
        raise EmbedTokenExists(
            "This website already has an active embed token; rotate it instead."
        )
    db.refresh(row)
    return row, raw_token


def rotate(db: Session, website_id) -> tuple[models.EmbedToken, str]:
    """Revoke the active token and issue a replacement in one transaction.

    One commit covers both rows. If the insert conflicts, the rollback also
    undoes the revocation, so the previously working snippet keeps working
    instead of the website ending up with no valid token.
    """
    raw_token = generate_token()
    now = datetime.now(UTC)
    row = _to_row(website_id, raw_token, created_at=now)
    revoked = 0
    current = active_token(db, website_id)
    if current is not None:
        current.revoked_at = now
        revoked = 1

    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EmbedTokenExists(
            "Another rotation won the race; reload the website and try again."
        )
    db.refresh(row)
    if current is not None:
        db.refresh(current)
    if revoked and current is not None and current.revoked_at is None:
        # Defensive: the commit should have kept this, but a stale row here
        # would mean two active tokens.
        raise RuntimeError("rotation did not revoke the previous embed token")
    return row, raw_token


def revoke(db: Session, website_id) -> models.EmbedToken:
    """Mark the active token revoked. The row is kept for the audit trail."""
    row = active_token(db, website_id)
    if row is None:
        raise EmbedTokenMissing("This website has no active embed token.")
    row.revoked_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row
