from fastapi import APIRouter, Depends

from site_gpt.app.core.auth import get_current_user

router = APIRouter()


@router.get("/")
def query_companies(user=Depends(get_current_user)):
    return {"message": "List of companies"}
