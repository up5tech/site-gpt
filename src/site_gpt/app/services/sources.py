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

from site_gpt.app.core.config import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    NOTION_MAX_BLOCKS,
    NOTION_MAX_PAGES,
    YOUTUBE_MAX_VIDEOS,
)
from site_gpt.app.services.net_guard import UnsafeUrl, assert_fetchable_url

# Redirects are followed manually so every hop can be re-validated: a public
# URL may redirect to a private or metadata address.
MAX_REDIRECTS = 5


class FileTooLarge(Exception):
    """Raised when fetched content would exceed MAX_UPLOAD_BYTES."""


class SourceRefError(ValueError):
    """A reference could not be turned into a usable file (a clear 400)."""


class SourceAuthError(SourceRefError):
    """The source rejected the per-request token (a clear 401)."""


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
        total = len(found)
        # Same rule as SITEMAP_SYNC_MAX_URLS: 0 disables the cap. Slicing by 0
        # would otherwise import nothing at all and look like a silent success.
        if YOUTUBE_MAX_VIDEOS > 0:
            found = found[:YOUTUBE_MAX_VIDEOS]
        return found, total

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


# --- Notion (V4 F3) ----------------------------------------------------------

NOTION_ID = re.compile(r"[0-9a-fA-F]{32}")
NOTION_HOSTS = {"notion.so", "notion.site"}


def parse_notion_ref(ref: str) -> tuple[str, str]:
    """Classify a Notion reference: `(kind, id)`, kind `page`/`database`/`auto`.

    Only Notion hosts are accepted, and only the id is ever used to build a
    request — the token is sent to `api.notion.com`, never to a host from the
    pasted link. A bare id cannot tell a page from a database, so it comes back
    as `auto` and the provider asks the API which one it is.
    """
    raw = (ref or "").strip()
    if not raw:
        raise SourceRefError("A Notion page or database link is required.")

    compact = raw.replace("-", "")
    if NOTION_ID.fullmatch(compact):
        return "auto", compact.lower()
    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in NOTION_HOSTS and not host.endswith(".notion.site"):
        raise SourceRefError(
            "That is not a Notion link. Paste a page or database URL."
        )

    # Search the path as-is first: a title directly before the id ("My-Page-<id>")
    # must not extend the match into the title once the hyphens are stripped.
    path = parsed.path or ""
    match = NOTION_ID.search(path) or NOTION_ID.search(path.replace("-", ""))
    if not match:
        raise SourceRefError("That Notion link has no page or database id.")
    # A database page URL carries its view id as `?v=`.
    kind = "database" if "v" in parse_qs(parsed.query) else "page"
    return kind, match.group(0).lower()


class NotionProvider(SourceProvider):
    """A Notion page, or every page of a database, as markdown files.

    The integration token is per request (the Google Drive precedent): it only
    ever goes into an `Authorization` header on `api.notion.com`, is never
    stored, echoed or logged, and a redirect off that host is refused instead of
    followed. Blocks are rendered to markdown under `NOTION_MAX_BLOCKS` and a
    database to one file per page under `NOTION_MAX_PAGES`, both reporting
    `truncated` when there was more to fetch.
    """

    API = "https://api.notion.com/v1"
    VERSION = "2022-06-28"

    async def acquire(self, ref: str, token: str | None = None) -> AcquiredFile:
        files, _, _ = await self.acquire_many(ref, token)
        return files[0]

    async def acquire_many(
        self, ref: str, token: str | None = None
    ) -> tuple[list[AcquiredFile], int, bool]:
        token = (token or "").strip()
        if not token:
            raise SourceAuthError("A Notion integration token is required.")

        kind, ref_id = parse_notion_ref(ref)
        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self.VERSION,
        }
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            if kind == "auto":
                kind = await self._kind_of(client, headers, ref_id)
            if kind == "database":
                pages, total = await self._database_pages(client, headers, ref_id)
                files = [
                    await self._page_file(client, headers, page["id"], page)
                    for page in pages
                ]
            else:
                files = [await self._page_file(client, headers, ref_id)]
                total = 1
        return files, total, total > len(files)

    async def _kind_of(
        self, client: httpx.AsyncClient, headers: dict[str, str], ref_id: str
    ) -> str:
        page = await self._json(
            client, headers, "GET", f"/pages/{ref_id}", allow_404=True
        )
        if page is not None:
            return "page"
        database = await self._json(
            client, headers, "GET", f"/databases/{ref_id}", allow_404=True
        )
        if database is not None:
            return "database"
        raise SourceRefError(
            "Notion returned 404 for that id. Check the link and that the page "
            "or database is shared with your integration."
        )

    async def _database_pages(
        self, client: httpx.AsyncClient, headers: dict[str, str], database_id: str
    ) -> tuple[list[dict], int]:
        """The pages to import (capped) and the database's real page count.

        Every query page is read even past `NOTION_MAX_PAGES`: a `total` taken
        from the first 100-page window would report a 500-page database as
        "25 of 100". Only the rows up to the cap are kept and no blocks are
        fetched for the rest, so counting costs query calls, not imports.
        """
        pages: list[dict] = []
        total = 0
        cursor = None
        while True:
            body: dict = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            data = await self._json(
                client,
                headers,
                "POST",
                f"/databases/{database_id}/query",
                json_body=body,
            )
            results = data.get("results") or []
            total += len(results)
            # Same rule as the other caps: 0 disables it.
            if NOTION_MAX_PAGES > 0:
                pages.extend(results[: max(NOTION_MAX_PAGES - len(pages), 0)])
            else:
                pages.extend(results)
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break

        if not total:
            raise SourceRefError("That Notion database has no pages to import.")
        return pages, total

    async def _page_file(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        page_id: str,
        page: dict | None = None,
    ) -> AcquiredFile:
        if page is None:
            page = await self._json(client, headers, "GET", f"/pages/{page_id}")
        title = self._page_title(page, page_id)

        self._seen = 0
        self._truncated = False
        lines = await self._render_page(client, headers, page_id)
        if self._truncated:
            lines.extend(
                [
                    "",
                    f"_[Truncated: only the first {self._seen} blocks of this page "
                    f"were imported (NOTION_MAX_BLOCKS).]_"
                ]
            )

        url = f"https://www.notion.so/{page_id.replace('-', '')}"
        body = f"# {title}\n\nSource: {url}\n\n" + "\n".join(lines).strip() + "\n"
        content = body.encode("utf-8")
        if len(content) > MAX_UPLOAD_BYTES:
            raise FileTooLarge(
                f"That Notion page is larger than the {MAX_UPLOAD_MB} MB limit."
            )
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        return AcquiredFile(
            content=content,
            filename=f"{slug or page_id}.md",
            content_type="text/markdown",
            source_ref=url,
        )

    def _page_title(self, page: dict, page_id: str) -> str:
        for prop in ((page or {}).get("properties") or {}).values():
            if prop.get("type") == "title":
                title = self._rich_text(prop.get("title"))
                if title.strip():
                    return title.strip()
        return f"Notion page {page_id.replace('-', '')}"

    async def _json(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        allow_404: bool = False,
    ):
        response = await client.request(
            method,
            f"{self.API}{path}",
            headers=headers,
            params=params,
            json=json_body,
        )
        if allow_404 and response.status_code == 404:
            return None
        self._raise_for(response)
        return response.json()

    def _raise_for(self, response: httpx.Response) -> None:
        """Turn a Notion error into a clear one, without ever echoing the token.

        A redirect is refused rather than followed: the `Authorization` header
        is only ever sent to `api.notion.com`.
        """
        if response.is_redirect:
            raise SourceRefError(
                "Notion answered with a redirect, which is refused. The token is "
                "only ever sent to api.notion.com."
            )
        if response.status_code in (401, 403):
            raise SourceAuthError(
                "Notion rejected the integration token. Check the token and "
                "that the page or database is shared with your integration."
            )
        if response.status_code == 404:
            raise SourceRefError(
                "Notion returned 404. Check the link and that the page or "
                "database is shared with your integration."
            )
        if response.status_code >= 400:
            raise SourceRefError(f"Notion returned HTTP {response.status_code}.")

    async def _children(
        self, client: httpx.AsyncClient, headers: dict[str, str], block_id: str
    ) -> list[dict]:
        results: list[dict] = []
        cursor = None
        while True:
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = await self._json(
                client, headers, "GET", f"/blocks/{block_id}/children", params=params
            )
            results.extend(data.get("results") or [])
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                return results
            # One nesting level can never need more blocks than the whole cap.
            if NOTION_MAX_BLOCKS > 0 and len(results) >= NOTION_MAX_BLOCKS:
                return results

    def _claim_block(self) -> bool:
        """Account for one block against NOTION_MAX_BLOCKS (0 disables it)."""
        if NOTION_MAX_BLOCKS > 0 and self._seen >= NOTION_MAX_BLOCKS:
            self._truncated = True
            return False
        self._seen += 1
        return True

    async def _render_page(
        self, client: httpx.AsyncClient, headers: dict[str, str], page_id: str
    ) -> list[str]:
        """Depth-first markdown render of a page's blocks, budgeted by the cap."""
        lines: list[str] = []
        stack: list[tuple] = [("children", page_id, 0, None)]
        while stack:
            task = stack.pop()
            if task[0] == "render":
                lines.extend(task[1])
                continue

            _, parent_id, depth, parent_type = task
            children = await self._children(client, headers, parent_id)
            if parent_type == "table":
                lines.extend(self._render_table(children))
                continue

            accepted: list[dict] = []
            for block in children:
                if not self._claim_block():
                    break
                accepted.append(block)
            for block in reversed(accepted):
                block_lines = self._render_block(block, depth)
                if block.get("has_children"):
                    stack.append(
                        ("children", block["id"], depth + 1, block.get("type"))
                    )
                stack.append(("render", block_lines))
        return lines

    def _render_table(self, rows: list[dict]) -> list[str]:
        lines: list[str] = []
        for index, row in enumerate(rows):
            if not self._claim_block():
                break
            cells = [
                self._rich_text(cell)
                for cell in ((row.get("table_row") or {}).get("cells") or [])
            ]
            lines.append("| " + " | ".join(cells) + " |")
            if index == 0 and cells:
                lines.append("| " + " | ".join("---" for _ in cells) + " |")
        return ["", *lines, ""] if lines else []

    def _render_block(self, block: dict, depth: int) -> list[str]:
        kind = block.get("type") or ""
        data = block.get(kind) or {}
        indent = "  " * depth
        text = self._rich_text(data.get("rich_text"))

        if kind == "paragraph":
            return [f"{indent}{text}".rstrip()] if text else []
        if kind in ("heading_1", "heading_2", "heading_3"):
            # Shift one level down: the page title already is the document's H1.
            prefix = "#" * (int(kind[-1]) + 1)
            return [f"{prefix} {text}"] if text else []
        if kind == "bulleted_list_item":
            return [f"{indent}- {text}".rstrip()]
        if kind == "numbered_list_item":
            return [f"{indent}1. {text}".rstrip()]
        if kind == "to_do":
            box = "x" if data.get("checked") else " "
            return [f"{indent}- [{box}] {text}".rstrip()]
        if kind == "toggle":
            return [f"{indent}- {text}".rstrip()]
        if kind in ("quote", "callout"):
            return [f"{indent}> {text}".rstrip()]
        if kind == "code":
            language = (data.get("language") or "").strip()
            return [f"```{language}", text, "```"]
        if kind == "divider":
            return ["---"]
        if kind == "child_page":
            return [f"{indent}- {data.get('title') or ''} (sub-page)".rstrip()]
        if kind in ("image", "video", "file", "pdf"):
            url = (
                (data.get("external") or {}).get("url")
                or (data.get("file") or {}).get("url")
                or ""
            )
            caption = self._rich_text(data.get("caption")) or kind
            return [f"![{caption}]({url})"]
        if kind == "table_row":
            cells = [
                self._rich_text(cell) for cell in (data.get("cells") or [])
            ]
            return ["| " + " | ".join(cells) + " |"]

        # Unsupported blocks degrade to their plain text, never to an error.
        fallback = text or (data.get("title") if isinstance(data.get("title"), str) else "")
        return [f"{indent}{fallback}".rstrip()] if fallback else []

    @staticmethod
    def _rich_text(items) -> str:
        """Render Notion rich-text items, keeping the inline formatting."""
        parts: list[str] = []
        for item in items or []:
            plain = item.get("plain_text")
            if plain is None:
                plain = (item.get("text") or {}).get("content", "")
            text = plain or ""
            annotations = item.get("annotations") or {}
            if annotations.get("code"):
                text = f"`{text}`"
            if annotations.get("bold"):
                text = f"**{text}**"
            if annotations.get("italic"):
                text = f"*{text}*"
            if annotations.get("strikethrough"):
                text = f"~~{text}~~"
            href = item.get("href")
            if href:
                text = f"[{text}]({href})"
            parts.append(text)
        return "".join(parts)


# Registry: source name -> provider class. Extend here for new origins.
PROVIDERS: dict[str, type[SourceProvider]] = {
    "local": UrlProvider,  # local is handled directly in upload.py, kept for completeness
    "url": UrlProvider,
    "google_drive": GoogleDriveProvider,
    "youtube": YoutubeProvider,
    "notion": NotionProvider,
}


def get_provider(source: str) -> SourceProvider:
    cls = PROVIDERS.get(source)
    if not cls:
        raise ValueError(
            f"Unknown source '{source}'. Supported: {sorted(PROVIDERS)}"
        )
    return cls()
