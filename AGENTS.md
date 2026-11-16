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

Unit tests use plain `unittest` (no extra deps): `uv run python -m unittest discover -s tests -v` — covers `split_text`, `extract_text_from_file`, `collect_sources`, `format_history`, `_client_ip`, the settings registry/allowlist, and the V2 services (`build_digest`, `render_digest_html`, `normalize_period`, `claim_period`, `rebuild_qa_document`, `emit_event_async`, API-key hashing/lookup). The widget's browser helpers are tested separately with node's built-in runner: `node --test tests/*.mjs` (there is deliberately no npm `test` script; `tests/test_widget_markdown.py` also shells out to node so `unittest discover` fails if it is missing and the tests regress). Also verify by import/compile: `uv run python -c "import site_gpt.app.main"` and `cd frontend && npm run build`.

Run the suite (or a single file: `uv run python -m unittest tests.test_settings -v`) after changing services under `src/site_gpt/app/services/` or the settings keys.

## Layout & ownership

- `src/site_gpt/app/main.py` — app + CORS (open, dev only) + router wiring. Add new routers here with `/api/...` prefix.
- `src/site_gpt/app/api/` — one module per resource; `routes.py` holds auth/chat/ingest/widget endpoints. Routers define full paths internally or rely on prefix in `main.py` — check before adding routes. `api/v1.py` (`/api/v1`, `X-API-Key` via `core/auth.get_api_key` + `require_scope`) reuses `claim_ingest` / `ensure_website_active` / `ensure_embed_allowed`; `api/api_key.py` (`/api/api-keys`, admin) mints and revokes keys through `services/api_keys.py` (SHA-256 + `API_KEY_PEPPER`, raw key returned once, never stored). `api/privacy.py` (`/api/privacy`, admin) owns the export and the two erasure endpoints — reuse `services/conversations.delete_conversation` rather than deleting rows by hand, and keep both routes company-scoped (a foreign `website_id` is a 404, not a 403). `api/integration.py`, `api/digest.py`, `api/analytics.py`, `api/feedback.py` and `api/handoff.py` are the other V2 routers.
- `src/site_gpt/app/models.py` + `src/site_gpt/app/db/base.py` (BaseModel: uuid `id`, `created_at/updated_at`) — all FKs use `ondelete` + cascade relationships; follow that pattern.
- `src/site_gpt/app/schemas/` — Pydantic models mirror each resource; paginated lists use `PaginatedResponse`.
- `src/site_gpt/app/services/` — `llm.py` (chat provider switches on `LLM_AI`; **embedding provider switches independently on `EMBEDDING_AI`**, defaulting to `LLM_AI`; `ALLOWED_CHAT_MODELS` is the only catalogue a runtime model switch may resolve to), `model_settings.py` (reads the company's `llm_provider`/`llm_model` pair and returns it only when it is in that catalogue), `rag.py` (raw SQL pgvector `<->` search + chat history + `SYSTEM_PROMPT`, which owns the reply-in-the-question's-language rule), `ingest.py` (chunk 1000/200 + embed), `ingest_claim.py` (atomic single-ingest claim `claim_ingest` + `STUCK_INGEST_AFTER`), `website_state.py` (the 403 for a disabled website, `ensure_website_active`), `api_keys.py` (`/api/v1` key issue/hash/lookup + scopes), `crawler.py` (sitemap + trafilatura), `parse.py` (file text extraction), `sources.py` (upload source providers), `embed_guard.py` (Origin/Referer allowlist, `is_authenticated`, and the 403-raising `ensure_embed_allowed` for public endpoints), `ratelimit.py` (in-memory per-IP limiter), `redis.py` (queue `queue:jobs` via `brpop`), `mail.py` (`await`-ing `send_email_async`; `send_email` is a sync wrapper for sync routes), `conversations.py` (session grouping + `delete_conversation`), `quota.py` (daily Redis counters), `digest.py` (`normalize_period`, `build_digest`, `render_digest_html`, `claim_period` — the claim row is inserted **before** the email so a period cannot be sent twice), `qa_training.py` (`rebuild_qa_document` → one `__qa_training__` extra document per website), `integrations.py` (`PROVIDERS`, `emit_event`/`emit_event_async`, HMAC `sha256(timestamp.body)`; every event becomes an `integration_deliveries` row *before* the first send, `attempt_delivery` records each outcome, `process_due_deliveries` is the worker's retry tick and claims each row with `SELECT … FOR UPDATE SKIP LOCKED` one at a time (a batch select would be released by the first attempt's commit, letting a second worker send rows 2..N) so two workers never send the same delivery, `purge_deliveries` clears a dead row's payload immediately (so Resend answers 409) and deletes settled rows past `DELIVERY_RETENTION_DAYS`, both in `DELIVERY_PURGE_BATCH_SIZE` (1000) id-scoped batches that commit individually — it runs on `DELIVERY_RETENTION_CHECK_SECONDS` (hourly), not on every retry tick, and `integration_deliveries` carries `(status, created_at)` for it, `resend_delivery` re-arms a dead row but first claims it with `resend_claim` (`FOR UPDATE SKIP LOCKED`) and must not commit between the claim and the send — that commit releases the lock and lets a second admin double-send (the loser gets 409); a provider failure is recorded, never raised, and a non-2xx response counts as a failure), `retention.py` (`retention_days` policy: `purge_company(db, company_id, days=None, dry_run=True)` hard-deletes expired `chat_messages`/`chat_feedback`/`handoff_requests`/`contacts`/`digest_log` through the company's websites, `_delete_batch` deletes in `RETENTION_BATCH_SIZE` (1000) id-scoped, separately committed batches so a large tenant cannot hold one long transaction, `purge_attachments` also removes expired `attachments` rows and the file each points at under `UPLOAD_ROOT` (`uploads/`, matching `api/upload.py`/`worker.py`) — scoped via the owning `extra_documents` row or, for a never-attached upload, the uploader's company; the file is unlinked only after the batch commits, a missing/unremovable file is logged not raised, and a `..` in `file_url` is refused; `companies_with_policy` is what the worker queues; `dry_run` counts without deleting — keep the `created_at < cutoff` comparison in one place so preview and apply agree), `session_tokens.py` (K4: `mint`/`verify`/`matches`/`authorize` — the widget's per-session read token; call `authorize` in any new public endpoint that returns a session's data, and never mint for a session that already has data without presenting its token — `mint` re-checks the presented token itself and turns a lost insert race into the same 403 `ALREADY_CLAIMED_DETAIL` instead of an `IntegrityError`; `chain_expired` is the absolute `SESSION_TOKEN_MAX_LIFETIME_SECONDS` ceiling measured from `created_at`, which rotation must never move; on a mint 403 the widget calls `newSession()` and mints once more — keep that single retry, an unbounded loop would hammer the endpoint).
- Settings: per-company keys live in `api/setting.py` (`DEFAULT_SETTINGS` = widget-facing, `INTERNAL_SETTINGS` = server-side; both seed registration and `PUT /api/settings`). Adding one means updating `tests/test_settings.py::INTERNAL_KEYS` (or the public tuple) in the same commit — `retention_days` is an internal key, editable from Settings → Privacy (`frontend/src/pages/Settings.tsx`) with a dry-run `POST /api/privacy/retention` preview.
- `src/site_gpt/app/core/config.py` — env-only config, no defaults with secrets except dev JWT fallback. New settings go here + `.env.example`.
- `src/site_gpt/app/scripts/widget.js` — vanilla JS, no build; config via `window.ChatWidgetConfig`.
- `frontend/src/` — pages per route (`App.tsx`), `utils/api.ts` (axios + JWT), `context/AuthContext` (token storage), Ant Design components.

## Conventions

- Python: SQLAlchemy 2.0 `Mapped/mapped_column` style, `Session = Depends(get_db)`, JWT via `core/auth.py` (`hash_password`/`verify_password`/`create_access_token`). Don't introduce new auth libs.
- Embeddings are `Vector(EMBEDDING_DIMENSIONS)` (default 1536) — the embedding model's output dimension must match `EMBEDDING_DIMENSIONS`; changing it requires an Alembic migration + re-ingest. `EMBEDDING_AI` selects the embedding provider independently of the chat provider `LLM_AI`.
- Chunking: `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` — keep consistent between `ingest.py` and new code.
- RAG search SQL lives in `rag.py::search` (single query over `embeddings` joined to `documents` **and** `extra_documents`, top 5, website-scoped with company-wide extra documents). Extend there, don't duplicate.
- Settings keys: appearance/widget keys go in `DEFAULT_SETTINGS`, server-side keys (models, emails, digest, quotas) in `INTERNAL_SETTINGS`; both seed registration and `POST /api/settings` through `ALL_SETTINGS`. `WIDGET_PUBLIC_KEYS` is an explicit literal tuple — a key is public only if you add it there deliberately, so never derive it from a registry dict.
- Mail is async: use `send_email_async(...)` (await it) in async code or worker jobs; `send_email(...)` is only a sync wrapper for sync endpoints and never blocks a running loop.
- Worker jobs are `{"type": "ingest", "website_id": ...}` on Redis list `queue:jobs`; `handle_ingest` in `worker.py` sets `websites.ingest_status` (`none → processing → completed`).
- Frontend: axios through `utils/api.ts`, Ant Design for UI, `VITE_BACKEND_URL` for base URL. No new UI framework.
- Uploads go to `uploads/` with metadata in `attachments` table (`status='tmp'` default).

## DB migrations

- Model change → `uv run alembic revision --autogenerate -m "[name]"`, review diff, `uv run alembic upgrade head`. Never edit applied migrations; ensure `pgvector` extension exists.
- Current head is `e7b3c94a1d52` (delivery retention index). The V2 chain is `07f83918a289 → c41d7e8a9f20` (api_keys, landed early) `→ 2f95a35b9d5d → 5fe07e597f12 → bebd929605ed → 94ca756068a7 → 5fbe6ce28d9b → b7d41c9e2f10 → d2f5a81c9b74 → e7b3c94a1d52`; `a1b2c3d4e5f6` is a merge revision of two older heads, not the head. Chain new migrations from the current head and keep a single linear head.
- **Indexes on busy tables are built `CONCURRENTLY`.** A plain `CREATE INDEX` takes a SHARE lock and blocks every write for the whole build, so new index migrations use `with op.get_context().autocommit_block(): op.create_index(..., postgresql_concurrently=True)` — see `d2f5a81c9b74` and `e7b3c94a1d52`. Caveats: `CONCURRENTLY` cannot run inside a transaction, so those migrations are **not atomic** (each index commits on its own and a later failure leaves the earlier ones in place); an interrupted build leaves an **invalid** index that the planner ignores but every write still maintains — drop it with `DROP INDEX CONCURRENTLY` and re-run the migration (it is not idempotent); `DROP INDEX CONCURRENTLY` needs the same autocommit block.
- Autogenerate always proposes drift: naive `DateTime()` ALTERs for the timestamptz columns (`api_keys.last_used_at`/`revoked_at`, `users.reset_token_expires_at`, `contacts.consent_at`) and a drop/create of `chat_feedback.website_id`'s FK. Remove those lines; keep only the real change.

## Do / don't

- DO reuse existing service helpers (`get_llm`, `get_embedding_model`, `embed_texts`, `enqueue_job`) instead of new clients.
- DO guard public endpoints with `services/embed_guard.ensure_embed_allowed`, check a website is servable with `services/website_state.ensure_website_active`, and claim ingests with `services/ingest_claim.claim_ingest` — never re-implement any of them in a route; a copy of the claim re-opens the double-crawl race.
- DO keep new API responses in matching `schemas/` file.
- DON'T add dependencies without need — `pyproject.toml` / `frontend/package.json` already cover LLM providers, mail, redis, antd.
- DON'T tighten CORS or rename env keys without updating `.env.example`, `README.md`, and `frontend/.env*`.
- DON'T break widget backward compat (`ChatWidgetConfig` keys, `localStorage` session/history keys).

<!-- trail:start -->
## Trail — repo context graph

This repo is indexed in `.trail/cache/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `trail map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `trail ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `trail grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `trail skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `trail callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `.trail/cache/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `trail ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `trail build` (deterministic,
no API key, $0).
<!-- trail:end -->
