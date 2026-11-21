"""The hosted chat page (V4-50).

`GET /chat/{website_id}` is the first-party URL for a bot: one HTML document
that loads the same `widget.js` an embed does, with `displayMode: 'page'`. These
tests pin the document it serves (config keys, same-origin API URL, versioned
script, title, favicon, noindex), the 404 for an unknown or malformed id, and
that a disabled website still gets the page — the widget's own 403 from
`/api/widget-config` is what shows the unavailable state.
"""

import os
import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from site_gpt.app import models
from site_gpt.app.api import chat_page, routes
from site_gpt.app.db.base import Base
from site_gpt.app.db.session import get_db

TABLES = [
    models.Company.__table__,
    models.Website.__table__,
    models.Setting.__table__,
]

LOGO = "https://cdn.example.com/bot-logo.png"


class ChatPageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=TABLES)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.company = models.Company(id=uuid4(), name="Acme")
        self.website = models.Website(
            id=uuid4(),
            url="https://customer.example.com",
            name="Customer",
            description="",
            site_map_url="https://customer.example.com/sitemap.xml",
            company_id=self.company.id,
            status="active",
        )
        self.db.add_all(
            [
                self.company,
                self.website,
                models.Setting(
                    key="assistant_name", value="Ada Bot", company_id=self.company.id
                ),
                models.Setting(
                    key="widget_logo_url", value=LOGO, company_id=self.company.id
                ),
            ]
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(chat_page.router)

        def override_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def get(self, website_id=None):
        return self.client.get(f"/chat/{website_id or self.website.id}")

    def set_setting(self, key, value):
        row = (
            self.db.query(models.Setting)
            .filter(
                models.Setting.company_id == self.company.id,
                models.Setting.key == key,
            )
            .first()
        )
        row.value = value
        self.db.commit()

    # --- the document -------------------------------------------------------

    def test_it_serves_an_html_page(self):
        response = self.get()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertTrue(response.text.lstrip().startswith("<!doctype html>"))

    def test_it_boots_the_widget_in_page_mode_from_the_visitor_origin(self):
        body = self.get().text

        self.assertIn("window.ChatWidgetConfig", body)
        self.assertIn("apiUrl: window.location.origin", body)
        self.assertIn(f'website_id: "{self.website.id}"', body)
        self.assertIn("displayMode: 'page'", body)
        # The versioned URL is what makes a deployed fix reach visitors.
        self.assertIn(f"/widget.js?v={routes.widget_version()}", body)

    def test_the_api_base_is_never_baked_in_by_the_server(self):
        # Behind a reverse proxy the Host/scheme this process sees is not the URL
        # the visitor used, so the browser's own origin must be the only source.
        body = self.client.get(
            f"/chat/{self.website.id}",
            headers={"host": "bot.customer.example"},
        ).text

        self.assertIn("apiUrl: window.location.origin", body)
        for leaked in ("testserver", "bot.customer.example", "localhost"):
            self.assertNotIn(leaked, body, leaked)

    def test_title_and_favicon_come_from_the_widget_settings(self):
        body = self.get().text

        self.assertIn("<title>Ada Bot</title>", body)
        self.assertIn(f'<link rel="icon" href="{LOGO}" />', body)

    def test_the_page_is_noindex(self):
        body = self.get().text

        self.assertIn('<meta name="robots" content="noindex, nofollow" />', body)

    def test_the_title_is_escaped(self):
        self.set_setting("assistant_name", "<script>alert(1)</script>")

        body = self.get().text

        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn(
            "<title>&lt;script&gt;alert(1)&lt;/script&gt;</title>", body
        )

    def test_a_non_https_logo_gets_no_favicon(self):
        self.set_setting("widget_logo_url", "javascript:alert(1)")

        body = self.get().text

        self.assertNotIn('rel="icon"', body)

    def test_a_missing_assistant_name_falls_back(self):
        self.set_setting("assistant_name", "   ")

        self.assertIn("<title>Chat</title>", self.get().text)

    # --- the tenant rule ----------------------------------------------------

    def test_an_unknown_website_is_a_404(self):
        response = self.get(uuid4())

        self.assertEqual(response.status_code, 404, response.text)

    def test_a_malformed_id_is_a_404(self):
        response = self.client.get("/chat/not-a-uuid")

        self.assertEqual(response.status_code, 404, response.text)

    def test_a_disabled_website_gets_the_unavailable_notice_instead_of_the_chat(self):
        # `ensure_website_active` changes the page: no widget and no config
        # request, just the notice an embed shows for the same state.
        self.website.status = "inactive"
        self.db.commit()

        response = self.get()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn(chat_page.UNAVAILABLE_MESSAGE, response.text)
        self.assertIn("class=\"notice\"", response.text)
        self.assertNotIn("window.ChatWidgetConfig", response.text)
        self.assertNotIn("/widget.js", response.text)

    def test_a_disabled_website_keeps_the_chrome_and_the_noindex(self):
        self.website.status = "inactive"
        self.db.commit()

        body = self.get().text

        self.assertIn("<title>Ada Bot</title>", body)
        self.assertIn(f'<link rel="icon" href="{LOGO}" />', body)
        self.assertIn('<meta name="robots" content="noindex, nofollow" />', body)


class PageHelpersTests(unittest.TestCase):
    def test_the_notice_is_the_widget_s_own_message(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src",
            "site_gpt",
            "app",
            "scripts",
            "widget.js",
        )
        with open(path, encoding="utf-8") as handle:
            self.assertIn(chat_page.UNAVAILABLE_MESSAGE, handle.read())

    def test_favicon_accepts_only_absolute_https_urls(self):
        self.assertEqual(chat_page.favicon_url(LOGO), LOGO)
        for refused in (
            "",
            None,
            "http://cdn.example.com/logo.png",
            "data:image/png;base64,AAAA",
            'https://cdn.example.com/a"onload="x',
            "javascript:alert(1)",
            "https://",
        ):
            self.assertEqual(chat_page.favicon_url(refused), "", refused)

    def test_title_strips_and_falls_back(self):
        self.assertEqual(chat_page.page_title("  Ada  "), "Ada")
        self.assertEqual(chat_page.page_title(""), chat_page.FALLBACK_TITLE)
        self.assertEqual(chat_page.page_title(None), chat_page.FALLBACK_TITLE)


if __name__ == "__main__":
    unittest.main()
