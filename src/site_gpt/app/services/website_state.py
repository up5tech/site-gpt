"""Whether a website may be served at all.

`websites.status` used to be written by the API and never read, so disabling a
bot meant deleting the website and losing its documents, history and leads.

The rule lives here, next to `ingest_claim` and `embed_guard`, because every
route that touches a website's public surface (chat, stream, contacts, widget
config, ingest) needs it — the versioned `/api/v1` routes included. A copy in a
route would drift from the rest.
"""

from fastapi import HTTPException, status

from site_gpt.app import models


def ensure_website_active(website: models.Website) -> None:
    """Raise 403 unless `website` may be served.

    Only an explicit other value disables the bot. `websites.status` is
    nullable, so a row created before the switch existed (or written by an old
    form that sent nothing) can hold NULL/empty — that means "never set", and
    treating it as disabled would silently kill a working bot.
    """
    current = (website.status or "").strip().lower()
    if current and current != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This website is disabled.",
        )
