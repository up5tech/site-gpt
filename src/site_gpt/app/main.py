from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from site_gpt.app.api.company import router as company_router
from site_gpt.app.api.document import router as document_router
from site_gpt.app.api.extra_document import router as extra_document_router
from site_gpt.app.api.routes import router
from site_gpt.app.api.setting import router as setting_router
from site_gpt.app.api.upload import router as upload_router
from site_gpt.app.api.user import router as user_router
from site_gpt.app.api.website import router as website_router
from site_gpt.app.core.config import CORS_ORIGINS

app = FastAPI(title="AI Agent Expose API")

# Browsers reject `allow_credentials=True` together with a wildcard origin,
# so credentials are only enabled for explicit (non-wildcard) origin lists.
origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
allow_credentials = origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(company_router, prefix="/api/companies")
app.include_router(setting_router, prefix="/api/settings")
app.include_router(document_router, prefix="/api/documents")
app.include_router(upload_router, prefix="/api/uploads")
app.include_router(user_router, prefix="/api/users")
app.include_router(website_router, prefix="/api/websites")
app.include_router(extra_document_router, prefix="/api/extra_documents")
