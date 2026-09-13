from uuid import UUID
from sqlalchemy.orm import Session
from langchain_core.documents import Document
import trafilatura
import requests
from bs4 import BeautifulSoup

from site_gpt.app import models

HEADERS = {
    "User-Agent": "SiteGPTBot/1.0 (+https://github.com/site-gpt)",
}


def load_sitemap(url: str):
    """Load a sitemap via LangChain (kept for compatibility)."""
    from langchain_community.document_loaders import SitemapLoader

    loader = SitemapLoader(web_path=url)
    return loader.load()


def crawl_page(url: str) -> tuple[str, str]:
    """Return (title, clean_text). title may be empty; text empty if nothing extracted."""
    try:
        response = requests.get(url, timeout=15, headers=HEADERS)
        response.raise_for_status()
    except Exception as e:
        print(f"[crawler] failed to fetch {url}: {e}")
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


def extract_urls_from_sitemap(sitemap_url: str) -> list[str]:
    try:
        resp = requests.get(sitemap_url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"[crawler] failed to fetch sitemap {sitemap_url}: {e}")
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
