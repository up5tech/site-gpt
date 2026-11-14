import ipaddress
import unittest
from unittest.mock import patch

from starlette.requests import Request

from site_gpt.app.services import ratelimit
from site_gpt.app.services.ratelimit import _client_ip, _trusted_networks


def make_request(headers=None, client=("127.0.0.1", 1234)):
    scope = {
        "type": "http",
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


class ClientIpTests(unittest.TestCase):
    def test_uses_first_x_forwarded_for_entry_from_local_proxy(self):
        request = make_request({"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_strips_surrounding_whitespace(self):
        request = make_request({"x-forwarded-for": "  1.1.1.1  "})
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_private_proxy_peer_is_trusted(self):
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("10.0.0.5", 5000)
        )
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_ipv6_loopback_proxy_is_trusted(self):
        request = make_request({"x-forwarded-for": "1.1.1.1"}, client=("::1", 5000))
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_public_peer_cannot_spoof_x_forwarded_for(self):
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("9.9.9.9", 5000)
        )
        self.assertEqual(_client_ip(request), "9.9.9.9")

    def test_malformed_forwarded_entry_falls_back_to_peer(self):
        request = make_request({"x-forwarded-for": "not-an-ip"})
        self.assertEqual(_client_ip(request), "127.0.0.1")

    def test_falls_back_to_socket_ip_without_header(self):
        request = make_request(client=("127.0.0.1", 4321))
        self.assertEqual(_client_ip(request), "127.0.0.1")

    def test_unknown_when_client_is_missing(self):
        request = make_request({"x-forwarded-for": "1.1.1.1"}, client=None)
        self.assertEqual(_client_ip(request), "unknown")


class TrustedProxyAllowlistTests(unittest.TestCase):
    """A public-address LB must be listed in TRUSTED_PROXY_IPS."""

    def test_listed_public_proxy_uses_forwarded_client_ip(self):
        networks = [ipaddress.ip_network("8.8.8.0/24")]
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("8.8.8.10", 5000)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_unlisted_public_proxy_keeps_socket_ip(self):
        networks = [ipaddress.ip_network("8.8.8.0/24")]
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("1.0.0.7", 5000)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "1.0.0.7")

    def test_single_ip_entry_matches_exactly(self):
        networks = _trusted_networks(["8.8.8.10"])
        trusted = make_request({"x-forwarded-for": "1.1.1.1"}, client=("8.8.8.10", 1))
        other = make_request({"x-forwarded-for": "1.1.1.1"}, client=("8.8.8.11", 1))

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(trusted), "1.1.1.1")
            self.assertEqual(_client_ip(other), "8.8.8.11")

    def test_ipv6_allowlist_entry(self):
        networks = _trusted_networks(["2001:db8::/32"])
        request = make_request(
            {"x-forwarded-for": "1.1.1.1"}, client=("2001:db8::5", 1)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_malformed_forwarded_entry_from_trusted_proxy_falls_back(self):
        networks = [ipaddress.ip_network("8.8.8.0/24")]
        request = make_request(
            {"x-forwarded-for": "definitely-not-an-ip"}, client=("8.8.8.10", 1)
        )

        with patch.object(ratelimit, "_TRUSTED_PROXIES", networks):
            self.assertEqual(_client_ip(request), "8.8.8.10")

    def test_parsing_skips_invalid_entries_and_handles_host_entries(self):
        networks = _trusted_networks(["nonsense", "10.0.0.0/8", "", "8.8.8.10"])

        self.assertEqual(
            [str(n) for n in networks], ["10.0.0.0/8", "8.8.8.10/32"]
        )

    def test_empty_configuration_trusts_nothing_public(self):
        self.assertEqual(_trusted_networks([]), [])


if __name__ == "__main__":
    unittest.main()
