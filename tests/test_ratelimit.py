import unittest

from starlette.requests import Request

from site_gpt.app.services.ratelimit import _client_ip


def make_request(headers=None, client=("9.9.9.9", 1234)):
    scope = {
        "type": "http",
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


class ClientIpTests(unittest.TestCase):
    def test_uses_first_x_forwarded_for_entry(self):
        request = make_request({"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_strips_surrounding_whitespace(self):
        request = make_request({"x-forwarded-for": "  1.1.1.1  "})
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_falls_back_to_socket_ip(self):
        self.assertEqual(_client_ip(make_request()), "9.9.9.9")

    def test_unknown_when_client_is_missing(self):
        self.assertEqual(_client_ip(make_request(client=None)), "unknown")


if __name__ == "__main__":
    unittest.main()
