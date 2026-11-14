import asyncio
import ipaddress
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api import upload as upload_api
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.services import crawler, net_guard, sources

PUBLIC_IP = "93.184.216.34"


def fake_resolve(host: str, port: int) -> list[str]:
    """Deterministic DNS for tests: literals keep their own address."""
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass

    table = {
        "localhost": ["127.0.0.1"],
        "internal.test": ["10.0.0.5"],
        "metadata.test": ["169.254.169.254"],
        "mixed.test": [PUBLIC_IP, "10.0.0.5"],
        "v6.test": ["::1"],
        "mapped.test": ["::ffff:127.0.0.1"],
    }
    if host == "unresolvable.test":
        raise OSError("name resolution failed")
    return table.get(host, [PUBLIC_IP])


class FakeRequestsResponse:
    """Minimal stand-in for requests.Response used by `crawler._safe_get`."""

    def __init__(self, status_code=200, headers=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.text = content.decode("utf-8", "ignore")

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and (
            "location" in self.headers
        )

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class UrlGuardTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(net_guard, "resolve_host_ips", side_effect=fake_resolve)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rejects_non_http_schemes(self):
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/x",
            "gopher://example.com/",
            "javascript:alert(1)",
            "data:text/html,<b>x</b>",
            "//example.com/no-scheme",
        ):
            with self.subTest(url=url):
                with self.assertRaises(net_guard.UnsafeUrl):
                    net_guard.assert_fetchable_url(url)

    def test_rejects_empty_url(self):
        with self.assertRaises(net_guard.UnsafeUrl):
            net_guard.assert_fetchable_url("   ")

    def test_rejects_private_and_metadata_ip_literals(self):
        for url in (
            "http://127.0.0.1/",
            "http://127.0.0.1:8000/api/websites",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/",
            "http://192.168.0.10/",
            "http://172.16.4.4/",
            "http://0.0.0.0/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(net_guard.UnsafeUrl):
                    net_guard.assert_fetchable_url(url)

    def test_rejects_hostnames_that_resolve_to_private_addresses(self):
        for url in (
            "http://localhost/x",
            "http://internal.test/x",
            "http://metadata.test/x",
            "http://v6.test/x",
            "http://mapped.test/x",
            "https://mixed.test/x",  # one private answer is enough
        ):
            with self.subTest(url=url):
                with self.assertRaises(net_guard.UnsafeUrl):
                    net_guard.assert_fetchable_url(url)

    def test_rejects_unresolvable_host(self):
        with self.assertRaises(net_guard.UnsafeUrl):
            net_guard.assert_fetchable_url("https://unresolvable.test/x")

    def test_accepts_a_public_host(self):
        url = "https://example.com/file.pdf"
        self.assertEqual(net_guard.assert_fetchable_url(url), url)

    def test_userinfo_cannot_hide_a_private_host(self):
        with self.assertRaises(net_guard.UnsafeUrl):
            net_guard.assert_fetchable_url("http://example.com@127.0.0.1/x")

    def test_is_public_ip(self):
        self.assertTrue(net_guard.is_public_ip(PUBLIC_IP))
        self.assertFalse(net_guard.is_public_ip("127.0.0.1"))
        self.assertFalse(net_guard.is_public_ip("::ffff:169.254.169.254"))


class UrlProviderSsrfTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(net_guard, "resolve_host_ips", side_effect=fake_resolve)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.requested: list[str] = []
        self.auth_headers: list[str | None] = []

    def _install_client(self, handler):
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        patcher = patch.object(sources.httpx, "AsyncClient", factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _handler(self, routes):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requested.append(str(request.url))
            self.auth_headers.append(request.headers.get("authorization"))
            route = routes.get(str(request.url))
            if route is None:
                raise AssertionError(f"unexpected request to {request.url}")
            return route

        return handler

    def _fetch(self, url, token=None):
        return asyncio.run(sources.UrlProvider().acquire(url, token))

    def test_rejects_private_url_before_any_request(self):
        self._install_client(self._handler({}))

        with self.assertRaises(net_guard.UnsafeUrl):
            self._fetch("http://169.254.169.254/latest/meta-data/")

        self.assertEqual(self.requested, [])

    def test_rejects_redirect_to_metadata_endpoint(self):
        self._install_client(
            self._handler(
                {
                    "https://example.com/start": httpx.Response(
                        302,
                        headers={"location": "http://169.254.169.254/latest/meta-data/"},
                    )
                }
            )
        )

        with self.assertRaises(net_guard.UnsafeUrl):
            self._fetch("https://example.com/start")

        # The metadata host was never contacted.
        self.assertEqual(self.requested, ["https://example.com/start"])

    def test_rejects_redirect_to_loopback(self):
        self._install_client(
            self._handler(
                {
                    "https://example.com/start": httpx.Response(
                        302, headers={"location": "http://127.0.0.1:8000/api/websites"}
                    )
                }
            )
        )

        with self.assertRaises(net_guard.UnsafeUrl):
            self._fetch("https://example.com/start")

        self.assertEqual(self.requested, ["https://example.com/start"])

    def test_follows_a_redirect_between_public_hosts(self):
        self._install_client(
            self._handler(
                {
                    "https://example.com/start": httpx.Response(
                        302, headers={"location": "https://cdn.example.org/file.txt"}
                    ),
                    "https://cdn.example.org/file.txt": httpx.Response(
                        200,
                        headers={"content-type": "text/plain"},
                        content=b"hello",
                    ),
                }
            )
        )

        acquired = self._fetch("https://example.com/start")

        self.assertEqual(acquired.content, b"hello")
        self.assertEqual(len(self.requested), 2)

    def test_rejects_too_many_redirects(self):
        routes = {
            f"https://example.com/{i}": httpx.Response(
                302, headers={"location": f"https://example.com/{i + 1}"}
            )
            for i in range(sources.MAX_REDIRECTS + 2)
        }
        self._install_client(self._handler(routes))

        with self.assertRaises(net_guard.UnsafeUrl):
            self._fetch("https://example.com/0")

    def test_token_is_not_forwarded_to_a_different_host(self):
        self._install_client(
            self._handler(
                {
                    "https://example.com/start": httpx.Response(
                        302, headers={"location": "https://cdn.example.org/file.txt"}
                    ),
                    "https://cdn.example.org/file.txt": httpx.Response(
                        200, content=b"ok"
                    ),
                }
            )
        )

        self._fetch("https://example.com/start", token="secret-token")

        self.assertEqual(
            self.auth_headers, ["Bearer secret-token", None]
        )

    def test_token_is_kept_on_a_same_host_redirect(self):
        self._install_client(
            self._handler(
                {
                    "https://example.com/a": httpx.Response(
                        302, headers={"location": "https://example.com/b"}
                    ),
                    "https://example.com/b": httpx.Response(200, content=b"ok"),
                }
            )
        )

        self._fetch("https://example.com/a", token="secret-token")

        self.assertEqual(
            self.auth_headers, ["Bearer secret-token", "Bearer secret-token"]
        )


class CrawlerSsrfTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(net_guard, "resolve_host_ips", side_effect=fake_resolve)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.requested: list[str] = []

    def _install_requests(self, routes):
        def fake_get(url, **kwargs):
            self.requested.append(url)
            if kwargs.get("allow_redirects") is not False:
                raise AssertionError("crawler must follow redirects manually")
            route = routes.get(url)
            if route is None:
                raise AssertionError(f"unexpected request to {url}")
            return route

        patcher = patch.object(crawler.requests, "get", side_effect=fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_crawl_page_refuses_non_http_url(self):
        self._install_requests({})

        self.assertEqual(crawler.crawl_page("file:///etc/passwd"), ("", ""))
        self.assertEqual(self.requested, [])

    def test_crawl_page_refuses_private_sitemap_entry(self):
        self._install_requests({})

        self.assertEqual(crawler.crawl_page("http://127.0.0.1:8000/api/websites"), ("", ""))
        self.assertEqual(self.requested, [])

    def test_crawl_page_refuses_redirect_to_private_host(self):
        self._install_requests(
            {
                "https://example.com/page": FakeRequestsResponse(
                    302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
                )
            }
        )

        self.assertEqual(crawler.crawl_page("https://example.com/page"), ("", ""))
        self.assertEqual(self.requested, ["https://example.com/page"])

    def test_extract_urls_from_sitemap_refuses_metadata_url(self):
        self._install_requests({})

        self.assertEqual(
            crawler.extract_urls_from_sitemap("http://169.254.169.254/sitemap.xml"), []
        )
        self.assertEqual(self.requested, [])

    def test_extract_urls_from_sitemap_refuses_private_redirect(self):
        self._install_requests(
            {
                "https://example.com/sitemap.xml": FakeRequestsResponse(
                    302, headers={"location": "http://10.0.0.5/sitemap.xml"}
                )
            }
        )

        self.assertEqual(
            crawler.extract_urls_from_sitemap("https://example.com/sitemap.xml"), []
        )
        self.assertEqual(self.requested, ["https://example.com/sitemap.xml"])

    def test_public_sitemap_still_works(self):
        self._install_requests(
            {
                "https://example.com/sitemap.xml": FakeRequestsResponse(
                    200,
                    content=(
                        b"<urlset><url><loc>https://example.com/a</loc></url>"
                        b"<url><loc>https://example.com/b</loc></url></urlset>"
                    ),
                )
            }
        )

        self.assertEqual(
            crawler.extract_urls_from_sitemap("https://example.com/sitemap.xml"),
            ["https://example.com/a", "https://example.com/b"],
        )

    def test_public_page_still_crawls(self):
        self._install_requests(
            {
                "https://example.com/a": FakeRequestsResponse(
                    200,
                    content=b"<html><head><title>Hello</title></head>"
                    b"<body><p>Some body text about widgets.</p></body></html>",
                )
            }
        )

        title, text = crawler.crawl_page("https://example.com/a")

        self.assertEqual(title, "Hello")
        self.assertIn("Some body text about widgets.", text)


class UploadEndpointSsrfTests(unittest.TestCase):
    def test_unsafe_url_returns_400(self):
        app = FastAPI()
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid4())
        client = TestClient(app)

        class UnsafeProvider:
            async def acquire(self, ref, token=None):
                raise net_guard.UnsafeUrl(
                    "'169.254.169.254' resolves to a non-public address"
                )

        with patch.object(upload_api, "get_provider", return_value=UnsafeProvider()):
            response = client.post(
                "/api/uploads/url",
                json={"url": "http://169.254.169.254/latest/meta-data/"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("non-public", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
