from uuid import UUID

from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.config import SITEMAP_SYNC_MAX_URLS


def add_missing_pages(
    db: Session, website_id: UUID, urls: list[str]
) -> tuple[int, bool]:
    """Create the sitemap URLs this website does not have yet.

    Shared by the admin sync endpoint (`api/website.py`'s `/load-site-map`) and
    the V4 daily scan (`worker.handle_sitemap_scan`), so the cap rule exists
    once. It lives in the service layer because the worker must not import the
    router layer: the dependency runs `services <- api`.

    Additions only: retiring a vanished page and deleting its documents is the
    scan's own step, deliberately not here, because the manual endpoint has
    never removed anything.

    The cap counts only the pages this call creates; existing pages do not
    consume the budget, so repeated syncs keep making progress instead of
    re-scanning the same first N URLs. Returns `(added, truncated)`; the caller
    commits.
    """
    added = 0
    truncated = False
    for url in urls:
        # Stop creating pages once this sync hits the cap: a sitemap can list
        # tens of thousands of URLs, and the next ingest crawls them all.
        if SITEMAP_SYNC_MAX_URLS > 0 and added >= SITEMAP_SYNC_MAX_URLS:
            truncated = True
            break
        # Scoped to this website: pages of another tenant that happen to share a
        # URL must not make this sync skip them.
        if (
            db.query(models.WebsitePage)
            .filter(
                models.WebsitePage.website_id == website_id,
                models.WebsitePage.url == url,
            )
            .first()
        ):
            continue
        db.add(
            models.WebsitePage(
                url=url,
                name=url,
                description="",
                website_id=website_id,
            )
        )
        added += 1
    return added, truncated
