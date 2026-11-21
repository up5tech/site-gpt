"""Origin/Referer allowlist for the public widget endpoints.

The widget is embedded by putting a `website_id` into
``window.ChatWidgetConfig``, so that id is public: anyone who copies it can call
``/api/chat`` (spending the customer's LLM credits) and ``/api/contacts``
(pushing leads into the customer's dashboard). The only signal that ties a
request to the customer's own site is the browser-supplied ``Origin`` or
``Referer`` header.

The check is intentionally soft, because a strict one breaks real embeds:

* **No usable header → allowed.** Browsers with a privacy-blocked referrer,
  ``referrerpolicy="no-referrer"``, ``file://`` demos and non-browser clients
  all send nothing; the widget must keep working for them.
* **Loopback origins → allowed** so local demo pages keep working.
* **The API's own origin → allowed** (V4 F5). The hosted page
  (`GET /chat/{website_id}`) is served by this API and calls it from that same
  origin, so its requests are first-party even though the origin is not the
  website's own URL. The comparison is exact scheme+host+port equality with
  `request.base_url` — a lookalike host, a different port or a scheme downgrade
  is still refused — and it is a convenience for the page, not origin
  authentication (K18 stays accepted).
* **A header that names a foreign site → refused.**

This raises the bar rather than fully closing the hole: a determined attacker
calling the API directly with no headers (or a forged ``Referer``) is still
accepted. V3 F4 adds an optional per-website `X-Embed-Token` on top (see
``ensure_embed_token_allowed``): it makes a deployed snippet revocable and can be
made mandatory, but it lives in the page source and can be replayed, so it does
not make the origin decision trustworthy.

The module also owns the two request gates every public endpoint shares, so new
routes (e.g. the versioned `/api/v1`) reuse them instead of copying the logic:
``is_authenticated`` (a dashboard JWT bypasses the origin check) and
``ensure_embed_allowed`` (the 403-raising wrapper).
"""

from urllib.parse import urlparse

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from site_gpt.app import models
from site_gpt.app.core.auth import verify_token
from site_gpt.app.core.config import EMBED_TOKEN_MODE, JWT_ALGORITHM, JWT_SECRET_KEY
from site_gpt.app.services import embed_tokens

# Origins that are always fine: local development and demos.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _host(value: str | None) -> str | None:
    """Extract a lowercase hostname from an origin, referer or bare host."""
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "//" not in candidate:
        candidate = f"//{candidate}"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    host = parsed.hostname
    return host.lower().rstrip(".") if host else None


def _same_site(host: str, allowed: str) -> bool:
    """`www.example.com` and `example.com` are the same site; nothing else is."""
    return host == allowed or host.removeprefix("www.") == allowed.removeprefix("www.")


def _origin(value: str | None) -> tuple[str, str, int] | None:
    """(scheme, host, port) for an absolute http(s) URL or origin, else None.

    The default port is filled in, so `https://x` and `https://x:443` are the
    same origin (they are — a browser cannot tell them apart either).
    """
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError:
        return None  # an unparseable port is not an origin we can trust
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return (scheme, parsed.hostname.lower().rstrip("."), port)


def request_origin(request) -> tuple[str, str, int] | None:
    """The origin this request was served from, as the server saw it.

    `request.base_url` follows the `Host` (and proxy) headers, which is the
    origin a browser on the hosted page puts in `Origin`. A request that cannot
    produce a usable origin (a stub, a malformed Host) is never first-party.
    """
    base_url = getattr(request, "base_url", None)
    if base_url is None:
        return None
    return _origin(str(base_url))


def is_first_party_request(request, source: str | None) -> bool:
    """True when `source` names exactly the origin serving this request.

    Exact scheme+host+port equality, no `www.` or suffix tolerance: this accepts
    the hosted page's own chat calls, not another site that resembles the API.
    """
    own = request_origin(request)
    return own is not None and own == _origin(source)


def allowed_hosts(website) -> list[str]:
    """Hosts a website may be embedded from."""
    hosts: list[str] = []
    for candidate in (getattr(website, "url", None),):
        host = _host(candidate)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def is_allowed_embed_request(request, website) -> bool:
    """True when this request may act on `website`'s public widget endpoints."""
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    # `Origin: null` (sandboxed iframe, file://) carries no site information.
    source = origin if origin and origin.strip().lower() != "null" else referer
    if not source:
        return True

    host = _host(source)
    if host is None:
        return True  # unparseable or opaque: treat as "no referrer"
    if host in LOOPBACK_HOSTS:
        return True
    # V4 F5: the hosted page calls the API from the origin it is served on. This
    # is the only addition for it; every third-party origin below is unchanged.
    if is_first_party_request(request, source):
        return True

    return any(_same_site(host, allowed) for allowed in allowed_hosts(website))


def is_authenticated(request, db) -> bool:
    """True when the request carries a valid JWT for an active user.

    The admin playground calls the same public chat endpoints as the widget but
    with the dashboard's token; those requests are not scoped by Origin.
    """
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    try:
        payload = verify_token(token, JWT_SECRET_KEY, [JWT_ALGORITHM])
    except HTTPException:
        return False
    user_id = payload.get("sub")
    if not user_id:
        return False
    return (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.status == "active")
        .first()
        is not None
    )


class EmbedTokenRefused(Exception):
    """A 403 from the embed-token gate, with a machine-readable `reason`.

    `reason` exists for the same purpose as the K4 session-token codes: the
    widget has to tell "your snippet is out of date" from "another tab holds
    this session", and it must never guess from prose. These reasons are
    deliberately **not** the session ones — an embed refusal never resets the
    visitor's session.
    """

    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, detail: str, reason: str):
        super().__init__(detail)
        self.detail = detail
        self.reason = reason


# Rendered by `embed_token_error_response` (registered in `main.py`).
async def embed_token_error_response(request, exc: EmbedTokenRefused):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "reason": exc.reason},
    )


# Stable reason codes (never branch on `detail`).
EMBED_TOKEN_REQUIRED = "embed_token_required"
INVALID_EMBED_TOKEN = "invalid_embed_token"
EMBED_TOKEN_HEADER = "x-embed-token"


def ensure_embed_token_allowed(request, db, website) -> None:
    """The per-website token gate (V3 F4).

    `compat` (default): a missing token is accepted — every snippet deployed
    before V3 sends none — but a token that *is* supplied must be valid, so a
    revoked snippet stops working immediately after rotation.

    `enforce`: a valid token is required. This is a deliberate breaking rollout,
    and it still is not an origin guarantee: the token is visible in the page and
    can be replayed (K18 stays accepted).

    The check is additive to the Origin/Referer one, never a replacement.
    """
    raw_token = (request.headers.get(EMBED_TOKEN_HEADER) or "").strip()
    if not raw_token:
        if EMBED_TOKEN_MODE == "enforce":
            raise EmbedTokenRefused(
                "This assistant requires an embed token.", EMBED_TOKEN_REQUIRED
            )
        return

    row = embed_tokens.find_active_token(
        db, raw_token, website_id=getattr(website, "id", None)
    )
    if row is None:
        # Wrong, revoked, or another website's token: one answer for all three.
        # The value is never echoed back.
        raise EmbedTokenRefused(
            "This embed token is not valid for this website.", INVALID_EMBED_TOKEN
        )
    embed_tokens.record_use(db, row)


def ensure_embed_allowed(
    request,
    db,
    website,
    *,
    allow_authenticated: bool = False,
    require_embed_token: bool = True,
) -> None:
    """Refuse requests whose Origin/Referer names a foreign site.

    Guards the public widget surface against someone copying a `website_id` and
    embedding another customer's bot from their own site. Shared by every public
    endpoint (chat, stream, contacts, widget config, `/api/v1`), so no caller can
    forget the check or ship a subtly different version of it. The one exception
    for the hosted page is inside `is_allowed_embed_request` (exact equality with
    this request's own origin), never a second copy of the rule.

    `require_embed_token=False` is for callers that already authenticated with a
    secret (`/api/v1`'s `X-API-Key`): the embed token is a *browser* control and
    requiring it there would break a server-to-server integration the moment an
    operator switches on `EMBED_TOKEN_MODE=enforce`.
    """
    if allow_authenticated and is_authenticated(request, db):
        return
    if not is_allowed_embed_request(request, website):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This origin is not allowed to embed that assistant.",
        )
    if require_embed_token:
        ensure_embed_token_allowed(request, db, website)
