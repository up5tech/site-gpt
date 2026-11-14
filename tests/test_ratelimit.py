import unittest

from starlette.requests import Request

from site_gpt.app.services.ratelimit import _client_ip


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


if __name__ == "__main__":
    unittest.main()
