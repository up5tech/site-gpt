from uuid import UUID
from sqlalchemy.orm import Session
from langchain_community.document_loaders import SitemapLoader
from langchain_core.documents import Document
import trafilatura
import requests
from bs4 import BeautifulSoup

from site_gpt.app import models


def load_sitemap(url: str):
    loader = SitemapLoader(web_path=url)
    return loader.load()


def crawl_page(url: str) -> str:
    response = requests.get(url, timeout=10)

    text = trafilatura.extract(response.text)
    return text or ""


def extract_urls_from_sitemap(sitemap_url: str) -> list[str]:
    resp = requests.get(sitemap_url)
    soup = BeautifulSoup(resp.content, "xml")

    urls = [loc.text for loc in soup.find_all("loc")]
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
        text = crawl_page(page.url)
        if not text:
            continue
        docs.append(
            Document(
                page_content=text, metadata={"source": page.url, "id": str(page.id)}
            )
        )
    return docs
