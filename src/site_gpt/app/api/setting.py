from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.setting import SettingRes

router = APIRouter()

# Single source of truth for the default per-company settings. Both the
# registration flow (`_default_setting_rows`) and `POST /api/settings` derive
# from this dict so new keys only have to be added in one place.
DEFAULT_SETTINGS: dict[str, str] = {
    "assistant_name": "Site GPT",
    "widget_header_color": "#4c74af",
    "widget_footer_color": "#4c74af",
    "widget_position": "bottom-right",
    "greeting_message": "Hi 👋 How can I help you?",
    "placeholder_text": "Type a message...",
    "suggested_questions": "",
}

# Only these keys are exposed by the public, unauthenticated
# `GET /api/widget-config`. Any internal setting added later stays private
# unless it is explicitly listed here.
WIDGET_PUBLIC_KEYS: tuple[str, ...] = tuple(DEFAULT_SETTINGS.keys())


def _default_setting_rows(company_id):
    """Build the default Setting rows for a newly created company."""
    return [
        models.Setting(key=key, value=value, company_id=company_id)
        for key, value in DEFAULT_SETTINGS.items()
    ]


@router.get("/")
def get_settings(
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    query = (
        db.query(models.Setting)
        .filter(models.Setting.company_id == user.company_id)
        .all()
    )
    return [SettingRes.model_validate(q, from_attributes=True) for q in query]


@router.put("/")
def update_settings(
    settings: list[SettingRes],
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    for setting in settings:
        existing = (
            db.query(models.Setting)
            .filter(
                models.Setting.key == setting.key,
                models.Setting.company_id == user.company_id,
            )
            .first()
        )
        if existing:
            existing.value = setting.value
        else:
            # Upsert so companies created before new keys were added can still
            # persist them (e.g. widget_position, greeting_message, ...).
            db.add(
                models.Setting(
                    key=setting.key,
                    value=setting.value,
                    company_id=user.company_id,
                )
            )
    db.commit()
    return {"message": "Settings updated successfully"}


@router.post("/")
def create_settings(
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    """Seed missing default settings rows — idempotent.

    Only keys the company does not have yet are inserted, so repeated calls
    never stack duplicate rows. Existing values are left untouched.
    """
    existing_keys = {
        key
        for (key,) in db.query(models.Setting.key)
        .filter(models.Setting.company_id == user.company_id)
        .all()
    }
    missing = [
        models.Setting(key=key, value=value, company_id=user.company_id)
        for key, value in DEFAULT_SETTINGS.items()
        if key not in existing_keys
    ]
    if missing:
        db.add_all(missing)
        db.commit()
    return {
        "created": len(missing),
        "skipped": len(DEFAULT_SETTINGS) - len(missing),
    }
