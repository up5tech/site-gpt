import logging

from fastapi import HTTPException, Header, Request, status, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from datetime import datetime, timedelta, UTC
from uuid import UUID

from jose import jwt
from passlib.context import CryptContext
from requests import Session

import site_gpt.app.models as models
from site_gpt.app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from site_gpt.app.core.logging import log_event
from site_gpt.app.db.session import get_db
from site_gpt.app.services.api_keys import find_api_key, scopes_of
from site_gpt.app.services import operator_access
from site_gpt.app.services import platform as platform_service


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# D13 (recorded 2026-11-24): the 24-hour tenant JWT stays for the launch cohort,
# and there is no per-session revocation. This number is therefore the ceiling on
# how long a stolen token or a leaked password stays usable on its own; the
# incident tools around it are account deactivation, user deletion, API-key
# revocation and a `JWT_SECRET_KEY` rotation, which `docs/security.md` records as
# the runbook. One named constant, so the enforced lifetime cannot drift away
# from the documented posture without this line changing.
ACCESS_TOKEN_TTL = timedelta(hours=24)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: dict,
    secret_key: str,
    algorithm: str = "HS256",
    expires_delta: timedelta | None = None,
):
    to_encode = data.copy()
    issued_at = datetime.now(UTC)
    expire = issued_at + (expires_delta or ACCESS_TOKEN_TTL)
    # `iat` is what makes the issued lifetime readable after the fact (an
    # incident review can say when a token was minted without trusting the
    # client), and `exp` is what this app enforces on every request.
    to_encode.update({"iat": issued_at, "exp": expire})
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=algorithm)
    return encoded_jwt


def verify_token(
    token: str,
    secret_key: str,
    algorithms: list = ["HS256"],
):
    try:
        payload = jwt.decode(token, secret_key, algorithms=algorithms)
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("exp") is None:
        # python-jose verifies `exp` only when it is present, so a signed token
        # without one would never age out — the 24-hour posture (D13) does not
        # allow a token that outlives it. Every token this app issues carries
        # `exp`, so refusing the rest cannot break a legitimate session.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    payload = verify_token(token, JWT_SECRET_KEY, [JWT_ALGORITHM])
    # `sub` is attacker-controlled for anything that can sign with the key and
    # garbage for a corrupted token: coerce it here so a malformed value is a
    # 401 like every other bad token, not a database error surfacing as a 500.
    try:
        user_id = UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.status == "active")
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_manager_user(
    user=Depends(get_current_user),
):
    if user.role != "admin" and user.role != "manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return user


def get_admin_user(
    user=Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return user


def get_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """Authenticate a company API key for the versioned `/api/v1` routes.

    Returns the `ApiKey` row: its `company_id` scopes every query and its scopes
    gate each route, so callers never pass a company id. JWT auth is untouched —
    this is an *additional* path for server-to-server callers.
    """
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    key = find_api_key(db, x_api_key.strip())
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    key.last_used_at = datetime.now(UTC)
    db.commit()
    return key


def require_scope(key, scope: str) -> None:
    """Raise 403 unless `key` was granted `scope`."""
    if scope not in scopes_of(key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is missing the '{scope}' scope",
        )


def require_platform_owner(
    request: Request,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The operator boundary (V5-40, D10; V6-11 network allowlist).

    Deliberately stricter than `get_admin_user` and independent of it: a tenant
    `admin` is not an operator, and the grant this reads can only be created out
    of band by `scripts/platform_owner.py`. Revocation is a timestamp, so the
    very next request after `revoke_owner` is refused.

    V6-11 / D5 (reopened 2026-11-27): the approved control is an operator
    network allowlist, checked here — in the application, on every route — so
    no `Host`, alternate API origin or proxy header can substitute for it. An
    empty list means "not restricted" outside production, where the production
    validator refuses to enable the console without a non-blanket list. A
    refusal uses the same 403 and detail as a missing grant, so a caller outside
    the network learns nothing about whether the surface exists.
    """
    if not operator_access.is_allowed(request):
        log_event("platform.network_refused", level=logging.WARNING)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    if not platform_service.is_owner(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return user
