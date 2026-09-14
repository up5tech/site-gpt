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

from dataclasses import dataclass

import httpx


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
        headers = {"Authorization": f"Bearer {token}"} if token else None
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(ref)
            resp.raise_for_status()
            # Best-effort filename from the URL path; fall back to "file".
            filename = ref.rstrip("/").split("?")[0].split("/")[-1] or "file"
            content_type = resp.headers.get("content-type")
            return AcquiredFile(
                content=resp.content,
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
            resp = await client.get(f"{self.API}/{ref}?alt=media")
            resp.raise_for_status()

            filename = info.get("name") or ref
            content_type = info.get("mimeType") or resp.headers.get("content-type")
            return AcquiredFile(
                content=resp.content,
                filename=filename,
                content_type=content_type,
            )

    async def _acquire_public(self, ref: str) -> AcquiredFile:
        """Download a file shared with 'Anyone with the link' (no auth)."""
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=True
        ) as client:
            resp = await client.get(f"{self.PUBLIC}&id={ref}")
            # Large files trigger a virus-scan warning page with a confirm
            # token; follow it to get the real binary.
            if "text/html" in resp.headers.get("content-type", ""):
                import re

                match = re.search(r"confirm=([0-9A-Za-z_-]+)", resp.text)
                if match:
                    resp = await client.get(
                        f"{self.PUBLIC}&id={ref}&confirm={match.group(1)}"
                    )
            filename = ref
            disp = resp.headers.get("content-disposition")
            if disp and "filename=" in disp:
                filename = disp.split("filename=")[-1].strip('"')
            return AcquiredFile(
                content=resp.content,
                filename=filename,
                content_type=resp.headers.get("content-type"),
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
