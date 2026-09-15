from dotenv import load_dotenv
import os

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY", "your-secret-key-change-this-in-production"
)
JWT_ALGORITHM = "HS256"

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

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

# Verbose SQL logging. Off by default in production; set SQL_ECHO=true to debug.
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() in ("1", "true", "yes", "on")

# How often (in hours) the worker should auto re-crawl a website to keep its
# knowledge base fresh. Set to 0 to disable the periodic scheduler.
CRAWL_REFRESH_HOURS = int(os.getenv("CRAWL_REFRESH_HOURS", "24"))

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
