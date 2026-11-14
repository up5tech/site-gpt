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
"""

from urllib.parse import urlparse

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
