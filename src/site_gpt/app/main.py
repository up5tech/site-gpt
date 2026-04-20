from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from site_gpt.app.api.routes import router
from site_gpt.app.api.company import router as company_router
from site_gpt.app.api.setting import router as setting_router

app = FastAPI(title="AI Agent Expose API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(company_router, prefix="/api/companies")
app.include_router(setting_router, prefix="/api/settings")
