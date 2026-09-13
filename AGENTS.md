# AGENTS.md

Instructions for AI coding agents working in this repo. Backend = FastAPI (Python 3.13, `src/site_gpt/`), frontend = React+Vite+TS (`frontend/`).

## Run / verify

```bash
source .venv/bin/activate
uv run uvicorn site_gpt.app.main:app --reload   # API :8000
uv run python -m site_gpt.app.worker            # ingest worker, separate terminal
uv run alembic upgrade head                     # apply migrations
cd frontend && npm run dev                      # UI :5173 (VITE_BACKEND_URL=http://localhost:8000)
```

No test suite exists (`tests/` is empty) — verify by import/compile: `uv run python -c "import site_gpt.app.main"` and `cd frontend && npm run build`.

## Layout & ownership

- `src/site_gpt/app/main.py` — app + CORS (open, dev only) + router wiring. Add new routers here with `/api/...` prefix.
- `src/site_gpt/app/api/` — one module per resource; `routes.py` holds auth/chat/ingest/widget endpoints. Routers define full paths internally or rely on prefix in `main.py` — check before adding routes.
- `src/site_gpt/app/models.py` + `src/site_gpt/app/db/base.py` (BaseModel: uuid `id`, `created_at/updated_at`) — all FKs use `ondelete` + cascade relationships; follow that pattern.
- `src/site_gpt/app/schemas/` — Pydantic models mirror each resource; paginated lists use `PaginatedResponse`.
- `src/site_gpt/app/services/` — `llm.py` (multi-provider switch on `LLM_AI`), `rag.py` (raw SQL pgvector `<->` search + chat history), `ingest.py` (chunk 1000/200 + embed), `crawler.py` (sitemap + trafilatura), `redis.py` (queue `queue:jobs` via `brpop`), `mail.py`.
- `src/site_gpt/app/core/config.py` — env-only config, no defaults with secrets except dev JWT fallback. New settings go here + `.env.example`.
- `src/site_gpt/app/scripts/widget.js` — vanilla JS, no build; config via `window.ChatWidgetConfig`.
- `frontend/src/` — pages per route (`App.tsx`), `utils/api.ts` (axios + JWT), `context/AuthContext` (token storage), Ant Design components.

## Conventions

- Python: SQLAlchemy 2.0 `Mapped/mapped_column` style, `Session = Depends(get_db)`, JWT via `core/auth.py` (`hash_password`/`verify_password`/`create_access_token`). Don't introduce new auth libs.
- Embeddings are `Vector(1536)` — embedding model changes must match this dimension or require a migration.
- Chunking: `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` — keep consistent between `ingest.py` and new code.
- RAG search SQL lives in `rag.py::search` (documents only, top 5, `website_id` scoped). Extend there, don't duplicate.
- Worker jobs are `{"type": "ingest", "website_id": ...}` on Redis list `queue:jobs`; `handle_ingest` in `worker.py` sets `websites.ingest_status` (`none → processing → completed`).
- Frontend: axios through `utils/api.ts`, Ant Design for UI, `VITE_BACKEND_URL` for base URL. No new UI framework.
- Uploads go to `uploads/` with metadata in `attachments` table (`status='tmp'` default).

## DB migrations

- Model change → `uv run alembic revision --autogenerate -m "[name]"`, review diff, `uv run alembic upgrade head`. Never edit applied migrations; ensure `pgvector` extension exists.

## Do / don't

- DO reuse existing service helpers (`get_llm`, `get_embedding_model`, `embed_texts`, `enqueue_job`) instead of new clients.
- DO keep new API responses in matching `schemas/` file.
- DON'T add dependencies without need — `pyproject.toml` / `frontend/package.json` already cover LLM providers, mail, redis, antd.
- DON'T tighten CORS or rename env keys without updating `.env.example`, `README.md`, and `frontend/.env*`.
- DON'T break widget backward compat (`ChatWidgetConfig` keys, `localStorage` session/history keys).
