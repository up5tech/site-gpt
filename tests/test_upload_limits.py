import asyncio
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


class FakeResponse:
    """Minimal stand-in for a streaming httpx.Response."""

    def __init__(self, chunks, content_length=None):
        self._chunks = chunks
        self.headers = (
            {"content-length": str(content_length)}
            if content_length is not None
            else {}
        )
        self.consumed = False

    async def aiter_bytes(self):
        self.consumed = True
        for chunk in self._chunks:
            yield chunk


class FakeUpload:
    """Stand-in for fastapi's UploadFile with controllable `size`."""

    def __init__(self, data: bytes, size=None):
        self._data = data
        self._pos = 0
        self.size = len(data) if size is None else size

    async def read(self, n: int) -> bytes:
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


class ReadLimitedTests(unittest.TestCase):
    def test_reads_content_within_the_limit(self):
        response = FakeResponse([b"abc", b"def"])

        with patch.object(sources, "MAX_UPLOAD_BYTES", 10):
            self.assertEqual(asyncio.run(sources.read_limited(response)), b"abcdef")

    def test_rejects_while_streaming_when_body_exceeds_the_limit(self):
        response = FakeResponse([b"aaaa", b"bbbb", b"cccc"])

        with patch.object(sources, "MAX_UPLOAD_BYTES", 10), patch.object(
            sources, "MAX_UPLOAD_MB", 1
        ):
            with self.assertRaises(sources.FileTooLarge):
                asyncio.run(sources.read_limited(response))

    def test_exactly_at_the_limit_is_accepted(self):
        response = FakeResponse([b"a" * 8])

        with patch.object(sources, "MAX_UPLOAD_BYTES", 8):
            self.assertEqual(len(asyncio.run(sources.read_limited(response))), 8)

    def test_oversized_content_length_rejects_without_reading_the_body(self):
        response = FakeResponse([b"a"], content_length=10_000)

        with patch.object(sources, "MAX_UPLOAD_BYTES", 100), patch.object(
            sources, "MAX_UPLOAD_MB", 1
        ):
            with self.assertRaises(sources.FileTooLarge):
                asyncio.run(sources.read_limited(response))

        self.assertFalse(response.consumed)

    def test_malformed_content_length_falls_back_to_streaming(self):
        response = FakeResponse([b"abc"])
        response.headers["content-length"] = "not-a-number"

        with patch.object(sources, "MAX_UPLOAD_BYTES", 10):
            self.assertEqual(asyncio.run(sources.read_limited(response)), b"abc")


class StreamToDiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "upload.bin")

    def test_writes_file_within_the_limit(self):
        upload = FakeUpload(b"hello world")

        with patch.object(upload_api, "MAX_UPLOAD_BYTES", 1024):
            written = asyncio.run(upload_api._stream_to_disk(upload, self.path))

        self.assertEqual(written, 11)
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"hello world")

    def test_rejects_and_removes_partial_file_when_too_big(self):
        upload = FakeUpload(b"x" * 5000, size=None)  # size unknown to the server

        with patch.object(upload_api, "MAX_UPLOAD_BYTES", 1024), patch.object(
            upload_api, "MAX_UPLOAD_MB", 1
        ):
            with self.assertRaises(Exception) as ctx:
                asyncio.run(upload_api._stream_to_disk(upload, self.path))

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertFalse(os.path.exists(self.path))

    def test_declared_size_over_limit_is_rejected_before_writing(self):
        upload = FakeUpload(b"tiny", size=999_999)

        with patch.object(upload_api, "MAX_UPLOAD_BYTES", 1024), patch.object(
            upload_api, "MAX_UPLOAD_MB", 1
        ):
            with self.assertRaises(Exception) as ctx:
                asyncio.run(upload_api._stream_to_disk(upload, self.path))

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertFalse(os.path.exists(self.path))


class UploadEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid4())
        self.client = TestClient(app)

    def test_oversized_upload_returns_413_and_writes_nothing(self):
        before = set(os.listdir("uploads")) if os.path.isdir("uploads") else set()

        with patch.object(upload_api, "MAX_UPLOAD_BYTES", 10), patch.object(
            upload_api, "MAX_UPLOAD_MB", 1
        ):
            response = self.client.post(
                "/api/uploads/", files={"file": ("big.txt", b"x" * 100)}
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("1 MB", response.json()["detail"])
        after = set(os.listdir("uploads")) if os.path.isdir("uploads") else set()
        self.assertEqual(after - before, set())

    def test_an_ooxml_mime_type_fits_the_attachment_column(self):
        # `attachments.file_type` is VARCHAR(50) while the OOXML types are 71
        # characters; storing one verbatim was a DataError on Postgres (the
        # V4-3G gate's .pptx import), so the value is clamped to the column.
        db = MagicMock()
        app = FastAPI()
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid4())
        client = TestClient(app)
        before = set(os.listdir("uploads")) if os.path.isdir("uploads") else set()
        mime = (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        )
        try:
            response = client.post(
                "/api/uploads/", files={"file": ("deck.pptx", b"PK\x03\x04", mime)}
            )
        finally:
            after = set(os.listdir("uploads")) if os.path.isdir("uploads") else set()
            for name in after - before:
                os.remove(os.path.join("uploads", name))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreater(len(mime), upload_api.FILE_TYPE_MAX)
        stored = db.add.call_args.args[0]
        self.assertEqual(stored.file_type, mime[: upload_api.FILE_TYPE_MAX])
        self.assertEqual(response.json()["file_type"], mime[: upload_api.FILE_TYPE_MAX])

    def test_remote_import_over_limit_returns_413(self):
        class OversizedProvider:
            async def acquire(self, ref, token=None):
                raise sources.FileTooLarge("too big")

        with patch.object(
            upload_api, "get_provider", return_value=OversizedProvider()
        ), patch.object(upload_api, "MAX_UPLOAD_MB", 1):
            response = self.client.post(
                "/api/uploads/url", json={"url": "https://example.com/big.zip"}
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("1 MB", response.json()["detail"])


class UrlProviderStreamingTests(unittest.TestCase):
    def test_url_provider_uses_a_streaming_read(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url)
            return httpx.Response(200, content=b"0123456789", headers={"content-type": "text/plain"})

        original = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        provider = sources.UrlProvider()
        with patch.object(sources, "MAX_UPLOAD_BYTES", 4), patch.object(
            sources, "MAX_UPLOAD_MB", 1
        ), patch.object(sources.httpx, "AsyncClient", side_effect=client_factory):
            with self.assertRaises(sources.FileTooLarge):
                asyncio.run(provider.acquire("https://example.com/file.bin"))

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
