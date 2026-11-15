from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from site_gpt.app.api.api_key import router as api_key_router
from site_gpt.app.api.company import router as company_router
from site_gpt.app.api.document import router as document_router
from site_gpt.app.api.extra_document import router as extra_document_router
from site_gpt.app.api.analytics import router as analytics_router
from site_gpt.app.api.digest import router as digest_router
from site_gpt.app.api.feedback import router as feedback_router
from site_gpt.app.api.handoff import router as handoff_router
from site_gpt.app.api.routes import router
from site_gpt.app.api.setting import router as setting_router
from site_gpt.app.api.upload import router as upload_router
from site_gpt.app.api.user import router as user_router
from site_gpt.app.api.v1 import router as v1_router
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
    # The admin Settings page reads this header off /widget.js to build a
    # cache-busting ?v= token for the install snippet; without exposing it the
    # browser hides the value from cross-origin JS.
    expose_headers=["X-Widget-Version"],
)

app.include_router(router)
app.include_router(company_router, prefix="/api/companies")
app.include_router(setting_router, prefix="/api/settings")
app.include_router(document_router, prefix="/api/documents")
app.include_router(upload_router, prefix="/api/uploads")
app.include_router(user_router, prefix="/api/users")
app.include_router(website_router, prefix="/api/websites")
app.include_router(extra_document_router, prefix="/api/extra_documents")
app.include_router(api_key_router, prefix="/api/api-keys")
app.include_router(feedback_router, prefix="/api/feedback")
# The handoff router carries its own paths (/api/handoff for the public POST,
# /api/handoffs for the admin list).
app.include_router(handoff_router)
app.include_router(digest_router)
app.include_router(analytics_router)
app.include_router(v1_router, prefix="/api/v1")
