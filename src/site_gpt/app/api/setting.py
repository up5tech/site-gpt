from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.db.session import get_db
from site_gpt.app.core.auth import get_admin_user
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
    return
