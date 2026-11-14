# Project memory — site-gpt

## Versioning (user-confirmed convention, 2026-11-14)

- **V1 = the current code** (baseline commit `f571f95`, Alembic head
  `07f83918a289`). Baseline + stabilization plan: `plans/PLAN_V1.md`.
- **V2 = the SiteGPT feature-parity upgrade** (`plans/SPEC.md`, features
  F1–F10, migrations M1–M5 chaining from `07f83918a289`).
- Rule: bug fixes, documentation corrections, safer defaults and tests belong
  to V1. Any new DB table/column, API router, admin page, env var, settings key
  or dependency belongs to V2. Do not backport V2 features into V1.

## Planning docs

- `plans/PLAN_V1.md` — what V1 ships, architecture, API/frontend contracts,
  runbook, known issues K1–K12, stabilization backlog S1–S6, freeze checklist.
- `plans/SPEC.md` — V2 requirements & design, ADR-1…ADR-7, F1…F10, phased rollout.
- `plans/PLAN_V2.md` — V2 **execution plan**: 39 checkable tasks V2-01…V2-46,
  5 waves, 5 hard gates, defaults D1–D7 for SPEC's open questions, migration
  ledger, rollback plan. Start here when implementing V2.
- S1 (email delivery) and S3 (settings + widget-config allowlist) in V1 are the
  same work as SPEC Phase 0 P0.1–P0.3. Implement once, in V1.
- V2 sequencing: `services/integrations.py::emit_event` stub lands in Wave 0
  because F5/F6 (Wave 2) emit events before F7 (Wave 3) adds providers.

## Verified V1 facts worth keeping

- `services/mail.py::send_email` calls `FastMail.send_message()` (async) without
  awaiting it → no email is ever sent. Fix before relying on any mail feature.
- `GET /api/widget-config` is public and returns every `settings` row — must be
  allowlisted before any internal setting is added.
- `README.md` / `AGENTS.md` contain claims that drift from the code (settings
  idempotency, `rag.py` "documents only"). Verify against source before citing.
- `rag.py::search` is the single retrieval SQL (UNION of `documents` +
  `extra_documents`, pgvector `<->`, top 5). Chunking 1000/200,
  `EMBEDDING_DIMENSIONS` default 1536 — changing it needs a migration + full
  re-ingest.
- No test suite (`tests/` empty). Verify with
  `uv run python -c "import site_gpt.app.main"`, `npm run build`, and manual
  smoke. After significant code changes run `graft build`.
- Widget backward-compat contract: `ChatWidgetConfig` keys and `localStorage`
  keys (`chat_widget_session`, `chat_widget_history`, `chat_widget_contact`,
  `chat_widget_initialized`, `sessionId`, `access_token`) must not be renamed.
