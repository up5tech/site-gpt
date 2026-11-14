"""SSRF guard for URLs the server fetches on behalf of users.

Any URL that arrives from a user (a remote import, a sitemap, a page found in a
sitemap) is attacker-controlled: without checks it can point at loopback, a
container-internal service, or the cloud metadata endpoint (169.254.169.254),
and the fetched body is stored and later quoted back in chat answers.

The rule enforced here is deliberately simple: only ``http``/``https``, and only
hosts whose every resolved address is public. Callers must re-check **each**
redirect hop, because a public URL can redirect to a private one.
"""

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")


class UnsafeUrl(ValueError):
    """Raised when a URL is not a public http(s) address we will fetch."""


def resolve_host_ips(host: str, port: int) -> list[str]:
    """Return every address `host` resolves to (patched in tests)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def is_public_ip(ip_text: str) -> bool:
    """True only for routable, non-special-purpose addresses."""
    address = ipaddress.ip_address(ip_text.split("%")[0])
    # ::ffff:127.0.0.1 must be judged as the IPv4 address it maps to.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def assert_fetchable_url(url: str) -> str:
    """Validate a URL before a request is made; returns it unchanged.

    Raises `UnsafeUrl` for a non-http(s) scheme, a missing host, an unresolvable
    host, or a host that resolves to any non-public address (a single private
    answer is enough to reject, since the client may pick it).
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrl("A URL is required.")

    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:  # malformed IPv6 literal, etc.
        raise UnsafeUrl("The URL could not be parsed.") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrl(
            "Only http:// and https:// URLs can be fetched "
            f"(got '{parsed.scheme or 'no scheme'}')."
        )

    host = parsed.hostname
    if not host:
        raise UnsafeUrl("The URL has no host.")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrl("The URL has an invalid port.") from exc

    try:
        addresses = resolve_host_ips(host, port)
    except OSError as exc:
        raise UnsafeUrl(f"Could not resolve host '{host}'.") from exc

    if not addresses:
        raise UnsafeUrl(f"Could not resolve host '{host}'.")

    for address in addresses:
        try:
            allowed = is_public_ip(address)
        except ValueError as exc:
            raise UnsafeUrl(f"'{host}' resolved to an invalid address.") from exc
        if not allowed:
            raise UnsafeUrl(
                f"'{host}' resolves to a non-public address and cannot be fetched."
            )

    return url
