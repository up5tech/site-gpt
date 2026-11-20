"""V4-31: the YouTube source provider, with every HTTP/library call stubbed.

The provider turns a video, playlist or channel into one markdown attachment per
video (title, watch URL, captions), capped at YOUTUBE_MAX_VIDEOS and reported as
added/total/truncated. A video without captions must be a clear 400 naming it —
never a silently empty document — and an oversized synthesized file is refused
like any other over-limit import.
"""

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
from site_gpt.app.services.parse import extract_text_from_file

VIDEO_A = "aaaaaaaaaaa"
VIDEO_B = "bbbbbbbbbbb"
VIDEO_C = "ccccccccccc"


class FakeSnippet:
    def __init__(self, text):
        self.text = text


class FakeFetched:
    def __init__(self, text):
        self._snippets = [FakeSnippet(text)]

    def __iter__(self):
        return iter(self._snippets)


class FakeTranscript:
    def __init__(self, text, *, is_generated=False):
        self._text = text
        self.is_generated = is_generated

    def fetch(self):
        return FakeFetched(self._text)


class FakeTranscriptApi:
    """Stands in for youtube_transcript_api.YouTubeTranscriptApi."""

    def __init__(self, tracks, error=None):
        self._tracks = tracks
        self._error = error

    def list(self, video_id):
        if self._error:
            raise self._error
        return list(self._tracks)


def http_stub(routes):
    """An httpx.AsyncClient factory answering from `routes` by URL prefix."""
    original = httpx.AsyncClient

    def handler(request):
        url = str(request.url)
        for prefix, factory in routes.items():
            if url.startswith(prefix):
                return factory()
        raise AssertionError(f"unexpected request: {url}")

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    return factory


def oembed(title="Intro to RAG"):
    return lambda: httpx.Response(200, json={"title": title})


def html_page(ids):
    return lambda: httpx.Response(
        200, text="".join(f'<a href="/watch?v={vid}">v</a>' for vid in ids)
    )


class YoutubeProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _acquire(self, ref, *, routes, api, max_videos=None, max_bytes=10_000):
        stack = [
            patch.object(sources.httpx, "AsyncClient", side_effect=http_stub(routes)),
            patch(
                "youtube_transcript_api.YouTubeTranscriptApi",
                return_value=api,
            ),
            patch.object(sources, "MAX_UPLOAD_BYTES", max_bytes),
        ]
        if max_videos is not None:
            stack.append(patch.object(sources, "YOUTUBE_MAX_VIDEOS", max_videos))
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)
        return asyncio.run(sources.YoutubeProvider().acquire_many(ref))

    def test_a_single_video_becomes_one_markdown_file(self):
        files, total, truncated = self._acquire(
            f"https://youtu.be/{VIDEO_A}",
            routes={"https://www.youtube.com/oembed": oembed()},
            api=FakeTranscriptApi([FakeTranscript("hello caption")]),
        )

        self.assertEqual((total, truncated), (1, False))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "intro-to-rag.md")
        self.assertEqual(
            files[0].source_ref, f"https://www.youtube.com/watch?v={VIDEO_A}"
        )
        body = files[0].content.decode("utf-8")
        self.assertIn("# Intro to RAG", body)
        self.assertIn(f"Video: https://www.youtube.com/watch?v={VIDEO_A}", body)
        self.assertIn("hello caption", body)

    def test_a_bare_video_id_is_accepted(self):
        files, total, _ = self._acquire(
            VIDEO_A,
            routes={"https://www.youtube.com/oembed": oembed()},
            api=FakeTranscriptApi([FakeTranscript("caption")]),
        )

        self.assertEqual(total, 1)
        self.assertEqual(len(files), 1)

    def test_manual_captions_win_over_generated_ones(self):
        files, _, _ = self._acquire(
            f"https://www.youtube.com/watch?v={VIDEO_A}",
            routes={"https://www.youtube.com/oembed": oembed()},
            api=FakeTranscriptApi(
                [
                    FakeTranscript("auto generated words", is_generated=True),
                    FakeTranscript("hand written words", is_generated=False),
                ]
            ),
        )

        body = files[0].content.decode("utf-8")
        self.assertIn("hand written words", body)
        self.assertNotIn("auto generated words", body)

    def test_a_playlist_is_capped_and_reports_total_and_truncated(self):
        files, total, truncated = self._acquire(
            "https://www.youtube.com/playlist?list=PL123",
            routes={
                "https://www.youtube.com/playlist": html_page(
                    [VIDEO_A, VIDEO_B, VIDEO_C]
                ),
                "https://www.youtube.com/oembed": oembed("Episode"),
            },
            api=FakeTranscriptApi([FakeTranscript("caption")]),
            max_videos=2,
        )

        self.assertEqual(len(files), 2)
        self.assertEqual(total, 3)
        self.assertTrue(truncated)
        self.assertEqual(
            [f.source_ref.rsplit("=", 1)[-1] for f in files], [VIDEO_A, VIDEO_B]
        )

    def test_zero_disables_the_cap(self):
        # SITEMAP_SYNC_MAX_URLS=0 means "no cap"; the YouTube cap follows it
        # instead of slicing every playlist down to nothing.
        files, total, truncated = self._acquire(
            "https://www.youtube.com/playlist?list=PL123",
            routes={
                "https://www.youtube.com/playlist": html_page(
                    [VIDEO_A, VIDEO_B, VIDEO_C]
                ),
                "https://www.youtube.com/oembed": oembed("Episode"),
            },
            api=FakeTranscriptApi([FakeTranscript("caption")]),
            max_videos=0,
        )

        self.assertEqual(len(files), 3)
        self.assertEqual(total, 3)
        self.assertFalse(truncated)

    def test_a_channel_url_expands_its_videos_tab(self):
        files, total, truncated = self._acquire(
            "https://www.youtube.com/@somechannel",
            routes={
                "https://www.youtube.com/@somechannel/videos": html_page([VIDEO_A]),
                "https://www.youtube.com/oembed": oembed("Talk"),
            },
            api=FakeTranscriptApi([FakeTranscript("caption")]),
        )

        self.assertEqual((len(files), total, truncated), (1, 1, False))

    def test_a_video_without_captions_names_the_video(self):
        with self.assertRaises(sources.SourceRefError) as caught:
            self._acquire(
                f"https://youtu.be/{VIDEO_A}",
                routes={"https://www.youtube.com/oembed": oembed()},
                api=FakeTranscriptApi([], error=RuntimeError("TranscriptsDisabled")),
            )

        self.assertIn(VIDEO_A, str(caught.exception))
        self.assertIn("No captions", str(caught.exception))

    def test_an_oversized_synthesized_file_is_refused(self):
        with self.assertRaises(sources.FileTooLarge):
            self._acquire(
                f"https://youtu.be/{VIDEO_A}",
                routes={"https://www.youtube.com/oembed": oembed()},
                api=FakeTranscriptApi([FakeTranscript("x" * 500)]),
                max_bytes=64,
            )

    def test_a_non_youtube_url_is_refused_without_fetching(self):
        with self.assertRaises(sources.SourceRefError):
            asyncio.run(
                sources.YoutubeProvider().acquire_many("https://example.com/video")
            )

    def test_the_markdown_flows_through_extract_text_from_file(self):
        files, _, _ = self._acquire(
            f"https://youtu.be/{VIDEO_A}",
            routes={"https://www.youtube.com/oembed": oembed()},
            api=FakeTranscriptApi([FakeTranscript("the transcript body")]),
        )

        path = os.path.join(self.tmp.name, files[0].filename)
        with open(path, "wb") as fh:
            fh.write(files[0].content)

        text = extract_text_from_file(path)
        self.assertIn("Intro to RAG", text)
        self.assertIn("the transcript body", text)

    def test_provider_is_registered(self):
        self.assertIsInstance(sources.get_provider("youtube"), sources.YoutubeProvider)


class YoutubeEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(upload_api.router, prefix="/api/uploads")
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid4())
        self.client = TestClient(app)
        self.addCleanup(self._remove_written_files)
        self.uploads_before = self._upload_files()

    def _upload_files(self):
        return set(os.listdir("uploads")) if os.path.isdir("uploads") else set()

    def _remove_written_files(self):
        for name in self._upload_files() - self.uploads_before:
            os.remove(os.path.join("uploads", name))

    def _post(self, ref, *, routes=None, api=None, max_bytes=10_000):
        stack = [
            patch.object(
                sources.httpx,
                "AsyncClient",
                side_effect=http_stub(
                    routes or {"https://www.youtube.com/oembed": oembed()}
                ),
            ),
            patch(
                "youtube_transcript_api.YouTubeTranscriptApi",
                return_value=api or FakeTranscriptApi([FakeTranscript("caption")]),
            ),
            patch.object(sources, "MAX_UPLOAD_BYTES", max_bytes),
        ]
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)
        return self.client.post("/api/uploads/youtube", json={"url": ref})

    def test_a_successful_import_uses_the_shared_file_shape(self):
        response = self._post(f"https://youtu.be/{VIDEO_A}")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["added"], body["total"], body["truncated"]), (1, 1, False))
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
        self.assertEqual(item["source"], "youtube")
        self.assertEqual(item["filename"], "intro-to-rag.md")
        self.assertEqual(
            item["source_ref"], f"https://www.youtube.com/watch?v={VIDEO_A}"
        )

    def test_no_captions_is_a_400_naming_the_video(self):
        response = self._post(
            f"https://youtu.be/{VIDEO_A}",
            api=FakeTranscriptApi([], error=RuntimeError("TranscriptsDisabled")),
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn(VIDEO_A, response.json()["detail"])
        self.assertEqual(self._upload_files() - self.uploads_before, set())

    def test_an_oversized_file_is_a_413_and_stores_nothing(self):
        response = self._post(
            f"https://youtu.be/{VIDEO_A}",
            api=FakeTranscriptApi([FakeTranscript("x" * 500)]),
            max_bytes=64,
        )

        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(self._upload_files() - self.uploads_before, set())

    def test_a_non_youtube_url_is_a_400(self):
        response = self._post("https://example.com/video")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._upload_files() - self.uploads_before, set())


if __name__ == "__main__":
    unittest.main()
