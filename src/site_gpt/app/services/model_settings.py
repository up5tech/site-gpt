"""Per-company chat model override (F3).

The settings store a (provider, model) pair, never a label or a free-form model
name. This module is the only place that turns those rows into arguments for
``llm.get_llm``, so:

* a value that is not one of ``ALLOWED_CHAT_MODELS`` pairs can never reach the
  chat client — an unknown pair silently falls back to the environment, which is
  the V1 behaviour;
* the *embedding* provider is untouched: switching it still requires a
  migration and a re-ingest (``EMBEDDING_AI``).
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.services.llm import ALLOWED_CHAT_MODELS

logger = logging.getLogger(__name__)

# The two settings that make up the pair. Empty values mean "not configured".
SETTING_KEYS = ("llm_provider", "llm_model")


def resolve(db: Session, website_id: UUID) -> tuple[str | None, str | None]:
    """Return the (provider, model) this website's company pinned.

    ``(None, None)`` means "use the environment": the company has no override,
    the pair is incomplete, or the pair is not in the catalogue. The lookup is
    one query — a join from the website to its company's two setting rows — so
    the chat path does not pay a round trip per setting.
    """
    rows = (
        db.query(models.Setting.key, models.Setting.value)
        .join(
            models.Website,
            models.Website.company_id == models.Setting.company_id,
        )
        .filter(
            models.Website.id == website_id,
            models.Setting.key.in_(SETTING_KEYS),
        )
        .all()
    )
    values = {key: value for key, value in rows}
    provider = (values.get("llm_provider") or "").strip()
    model = (values.get("llm_model") or "").strip()
    if not provider and not model:
        return (None, None)

    pair = (provider, model)
    if pair not in ALLOWED_CHAT_MODELS.values():
        logger.warning(
            "website %s has an unknown chat model %r/%r; using the environment",
            website_id,
            provider,
            model,
        )
        return (None, None)
    return pair
