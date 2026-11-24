"""V4-32: the Notion source provider, with every HTTP call stubbed.

A page is rendered to one markdown file (headings, lists, tables, code, quotes;
unknown blocks degrade to their text), a database to one file per page, both
capped and reported as added/total/truncated. The integration token is per
request: it only goes to `api.notion.com`, is refused on a redirect, and never
appears in an error, a log record or a response body. A rejected token is a
clear 401/400 and stores nothing.
"""

import asyncio
import itertools
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_gpt.app.api import upload as upload_api
from site_gpt.app.core.auth import get_current_user
from site_gpt.app.db.session import get_db
from site_gpt.app.services import sources
from site_gpt.app.services.parse import extract_text_from_file

PAGE_ID = "11111111111111111111111111111111"
DASHED_PAGE_ID = "11111111-1111-1111-1111-111111111111"
DB_ID = "22222222222222222222222222222222"
DB_VIEW_ID = "33333333333333333333333333333333"
TOKEN = "secret_notion_token_123"

_ids = itertools.count()


def rt(text, *, bold=False, italic=False, code=False, strike=False, href=None):
    return {
        "type": "text",
        "plain_text": text,
        "text": {"content": text},
        "annotations": {
            "bold": bold,
            "italic": italic,
            "strikethrough": strike,
            "underline": False,
            "code": code,
            "color": "default",
        },
        "href": href,
    }


def blk(kind, children=False, **data):
    return {
        "id": f"block{next(_ids):04d}",
        "type": kind,
        "has_children": children,
        kind: data,
    }


def para(text):
    return blk("paragraph", rich_text=[rt(text)])


def page(page_id, title, *, properties=None):
    if properties is None:
        properties = {"Name": {"type": "title", "title": [rt(title)]}}
    return {"id": page_id, "properties": properties}


class NotionStub:
    """Canned Notion API responses, recording every request it receives."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.routes = {}

    def route(self, method, path, response):
        self.routes[(method, path)] = response
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responder = self.routes.get((request.method, request.url.path))
        if responder is None:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return responder() if callable(responder) else responder

    def install(self):
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(self.handler)
            return original(*args, **kwargs)

        patcher = patch.object(sources.httpx, "AsyncClient", side_effect=factory)
        patcher.start()
        return patcher

    @property
    def hosts(self):
        return {request.url.host for request in self.requests}


def ok(payload):
    return lambda: httpx.Response(200, json=payload)


def children_page(*blocks):
    return lambda: httpx.Response(
        200, json={"results": list(blocks), "has_more": False, "next_cursor": None}
    )


class NotionProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stub = NotionStub()
        self.addCleanup(self.stub.install().stop)

    def test_a_page_is_rendered_to_markdown(self):
        parent = blk("bulleted_list_item", children=True, rich_text=[rt("parent")])
        table = blk("table", children=True, table_width=2)
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", ok(page(PAGE_ID, "My Page"))
        ).route(
            "GET",
            f"/v1/blocks/{PAGE_ID}/children",
            children_page(
                blk("heading_1", rich_text=[rt("Intro")]),
                blk(
                    "paragraph",
                    rich_text=[
                        rt("hello "),
                        rt("bold", bold=True),
                        rt(" link", href="https://example.com"),
                    ],
                ),
                parent,
                blk("numbered_list_item", rich_text=[rt("first")]),
                blk("to_do", checked=True, rich_text=[rt("done")]),
                blk("quote", rich_text=[rt("quoted")]),
                blk("code", language="python", rich_text=[rt("print(1)")]),
                blk("divider"),
                blk("callout", rich_text=[rt("note")]),
                table,
                blk("unsupported_thing", rich_text=[rt("loose text")]),
            ),
        ).route(
            "GET",
            f"/v1/blocks/{parent['id']}/children",
            children_page(blk("bulleted_list_item", rich_text=[rt("child")])),
        ).route(
            "GET",
            f"/v1/blocks/{table['id']}/children",
            children_page(
                blk("table_row", cells=[[rt("a")], [rt("b")]]),
                blk("table_row", cells=[[rt("1")], [rt("2")]]),
            ),
        )

        files, total, truncated, total_exact = asyncio.run(
            sources.NotionProvider().acquire_many(
                f"https://www.notion.so/My-Page-{PAGE_ID}", TOKEN
            )
        )

        self.assertEqual((total, truncated), (1, False))
        self.assertTrue(total_exact)
        self.assertEqual(files[0].filename, "my-page.md")
        self.assertEqual(files[0].source_ref, f"https://www.notion.so/{PAGE_ID}")
        body = files[0].content.decode("utf-8")
        for expected in (
            "# My Page",
            f"Source: https://www.notion.so/{PAGE_ID}",
            "## Intro",
            "hello **bold**[ link](https://example.com)",
            "- parent",
            "  - child",
            "1. first",
            "- [x] done",
            "> quoted",
            "```python",
            "print(1)",
            "---",
            "> note",
            "| a | b |",
            "| --- | --- |",
            "| 1 | 2 |",
            "loose text",
        ):
            self.assertIn(expected, body)

    def test_the_block_cap_stops_at_notion_max_blocks(self):
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", ok(page(PAGE_ID, "Long"))
        ).route(
            "GET",
            f"/v1/blocks/{PAGE_ID}/children",
            children_page(*[para(f"paragraph {i}") for i in range(1, 6)]),
        )

        with patch.object(sources, "NOTION_MAX_BLOCKS", 3):
            files, total, truncated, total_exact = asyncio.run(
                sources.NotionProvider().acquire_many(PAGE_ID, TOKEN)
            )

        body = files[0].content.decode("utf-8")
        self.assertIn("paragraph 3", body)
        self.assertNotIn("paragraph 4", body)
        self.assertNotIn("paragraph 5", body)
        self.assertIn("Truncated", body)
        self.assertIn("first 3 blocks", body)
        self.assertEqual((total, truncated), (1, False))
        self.assertTrue(total_exact)

    def test_a_database_becomes_one_file_per_page_capped(self):
        pages = [
            page("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "Alpha"),
            page("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "Beta"),
            page("cccccccccccccccccccccccccccccccc", "Gamma"),
        ]
        self.stub.route(
            "POST",
            f"/v1/databases/{DB_ID}/query",
            lambda: httpx.Response(
                200,
                json={"results": pages, "has_more": False, "next_cursor": None},
            ),
        )
        for item, name in zip(pages[:2], ("Alpha", "Beta")):
            self.stub.route(
                "GET",
                f"/v1/blocks/{item['id']}/children",
                children_page(para(f"{name} body")),
            )

        with patch.object(sources, "NOTION_MAX_PAGES", 2):
            files, total, truncated, total_exact = asyncio.run(
                sources.NotionProvider().acquire_many(
                    f"https://www.notion.so/{DB_ID}?v={DB_VIEW_ID}", TOKEN
                )
            )

        self.assertEqual([f.filename for f in files], ["alpha.md", "beta.md"])
        self.assertEqual((total, truncated), (3, True))
        self.assertTrue(total_exact)
        self.assertIn("Alpha body", files[0].content.decode("utf-8"))

    def _windows(self, *windows):
        """Route the database query to these responses in order, one per page."""
        remaining = [
            lambda response=response: response for response in windows
        ]

        def next_page():
            self.assertTrue(remaining, "the query was paged past its last page")
            return remaining.pop(0)()

        return self.stub.route("POST", f"/v1/databases/{DB_ID}/query", next_page)

    def _query_requests(self):
        return [
            request
            for request in self.stub.requests
            if request.url.path == f"/v1/databases/{DB_ID}/query"
        ]

    def test_the_total_counts_every_query_page_past_the_cap(self):
        ids = [f"{n:032x}" for n in range(1, 151)]
        self._windows(
            httpx.Response(
                200,
                json={
                    "results": [page(pid, f"Row {n}") for n, pid in enumerate(ids[:100], 1)],
                    "has_more": True,
                    "next_cursor": "cursor-2",
                },
            ),
            httpx.Response(
                200,
                json={
                    "results": [
                        page(pid, f"Row {n}") for n, pid in enumerate(ids[100:], 101)
                    ],
                    "has_more": False,
                    "next_cursor": None,
                },
            ),
        )
        for n, pid in enumerate(ids[:25], 1):
            self.stub.route(
                "GET",
                f"/v1/blocks/{pid}/children",
                children_page(para(f"body {n}")),
            )

        with patch.object(sources, "NOTION_MAX_PAGES", 25):
            files, total, truncated, total_exact = asyncio.run(
                sources.NotionProvider().acquire_many(
                    f"https://www.notion.so/{DB_ID}?v={DB_VIEW_ID}", TOKEN
                )
            )

        # 150 pages really exist, so "25 of 150" — not "25 of 100".
        self.assertEqual(len(files), 25)
        self.assertEqual((total, truncated), (150, True))
        self.assertTrue(total_exact)  # two windows is inside the count budget
        queries = self._query_requests()
        self.assertEqual(len(queries), 2)
        self.assertEqual(json.loads(queries[1].content)["start_cursor"], "cursor-2")
        # Counting past the cap reads page rows only: no blocks are fetched
        # for a page the import never creates.
        fetched = {request.url.path for request in self.stub.requests}
        self.assertNotIn(f"/v1/blocks/{ids[25]}/children", fetched)

    def test_a_database_spanning_query_pages_imports_every_page(self):
        first = [page(f"{n:032x}", f"Row {n}") for n in range(1, 6)]
        second = [page(f"{n:032x}", f"Row {n}") for n in range(6, 8)]
        self._windows(
            httpx.Response(
                200,
                json={"results": first, "has_more": True, "next_cursor": "more"},
            ),
            httpx.Response(
                200,
                json={"results": second, "has_more": False, "next_cursor": None},
            ),
        )
        for item in first + second:
            self.stub.route(
                "GET",
                f"/v1/blocks/{item['id']}/children",
                children_page(para(f"body of {item['id']}")),
            )

        with patch.object(sources, "NOTION_MAX_PAGES", 25):
            files, total, truncated, total_exact = asyncio.run(
                sources.NotionProvider().acquire_many(
                    f"https://www.notion.so/{DB_ID}?v={DB_VIEW_ID}", TOKEN
                )
            )

        self.assertEqual(len(files), 7)
        self.assertEqual([f.filename for f in files[:2]], ["row-1.md", "row-2.md"])
        self.assertEqual((total, truncated), (7, False))
        self.assertTrue(total_exact)
        self.assertEqual(len(self._query_requests()), 2)
        # Both windows' blocks were fetched, so the count and the import agree.
        fetched = {request.url.path for request in self.stub.requests}
        for item in first + second:
            self.assertIn(f"/v1/blocks/{item['id']}/children", fetched)

    def test_the_count_stops_at_the_budget_and_reports_a_lower_bound(self):
        # Three query windows; cap 5, counting budget 2 windows. Counting must
        # stop there instead of reading a huge database to its end, and say so.
        windows = [
            [page(f"{n:032x}", f"Row {n}") for n in range(1, 4)],
            [page(f"{n:032x}", f"Row {n}") for n in range(4, 7)],
            [page(f"{n:032x}", f"Row {n}") for n in range(7, 10)],
        ]
        self._windows(
            *[
                httpx.Response(
                    200,
                    json={
                        "results": rows,
                        "has_more": index < len(windows) - 1,
                        "next_cursor": (
                            None if index == len(windows) - 1 else "next"
                        ),
                    },
                )
                for index, rows in enumerate(windows)
            ]
        )
        for n in range(1, 6):
            self.stub.route(
                "GET",
                f"/v1/blocks/{n:032x}/children",
                children_page(para(f"body {n}")),
            )

        with patch.object(sources, "NOTION_MAX_PAGES", 5), patch.object(
            sources, "NOTION_MAX_COUNT_PAGES", 2
        ):
            files, total, truncated, total_exact = asyncio.run(
                sources.NotionProvider().acquire_many(
                    f"https://www.notion.so/{DB_ID}?v={DB_VIEW_ID}", TOKEN
                )
            )

        self.assertEqual(len(files), 5)
        # Two windows of three rows were read, so 6 is a lower bound, not 9.
        self.assertEqual((total, truncated, total_exact), (6, True, False))
        self.assertEqual(len(self._query_requests()), 2)
        # The pages beyond the import cap are never rendered or fetched.
        fetched = {request.url.path for request in self.stub.requests}
        self.assertNotIn(f"/v1/blocks/{7:032x}/children", fetched)

    def test_a_bare_id_asks_the_api_whether_it_is_a_page(self):
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", ok(page(PAGE_ID, "Bare"))
        ).route(
            "GET",
            f"/v1/blocks/{PAGE_ID}/children",
            children_page(para("bare body")),
        )

        files, _, _, _ = asyncio.run(
            sources.NotionProvider().acquire_many(PAGE_ID, TOKEN)
        )

        self.assertEqual(files[0].filename, "bare.md")

    def test_a_bare_id_falls_back_to_a_database(self):
        self.stub.route(
            "GET", f"/v1/pages/{DB_ID}", lambda: httpx.Response(404)
        ).route(
            "GET", f"/v1/databases/{DB_ID}", lambda: httpx.Response(200, json={})
        ).route(
            "POST",
            f"/v1/databases/{DB_ID}/query",
            lambda: httpx.Response(
                200,
                json={
                    "results": [page("dddddddddddddddddddddddddddddddd", "Row")],
                    "has_more": False,
                    "next_cursor": None,
                },
            ),
        ).route(
            "GET",
            "/v1/blocks/dddddddddddddddddddddddddddddddd/children",
            children_page(para("row body")),
        )

        files, total, truncated, total_exact = asyncio.run(
            sources.NotionProvider().acquire_many(DB_ID, TOKEN)
        )

        self.assertEqual([f.filename for f in files], ["row.md"])
        self.assertEqual((total, truncated), (1, False))
        self.assertTrue(total_exact)

    def test_a_rejected_token_is_a_clear_auth_error_without_the_token(self):
        self.stub.route("GET", f"/v1/pages/{PAGE_ID}", lambda: httpx.Response(401))

        with self.assertRaises(sources.SourceAuthError) as caught:
            asyncio.run(sources.NotionProvider().acquire_many(PAGE_ID, TOKEN))

        self.assertIn("rejected the integration token", str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_the_token_never_reaches_a_log_record(self):
        records: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        self.stub.route("GET", f"/v1/pages/{PAGE_ID}", lambda: httpx.Response(401))

        with self.assertRaises(sources.SourceAuthError):
            asyncio.run(sources.NotionProvider().acquire_many(PAGE_ID, TOKEN))

        self.assertNotIn(TOKEN, "\n".join(records))

    def test_the_token_is_only_ever_sent_to_the_notion_api_host(self):
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", ok(page(PAGE_ID, "Doc"))
        ).route(
            "GET", f"/v1/blocks/{PAGE_ID}/children", children_page(para("body"))
        )

        asyncio.run(sources.NotionProvider().acquire_many(PAGE_ID, TOKEN))

        self.assertEqual(self.stub.hosts, {"api.notion.com"})
        self.assertTrue(self.stub.requests)
        for request in self.stub.requests:
            self.assertEqual(request.headers["authorization"], f"Bearer {TOKEN}")
            self.assertEqual(request.headers["notion-version"], "2022-06-28")

    def test_a_redirect_off_the_notion_api_is_refused(self):
        self.stub.route(
            "GET",
            f"/v1/pages/{PAGE_ID}",
            lambda: httpx.Response(
                302, headers={"location": "https://evil.example/steal"}
            ),
        )

        with self.assertRaises(sources.SourceRefError) as caught:
            asyncio.run(sources.NotionProvider().acquire_many(PAGE_ID, TOKEN))

        self.assertIn("redirect", str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(self.stub.hosts, {"api.notion.com"})

    def test_a_public_page_is_refused_without_any_request(self):
        with self.assertRaises(sources.SourceRefError):
            asyncio.run(
                sources.NotionProvider().acquire_many(
                    "https://example.com/not-a-notion-page", TOKEN
                )
            )

        self.assertEqual(self.stub.requests, [])

    def test_a_missing_token_is_refused_before_any_request(self):
        with self.assertRaises(sources.SourceAuthError):
            asyncio.run(sources.NotionProvider().acquire_many(PAGE_ID, "  "))

        self.assertEqual(self.stub.requests, [])

    def test_the_markdown_flows_through_extract_text_from_file(self):
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", ok(page(PAGE_ID, "Doc"))
        ).route(
            "GET", f"/v1/blocks/{PAGE_ID}/children", children_page(para("the body"))
        )

        files, _, _, _ = asyncio.run(
            sources.NotionProvider().acquire_many(PAGE_ID, TOKEN)
        )

        path = os.path.join(self.tmp.name, files[0].filename)
        with open(path, "wb") as fh:
            fh.write(files[0].content)

        text = extract_text_from_file(path)
        self.assertIn("Doc", text)
        self.assertIn("the body", text)

    def test_provider_is_registered(self):
        self.assertIsInstance(
            sources.get_provider("notion"), sources.NotionProvider
        )


class NotionRefTests(unittest.TestCase):
    def test_page_urls_and_ids(self):
        self.assertEqual(
            sources.parse_notion_ref(f"https://www.notion.so/My-Page-{PAGE_ID}"),
            ("page", PAGE_ID),
        )
        self.assertEqual(
            sources.parse_notion_ref(f"https://team.notion.site/Title-{PAGE_ID}"),
            ("page", PAGE_ID),
        )
        self.assertEqual(
            sources.parse_notion_ref(f"https://www.notion.so/{PAGE_ID}"),
            ("page", PAGE_ID),
        )

    def test_a_view_url_is_a_database(self):
        self.assertEqual(
            sources.parse_notion_ref(
                f"https://www.notion.so/Team-{DB_ID}?v={DB_VIEW_ID}"
            ),
            ("database", DB_ID),
        )

    def test_bare_ids_are_resolved_by_the_api(self):
        self.assertEqual(sources.parse_notion_ref(PAGE_ID), ("auto", PAGE_ID))
        self.assertEqual(
            sources.parse_notion_ref(DASHED_PAGE_ID), ("auto", PAGE_ID)
        )

    def test_non_notion_links_and_idless_pages_are_refused(self):
        for ref in (
            "https://example.com/abc",
            "https://www.notion.so/no-id-here",
            "",
        ):
            with self.subTest(ref=ref):
                with self.assertRaises(sources.SourceRefError):
                    sources.parse_notion_ref(ref)


class NotionEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid4(), role="admin")
        self.client = TestClient(app)
        self.stub = NotionStub()
        self.addCleanup(self.stub.install().stop)
        self.addCleanup(self._remove_written_files)
        self.uploads_before = self._upload_files()

    def _upload_files(self):
        return set(os.listdir("uploads")) if os.path.isdir("uploads") else set()

    def _remove_written_files(self):
        for name in self._upload_files() - self.uploads_before:
            os.remove(os.path.join("uploads", name))

    def _post(self, ref, token=TOKEN):
        return self.client.post(
            "/api/uploads/notion", json={"url": ref, "token": token}
        )

    def test_a_successful_import_uses_the_shared_file_shape(self):
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", ok(page(PAGE_ID, "My Page"))
        ).route(
            "GET", f"/v1/blocks/{PAGE_ID}/children", children_page(para("body"))
        )

        response = self._post(f"https://www.notion.so/My-Page-{PAGE_ID}")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            (body["added"], body["total"], body["truncated"], body["total_exact"]),
            (1, 1, False, True),
        )
        item = body["files"][0]
        self.assertEqual(
            set(item),
            {
                "file_id",
                "filename",
                "file_url",
                "file_size",
                "file_type",
                "source",
                "source_ref",
            },
        )
        self.assertEqual(item["source"], "notion")
        self.assertEqual(item["filename"], "my-page.md")
        self.assertEqual(
            item["source_ref"], f"https://www.notion.so/{PAGE_ID}"
        )
        self.assertNotIn(TOKEN, response.text)

    def test_a_rejected_token_is_a_401_and_stores_nothing(self):
        self.stub.route("GET", f"/v1/pages/{PAGE_ID}", lambda: httpx.Response(403))

        response = self._post(PAGE_ID)

        self.assertEqual(response.status_code, 401, response.text)
        self.assertIn("rejected the integration token", response.json()["detail"])
        self.assertNotIn(TOKEN, response.text)
        self.assertEqual(self._upload_files() - self.uploads_before, set())

    def test_a_missing_notion_page_is_a_400_and_stores_nothing(self):
        self.stub.route(
            "GET", f"/v1/pages/{PAGE_ID}", lambda: httpx.Response(404)
        ).route("GET", f"/v1/databases/{PAGE_ID}", lambda: httpx.Response(404))

        response = self._post(PAGE_ID)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("404", response.json()["detail"])
        self.assertEqual(self._upload_files() - self.uploads_before, set())

    def test_a_non_notion_link_is_a_400_and_makes_no_request(self):
        response = self._post("https://example.com/abc")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.stub.requests, [])
        self.assertEqual(self._upload_files() - self.uploads_before, set())


if __name__ == "__main__":
    unittest.main()
