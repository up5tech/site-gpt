"""The hosted chat page (V4 F5).

Every website gets a first-party URL — ``GET /chat/{website_id}`` — that loads
the same ``widget.js`` an embed does, with ``displayMode: 'page'``. There is no
build step: the page is one HTML string, the ``widget.js`` precedent, so a
deployment can never serve a stale bundle.

The page is public and carries the embed's guards: the website must exist (an
unknown id is a 404 — the tenant rule, never a 403) and `ensure_website_active`
decides whether it may be served. A disabled website gets the widget's
unavailable notice rendered server-side instead of the chat, so the visitor sees
the same state an embed shows without loading the script or paying a refused
config request.

The widget's API base is the browser's own origin (``window.location.origin``),
not anything this process can see: behind a reverse proxy the request's Host and
scheme are not the URL the visitor used, and a hardcoded value would send the
widget to the wrong place. An alternative hostname therefore needs no config.
Nothing about the third-party origin posture changes in this task — the page
calls the API from its own origin, which `embed_guard` starts accepting as
first-party in V4-51.
"""

import json
from html import escape
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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

# Deliberately the same sentence the widget paints for a disabled website
# (`UNAVAILABLE_MESSAGE` in `scripts/widget.js`): the hosted page and an embed
# must not describe the same state in two different ways.
UNAVAILABLE_MESSAGE = (
    "This assistant is temporarily unavailable. Please try again later."
)


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


def _document(*, title: str, favicon: str, body: str) -> str:
    """The shared shell: escaped head, noindex, and the caller's body."""
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

      .notice {{
        margin: 0;
        padding: 48px 16px;
        font: 15px/1.5 Arial, sans-serif;
        color: #444444;
        text-align: center;
      }}
    </style>
  </head>
  <body>
{body}
  </body>
</html>
"""


def render_chat_page(
    website: models.Website, *, version: str, title: str, favicon: str
) -> str:
    """The live page: the widget's own config keys, in page mode."""
    body = f"""    <script>
      // The embed's own config keys; `displayMode: 'page'` is the only addition,
      // so widget.js fills the viewport and renders no launcher bubble. The base
      // is the visitor's own origin, which stays correct behind a reverse proxy.
      window.ChatWidgetConfig = {{
        apiUrl: window.location.origin,
        website_id: {json.dumps(str(website.id))},
        displayMode: 'page'
      }};
    </script>
    <script src="/widget.js?v={escape(version)}" async></script>"""
    return _document(title=title, favicon=favicon, body=body)


def render_unavailable_page(*, title: str, favicon: str) -> str:
    """A disabled website: the same notice the widget paints, with no chat."""
    body = f'    <p class="notice">{escape(UNAVAILABLE_MESSAGE)}</p>'
    return _document(title=title, favicon=favicon, body=body)


def _website_or_404(db: Session, website_id: str) -> models.Website:
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
    return website


@router.get("/chat/{website_id}", response_class=HTMLResponse)
def chat_page(website_id: str, db: Session = Depends(get_db)):
    """Public full-page chat for one website (V4 F5)."""
    website = _website_or_404(db, website_id)
    title = page_title(company_setting(db, website.company_id, TITLE_SETTING))
    favicon = favicon_url(
        company_setting(db, website.company_id, LOGO_SETTING)
    )

    try:
        ensure_website_active(website)
    except HTTPException:
        # Disabled: no widget, no config request — just the notice the widget
        # itself shows in an embed. Still a 200: the page exists and explains
        # the state; that is not a client error.
        return HTMLResponse(content=render_unavailable_page(title=title, favicon=favicon))

    return HTMLResponse(
        content=render_chat_page(
            website, version=widget_version(), title=title, favicon=favicon
        )
    )
