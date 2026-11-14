import hashlib
import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api import routes


class WidgetAssetTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def test_served_with_a_short_cache_and_a_version(self):
        response = self.client.get("/widget.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])
        self.assertIn("max-age=300", response.headers["cache-control"])
        self.assertIn("public", response.headers["cache-control"])

        with open(routes.WIDGET_JS_PATH, "rb") as handle:
            expected = hashlib.sha256(handle.read()).hexdigest()[:8]
        self.assertEqual(response.headers["x-widget-version"], expected)

    def test_version_query_is_accepted_and_ignored_for_content(self):
        plain = self.client.get("/widget.js")
        versioned = self.client.get("/widget.js", params={"v": "deadbeef"})

        self.assertEqual(versioned.status_code, 200)
        self.assertEqual(versioned.content, plain.content)
        # Same content hash for both URLs; only the URL differs, which is what
        # makes the query a cache key.
        self.assertEqual(
            versioned.headers["x-widget-version"],
            plain.headers["x-widget-version"],
        )

    def test_version_changes_when_the_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "widget.js")
            with open(path, "wb") as handle:
                handle.write(b"first")
            first = routes.widget_version(path)

            with open(path, "wb") as handle:  # same mtime is fine: size differs
                handle.write(b"second-version")
            second = routes.widget_version(path)

        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{8}$")

    def test_version_is_stable_for_an_unchanged_file(self):
        self.assertEqual(routes.widget_version(), routes.widget_version())


if __name__ == "__main__":
    unittest.main()
