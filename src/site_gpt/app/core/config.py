from dotenv import load_dotenv
import os

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY", "your-secret-key-change-this-in-production"
)
JWT_ALGORITHM = "HS256"

# Pepper mixed into the SHA-256 of company API keys before they are stored
# (ADR-6). Required in production; changing it invalidates every issued key.
# Left empty in development so local runs and the test suite need no setup.
API_KEY_PEPPER = os.getenv("API_KEY_PEPPER", "")

# Fallback UI language for the embeddable widget when the visitor's browser
# language cannot be detected. "auto" follows `navigator.language`; a BCP-47
# code (e.g. "vi") pins that language. Never a prompt override — the chat model
# always answers in the language of the question.
DEFAULT_WIDGET_LANGUAGE = os.getenv("DEFAULT_WIDGET_LANGUAGE", "auto")

# K4: session tokens. The widget mints one per session and sends it as
# `X-Session-Token` when it reads its own history or contact. `compat` (the
# default) keeps a tokenless read working for embeds that predate the token —
# but only for a session nobody has claimed yet; `enforce` requires the token
# everywhere. Flip to `enforce` once the embed snippet has been reloaded on the
# customer sites, and only after reading the legacy-session note in
# docs/security.md.
SESSION_TOKEN_MODE = os.getenv("SESSION_TOKEN_MODE", "compat").strip().lower()

# How long one minted token value stays valid for a read, in seconds (default
# 30 days). A session that presents an expired token may still rotate it:
# possession of the old value is proof, and the alternative is losing a returning
# visitor's history.
SESSION_TOKEN_TTL_SECONDS = int(os.getenv("SESSION_TOKEN_TTL_SECONDS", "2592000"))

# Absolute ceiling for one session's token, measured from the row's `created_at`
# (which rotation never moves), in seconds (default 180 days). Without this the
# TTL would bound nothing: whoever holds a token — including someone who stole
# it — can keep rotating it for ever, and each rotation grants a fresh TTL. Past
# this point reads and rotations both fail, so a stolen token has a hard end.
SESSION_TOKEN_MAX_LIFETIME_SECONDS = int(
    os.getenv("SESSION_TOKEN_MAX_LIFETIME_SECONDS", "15552000")
)

# HMAC-SHA256 secret used to sign outbound webhook payloads
# (`X-SiteGPT-Signature: sha256=...`). Only the webhook integration needs it; an
# empty value means receivers cannot verify what we send.
INTEGRATION_WEBHOOK_SECRET = os.getenv("INTEGRATION_WEBHOOK_SECRET")

LLM_AI = os.getenv("LLM_AI", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_EMBEDDING_MODEL = os.getenv("LLM_EMBEDDING_MODEL", "text-embedding-3-small")

# The embedding provider is fully independent of the chat provider. It defaults
# to the chat provider (LLM_AI) so existing single-provider setups keep working
# unchanged — set EMBEDDING_AI explicitly to mix providers, e.g. chat via Ollama
# (Qwen) but embeddings via OpenAI text-embedding-3-small, or vice versa.
EMBEDDING_AI = os.getenv("EMBEDDING_AI", LLM_AI)
# Dimension of the vectors stored in the `embeddings` table. Must match the
# chosen embedding model's output dimension (e.g. 1024 for bge-m3, 768 for
# nomic-embed-text). Changing this from the default requires an Alembic
# migration that alters the column AND re-ingesting the knowledge base.
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))

OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPEN_ROUTER_API_KEY = os.getenv("OPEN_ROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_USERNAME = os.getenv("OLLAMA_USERNAME")
OLLAMA_PASSWORD = os.getenv("OLLAMA_PASSWORD")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_DB = os.getenv("REDIS_DB", "0")

# V3-03 scaffolding (not yet wired into behaviour): every feature defaults to
# the V2.1 behaviour. RATE_LIMIT_BACKEND switches the per-IP limiter between
# the in-process `memory` backend (default, V2.1) and the shared `redis`
# backend (V3-10); EMBED_TOKEN_MODE selects `compat` (missing embed tokens
# accepted) vs `enforce` (a valid token is required, V3-23).
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
EMBED_TOKEN_MODE = os.getenv("EMBED_TOKEN_MODE", "compat").strip().lower()

# V3 topic clustering (F2, Wave 3): bounded inputs + scheduler cadence. The
# cadence is only how often the worker checks; window boundaries come from
# `normalize_period`/`digest_day`, not from this value.
TOPIC_CLUSTER_MAX_MESSAGES = int(os.getenv("TOPIC_CLUSTER_MAX_MESSAGES", "500"))
TOPIC_CLUSTER_INTERVAL_SECONDS = int(
    os.getenv("TOPIC_CLUSTER_INTERVAL_SECONDS", "86400")
)

# V3 live-agent inbox (F3, Wave 4): presence lease TTL and SSE heartbeat.
INBOX_PRESENCE_TTL_SECONDS = int(os.getenv("INBOX_PRESENCE_TTL_SECONDS", "60"))
INBOX_STREAM_HEARTBEAT_SECONDS = int(
    os.getenv("INBOX_STREAM_HEARTBEAT_SECONDS", "15")
)

# V4-02 scaffolding (registry only; wired in the waves that use them). Every
# value defaults to the V3 behaviour, so a deployment that sets none of them
# behaves exactly like tag `v3`.
#
# Per-session message cap (F4, D6): visitor messages one session may send inside
# one idle window. 0 disables it; the per-company `session_message_limit`
# setting wins when a row exists. `parse_limit` turns a typo into this default.
SESSION_MESSAGE_LIMIT = int(os.getenv("SESSION_MESSAGE_LIMIT", "0"))
# TTL of one session's counter, refreshed on every accepted message: the cap is
# an idle window, not a lifetime ban, so a returning visitor is not punished.
SESSION_CAP_TTL_SECONDS = int(os.getenv("SESSION_CAP_TTL_SECONDS", "86400"))

# Daily sitemap diff scan (F4, D7): how often the worker looks for opted-in
# websites. Only a company with `sitemap_scan_enabled=true` is queued.
SITEMAP_SCAN_INTERVAL_SECONDS = int(
    os.getenv("SITEMAP_SCAN_INTERVAL_SECONDS", "86400")
)

# Per-conversation AI insights (F2, D3). The caps are the whole cost control:
# at most this many settled conversations per company per run, this many per
# temperature-0 LLM call, this many transcript characters per conversation, and
# this long after the last message before a conversation counts as settled.
INSIGHT_INTERVAL_SECONDS = int(os.getenv("INSIGHT_INTERVAL_SECONDS", "86400"))
INSIGHT_MAX_CONVERSATIONS = int(os.getenv("INSIGHT_MAX_CONVERSATIONS", "50"))
INSIGHT_BATCH_SIZE = int(os.getenv("INSIGHT_BATCH_SIZE", "10"))
INSIGHT_TRANSCRIPT_CHARS = int(os.getenv("INSIGHT_TRANSCRIPT_CHARS", "4000"))
INSIGHT_SETTLE_MINUTES = int(os.getenv("INSIGHT_SETTLE_MINUTES", "60"))

# New training sources (F3, D2). A YouTube playlist/channel expands to at most
# this many videos, a Notion page render to at most this many blocks, and a
# Notion database to at most this many pages, so one import can never crawl a
# whole workspace.
YOUTUBE_MAX_VIDEOS = int(os.getenv("YOUTUBE_MAX_VIDEOS", "25"))
NOTION_MAX_BLOCKS = int(os.getenv("NOTION_MAX_BLOCKS", "1000"))
NOTION_MAX_PAGES = int(os.getenv("NOTION_MAX_PAGES", "25"))
# Counting a database costs one `POST /query` per 100 pages, so a huge one must
# not be paged to the end inside a single import: `total` is exact only while it
# took at most this many query pages to find out, and a lower bound (flagged as
# `total_exact: false`) otherwise. 0 never counts past what the import cap needs.
NOTION_MAX_COUNT_PAGES = int(os.getenv("NOTION_MAX_COUNT_PAGES", "10"))

# V5 Stripe billing. No SDK import or provider call is made from configuration;
# when disabled (the default), self-hosted deployments need no Stripe settings.
BILLING_ENABLED = os.getenv("BILLING_ENABLED", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
# The plan-code → Stripe Price ID mapping, private server configuration: either
# a JSON object (`{"starter:month": "price_..."}`) or comma-separated
# `code:interval=price_...` entries. Absent mapping means that plan cannot be
# bought — Checkout fails closed rather than guessing a price (V5 invariant 8).
STRIPE_PRICE_IDS = os.getenv("STRIPE_PRICE_IDS", "").strip()
# Keep the Stripe API contract explicit and independent of SDK defaults.
STRIPE_API_VERSION = os.getenv("STRIPE_API_VERSION", "2026-11-18.endive").strip()


def validate_billing_config() -> None:
    """Fail fast on incomplete enabled billing config without exposing secrets."""
    if not BILLING_ENABLED:
        return

    missing = [
        name
        for name, value in (
            ("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY),
            ("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET),
            ("STRIPE_API_VERSION", STRIPE_API_VERSION),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "BILLING_ENABLED=true requires: " + ", ".join(missing)
        )


FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

# Comma-separated IPs/CIDRs of reverse proxies or load balancers whose
# X-Forwarded-For header may be trusted (e.g. a cloud LB with a public address).
# Loopback/private peers are trusted automatically; use this only for proxies
# that connect from a public IP, otherwise every visitor shares one rate-limit
# bucket (keyed by the LB's address). Entries that are not valid IPs/CIDRs are
# ignored.
TRUSTED_PROXY_IPS = tuple(
    entry.strip()
    for entry in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
    if entry.strip()
)

# Verbose SQL logging. Off by default in production; set SQL_ECHO=true to debug.
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() in ("1", "true", "yes", "on")

# How often (in hours) the worker should auto re-crawl a website to keep its
# knowledge base fresh. Set to 0 to disable the periodic scheduler.
CRAWL_REFRESH_HOURS = int(os.getenv("CRAWL_REFRESH_HOURS", "24"))

# Weekly digest (F6). DIGEST_ENABLED is the global switch for the worker's
# digest loop, DIGEST_CHECK_SECONDS is how often it looks for companies whose
# hour has come, and DIGEST_HOUR is the default UTC hour for a company without
# its own `digest_hour` setting. The per-company switches (`digest_enabled`,
# `digest_hour`, `digest_day`, `digest_recipients`) live in `settings`.
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
DIGEST_CHECK_SECONDS = int(os.getenv("DIGEST_CHECK_SECONDS", "3600"))

# How often the worker looks for integration deliveries that are due for a
# retry. Retries are cheap (a select and maybe one HTTP call), so this is
# minutes rather than hours; the backoff itself lives in `services/integrations`.
DELIVERY_CHECK_SECONDS = int(os.getenv("DELIVERY_CHECK_SECONDS", "60"))

# How long a settled (`delivered`/`dead`) integration delivery row is kept, in
# days (default 30). Those rows carry the event payload — a lead's name and email
# — so they are deleted once this window passes; a dead row's payload is cleared
# immediately because it can never be retried. 0 keeps the rows (the dead-payload
# clear still runs). See `services/integrations.purge_deliveries`.
DELIVERY_RETENTION_DAYS = int(os.getenv("DELIVERY_RETENTION_DAYS", "30"))

# How often the delivery retention pass runs, in seconds (default 1 hour). It is
# deliberately slower than `DELIVERY_CHECK_SECONDS`: a row only becomes due for
# deletion days after it settled, so scanning on every retry tick buys nothing.
DELIVERY_RETENTION_CHECK_SECONDS = int(
    os.getenv("DELIVERY_RETENTION_CHECK_SECONDS", "3600")
)

# How often the worker queues the retention purge for companies that set a
# `retention_days` policy. Daily: the purge removes rows older than the policy,
# so a faster tick would only re-scan the same rows.
RETENTION_CHECK_SECONDS = int(os.getenv("RETENTION_CHECK_SECONDS", "86400"))
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "9"))

# Maximum cosine distance for a retrieved chunk to be used as context. Chunks
# further away are discarded, and when nothing survives the question is
# answered with a canned "no information" reply without calling the LLM.
# Lower = stricter; raise it if relevant answers start saying "no information".
# A negative value disables the threshold (V1 behaviour: always use top-k).
# Measured with the configured embedding model: an answerable question lands at
# ~0.48-0.55 from its chunk, an unrelated one at ~0.67-0.75. 0.6 sits between
# them; 0.5 (the earlier default) rejected most legitimate questions.
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.6"))

# Largest file the API accepts from an upload or downloads from a remote source,
# in megabytes. Enforced while streaming, so an oversized request is rejected
# without being buffered into memory or written to disk in full.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Most pages one sitemap sync may create. A sitemap can list tens of thousands of
# URLs; without a cap a single click creates all of them and the next ingest
# crawls every one. Repeated syncs keep adding where the last one stopped.
# 0 disables the cap.
SITEMAP_SYNC_MAX_URLS = int(os.getenv("SITEMAP_SYNC_MAX_URLS", "500"))

# Daily ceiling on chat messages per website, counted in Redis and reset at UTC
# midnight. Per-IP rate limiting alone cannot bound what one viral embed spends
# on the owner's LLM account; 0 disables the cap.
DAILY_MESSAGE_LIMIT = int(os.getenv("DAILY_MESSAGE_LIMIT", "1000"))

# Optional: surface a "Connect Google Drive" picker in the frontend and/or
# enable a service-account backend flow. The default import path uses an access
# token sent by the client, so these are not required for basic usage.
GOOGLE_DRIVE_ENABLED = os.getenv("GOOGLE_DRIVE_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")

# The platform-owner console (V5 Wave 4). Off by default: the surface is the
# operator control plane, not a tenant feature, and D10 requires approved strong
# auth or a private-network restriction before it is reachable in production.
# While it stays false every /api/platform route answers 404.
PLATFORM_CONSOLE_ENABLED = os.getenv("PLATFORM_CONSOLE_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
