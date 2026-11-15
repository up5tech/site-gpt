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
* **A header that names a foreign site → refused.**

This raises the bar rather than fully closing the hole: a determined attacker
calling the API directly with no headers (or a forged ``Referer``) is still
accepted. Closing that needs a signed embed token per website (a schema change,
so V2).

The module also owns the two request gates every public endpoint shares, so new
routes (e.g. the versioned `/api/v1`) reuse them instead of copying the logic:
``is_authenticated`` (a dashboard JWT bypasses the origin check) and
``ensure_embed_allowed`` (the 403-raising wrapper).
"""

from urllib.parse import urlparse

from fastapi import HTTPException, status

from site_gpt.app import models
from site_gpt.app.core.auth import verify_token
from site_gpt.app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY

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


def ensure_embed_allowed(
    request,
    db,
    website,
    *,
    allow_authenticated: bool = False,
) -> None:
    """Refuse requests whose Origin/Referer names a foreign site.

    Guards the public widget surface against someone copying a `website_id` and
    embedding another customer's bot from their own site. Shared by every public
    endpoint (chat, stream, contacts, widget config, `/api/v1`), so no caller can
    forget the check or ship a subtly different version of it.
    """
    if allow_authenticated and is_authenticated(request, db):
        return
    if not is_allowed_embed_request(request, website):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This origin is not allowed to embed that assistant.",
        )
