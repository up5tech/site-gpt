import logging
from urllib.parse import urljoin
from uuid import UUID
from sqlalchemy.orm import Session
from langchain_core.documents import Document
import trafilatura
import requests
from bs4 import BeautifulSoup

from site_gpt.app import models
from site_gpt.app.core.logging import log_event, log_exception
from site_gpt.app.services.net_guard import UnsafeUrl, assert_fetchable_url

HEADERS = {
    "User-Agent": "SiteGPTBot/1.0 (+https://github.com/site-gpt)",
}

# Every hop is re-validated: sitemap entries and redirects are user-controlled
# and must not be able to reach loopback, internal services or cloud metadata.
MAX_REDIRECTS = 5


def _safe_get(url: str, timeout: int = 15) -> requests.Response:
    """GET a URL, rejecting non-http(s) and non-public hosts on every hop."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        assert_fetchable_url(current)
        response = requests.get(
            current, timeout=timeout, headers=HEADERS, allow_redirects=False
        )
        if response.is_redirect:
            location = (response.headers.get("location") or "").strip()
            if not location:
                raise UnsafeUrl(f"Redirect from '{current}' had no Location.")
            current = urljoin(current, location)
            continue
        response.raise_for_status()
        return response
    raise UnsafeUrl(f"Too many redirects (more than {MAX_REDIRECTS}).")


def load_sitemap(url: str):
    """Load a sitemap via LangChain (kept for compatibility)."""
    from langchain_community.document_loaders import SitemapLoader

    loader = SitemapLoader(web_path=url)
    return loader.load()


def crawl_page(url: str) -> tuple[str, str]:
    """Return (title, clean_text). title may be empty; text empty if nothing extracted."""
    try:
        response = _safe_get(url)
    except UnsafeUrl as e:
        log_exception(
            "crawler.refused_fetch", e, level=logging.WARNING, url=url
        )
        return "", ""
    except Exception as e:
        log_exception("crawler.fetch_failed", e, level=logging.WARNING, url=url)
        return "", ""

    html = response.text

    # Extract main article text with trafilatura.
    extracted = trafilatura.extract(html) or ""
    if not extracted:
        # Fallback: strip tags with BeautifulSoup.
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        extracted = soup.get_text(separator="\n")

    # Best-effort title.
    title = ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
    except Exception:
        pass

    return title, extracted.strip()


def extract_urls_from_sitemap(
    sitemap_url: str, *, raise_on_error: bool = False
) -> list[str]:
    """Read a sitemap's URLs.

    A crawl should skip a broken sitemap, so the default swallows the error and
    returns `[]`. Callers that must tell the user *why* nothing was found (the
    admin sync endpoint) pass `raise_on_error=True` and get the original
    `UnsafeUrl` / fetch exception instead of a silent empty list.
    """
    try:
        resp = _safe_get(sitemap_url)
    except UnsafeUrl as e:
        log_exception(
            "crawler.sitemap_refused", e, level=logging.WARNING, url=sitemap_url
        )
        if raise_on_error:
            raise
        return []
    except Exception as e:
        log_exception(
            "crawler.sitemap_fetch_failed", e, level=logging.WARNING, url=sitemap_url
        )
        if raise_on_error:
            raise
        return []

    soup = BeautifulSoup(resp.content, "xml")
    urls = [loc.text.strip() for loc in soup.find_all("loc") if loc.text]
    return urls


def crawl_website(db: Session, website_id: UUID) -> list[Document]:
    website_pages = (
        db.query(models.WebsitePage)
        .filter(models.WebsitePage.website_id == website_id)
        .filter(models.WebsitePage.status == "active")
        .all()
    )
    docs: list[Document] = []
    for page in website_pages:
        title, text = crawl_page(page.url)
        if not text:
            continue
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source": page.url,
                    "id": str(page.id),
                    "title": title or page.name or page.url,
                },
            )
        )
    return docs
