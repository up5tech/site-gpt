from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.core.auth import get_admin_user
from site_gpt.app.db.session import get_db
from site_gpt.app.schemas.setting import SettingRes

router = APIRouter()


@router.get("/")
def get_settings(
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    query = db.query(models.Setting).all()
    return [SettingRes.model_validate(q) for q in query]


@router.put("/")
def update_settings(
    settings: list[SettingRes],
    db: Session = Depends(get_db),
    user=Depends(get_admin_user),
):
    for setting in settings:
        db.query(models.Setting).filter(models.Setting.key == setting.key).update(
            {"value": setting.value}
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
            key="widget_header_color", value="green", company_id=user.company_id
        ),
        models.Setting(
            key="widget_footer_color", value="green", company_id=user.company_id
        ),
    ]
    db.add_all(default_settings)
    db.commit()
    return {"message": "Settings created successfully"}
