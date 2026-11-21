"""The hosted chat page (V4 F5).

Every website gets a first-party URL — ``GET /chat/{website_id}`` — that loads
the same ``widget.js`` an embed does, with ``displayMode: 'page'``. There is no
build step: the page is one HTML string, the ``widget.js`` precedent, so a
deployment can never serve a stale bundle.

The page is public and carries the embed's guards: the website must exist (an
unknown id is a 404 — the tenant rule, never a 403) and `ensure_website_active`
decides whether it may be served. A disabled website still gets the page: its
own ``/api/widget-config`` read is refused (403) and the widget paints the
unavailable state it already owns. Raising here instead would replace that
visitor-facing notice with a bare JSON API error.

Nothing about the third-party origin posture changes in this task — the page
calls the API from its own origin, which `embed_guard` starts accepting as
first-party in V4-51.
"""

import json
from html import escape
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.api.routes import widget_version
from site_gpt.app.api.setting import company_setting
from site_gpt.app.db.session import get_db
from site_gpt.app.services.website_state import ensure_website_active

router = APIRouter()

# Title and favicon come from the same two allowlisted settings `GET
# /api/widget-config` publishes, read server-side so the tab is correct before
# any JavaScript runs.
TITLE_SETTING = "assistant_name"
LOGO_SETTING = "widget_logo_url"
FALLBACK_TITLE = "Chat"


def page_title(raw: str | None) -> str:
    """The document title: the owner's assistant name, else a neutral one."""
    return (raw or "").strip() or FALLBACK_TITLE


def favicon_url(raw: str | None) -> str:
    """A favicon candidates may use, or '' when the logo is not usable.

    Only absolute https URLs are accepted. The widget also allows raster `data:`
    URIs for its avatar, but a favicon is an attribute sink for a value the owner
    types, so the narrower rule is deliberate: anything else is simply omitted.
    """
    candidate = (raw or "").strip()
    if not candidate.lower().startswith("https://"):
        return ""
    if any(char in candidate for char in ('"', "'", "<", ">", " ", "\t", "\n")):
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    return candidate if parsed.scheme and parsed.netloc else ""


def render_chat_page(
    website: models.Website,
    *,
    api_url: str,
    version: str,
    title: str,
    favicon: str,
) -> str:
    """The page's HTML. Every interpolated value is escaped or JSON-quoted."""
    icon = (
        f'\n    <link rel="icon" href="{escape(favicon, quote=True)}" />'
        if favicon
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <!-- A hosted bot page is a private conversation surface, not a search result. -->
    <meta name="robots" content="noindex, nofollow" />
    <title>{escape(title)}</title>{icon}
    <style>
      html,
      body {{
        margin: 0;
        height: 100%;
        background: #ffffff;
      }}
    </style>
  </head>
  <body>
    <script>
      // The embed's own config keys; `displayMode: 'page'` is the only addition,
      // so widget.js fills the viewport and renders no launcher bubble.
      window.ChatWidgetConfig = {{
        apiUrl: {json.dumps(api_url)},
        website_id: {json.dumps(str(website.id))},
        displayMode: 'page'
      }};
    </script>
    <script src="/widget.js?v={escape(version)}" async></script>
  </body>
</html>
"""


@router.get("/chat/{website_id}", response_class=HTMLResponse)
def chat_page(
    website_id: str, request: Request, db: Session = Depends(get_db)
):
    """Public full-page chat for one website (V4 F5)."""
    try:
        site_uuid = UUID(website_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )
    website = (
        db.query(models.Website).filter(models.Website.id == site_uuid).first()
    )
    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
        )

    try:
        ensure_website_active(website)
    except HTTPException:
        # Disabled: serve the shell anyway — widget-config refuses with 403 and
        # the widget shows its existing unavailable notice. An API error page
        # here would be a worse experience than that state.
        pass

    html = render_chat_page(
        website,
        # The page is served by this API, so the widget calls the same origin.
        api_url=str(request.base_url).rstrip("/"),
        version=widget_version(),
        title=page_title(
            company_setting(db, website.company_id, TITLE_SETTING)
        ),
        favicon=favicon_url(
            company_setting(db, website.company_id, LOGO_SETTING)
        ),
    )
    return HTMLResponse(content=html)
