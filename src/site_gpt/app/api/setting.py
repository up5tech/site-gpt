from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.setting import SettingRes

router = APIRouter()


def _default_setting_rows(company_id):
    """Build the default Setting rows for a newly created company."""
    return [
        models.Setting(key="assistant_name", value="Site GPT", company_id=company_id),
        models.Setting(key="widget_header_color", value="#4c74af", company_id=company_id),
        models.Setting(key="widget_footer_color", value="#4c74af", company_id=company_id),
        models.Setting(key="widget_position", value="bottom-right", company_id=company_id),
        models.Setting(
            key="greeting_message",
            value="Hi 👋 How can I help you?",
            company_id=company_id,
        ),
        models.Setting(
            key="placeholder_text", value="Type a message...", company_id=company_id
        ),
        models.Setting(key="suggested_questions", value="", company_id=company_id),
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
    default_settings = [
        models.Setting(
            key="assistant_name", value="Site GPT", company_id=user.company_id
        ),
        models.Setting(
            key="widget_header_color", value="#4c74af", company_id=user.company_id
        ),
        models.Setting(
            key="widget_footer_color", value="#4c74af", company_id=user.company_id
        ),
        models.Setting(
            key="widget_position", value="bottom-right", company_id=user.company_id
        ),
        models.Setting(
            key="greeting_message",
            value="Hi 👋 How can I help you?",
            company_id=user.company_id,
        ),
        models.Setting(
            key="placeholder_text", value="Type a message...", company_id=user.company_id
        ),
        models.Setting(
            key="suggested_questions", value="", company_id=user.company_id
        ),
    ]
    db.add_all(default_settings)
    db.commit()
    return {"message": "Settings created successfully"}
