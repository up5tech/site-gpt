"""Public display configuration (V5-43).

One anonymous, read-only endpoint for the marketing shell: the optional status
message and support address an operator sets in the platform console. Only the
two display keys in `services.platform_settings.PUBLIC_KEYS` can appear here —
there is no environment dump, no secret and no tenant data. An unset key is an
empty string, so the page simply hides that element.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.platform import PublicConfig
from site_gpt.app.services import platform_settings

router = APIRouter()


@router.get("/api/public/config", response_model=PublicConfig, tags=["public"])
def public_config(db: Session = Depends(get_db)) -> PublicConfig:
    return PublicConfig(**platform_settings.public_config(db))
