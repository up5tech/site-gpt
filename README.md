# SiteGPT

Turn any company website + extra documents into an embeddable AI chat bot (RAG).

![Example](./site-gpt.png)

## How it works

1. Register company → creates company + admin user
2. Add website (URL + sitemap) → add/select pages → `POST /api/ingest`
3. Worker crawls pages (`trafilatura`), chunks (1000/200), embeds, stores in `pgvector`
4. Extra documents (text/file uploads in `uploads/`) are ingested the same way
5. Chat: `POST /api/chat` → embed question → pgvector similarity search (top 5) → LLM answers with context + last 10 chat messages
6. Embed on any site via `GET /widget.js`

## Tech stack

- **Backend:** FastAPI, SQLAlchemy, Alembic, pgvector, Redis (queue), JWT (`python-jose`), multi-LLM via LangChain (`ollama` / `openai` / `custom_openai` / `gemini` / `groq` / `openrouter`)
- **Frontend:** React 18 + Vite + TypeScript + Ant Design + axios + react-router
- **Infra:** PostgreSQL + pgvector, Redis, Ollama (default local LLM)

## Repo structure

```
src/site_gpt/app/
  main.py              # FastAPI app + router wiring
  api/                 # routes.py (auth/chat/ingest/widget), company, user, website, document, extra_document, setting, upload
  models.py            # Company, User, Website, WebsitePage, Document, ExtraDocument, Attachment, Embedding, ChatMessage, Setting
  schemas/             # Pydantic request/response per resource
  services/            # llm.py, rag.py, ingest.py, crawler.py, redis.py, mail.py
  core/                # config.py (env), auth.py (hash/JWT)
  db/                  # session.py, base.py, vector_store.py
  scripts/widget.js    # embeddable chat widget (window.ChatWidgetConfig)
  worker.py            # Redis queue consumer (ingest jobs)
frontend/src/
  pages/ (Dashboard, Websites, WebsiteDetail, ExtraDocuments, Users, Settings, Login, Register)
  components/ (Layout, Chat, WebsiteTable, CompanyTable, UserTable)
  context/ (AuthContext, ChatContext), utils/api.ts, types/api.ts
alembic/                # DB migrations
uploads/                # uploaded attachment storage
```

## Prerequisites

- Python 3.13 + `uv`, Node 18+, PostgreSQL with `pgvector` extension, Redis, Ollama (or any LLM API key)

## Setup — backend

```bash
cp .env.example .env   # fill DATABASE_URL, LLM_*, REDIS_*, MAIL_*
uv venv --python 3.13 && source .venv/bin/activate
uv sync
uv run alembic upgrade head
uv run uvicorn site_gpt.app.main:app --reload        # API :8000
uv run python -m site_gpt.app.worker                 # ingest worker (separate terminal)
```

## Setup — frontend

```bash
cd frontend
echo "VITE_BACKEND_URL=http://localhost:8000" > .env
npm install && npm run dev   # :5173
```

## Env vars

| Key | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | SQLAlchemy Postgres URL |
| `LLM_AI` | `openai` | `ollama\|openai\|custom_openai\|gemini\|groq\|openrouter` |
| `LLM_MODEL` | `gpt-4o-mini` | chat model |
| `LLM_EMBEDDING_MODEL` | `text-embedding-3-small` | embedding model |
| `OPENAI_API_BASE_URL` / `OPENAI_API_KEY` | — | OpenAI or Ollama-compatible endpoint |
| `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPEN_ROUTER_API_KEY` | — | provider keys |
| `OLLAMA_HOST` / `OLLAMA_USERNAME` / `OLLAMA_PASSWORD` | `http://localhost:11434` | Ollama (optional basic auth) |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB` | `localhost/6379` | job queue |
| `MAIL_*` | — | forgot/reset password via fastapi-mail |
| `JWT_SECRET_KEY` | dev default | **change in prod** |
| `VITE_BACKEND_URL` (frontend) | — | backend base URL |

## Key API endpoints

- `POST /api/register` — create company + admin user
- `POST /api/token` — login → JWT
- `POST /api/ingest?website_id=` — enqueue crawl+embed job
- `POST /api/chat` — `{website_id, session_id, question}` → `{answer}`
- `GET /widget.js` — embeddable widget
- `GET /health`
- `/api/companies`, `/api/users` (+`/me`, `/forgot-password`, `/reset-password`), `/api/websites` (+`/{id}/pages`, `/{id}/load-site-map`), `/api/documents`, `/api/extra_documents`, `/api/settings`, `/api/uploads`

## Embed widget

```html
<script>
  window.ChatWidgetConfig = { apiUrl: 'http://localhost:8000', website_id: '<WEBSITE_ID>' };
</script>
<script src="http://localhost:8000/widget.js"></script>
```

## Dev commands

```bash
uv run alembic revision --autogenerate -m "[name]" && uv run alembic upgrade head
cd frontend && npm run build && npm run lint
```

## Embedding dimension caveat

The `embeddings` table column is `Vector(1536)` (matches OpenAI `text-embedding-3-small`).
If you switch `LLM_AI` to **ollama** with an embedding model that outputs a different
dimension (e.g. `nomic-embed-text` → 768), ingestion will fail on insert. Either keep a
1536-dim embedding model, or change the column dimension + `Embedding.embedding` in
`models.py` to match and regenerate a migration.

## Fixes & improvements applied

- **RAG now answers from uploaded documents too.** `services/rag.py::search` previously
  only queried `documents` (crawled pages). It now UNIONs `embeddings` from both
  `documents` (by `website_id`) and `extra_documents` (by `website_id` **or** company), so
  the chatbot actually uses the knowledge users upload.
- **Ingestion no longer crashes.** `crawler.crawl_page` now returns `(title, text)`, fixing
  the `KeyError: 'title'` that broke every ingest job in `worker.py`. The worker also
  upserts pages by URL (no more duplicate growth) and is wrapped in error handling that sets
  `ingest_status = 'failed'` on error.
- **Uploaded files are now searchable.** New `services/parse.py` extracts text from
  `.txt/.md/.csv/.json/.html/.pdf/.docx` and the worker embeds both the extra-document text
  **and** its attachment contents (added `pypdf` + `python-docx` deps).
- **Re-ingest is idempotent.** `ingest_document` / `ingest_extra_document` drop existing
  chunks before re-embedding, so re-running ingest won't duplicate vectors.
- **`POST /api/ingest` is now protected** — requires a manager/admin token and ownership of
  the website (was fully public).
- **Settings are scoped per company** — `GET/PUT /api/settings` no longer leaks or edits
  other companies' settings.
- **Upload safety** — files are stored under a UUID name (collision- and path-traversal-safe)
  instead of the raw filename.
- **Forgot/reset password fixed & secured** — old flow overwrote the live password with a
  garbage hash and sent no email. Now `forgot-password` issues a 30-min token, emails a
  reset link (`FRONTEND_URL`), and `reset-password` verifies the token + expiry. Added
  `reset_token` / `reset_token_expires_at` columns (migration `3f1a9c0d7e22`).
- **CORS** — `allow_credentials` is auto-disabled when `CORS_ORIGINS=*`
  (browsers reject the wildcard+credentials combo). Set an explicit origin list in prod.
- **Dead dual embedding backend removed** — dropped `db/vector_store.py` + unused
  `ingest_documents` (langchain-postgres `PGVector`) to avoid a second, divergent vector
  store.
- **Chat prompt** — `ask()` now uses a system instruction to answer only from context and
  say it lacks the info otherwise.
