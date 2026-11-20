"""Source-agnostic file acquisition for attachments.

Extra documents can be built from files that live in many places, not just a
direct local upload. Each *source* knows how to fetch the raw bytes + metadata
of a file identified by a reference (a remote URL, a cloud file id, ...).

The acquired bytes are always normalized into a local file under ``uploads/``
(see ``api/upload.py``), so the rest of the RAG pipeline (``services/parse.py``
and ``worker.py``) stays completely source-independent. To support a new origin
(Dropbox, OneDrive, S3, ...), add a provider class and register it in
``PROVIDERS`` below — no other code needs to change.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx

from site_gpt.app.core.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, YOUTUBE_MAX_VIDEOS
from site_gpt.app.services.net_guard import UnsafeUrl, assert_fetchable_url

# Redirects are followed manually so every hop can be re-validated: a public
# URL may redirect to a private or metadata address.
MAX_REDIRECTS = 5


class FileTooLarge(Exception):
    """Raised when fetched content would exceed MAX_UPLOAD_BYTES."""


class SourceRefError(ValueError):
    """A reference could not be turned into a usable file (a clear 400)."""


async def read_limited(response) -> bytes:
    """Read a streaming HTTP response, aborting as soon as it is too big.

    The body is consumed chunk by chunk, so an oversized (or unbounded)
    response never has to be buffered in full to be rejected. Callers wrap
    this in `client.stream(...)` so httpx does not buffer either.
    """
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_UPLOAD_BYTES:
                raise FileTooLarge(
                    f"File is larger than the {MAX_UPLOAD_MB} MB limit."
                )
        except ValueError:
            pass  # malformed header: fall through to the streaming check

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise FileTooLarge(
                f"File is larger than the {MAX_UPLOAD_MB} MB limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _download(
    client: httpx.AsyncClient,
    url: str,
    headers_for: Callable[[str], dict[str, str] | None] | None = None,
) -> tuple[bytes, str | None, str | None]:
    """Fetch a URL through the SSRF guard, following redirects manually.

    Returns (content, content_type, content-disposition). Each redirect target
    is validated before it is requested, so an internal address can never be
    reached by bouncing off a public host.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        assert_fetchable_url(current)
        headers = headers_for(current) if headers_for else None
        async with client.stream("GET", current, headers=headers) as resp:
            if resp.is_redirect:
                location = (resp.headers.get("location") or "").strip()
                if not location:
                    raise UnsafeUrl(f"Redirect from '{current}' had no Location.")
                current = urljoin(current, location)
                continue
            resp.raise_for_status()
            content = await read_limited(resp)
            return (
                content,
                resp.headers.get("content-type"),
                resp.headers.get("content-disposition"),
            )
    raise UnsafeUrl(f"Too many redirects (more than {MAX_REDIRECTS}).")


@dataclass
class AcquiredFile:
    """Normalized representation of a fetched file, ready to be stored locally."""

    content: bytes
    filename: str
    content_type: str | None
    # Where this specific file came from (a video URL, a Notion page id): the
    # attachment row keeps it so the UI can deep-link back to the source.
    source_ref: str | None = None


class SourceProvider:
    """Base interface every source must implement."""

    async def acquire(self, ref: str, token: str | None = None) -> AcquiredFile:
        raise NotImplementedError

    async def acquire_many(
        self, ref: str, token: str | None = None
    ) -> tuple[list[AcquiredFile], int, bool]:
        """Every file one reference resolves to, with `(total, truncated)`.

        Most sources are one file. A playlist or channel expands to many, so the
        endpoint saves each one and reports the sitemap-sync-style counts.
        """
        return [await self.acquire(ref, token)], 1, False


class UrlProvider(SourceProvider):
    """Fetch a file from an arbitrary public/authenticated HTTP(S) URL."""

    async def acquire(self, ref: str, token: str | None = None) -> AcquiredFile:
        # The token is only ever sent to the host the user gave us: a redirect to
        # another host must not receive the caller's credentials.
        token_host = urlparse(ref).hostname

        def headers_for(url: str) -> dict[str, str] | None:
            if token and urlparse(url).hostname == token_host:
                return {"Authorization": f"Bearer {token}"}
            return None

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            content, content_type, _ = await _download(client, ref, headers_for)
            # Best-effort filename from the URL path; fall back to "file".
            filename = ref.rstrip("/").split("?")[0].split("/")[-1] or "file"
            return AcquiredFile(
                content=content,
                filename=filename,
                content_type=content_type,
            )


class GoogleDriveProvider(SourceProvider):
    """Download a Google Drive file.

    Two modes:
    * With an OAuth ``access_token`` (recommended): fetches metadata + binary
      via the Drive REST API. The frontend obtains the token via the Google
      Picker / OAuth popup, so no backend client secret is needed.
    * Without a token: falls back to the public "anyone-with-the-link" download
      endpoint, so a user can simply paste a share link for a publicly shared
      file with no OAuth setup at all.
    """

    API = "https://www.googleapis.com/drive/v3/files"
    PUBLIC = "https://drive.google.com/uc?export=download"

    async def acquire(self, ref: str, token: str | None = None) -> AcquiredFile:
        if token:
            return await self._acquire_authenticated(ref, token)
        return await self._acquire_public(ref)

    async def _acquire_authenticated(
        self, ref: str, token: str
    ) -> AcquiredFile:
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            # First, fetch metadata for the canonical filename + mime type.
            meta = await client.get(f"{self.API}/{ref}?fields=name,mimeType")
            meta.raise_for_status()
            info = meta.json()

            # Google Drive may return a Google-Doc export rather than a binary
            # download; for now we only support direct binary files.
            content, header_type, _ = await _download(
                client, f"{self.API}/{ref}?alt=media"
            )

            filename = info.get("name") or ref
            content_type = info.get("mimeType") or header_type
            return AcquiredFile(
                content=content,
                filename=filename,
                content_type=content_type,
            )

    async def _acquire_public(self, ref: str) -> AcquiredFile:
        """Download a file shared with 'Anyone with the link' (no auth)."""
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False
        ) as client:
            content, content_type, disposition = await _download(
                client, f"{self.PUBLIC}&id={ref}"
            )
            # Large files trigger a virus-scan warning page with a confirm
            # token; follow it to get the real binary.
            if "text/html" in (content_type or ""):
                match = re.search(
                    r"confirm=([0-9A-Za-z_-]+)", content.decode("utf-8", "ignore")
                )
                if match:
                    content, content_type, disposition = await _download(
                        client, f"{self.PUBLIC}&id={ref}&confirm={match.group(1)}"
                    )
            filename = ref
            if disposition and "filename=" in disposition:
                filename = disposition.split("filename=")[-1].strip('"')
            return AcquiredFile(
                content=content,
                filename=filename,
                content_type=content_type,
            )


# --- YouTube (V4 F3) ---------------------------------------------------------

YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_WATCH = "https://www.youtube.com/watch?v={}"
YOUTUBE_OEMBED = "https://www.youtube.com/oembed?url={}&format=json"
YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com"}


def parse_youtube_ref(ref: str) -> tuple[str, str]:
    """Classify a YouTube reference: `("video", id)` or `("playlist"/"channel", url)`.

    Only YouTube hosts are accepted, so a user-supplied link cannot make the
    server fetch an arbitrary host. A bare 11-character id is a video.
    """
    raw = (ref or "").strip()
    if not raw:
        raise SourceRefError("A YouTube video, playlist or channel link is required.")
    if YOUTUBE_VIDEO_ID.match(raw):
        return "video", raw
    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        if YOUTUBE_VIDEO_ID.match(video_id):
            return "video", video_id
        raise SourceRefError("That youtu.be link has no video id.")
    if host not in YOUTUBE_HOSTS:
        raise SourceRefError(
            "That is not a YouTube link. Paste a video, playlist or channel URL."
        )

    path = parsed.path or "/"
    query = parse_qs(parsed.query)
    if path == "/watch":
        video_id = (query.get("v") or [""])[0]
        if YOUTUBE_VIDEO_ID.match(video_id):
            return "video", video_id
        raise SourceRefError("That YouTube watch link has no video id.")
    if path.startswith(("/shorts/", "/embed/", "/live/")):
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and YOUTUBE_VIDEO_ID.match(parts[1]):
            return "video", parts[1]
        raise SourceRefError("That YouTube link has no video id.")
    if path == "/playlist":
        list_id = (query.get("list") or [""])[0]
        if not list_id:
            raise SourceRefError("That playlist link has no list id.")
        return "playlist", f"https://www.youtube.com/playlist?list={quote(list_id)}"
    if path.startswith(("/@", "/channel/", "/c/", "/user/")):
        return "channel", f"https://www.youtube.com{path.rstrip('/')}/videos"
    raise SourceRefError(
        "That YouTube link does not point at a video, a playlist or a channel."
    )


class YoutubeProvider(SourceProvider):
    """Captions of a video, playlist or channel as markdown files.

    Each video becomes one `AcquiredFile` (`# title`, the watch URL, the caption
    text), so an import lands in the same `file_ids` → extra-document → ingest
    path as a local upload. Playlist/channel expansion is capped at
    `YOUTUBE_MAX_VIDEOS`; the endpoint reports added/total/truncated like the
    sitemap sync. A video without captions is a clear error naming it, never an
    empty document.
    """

    async def acquire(self, ref: str, token: str | None = None) -> AcquiredFile:
        files, _, _ = await self.acquire_many(ref, token)
        return files[0]

    async def acquire_many(
        self, ref: str, token: str | None = None
    ) -> tuple[list[AcquiredFile], int, bool]:
        kind, value = parse_youtube_ref(ref)
        if kind == "video":
            video_ids, total = [value], 1
        else:
            video_ids, total = await self._expand(value)
        truncated = total > len(video_ids)
        files = [await self._video_file(video_id) for video_id in video_ids]
        return files, total, truncated

    async def _expand(self, url: str) -> tuple[list[str], int]:
        """Video ids listed on a playlist/channel page, capped, and the total."""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept-Language": "en"})
            response.raise_for_status()
            html = response.text

        found: list[str] = []
        for match in re.finditer(
            r"/(?:watch\?v=|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", html
        ):
            if match.group(1) not in found:
                found.append(match.group(1))
        if not found:
            raise SourceRefError(
                "No videos were found on that playlist or channel page. Check "
                "that the link is public and try again."
            )
        return found[:YOUTUBE_MAX_VIDEOS], len(found)

    async def _video_file(self, video_id: str) -> AcquiredFile:
        url = YOUTUBE_WATCH.format(video_id)
        title = await self._title(video_id, url)
        captions = self._captions(video_id)
        content = f"# {title}\n\nVideo: {url}\n\n{captions}\n".encode("utf-8")
        if len(content) > MAX_UPLOAD_BYTES:
            raise FileTooLarge(
                f"The captions of {url} are larger than the {MAX_UPLOAD_MB} MB limit."
            )
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        return AcquiredFile(
            content=content,
            filename=f"{slug or video_id}.md",
            content_type="text/markdown",
            source_ref=url,
        )

    async def _title(self, video_id: str, url: str) -> str:
        """The video title from YouTube's public oEmbed endpoint (best effort)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    YOUTUBE_OEMBED.format(quote(url, safe=""))
                )
                if response.status_code == 200:
                    title = (response.json() or {}).get("title")
                    if isinstance(title, str) and title.strip():
                        return title.strip()
        except Exception as e:  # noqa: BLE001 - a missing title must not fail the import
            print(f"[youtube] could not read the title of {video_id}: {e}")
        return f"YouTube video {video_id}"

    def _captions(self, video_id: str) -> str:
        """Caption text, preferring a manually-created transcript."""
        from youtube_transcript_api import YouTubeTranscriptApi

        try:
            transcripts = list(YouTubeTranscriptApi().list(video_id))
        except Exception as e:  # noqa: BLE001 - every failure becomes a clear 400
            raise SourceRefError(
                f"No captions are available for video {video_id} ({e})."
            ) from e
        if not transcripts:
            raise SourceRefError(f"No captions are available for video {video_id}.")

        # Manual captions first; otherwise the first available language (which
        # is the auto-generated track when that is all the video has).
        chosen = next(
            (item for item in transcripts if not item.is_generated), transcripts[0]
        )
        try:
            fetched = chosen.fetch()
        except Exception as e:  # noqa: BLE001
            raise SourceRefError(
                f"The captions for video {video_id} could not be downloaded ({e})."
            ) from e

        text = " ".join(
            snippet.text.strip()
            for snippet in fetched
            if snippet.text and snippet.text.strip()
        )
        if not text:
            raise SourceRefError(f"The captions for video {video_id} are empty.")
        return text


# Registry: source name -> provider class. Extend here for new origins.
PROVIDERS: dict[str, type[SourceProvider]] = {
    "local": UrlProvider,  # local is handled directly in upload.py, kept for completeness
    "url": UrlProvider,
    "google_drive": GoogleDriveProvider,
    "youtube": YoutubeProvider,
}


def get_provider(source: str) -> SourceProvider:
    cls = PROVIDERS.get(source)
    if not cls:
        raise ValueError(
            f"Unknown source '{source}'. Supported: {sorted(PROVIDERS)}"
        )
    return cls()
