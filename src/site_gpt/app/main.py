from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from site_gpt.app.api.api_key import router as api_key_router
from site_gpt.app.api.billing import router as billing_router
from site_gpt.app.api.chat_page import router as chat_page_router
from site_gpt.app.api.company import router as company_router
from site_gpt.app.api.document import router as document_router
from site_gpt.app.api.extra_document import router as extra_document_router
from site_gpt.app.api.analytics import router as analytics_router
from site_gpt.app.api.digest import router as digest_router
from site_gpt.app.api.feedback import router as feedback_router
from site_gpt.app.api.handoff import router as handoff_router
from site_gpt.app.api.inbox import router as inbox_router
from site_gpt.app.api.integration import router as integration_router
from site_gpt.app.api.plan import router as plan_router
from site_gpt.app.api.platform import router as platform_router
from site_gpt.app.api.privacy import router as privacy_router
from site_gpt.app.api.routes import router
from site_gpt.app.api.setting import router as setting_router
from site_gpt.app.api.upload import router as upload_router
from site_gpt.app.api.user import router as user_router
from site_gpt.app.api.v1 import router as v1_router
from site_gpt.app.api.website import router as website_router
from site_gpt.app.core.config import CORS_ORIGINS, validate_billing_config
from site_gpt.app.services.embed_guard import (
    EmbedTokenRefused,
    embed_token_error_response,
)
from site_gpt.app.services.session_tokens import SessionTokenError, error_response

DESCRIPTION = """
SiteGPT admin API, worker and embeddable chat widget.

Two authentication paths coexist:

* **JWT** (`Authorization: Bearer …`) for the admin console and every legacy
  `/api/...` route.
* **API key** (`X-API-Key: sk_…`) for the versioned [`/api/v1`] routes, so a
  server-to-server integration never needs an admin password. See
  `docs/api-v1.md` for scopes, examples and rate limits.
"""

TAGS_METADATA = [
    {
        "name": "v1",
        "description": "Versioned, API-key-authenticated endpoints (F8). "
        "Keys are created under Settings → API keys.",
    },
    {
        "name": "integrations",
        "description": "Outbound webhook/Slack/Zendesk/Crisp integrations (F7). "
        "Reads never return a stored credential.",
    },
]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail fast only when billing was explicitly enabled. The default/off path
    # remains independent of Stripe credentials and makes no provider calls.
    validate_billing_config()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AI Agent Expose API",
    version="2.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Session-token refusals carry a `reason` code beside the human `detail`, so the
# widget can tell "this id is dead" from "another tab holds it" without parsing
# prose.
app.add_exception_handler(SessionTokenError, error_response)

# Embed-token refusals (V3 F4) carry `reason` too — `embed_token_required` in
# `enforce` mode, `invalid_embed_token` for a wrong/revoked/foreign token. These
# are deliberately separate codes: an embed refusal must never make the widget
# reset the visitor's session.
app.add_exception_handler(EmbedTokenRefused, embed_token_error_response)

# Browsers reject `allow_credentials=True` together with a wildcard origin,
# so credentials are only enabled for explicit (non-wildcard) origin lists.
origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
allow_credentials = origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    # Deliberately a wildcard, not a list: widget requests now carry
    # `X-Session-Token` (K4) and `X-Embed-Token` (V3 F4) beside `Content-Type`,
    # and the dashboard adds `Authorization`. Replacing this with an allowlist
    # would tighten CORS for existing embeds, so the preflight carrying
    # `X-Embed-Token` is pinned by a test in `tests/test_embed_origin.py`
    # instead.
    allow_headers=["*"],
    # The admin Settings page reads this header off /widget.js to build a
    # cache-busting ?v= token for the install snippet; without exposing it the
    # browser hides the value from cross-origin JS.
    expose_headers=["X-Widget-Version"],
)

app.include_router(router)
# The hosted chat page (V4 F5) carries its own /chat/{website_id} path.
app.include_router(chat_page_router)
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
app.include_router(integration_router, prefix="/api/integrations")
app.include_router(inbox_router, prefix="/api/inbox")
app.include_router(privacy_router, prefix="/api/privacy")
# The public plan catalog (V5 F1) carries its own /api/plans path and needs no
# authentication: it is what the marketing pricing page reads.
app.include_router(plan_router)
# Billing (V5 F2) owns /api/billing/*: status, summary, Checkout, Billing Portal
# and the signature-verified Stripe webhook. Everything but `status` answers 404
# while BILLING_ENABLED is false.
app.include_router(billing_router)
# The platform-owner surface (V5-40) owns /api/platform/*: who the operator
# is and the audit trail. 404 for the whole surface unless
# PLATFORM_CONSOLE_ENABLED is true, and owner-only when it is.
app.include_router(platform_router)
app.include_router(v1_router, prefix="/api/v1")


def _openapi_with_api_key():
    """Publish the `X-API-Key` scheme that the v1 routes already enforce.

    `get_api_key` reads a plain header, which FastAPI cannot document on its own,
    so the scheme and the per-operation security requirement are added here — the
    spec and `docs/api-v1.md` stay in step with the code.
    """
    from fastapi.openapi.utils import get_openapi

    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=TAGS_METADATA,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "ApiKeyAuth"
    ] = {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for operation in operations.values():
            if isinstance(operation, dict):
                operation["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_api_key
