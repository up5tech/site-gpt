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
from urllib.parse import urljoin, urlparse

import httpx

from site_gpt.app.core.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from site_gpt.app.services.net_guard import UnsafeUrl, assert_fetchable_url

# Redirects are followed manually so every hop can be re-validated: a public
# URL may redirect to a private or metadata address.
MAX_REDIRECTS = 5


class FileTooLarge(Exception):
    """Raised when fetched content would exceed MAX_UPLOAD_BYTES."""


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


class SourceProvider:
    """Base interface every source must implement."""

    async def acquire(self, ref: str, token: str | None = None) -> AcquiredFile:
        raise NotImplementedError


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


# Registry: source name -> provider class. Extend here for new origins.
PROVIDERS: dict[str, type[SourceProvider]] = {
    "local": UrlProvider,  # local is handled directly in upload.py, kept for completeness
    "url": UrlProvider,
    "google_drive": GoogleDriveProvider,
}


def get_provider(source: str) -> SourceProvider:
    cls = PROVIDERS.get(source)
    if not cls:
        raise ValueError(
            f"Unknown source '{source}'. Supported: {sorted(PROVIDERS)}"
        )
    return cls()
