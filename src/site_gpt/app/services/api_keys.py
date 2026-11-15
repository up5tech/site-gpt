"""Issue, hash and resolve the company API keys behind `/api/v1`.

Keys are stored hashed only (ADR-6): the raw value is shown once on creation and
never persisted, logged or returned again. The short `key_prefix` exists so an
owner can tell keys apart in the dashboard.

Lookup goes through the unique `key_hash` column and then compares with
`hmac.compare_digest`, so a request cannot learn a stored digest byte by byte.
No new dependency: `hashlib`/`hmac`/`secrets` are stdlib.
"""

import hashlib
import hmac
import json
import secrets

from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.config import API_KEY_PEPPER

# Raw keys look like `sk_<43 url-safe chars>`; the dashboard shows the first 12.
RAW_KEY_PREFIX = "sk_"
KEY_PREFIX_LEN = 12

# Scopes a key may be granted. Kept deliberately small: one per capability the
# versioned API exposes, so a leaked key can be limited to what it was for.
ALLOWED_SCOPES = ("read", "ingest:write", "settings:write", "chat:write")


def generate_api_key() -> str:
    """A fresh raw key. Store `hash_api_key(raw)` and show `raw` once."""
    return RAW_KEY_PREFIX + secrets.token_urlsafe(32)


def key_prefix(raw_key: str) -> str:
    """The non-secret prefix stored for display (`sk_abc12345`)."""
    return raw_key[:KEY_PREFIX_LEN]


def hash_api_key(raw_key: str) -> str:
    """SHA-256 of pepper + raw key, hex encoded (64 chars)."""
    return hashlib.sha256(f"{API_KEY_PEPPER}{raw_key}".encode("utf-8")).hexdigest()


def parse_scopes(raw: str | None) -> list[str]:
    """The scope list stored as JSON, tolerating a malformed row."""
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [scope for scope in value if isinstance(scope, str)]


def scopes_of(key: models.ApiKey) -> list[str]:
    return parse_scopes(key.scopes)


def create_api_key(
    db: Session,
    *,
    company_id,
    name: str,
    scopes: list[str],
) -> tuple[models.ApiKey, str]:
    """Persist a new key; returns `(row, raw_key)` — the raw key is shown once."""
    raw_key = generate_api_key()
    key = models.ApiKey(
        company_id=company_id,
        name=name,
        key_prefix=key_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
        scopes=json.dumps(sorted(set(scopes))),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key, raw_key


def find_api_key(db: Session, raw_key: str) -> models.ApiKey | None:
    """The active key matching `raw_key`, or None.

    A revoked key is treated exactly like an unknown one so a response cannot be
    used to probe whether a key ever existed.
    """
    digest = hash_api_key(raw_key)
    key = (
        db.query(models.ApiKey)
        .filter(models.ApiKey.key_hash == digest)
        .first()
    )
    if key is None or key.revoked_at is not None:
        return None
    if not hmac.compare_digest(key.key_hash, digest):
        return None
    return key
