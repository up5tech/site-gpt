"""Per-session tokens for the widget's own history (K4).

The problem: `session_id` is chosen by the browser, and the widget reads its
history with nothing but `website_id` (public, in the embed) plus that id. Any
leak of a session id — a log line, a referrer, a screenshot — handed over the
whole transcript and the visitor's email.

The fix: the first time a visitor's widget talks to us it mints a random token
for that session and keeps it in `localStorage`; only `sha256(token)` is stored.
Reading a session now needs that token, so the id alone is no longer enough.

Two rules keep this from becoming theatre:

- **Minting is not an oracle.** A token is issued for a session that has no
  stored data yet (a genuinely new visitor), or as a *rotation* by a caller that
  already presents a matching token. A session that already has messages but no
  token row is legacy data and cannot be claimed by anyone who simply knows its
  id.
- **`compat` mode is a transition, not a hole.** Without a token, a read is only
  allowed for a session that has no token row and only while
  `SESSION_TOKEN_MODE=compat`; a session that was claimed is protected
  immediately. `enforce` requires the token for every read.

Tokens expire (`SESSION_TOKEN_TTL_SECONDS`, default 30 days). Expiry is not a
lockout: `matches()` deliberately ignores it so the holder of an old token can
rotate it, and the widget re-mints on a 403.

That renewal is what makes a TTL alone meaningless — a stolen token could be
rotated every 29 days for ever — so a session's token chain has an **absolute
ceiling**: `SESSION_TOKEN_MAX_LIFETIME_SECONDS` (default 180 days) counted from
the row's `created_at`, which rotation never touches. Inside it, rotation of an
expired token is allowed; past it, reads fail (`verify`) and rotation is refused
(`mint`), and the visitor has to start a new session. The TTL therefore bounds an
idle token, and the ceiling bounds the credential as a whole.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.config import (
    SESSION_TOKEN_MAX_LIFETIME_SECONDS,
    SESSION_TOKEN_MODE,
    SESSION_TOKEN_TTL_SECONDS,
)

# Raw tokens look like `sst_<43 url-safe chars>`; the prefix makes one
# identifiable in a log without revealing anything.
TOKEN_PREFIX = "sst_"

# One message for both ways of arriving at "this session is already claimed":
# finding the row before inserting, and losing the race to another request. A
# caller must not be able to tell the two apart.
ALREADY_CLAIMED_DETAIL = (
    "This session already has a token; send it as X-Session-Token to rotate it"
)

# Distinct from the message above on purpose: telling a caller to "send the
# token to rotate it" when rotation is exactly what is refused would be a lie.
SESSION_EXPIRED_DETAIL = (
    "This session's token has reached its maximum lifetime and cannot be renewed; "
    "start a new session"
)

# Machine-readable reasons, sent alongside the human `detail`. The widget has to
# tell two 403s apart: "this id is dead, start a new session" (`session_expired`)
# versus "another tab holds it, keep this one" (`session_claimed`). Resetting on
# the second one is what made two tabs silently lose each other's history.
REASON_CLAIMED = "session_claimed"
REASON_EXPIRED = "session_expired"
REASON_INVALID = "invalid_token"
REASON_REQUIRED = "token_required"


class SessionTokenError(HTTPException):
    """A refusal with a stable `reason` the client can branch on."""

    def __init__(self, status_code: int, detail: str, reason: str):
        super().__init__(status_code=status_code, detail=detail)
        self.reason = reason


async def error_response(request, exc: SessionTokenError):
    """Render a `SessionTokenError` as `{detail, reason}` (registered in main).

    `HTTPException` alone would only send `detail`, and string matching on prose
    is how a client ends up resetting a session it should have kept.
    """
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "reason": exc.reason},
        headers=getattr(exc, "headers", None),
    )


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """SHA-256 of the raw token, hex encoded (64 chars).

    No pepper here on purpose: the token is 256 bits of randomness, so a stolen
    digest is not brute-forceable, and a pepper would make a rotation incident
    invalidate every live session for no gain.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def row_for(
    db: Session, website_id: UUID, session_id: str
) -> models.SessionToken | None:
    return (
        db.query(models.SessionToken)
        .filter(
            models.SessionToken.website_id == website_id,
            models.SessionToken.session_id == session_id,
        )
        .first()
    )


def matches(row: models.SessionToken | None, raw_token: str | None) -> bool:
    """Whether `raw_token` is this row's token, ignoring expiry and revocation.

    Used for rotation: an expired token must still be able to renew itself,
    otherwise a returning visitor silently loses their history.
    """
    if row is None or not raw_token:
        return False
    return hmac.compare_digest(row.token_hash, hash_token(raw_token))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def chain_expired(
    row: models.SessionToken | None, now: datetime | None = None
) -> bool:
    """Whether this session's token chain has passed its absolute lifetime.

    Measured from `created_at`, which rotation never moves, so renewing the token
    cannot extend it. A row without a timestamp (only mocks have that) is treated
    as fresh rather than dead.
    """
    if row is None:
        return False
    started = _as_utc(row.created_at)
    if started is None:
        return False
    now = _as_utc(now) or datetime.now(UTC)
    return now >= started + timedelta(seconds=SESSION_TOKEN_MAX_LIFETIME_SECONDS)


def verify(
    row: models.SessionToken | None,
    raw_token: str | None,
    now: datetime | None = None,
) -> bool:
    """Whether `raw_token` is valid right now: matching, unrevoked, unexpired,
    and inside the session's absolute lifetime."""
    if not matches(row, raw_token):
        return False
    if row.revoked_at is not None:
        return False
    if chain_expired(row, now):
        return False
    now = _as_utc(now) or datetime.now(UTC)
    expires_at = _as_utc(row.expires_at)
    return expires_at is None or expires_at > now


def mint(
    db: Session,
    website_id: UUID,
    session_id: str,
    ttl_seconds: int | None = None,
    presented_token: str | None = None,
) -> tuple[str, models.SessionToken]:
    """Create or rotate the token of one session. Returns `(raw_token, row)`.

    Concurrent first loads of the same brand-new session are a real pattern (two
    tabs, a prefetch and a page load), and both can pass the "no row yet" check
    before either inserts. The unique constraint on `(website_id, session_id)` is
    what actually decides the winner; the loser gets the same 403 a caller would
    get from finding the row, instead of a 500.
    """
    ttl = SESSION_TOKEN_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    raw_token = generate_token()
    row = row_for(db, website_id, session_id)
    if row is not None and (
        row.revoked_at is not None or not matches(row, presented_token)
    ):
        # The route checked before calling, but a concurrent request may have
        # claimed the session in between. Rotating then would hand a token to
        # someone who merely knows the id, so the rule is enforced here too.
        raise SessionTokenError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ALREADY_CLAIMED_DETAIL,
            reason=REASON_CLAIMED,
        )
    if row is not None and chain_expired(row):
        raise SessionTokenError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SESSION_EXPIRED_DETAIL,
            reason=REASON_EXPIRED,
        )
    if row is not None:
        row.token_hash = hash_token(raw_token)
        row.expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        row.last_seen_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
        return raw_token, row

    row = models.SessionToken(
        website_id=website_id,
        session_id=session_id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Lost the race (or, far less likely, the website vanished mid-request).
        # Only a now-existing token row means "another request claimed it";
        # anything else is a genuine failure and is re-raised rather than
        # disguised as a 403.
        db.rollback()
        if row_for(db, website_id, session_id) is not None:
            raise SessionTokenError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ALREADY_CLAIMED_DETAIL,
                reason=REASON_CLAIMED,
            )
        raise
    db.refresh(row)
    return raw_token, row


def session_has_data(db: Session, website_id: UUID, session_id: str) -> bool:
    """Whether this session already has messages or a contact stored.

    A session with data exists only because a visitor used the widget before
    tokens did, so issuing a fresh token for it on request would be an oracle:
    whoever guessed the id would be handed the credential.
    """
    message = (
        db.query(models.ChatMessage.id)
        .filter(
            models.ChatMessage.website_id == website_id,
            models.ChatMessage.session_id == session_id,
        )
        .first()
    )
    if message is not None:
        return True
    contact = (
        db.query(models.Contact.id)
        .filter(
            models.Contact.website_id == website_id,
            models.Contact.session_id == session_id,
        )
        .first()
    )
    return contact is not None


def token_required(mode: str | None = None) -> bool:
    """Whether reads must present a token. Normalised here as well as in
    config, so an operator's `ENFORCE` or ` enforce ` cannot silently keep
    compat mode on."""
    value = mode if mode is not None else SESSION_TOKEN_MODE
    return str(value or "").strip().lower() == "enforce"


def authorize(
    db: Session,
    website: models.Website,
    session_id: str,
    raw_token: str | None,
) -> None:
    """Raise unless this caller may read the session. The route-level guard.

    Order matters: a token that is present but wrong is always refused, even in
    `compat`, so a forged value can never fall back to "no token, therefore
    allowed".
    """
    row = row_for(db, website.id, session_id)
    now = datetime.now(UTC)

    if raw_token:
        if not verify(row, raw_token, now):
            raise SessionTokenError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired session token",
                reason=REASON_INVALID,
            )
        row.last_seen_at = now
        db.commit()
        return

    if token_required():
        raise SessionTokenError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A session token is required. Reload the page to obtain one.",
            reason=REASON_REQUIRED,
        )
    if row is not None:
        # Claimed while the transition window is still open: the token is the
        # only way in from the moment it exists.
        raise SessionTokenError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This conversation is protected by a session token",
            reason=REASON_CLAIMED,
        )
    # Legacy embed, legacy session: readable until `SESSION_TOKEN_MODE=enforce`.
    return
