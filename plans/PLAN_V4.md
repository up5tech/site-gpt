# PLAN — Version 4 execution plan

| | | |
|---|---|---|
| Version | **V4** — closes the feature gap against sitegpt.ai recorded in the 2026-11-20 comparison (§2): advanced analytics, per-conversation AI insights, new training sources, per-conversation cost caps + sitemap auto-scan, and a hosted chat page |
| Status | **Draft — planning only. No task started, no gate run, no migration written.** D1–D9 below are defaults verified against code anchors (§3); the environment pre-flight is unticked and must run before Wave 0 closes |
| Created | 2026-11-20 |
| Derived from | `plans/PLAN_V3.md` (§2 non-goals, §4 invariants, §8 release-tag policy), `plans/SPEC.md`, `README.md` §V3, `docs/security.md` §5 (K18 stays accepted), and the sitegpt.ai feature/pricing comparison of 2026-11-20 (gap list reproduced in §2 so this plan is self-contained) |
| Baseline | V3 tag `v3` = `2e5ab734b09b4eb229f927a875e737153c544779` (immutable); current `master` HEAD `6dd8866e3bc3d4821d39727858fb4eb9a9f18871` is docs-only after the tag; V4 work lives on `feat/v4` branched from current `master`; Alembic head `1c5516fa864d`; suite counts are historical (V3-4G recorded 47 modules / 718 Python tests / 46 node checks) and **must be re-run at pre-flight, never copied** |
| Scope | 5 features (F1–F5), 6 waves (W0–W5), 6 gates, 1 migration (M10), 25 tasks, exactly 2 new Python dependencies (D2), 0 new JS dependencies |
| Review note | Pre-implementation plan. Every feature is off by default; with all V4 flags off the deployment behaves exactly as tag `v3` |
| Out of scope | iOS app, WhatsApp / Messenger / Google Chat / Freshdesk Messaging / Zoho SalesIQ channels, Zendesk AI Agent (OAuth install), AI Email Support, Dropbox / OneDrive / Box / GitHub sources (each needs its own OAuth app — V5 candidates), white-label / billing / plans, SOC 2 Type II / HIPAA BAA / signed DPA / "GDPR certification" (legal, not code — unchanged since V2), a charting library (D1), an `EMBEDDING_DIMENSIONS` change (**no re-ingest anywhere in V4**), WebSocket transport, a second auth library, and any backport of V4 work into V3 |

---

## 1. How to use this plan

- Each task has an ID `V4-xx`, a size (`S` / `M` / `L`), a dependency, the files it
  touches, what to do, and a **Done when** condition. Tick the box only when that
  condition is met; add a `Done:` line with the evidence, as `PLAN_V3.md` does.
- **Follow the dependency graph.** Wave 1 starts only after the Wave 0 gate
  (`V4-0G`), then Wave 2 after `V4-1G`, and so on. Do not parallelize a task
  against a gate it depends on; §6 is authoritative.
- **One task ≈ one commit**, on branch `feat/v4` (branch from current `master`
  after verifying its delta from the `v3` tag, not from the tag itself — the
  docs commits above the tag are expected, §8 of PLAN_V3). A gate is its own
  commit — `chore(v4): V4-NG gate — docs + trail build`.
- `PLAN_V3.md` says what V3 did; this file says what V4 does and in what order.
  When a V4 task contradicts `README.md`, `AGENTS.md` or `docs/security.md`, fix
  the docs in that task rather than deferring.
- Sizes are relative complexity, not time estimates.
- **Wave order is deliberate:** analytics first (no provider cost, no schema),
  then the spend/freshness guards (they must exist **before** V4 adds features
  that cost provider money), then sources, then insights (the LLM-cost feature,
  built last among the data features so the caps and claim patterns are already
  proven), then the hosted page (smallest, but touches `embed_guard`, so it gets
  its own wave and negative tests).

---

## 2. Traceability matrix — the gap this plan closes

Gap source: sitegpt.ai homepage + pricing pages, fetched 2026-11-20. The project
already matches the Growth tier's core (widget, digest, handoff + live inbox,
leads, Q&A training, Slack/Zendesk/Crisp/webhook integrations, scoped API keys,
rate limiting, auto re-crawl) and parts of Scale (signed durable webhooks,
weekly topic clustering). What remains, and where V4 answers it:

| V4 feature | sitegpt.ai capability it matches | Tier there | What the repo has today (verified anchor) | Migration | Wave | Exit criterion |
|---|---|---|---|---|---|---|
| F1 Advanced analytics | Daily trend charts, engagement funnel, CSV export, "exact top questions visitors keep asking" | Growth+ | `GET /api/analytics/summary` returns only `build_digest` aggregates over a rolling window (`api/analytics.py:22-33`); no trend, funnel, export or repeated-question list | — | 1 | Trend + funnel + top questions render from one shared definition; aggregate CSV downloads; digest payload byte-unchanged |
| F2 Per-conversation AI insights | "AI-classified topics, sentiment, and resolution outcomes for every conversation" | Scale+ | Topic clusters exist but are **weekly aggregates** (`services/topics.py`); nothing classifies an individual conversation | M10 | 4 | Opt-in company gets sentiment/resolution/summary per conversation at bounded provider cost; rows are derived data that cascade with erasure/retention |
| F3 New training sources | YouTube videos/playlists/channels; Notion; PPTX uploads | all tiers | `services/sources.py` registry has only `local`/`url`/`google_drive`; `services/parse.py` handles txt/md/csv/json/html/pdf/docx — **no pptx** (`parse.py:10-65`) | — | 3 | A YouTube playlist, a Notion page and a `.pptx` file all become searchable knowledge through the **unchanged** ingest pipeline |
| F4 Cost & freshness controls | "Rate Limiting: max messages per conversation"; "Auto Scan (Daily): find new or removed URLs" | Growth+ / Scale+ | `services/quota.py` caps per **website per day** only; sitemap sync is manual (`crawler.extract_urls_from_sitemap`, `crawler.py:82`); `scheduler_loop` re-crawls known pages but never re-reads the sitemap | — | 2 | A chatty single session hits a friendly per-session ceiling without spending the daily budget; an opted-in site picks up new/removed sitemap URLs daily without wiping knowledge on a bad fetch |
| F5 Hosted chat page | "Each chatbot gets its own unique url… directly link to the chatbot" | all tiers | Widget is embed-only (`GET /widget.js` + `ChatWidgetConfig`); no first-party page | — | 5 | `GET /chat/{website_id}` serves a full-page chat that passes the same guards as the embed; third-party origin posture (K18) unchanged |

**Explicitly deferred (V5 candidates, not silently dropped):** mobile agent app,
chat channels (WhatsApp/Messenger/Google Chat/Freshdesk/Zoho SalesIQ), Zendesk AI
Agent OAuth install, AI Email Support, Dropbox/OneDrive/Box/GitHub providers,
white-label and billing. Compliance certifications remain legal work, not code
(D9). Anything beyond the five features here is a new plan.

---

## 3. Pre-flight decisions (blocking)

Resolve these before the affected wave starts; record any change here first.
Changing one after its wave is complete means rework, so decide now.

| ID | Question | Default for V4 | Revisit before |
|---|---|---|---|
| D1 | How are trend/funnel charts rendered? | **Hand-rolled inline SVG inside `frontend/src/pages/Analytics.tsx`, Ant Design for everything else.** No charting library — the V3 non-goal stands. The dataset is tiny (≤ 90 daily points, 5 funnel stages), so a dependency buys nothing. Charts get direct labels and luminance-separable fills, not color-only encoding. | V4-12 |
| D2 | Which new dependencies are allowed? | **Exactly two Python packages: `python-pptx` (PPTX text) and `youtube-transcript-api` (YouTube captions).** Both follow the `pypdf`/`python-docx` optional-import pattern in `parse.py` — a clear error when missing, never a silent skip. Notion uses the **existing `httpx`** against `api.notion.com` (no SDK). No new JS dependency. Versions pinned in `pyproject.toml` + `uv.lock` in V4-03; any further package needs a rewritten D2 first. | V4-03 |
| D3 | Insight storage, claim, cost and refresh | **One `conversation_insights` row per conversation (unique `conversation_id`, FK CASCADE), no runs table.** The unique insert **is** the claim (lost race → skip, the `ensure_conversation`/`topics.claim_run` precedent). Eligible: ≥ 1 visitor message, settled (`last_message_at` older than `INSIGHT_SETTLE_MINUTES`), and no row or a completed row older than the conversation's newest message. Caps: ≤ `INSIGHT_MAX_CONVERSATIONS` (50) per company per run, transcript ≤ `INSIGHT_TRANSCRIPT_CHARS` (4000) over the last ≤ 20 messages, ≤ `INSIGHT_BATCH_SIZE` (10) conversations per temperature-0 LLM call, fixed prompt treating transcripts as untrusted data (the topics naming precedent). A completed row may be refreshed in place when the conversation grows; `failed` retries next tick. Rows store enums + a ≤ 280-char summary — **never raw transcript text**. | V4-41 |
| D4 | Funnel / top-question definitions, and the digest | **One definition, shared with the digest's session/unanswered semantics.** Funnel stages (each a count of distinct sessions in the window): `started` → `answered` (≥ 1 `assistant`/`agent` reply) → `lead` (a `contacts` row) → `handoff` (a `handoff_requests` row) → `human` (a `conversations` row that reached `human`). Stages are documented as overlapping counts, not a strict subset chain. Top questions = exact-match grouping of normalized visitor questions (lowercase, whitespace collapsed, trailing punctuation stripped), top 10 with counts — **no embeddings, no LLM**. The weekly **digest payload stays byte-for-byte unchanged** in V4 (the V3 guarantee is not reopened); insights surface only in the console and `/api/analytics/*`. | V4-10 |
| D5 | What does the CSV export contain? | **Aggregates only** — daily trend, funnel, top questions/topics for the requested window. Manager+, company-scoped, `text/csv` attachment. Every cell starting with `=`, `+`, `-`, `@`, TAB or CR is prefixed with `'` (spreadsheet formula injection). **No PII**: transcripts, contacts and session ids stay in the existing `/api/privacy/export`, which already owns that surface. | V4-11 |
| D6 | Per-session cap semantics and ordering | **Internal key `session_message_limit` (default `0` = off, seeded from env `SESSION_MESSAGE_LIMIT`).** Counts visitor (`role='user'`) messages per `(website_id, session_id)` in Redis (`quota:session:<website>:<session>`, TTL `SESSION_CAP_TTL_SECONDS` = 86400, refreshed on each accepted message — an idle window, not a lifetime ban). Order in the chat handlers: per-IP limiter (burst) → **session cap** → daily quota consume — a session-capped refusal never spends the daily budget. Refusal is a friendly answer / the usual SSE `chunk`+`done` pair (`quota_sse_events` precedent), no LLM call, no session reset. Redis outage **fails open** exactly like the daily quota. | V4-20 |
| D7 | Sitemap auto-scan safety | **Internal key `sitemap_scan_enabled` (default `false`), company-wide; worker `sitemap_loop` every `SITEMAP_SCAN_INTERVAL_SECONDS` (86400).** Only `active` websites with a sitemap URL of opted-in companies. New pages capped by the existing `SITEMAP_SYNC_MAX_URLS`; a URL that disappeared is marked inactive and its document deleted (the existing page-delete semantics). **A failed or empty sitemap fetch changes nothing** — removals are applied only after a fully successful, non-empty fetch, so a transient 500 can never wipe a knowledge base. Ingest is queued only when something changed, through `claim_ingest` (a processing site is skipped, never double-crawled). No new column in V4; the website detail page keeps showing pages + `ingest_status`. | V4-22 |
| D8 | Hosted page vs the Origin allowlist | **First-party exception, narrowly scoped:** `embed_guard` additionally accepts an `Origin`/`Referer` whose scheme+host+port equals the API's **own request origin** (`request.base_url`) — the hosted page is served by this API, so its chat calls are first-party. Third-party origins keep the exact V3 behaviour; the no-Origin soft acceptance (K18) is unchanged and stays documented as accepted. The page is public, `ensure_website_active` applies (a disabled site renders the widget's existing unavailable state), and every chat call keeps the IP limiter, session cap, daily quota and K4 session token. `ChatWidgetConfig` gains one **optional** key `displayMode: 'page'` (default `'bubble'`); no `localStorage` key changes. | V4-51 |
| D9 | Legal/commercial items | **Still out of scope** — SOC 2, HIPAA BAA, signed DPA, pricing, trial, white-label, mobile app, chat channels. V4 adds no compliance claim and no marketing wording; `docs/security.md` §1 stays true. | — |

**D1–D9 verified against code (plan authoring, 2026-11-20) — anchors confirmed:**

- D1: `frontend/src/pages/Analytics.tsx` exists; `frontend/package.json` has no
  chart library; V3 §2 non-goals already forbid one. Confirmed.
- D2: `services/parse.py:45-63` is the optional-dependency precedent (`pypdf`,
  `python-docx` imported inside the branch); `services/sources.py:33-91` already
  downloads via `httpx` with `read_limited` (size cap) and a credential-host
  rule. No `youtube`, `notion` or `pptx` code exists anywhere in `src/`.
  Confirmed.
- D3: `models.py:295` — `conversations` is unique on `(website_id, session_id)`
  with `last_message_at`; `services/topics.py` owns the claim/cap/untrusted-prompt
  pattern to copy. Confirmed.
- D4: `api/analytics.py:22-33` reuses `build_digest` so page and email cannot
  disagree; `chat_messages.answered` (`models.py:270`) and
  `idx_chat_messages_website_id_created_at` (`models.py:258`) already exist —
  trend/funnel need **no new index**. Confirmed.
- D5: `/api/privacy/export` already owns PII export (`api/privacy.py`); the
  analytics CSV is a second, aggregate-only surface. Confirmed.
- D6: `services/quota.py:30-119` — `parse_limit`, `consume_message`,
  `quota_sse_events` are the exact helpers to extend; README "Limit composition"
  documents the current ordering the session cap slots into. Confirmed.
- D7: `crawler.extract_urls_from_sitemap(..., raise_on_error=...)`
  (`crawler.py:82-101`), `worker.scheduler_loop` (`worker.py:619-666`) and
  `topic_loop` (`worker.py:562-574`) are the loop precedents; `claim_ingest`
  guards the queue. Confirmed.
- D8: `services/embed_guard.py:42` (`LOOPBACK_HOSTS`) and `:185`
  (`ensure_embed_allowed`) — the guard already has a documented first-party-style
  exception (loopback demos); the hosted-page origin rule extends the same
  function, never a copy. Confirmed.
- D9: `docs/security.md` §1 makes no compliance claim; V4 keeps it that way.
  Confirmed.

### Environment pre-flight

- [ ] Confirm `v3` resolves to `2e5ab734b09b4eb229f927a875e737153c544779`, record
      `git rev-parse HEAD` (`6dd8866…` at authoring), inspect the delta from the
      tag (expected: docs-only), and branch `feat/v4` from current `master`.
      Keep unrelated code changes out of the V4 starting point.
- [ ] `uv run alembic current` = `uv run alembic heads` = `1c5516fa864d` (single
      head). M10 chains from it.
- [ ] `pg_dump` backup before M10 (`backups/`, already gitignored).
- [ ] Redis reachable (`GET /health` reports `redis: true`); if not, the session
      cap and insight loop remain implementable but their Redis paths cannot be
      verified — record those checks as **blocked**, never tick them silently.
- [ ] Baseline green, counts recorded from the **actual run**:
      `uv run python -m unittest discover -s tests -v`,
      `node --test tests/*.mjs`, `cd frontend && npm run build && npm run lint`,
      `trail build`. (V3-4G recorded 47 modules / 718 / 46 — do not copy.)
- [ ] Provider reachability probe for D2/D3: can this environment reach
      `youtube.com` captions and `api.notion.com`, and is an LLM/embedding
      provider configured? If not, F2/F3 end-to-end checks are **blocked and
      unexecuted** at their gates (unit tests with stubs still run), exactly as
      V3-4G recorded its provider-bound items.

---

## 4. Invariants (every task)

Carried from `PLAN_V3.md` §4 and `AGENTS.md`; new V4 rules marked **V4**.

1. `ChatWidgetConfig` keys and every `localStorage` key stay valid; new config is
   optional with a default. **V4:** `displayMode` is additive — a snippet that
   never sends it renders the bubble exactly as before.
2. `services/rag.py::search` stays the only retrieval SQL. New sources normalize
   into local files under `uploads/` so `parse.py` → chunk → embed is unchanged;
   insights read bounded `chat_messages`, never the `embeddings` table.
3. Chunking stays 1000/200 via `split_text`.
4. `EMBEDDING_DIMENSIONS` unchanged → **no re-ingest at any point in V4**.
5. Reuse `get_llm`, `embed_texts`, `enqueue_job`, `rate_limit`, `send_email_async`,
   `authorize`, `claim_ingest`, `parse_limit`, `consume_message`. No new SDK
   client; the **only** new dependencies are the two approved in D2.
6. Public endpoints keep `ensure_embed_allowed` + `ensure_website_active`;
   the hosted-page origin rule **extends** `embed_guard`, never a parallel copy.
7. New env var → `core/config.py` + `.env.example` + the README table, same task.
8. New settings key → `api/setting.py` registry **and** `tests/test_settings.py`'s
   `INTERNAL_KEYS`/public tuple in the same commit. `WIDGET_PUBLIC_KEYS` stays
   **exactly 14** — no V4 key is widget-public.
9. Every feature is **off by default** (`session_message_limit=0`,
   `sitemap_scan_enabled=false`, `conversation_insights_enabled=false`). With all
   V4 flags off, behaviour equals tag `v3`, including a byte-identical digest.
10. Tenant scoping is not optional: every analytics, insight, export and hosted
    page query filters by company/website ownership; a foreign resource id is a
    **404**, never a 403.
11. Migrations that add indexes to busy tables build `CONCURRENTLY` inside
    `op.get_context().autocommit_block()`. M10 is a **new empty table** — its
    indexes build transactionally (the M7/M8 precedent).
12. After each gate: `trail build`, then update `README.md`, `AGENTS.md`,
    `docs/security.md` (where affected) and this file's dashboard — inside the
    gate commit, never after the tag.
13. Redis counters and pub/sub are best-effort: the session cap fails open on a
    Redis outage (D6), and no V4 feature stores state only in Redis.
14. **V4:** insight rows are derived data. They cascade from `conversations`
    (FK `ON DELETE CASCADE`), so `erase_session`, `delete_conversation` and the
    retention purge cover them **without a second delete path** — and a task
    that touches any of those must prove it with a test, not assume it.
15. **V4:** the weekly digest payload (JSON and HTML) stays byte-for-byte the
    V3 output. F1/F2 surface in `/api/analytics/*` and the console only.
16. **V4:** the analytics CSV contains aggregates only — no session ids, no
    contact details, no message text — and neutralizes formula-leading cells.

---

## 5. Waves

### Wave 0 — Foundation (no schema change)

**Goal:** lock the nine contracts, add the two approved dependencies and the
env/settings scaffolding, and record a real baseline so no wave invents its own
version. **Entry:** environment pre-flight above.

- [ ] **V4-01 · Decisions + scope doc** — `S`, depends: —, migration: —
  - Files: `plans/PLAN_V4.md`.
  - Do: re-verify every D-row against the code (the anchors in §3 were checked
    at authoring; re-check anything that moved). Confirm the deferred list in
    §2 is still the right scope. Record the environment pre-flight results.
  - Done when: every D-row is confirmed or rewritten here first, and no task
    below depends on an unconfirmed decision.

- [ ] **V4-02 · Env + settings scaffolding** — `S`, depends: V4-01, migration: —
  - Files: `core/config.py`, `.env.example`, `README.md`, `api/setting.py`,
    `tests/test_settings.py`.
  - Do: add (all defaulted to the V3 behaviour) `SESSION_MESSAGE_LIMIT=0`,
    `SESSION_CAP_TTL_SECONDS=86400`, `SITEMAP_SCAN_INTERVAL_SECONDS=86400`,
    `INSIGHT_INTERVAL_SECONDS=86400`, `INSIGHT_MAX_CONVERSATIONS=50`,
    `INSIGHT_BATCH_SIZE=10`, `INSIGHT_TRANSCRIPT_CHARS=4000`,
    `INSIGHT_SETTLE_MINUTES=60`, `YOUTUBE_MAX_VIDEOS=25`,
    `NOTION_MAX_BLOCKS=1000`, `NOTION_MAX_PAGES=25`; internal keys
    `session_message_limit` (`"0"`), `sitemap_scan_enabled` (`"false"`),
    `conversation_insights_enabled` (`"false"`). Nothing is wired yet beyond
    the registry, so `WIDGET_PUBLIC_KEYS` does not grow.
  - Done when: settings tests pass at the new key count, `GET /api/widget-config`
    still publishes exactly the 14 allowlisted keys, and `.env.example`
    documents every variable with its default.

- [ ] **V4-03 · The two approved dependencies** — `S`, depends: V4-02, migration: —
  - Files: `pyproject.toml`, `uv.lock`, `services/parse.py` (import probe only).
  - Do: add `python-pptx` and `youtube-transcript-api`, pinned, with a one-line
    justification each in the commit body (D2). Verify `uv sync` resolves and
    `import site_gpt.app.main` / `worker` still pass with both installed **and**
    with neither importable at module load (they are branch-local imports, the
    `pypdf` pattern). No other package changes.
  - Done when: `uv.lock` diff contains only the two packages and their
    transitive deps, and a missing-package path raises a clear error rather
    than failing silently.

- [ ] **V4-04 · Test + graph baseline** — `S`, depends: V4-03, migration: —
  - Files: `AGENTS.md`, `tests/`, `.trail/`.
  - Do: state in `AGENTS.md` which suites V4 extends (no new runner), point at
    this plan's §9 runbook, run `trail build`. Record the real baseline counts
    in the pre-flight block — from the run, not from a doc.
  - Done when: the recorded counts match a real run, and `trail ask` finds the
    new settings keys.

#### Gate V4-0G

- [ ] `uv run python -c "import site_gpt.app.main"` and `import site_gpt.app.worker` pass.
- [ ] `alembic current` is still `1c5516fa864d` (Wave 0 adds no revision).
- [ ] Both suites, `npm run build && npm run lint`, `trail build` pass; counts recorded.
- [ ] `GET /api/widget-config` unchanged (14 keys); `/health` unchanged.
- [ ] commit `chore(v4): V4-0G gate — foundation`.

---

### Wave 1 — F1 Advanced analytics (no schema change)

**Goal:** daily trends, an engagement funnel, repeated-question detection and an
aggregate CSV export — from the data already stored, with the digest's
definitions, no new index and no chart library. **Entry:** V4-0G.

- [ ] **V4-10 · Trend, funnel and top questions, one definition** — `M`, depends: V4-0G, migration: —
  - Files: `services/analytics.py` (new), `services/digest.py` (read-only reuse),
    `schemas/digest.py`, `api/analytics.py`, `api/v1.py`,
    `tests/test_analytics.py` (new).
  - Do: add `daily_trend(db, company_id, start, end)` (per-UTC-day conversations,
    messages, visitor messages, new contacts, 👍/👎, unanswered — grouped over
    the company's websites, riding `idx_chat_messages_website_id_created_at`),
    `engagement_funnel(...)` (the five D4 stages, distinct sessions each) and
    `top_questions(...)` (normalized exact-match grouping, top 10 with counts).
    Import the session/unanswered definitions from `digest.py` — do not fork
    them. Extend `AnalyticsSummary` **additively** (`trend`, `funnel`,
    `top_questions`); existing keys keep their exact meaning, so
    `/api/v1/analytics/summary` gains the fields without a contract break.
    `build_digest` is not edited.
  - Done when: unit tests pin each aggregation against a seeded fixture
    (multi-website company, agent rows, an unanswered question, a lead without
    a handoff); a foreign company id reads nothing; the digest output for the
    same fixture is byte-identical to the pre-change module.

- [ ] **V4-11 · Aggregate CSV export** — `S`, depends: V4-10, migration: —
  - Files: `api/analytics.py`, `services/analytics.py`, `schemas/`,
    `tests/test_analytics_export.py` (new).
  - Do: `GET /api/analytics/export.csv?days=` — manager+, company-scoped,
    `text/csv` attachment named with the window dates, rows = daily trend +
    funnel + top questions (D5). Neutralize every cell leading with `=`, `+`,
    `-`, `@`, TAB or CR by prefixing `'`. No session ids, no contact fields, no
    message text. Reuse the V4-10 helpers; no second aggregation.
  - Done when: a test downloads the CSV, asserts the header/row shape, asserts
    a question starting with `=HYPERLINK(...)` comes out neutralized, and
    asserts a manager of another company gets 404/empty-for-own-data only.

- [ ] **V4-12 · Analytics page: SVG trend, funnel, top questions, export** — `M`, depends: V4-11, migration: —
  - Files: `frontend/src/pages/Analytics.tsx`, `frontend/src/types/api.ts`,
    `frontend/src/utils/api.ts`.
  - Do: render the daily trend as a hand-rolled SVG bar/line chart (D1) with
    direct value labels and a luminance-separable two-series fill (messages vs
    conversations), the funnel as five labelled horizontal bars with counts and
    stage-to-stage conversion, and top questions as an Ant Design table with
    counts. Add an **Export CSV** button hitting V4-11 (window = the page's
    current `days` selector). Keep every existing card unchanged; new sections
    degrade to "no data in this window" on an empty range, never a broken axis.
  - Done when: `npm run build && npm run lint` pass; the page renders seeded
    data end-to-end against the dev API (or the blocked-item rule applies and
    the component is exercised with a fixture); the 1-day and 90-day windows
    both render without overflow at desktop and mobile widths.

- [ ] **V4-13 · Docs: analytics surface** — `S`, depends: V4-12, migration: —
  - Files: `README.md`, `AGENTS.md`, `docs/api-v1.md`.
  - Do: document the new summary fields, the CSV endpoint and its
    aggregate-only/PII boundary, and the funnel definition (overlapping counts,
    not a strict chain). Note the additive `/api/v1` change in `docs/api-v1.md`.
  - Done when: no doc still describes analytics as "counts + topics only", and
    the digest-unchanged guarantee is stated where F2 will later be tempted.

#### Gate V4-1G

- [ ] Both suites + widget suite + build + lint + `trail build` pass; `alembic current` unchanged.
- [ ] Digest byte-comparison: `build_digest` JSON + HTML for a fixed fixture
      identical to the module loaded from tag `v3` (the V3-3G technique).
- [ ] CSV downloaded by hand from the dev API; formula cell neutralized; no PII
      column present (record the header line here).
- [ ] `/api/v1/analytics/summary` with a `read`-scoped key returns the new fields
      and still refuses a foreign website id with 404.
- [ ] commit `chore(v4): V4-1G gate — advanced analytics`.

---

### Wave 2 — F4 Cost & freshness controls (no schema change)

**Goal:** the per-conversation ceiling and the daily sitemap scan exist **before**
V4 adds provider-cost features. Both opt-in, both fail safe. **Entry:** V4-1G.

- [ ] **V4-20 · Per-session message cap** — `M`, depends: V4-1G, migration: —
  - Files: `services/quota.py`, `api/routes.py`, `api/v1.py`,
    `tests/test_session_cap.py` (new).
  - Do: extend `quota.py` with `consume_session_message(website_id, session_id,
    *, limit)` — Redis `INCR` + TTL refresh on
    `quota:session:<website_id>:<session_id>`, `parse_limit` for the setting
    (garbage/negative → env default, `0` disables, the daily-cap precedent).
    Wire into `POST /api/chat`, `/api/chat/stream` and `/api/v1/chat` **after**
    the IP limiter and **before** `consume_message` (D6): a capped session gets
    the friendly refusal as a normal answer / SSE `chunk`+`done`, spends no
    daily budget, calls no LLM, and never resets the K4 session. Redis outage
    fails open with a logged error, exactly like the daily quota.
  - Done when: tests prove the ordering (capped refusal leaves the daily
    counter untouched), the TTL refresh, the `0`/garbage fallbacks, fail-open,
    and that two sessions of one website have independent counters; the
    limit-ordering test from V3-12 is extended, not duplicated.

- [ ] **V4-21 · Session cap in Settings + dashboard visibility** — `S`, depends: V4-20, migration: —
  - Files: `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Dashboard.tsx`,
    `README.md`.
  - Do: expose `session_message_limit` in Settings (internal key, admin-only
    write path already exists) next to `daily_message_limit`, with helper text
    ("0 = unlimited; counted per visitor session, idle-reset after 24 h").
    Dashboard keeps the daily quota bar unchanged; no per-session UI in V4.
  - Done when: saving the key round-trips through `PUT /api/settings`, the
    widget-config allowlist is still 14 keys, and the README settings table
    documents the key and its ordering.

- [ ] **V4-22 · Daily sitemap auto-scan** — `L`, depends: V4-21, migration: —
  - Files: `worker.py` (`sitemap_loop`, `handle_sitemap_scan`,
    `enqueue_due_sitemap_scans`), `services/crawler.py` (reuse only),
    `api/website.py` (reuse the sync helpers), `tests/test_sitemap_scan.py` (new).
  - Do: a new worker loop on `SITEMAP_SCAN_INTERVAL_SECONDS` queues
    `{"type": "sitemap_scan", "website_id": …}` for `active` websites with a
    sitemap URL whose company has `sitemap_scan_enabled=true` and whose last
    scan is older than the interval (track last-scan in Redis,
    `sitemap:scan:<website_id>` — best-effort; a lost key costs one extra scan,
    never a wrong deletion). The handler: fetch via
    `extract_urls_from_sitemap` (silent-skip path — on **any** fetch/parse
    failure or an empty URL set, change nothing and log); add new pages capped
    by `SITEMAP_SYNC_MAX_URLS`; only after a fully successful non-empty fetch,
    mark vanished pages inactive and delete their documents (the existing
    page-delete semantics, embeddings cascade); queue one ingest via
    `claim_ingest` **only if something changed** — a processing website is
    skipped. Register the job type in the worker dispatch and AGENTS.md.
  - Done when: tests prove — failed fetch changes zero rows; empty sitemap
    changes zero rows; a successful diff adds/removes exactly the delta; a
    second concurrent scan cannot double-queue ingest (claim 409 path); the
    flag off queues nothing; removals never run before a successful fetch.

- [ ] **V4-23 · Docs: caps and freshness** — `S`, depends: V4-22, migration: —
  - Files: `README.md` (Limit composition, env table, worker job types),
    `AGENTS.md`, `docs/security.md` (fail-open note).
  - Do: rewrite "Limit composition" to the three-guard order (IP limiter →
    session cap → daily quota) and document the scan's fail-safe rule and its
    Redis last-scan key as best-effort. State plainly that fail-open means an
    outage admits messages, as the daily cap already does.
  - Done when: no doc describes the daily cap as the only per-visitor ceiling,
    and the scan's "never wipe on a bad fetch" rule is written where an
    operator will read it.

#### Gate V4-2G

- [ ] Both suites + widget suite + build + lint + `trail build` pass; `alembic current` unchanged.
- [ ] Hand check on the dev API: set `session_message_limit=3`, send 4 messages
      in one session → 4th is the friendly refusal, daily counter unchanged;
      a second session still chats. Set `0` → unlimited again.
- [ ] Hand check: opt a test website in, point it at a local sitemap fixture,
      run one scan → new page added, removed page's document gone, one ingest
      queued; serve a 500 sitemap → zero changes (record both).
- [ ] All V4 flags off → chat, ingest and worker behaviour identical to `v3`
      (no scan jobs queued, no session counter written).
- [ ] commit `chore(v4): V4-2G gate — cost & freshness`.

---

### Wave 3 — F3 New training sources (no schema change)

**Goal:** YouTube, Notion and PPTX become knowledge through the **unchanged**
pipeline: every source normalizes into a local file under `uploads/`, then
`parse.py` → chunk 1000/200 → embed. **Entry:** V4-2G.

- [ ] **V4-30 · PPTX extraction** — `S`, depends: V4-2G, migration: —
  - Files: `services/parse.py`, `tests/test_parse.py` (extend).
  - Do: a `pptx` branch using `python-pptx` (branch-local import, D2): slide
    text from every shape with a text frame, plus speaker notes, joined per
    slide. Unsupported/empty decks raise the same clear errors as the PDF
    path. Add `pptx` to the upload accept list in the frontend only in V4-33.
  - Done when: a seeded two-slide deck with notes extracts both slides' text
    and notes; a missing `python-pptx` raises a clear error; the existing
    parse tests stay green.

- [ ] **V4-31 · YouTube provider** — `M`, depends: V4-30, migration: —
  - Files: `services/sources.py` (`YoutubeProvider`), `api/upload.py`
    (`POST /api/uploads/youtube`), `core/config.py` (reuse `YOUTUBE_MAX_VIDEOS`),
    `tests/test_sources_youtube.py` (new, stubbed).
  - Do: accept a video URL/ID, a playlist URL or a channel URL. Playlist/channel
    expansion is capped at `YOUTUBE_MAX_VIDEOS` (25) and reports
    `added/total/truncated` like the sitemap sync. Each video becomes one
    `AcquiredFile` — a `.md` with title, video URL and caption text
    (`youtube-transcript-api`, prefer manually-created captions, fall back to
    the first available language). No captions → a clear 400 naming the video,
    never a silent empty document. Synthesized files respect `MAX_UPLOAD_MB`.
    Register in `PROVIDERS`; the endpoint returns the exact
    `{file_id, filename, file_url, file_size, file_type, source, source_ref}`
    shape of the URL/Drive endpoints, so `file_ids` → `POST /api/extra_documents`
    → worker ingest is untouched. All HTTP in tests is stubbed.
  - Done when: stubbed tests cover single video, capped playlist, no-caption
    400, oversize refusal, and that the produced file flows through
    `extract_text_from_file` unchanged; a live import is attempted at the gate
    (blocked-item rule if the network/provider is unavailable).

- [ ] **V4-32 · Notion provider** — `M`, depends: V4-31, migration: —
  - Files: `services/sources.py` (`NotionProvider`), `api/upload.py`
    (`POST /api/uploads/notion`), `tests/test_sources_notion.py` (new, stubbed).
  - Do: accept a page or database URL/ID plus an **integration token passed per
    request** (the Google Drive `access_token` precedent — never stored, never
    logged, never echoed; reads mask it). Existing `httpx` against
    `api.notion.com` only — the token is sent to no other host, including
    redirects (the `UrlProvider.headers_for` rule). Page → recursive block
    fetch capped at `NOTION_MAX_BLOCKS` (1000), rendered to markdown (headings,
    lists, tables, code, quotes; unsupported blocks degrade to their plain
    text). Database → query capped at `NOTION_MAX_PAGES` (25), one file per
    page, same `truncated` reporting. Auth failure → clear 401/400 from the
    endpoint, not a stored half-file.
  - Done when: stubbed tests cover page render, block cap, database cap,
    token-never-logged (caplog assertion), redirect-host refusal, and the
    shared response shape; a live import is attempted at the gate or recorded
    blocked.

- [ ] **V4-33 · Frontend + docs: the new sources** — `S`, depends: V4-32, migration: —
  - Files: `frontend/src/pages/ExtraDocuments.tsx`, `frontend/src/types/api.ts`,
    `README.md`, `AGENTS.md`, `.env.example` (already written in V4-02 — verify).
  - Do: "From YouTube" and "From Notion" buttons beside the existing URL/Drive
    controls (Notion prompts for the integration token in a password field,
    held in component state only); imported files show `YouTube` / `Notion`
    badges in the same list and flow into the existing `file_ids` path. Accept
    `.pptx` in the upload control. README: the source table, the two new
    endpoints, the caps, and the token-handling rule.
  - Done when: build + lint pass; the three new source kinds appear in the
    list with badges after a stubbed/dev import; no token value persists in
    localStorage, the DB or a log line.

#### Gate V4-3G

- [ ] Both suites + widget suite + build + lint + `trail build` pass; `alembic current` unchanged.
- [ ] One end-to-end import per source (YouTube video, Notion page, `.pptx`)
      → ingest → a chat question answered **from that source** with a citation.
      Provider/network-bound steps follow the blocked-item rule.
- [ ] Negative: a video without captions → 400 and no attachment row; a wrong
      Notion token → 401/400 and no file left under `uploads/`; an oversize
      synthesized file → 413-equivalent refusal, nothing stored.
- [ ] `MAX_UPLOAD_MB`, `read_limited` and the credential-host rule are reused,
      not re-implemented (review checklist).
- [ ] commit `chore(v4): V4-3G gate — training sources`.

---

### Wave 4 — F2 Per-conversation AI insights, M10

**Goal:** opt-in sentiment/resolution/summary per conversation at bounded,
auditable provider cost — derived data that lives and dies with its
conversation. **Entry:** V4-3G.

- [ ] **V4-40 · M10: `conversation_insights`** — `S`, depends: V4-3G, migration: M10
  - Files: `models.py`, `alembic/versions/<rev>_v4_m10_conversation_insights.py`.
  - Do: one new table — uuid `id`, `conversation_id` FK **unique** `ON DELETE
    CASCADE`, `status` (`processing`/`completed`/`failed`, check constraint),
    `sentiment` (`positive`/`neutral`/`negative`/`frustrated`, nullable),
    `resolution` (`resolved`/`unresolved`/`escalated`/`unknown`, nullable),
    `summary` `String(280)` nullable, `model` `String(120)` (which pair
    produced it), `claimed_at`, BaseModel timestamps. Indexes:
    unique `conversation_id` (the claim lock) and `(status, claimed_at)` for
    stale recovery — both transactional, new empty table (invariant 11).
    Autogenerate drift removal per AGENTS.md. **Migration only — no service.**
  - Done when: `alembic upgrade head` from the §3 backup replays to a single
    head chained from `1c5516fa864d`; downgrade drops the table (documented
    data loss: derived classifications only); the drift lines are gone.

- [ ] **V4-41 · Insight service: claim, cap, classify** — `L`, depends: V4-40, migration: —
  - Files: `services/insights.py` (new), `tests/test_insights.py` (new).
  - Do: `claim(conversation_id)` inserts the `processing` row — a lost insert
    race rolls back and returns `None` (the `topics.claim_run` pattern); a
    stale `processing` claim (silent > 30 min) is taken over in place;
    `completed` rows are re-claimable only when the conversation has newer
    messages (D3). `run_for_company(db, company_id)`: select eligible
    conversations (flag on, ≥ 1 visitor message, settled per
    `INSIGHT_SETTLE_MINUTES`, no row or refresh-due), cap at
    `INSIGHT_MAX_CONVERSATIONS`; build each transcript from the last ≤ 20
    messages truncated to `INSIGHT_TRANSCRIPT_CHARS` total; classify in
    batches of ≤ `INSIGHT_BATCH_SIZE` with **one** temperature-0 `get_llm`
    call per batch, fixed prompt, transcripts quoted as untrusted data;
    validate the JSON, clamp enums, truncate `summary` ≤ 280; write
    `completed` + `model`. A provider/parse failure marks the batch's rows
    `failed` (retryable next tick) and never raises into the worker.
    **One run costs at most ⌈50/10⌉ = 5 LLM calls and zero embedding calls.**
  - Done when: stubbed-LLM tests prove the claim race (one winner), the caps
    (questions, chars, batch, calls), enum clamping, failure→`failed`→retry,
    refresh-on-new-message, and that no raw transcript text is persisted
    beyond the 280-char summary; tenant scoping is a query-level join.

- [ ] **V4-42 · Worker loop + scheduler** — `S`, depends: V4-41, migration: —
  - Files: `worker.py` (`insight_loop`, `handle_insights`,
    `enqueue_due_insights`), `tests/test_worker_insights.py` (new).
  - Do: `insight_loop` wakes every `INSIGHT_INTERVAL_SECONDS`, queues
    `{"type": "insights", "company_id": …}` for opted-in companies; the
    handler calls `run_for_company`. Register the job type in the dispatch and
    AGENTS.md. Flag off → nothing queued, no row written, no provider call.
  - Done when: tests prove the opt-in gate, the cadence, and that a failed run
    leaves previous classifications intact (the topics guarantee).

- [ ] **V4-43 · Read side: console badges + analytics outcomes** — `M`, depends: V4-42, migration: —
  - Files: `api/inbox.py`, `services/inbox.py` (read-only join),
    `schemas/`, `api/analytics.py`, `services/analytics.py`,
    `frontend/src/pages/Inbox.tsx`, `frontend/src/pages/Analytics.tsx`,
    `frontend/src/types/api.ts`.
  - Do: conversation list/detail gain nullable `sentiment`/`resolution`/
    `summary` (additive schema; absent when no row). The inbox queue shows
    small sentiment/resolution tags and the detail pane the summary.
    `/api/analytics/summary` gains an `outcomes` breakdown **only** for a
    company with the flag on (else the key is absent — V3 clients see the V3
    shape). The digest is not touched (invariant 15).
  - Done when: build + lint pass; a seeded insight renders in both pages; a
    flag-off company's summary is byte-identical to the V4-1G output; foreign
    conversation ids stay 404.

- [ ] **V4-44 · Privacy, erasure, retention — prove the cascade** — `S`, depends: V4-43, migration: —
  - Files: `tests/test_privacy_retention_endpoint.py` (extend),
    `tests/test_conversations.py` (extend), `docs/security.md`, `README.md`.
  - Do: no new delete path — the FK cascade is the mechanism (invariant 14).
    Add tests proving `erase_session`, `delete_conversation` and
    `purge_company` (conversation expiry on `last_message_at`) each leave
    **zero** orphan insight rows, and that the privacy export does not need a
    new section (insights are derived labels; document that decision).
    `docs/security.md` §4 gains the insight data-flow paragraph: what is
    sent to the provider (bounded transcript), what is stored (enums +
    ≤ 280-char summary), what cascades.
  - Done when: the three cascade tests pass against a real database at the
    gate, and the security doc states the provider exposure honestly.

- [ ] **V4-45 · Docs: insights** — `S`, depends: V4-44, migration: —
  - Files: `README.md` (settings table, env table, worker job types, a
    "Conversation insights (F2)" section), `AGENTS.md` (ownership + migration
    head), `plans/SPEC.md` (note the Scale-tier parity item).
  - Do: document the opt-in, the exact cost bound (≤ 5 LLM calls per company
    per run, zero embedding calls), the claim/refresh lifecycle, and the
    derived-data guarantees. Update the migration-head references.
  - Done when: no doc still says sentiment/resolution is unimplemented, and
    the cost bound in the docs matches the constants in code.

#### Gate V4-4G

- [ ] M10 replayed from an empty Postgres 16 + pgvector: `1c5516fa864d → M10`,
      single head, downgrade tested on the throwaway database.
- [ ] Both suites + widget suite + build + lint + `trail build` pass; counts recorded.
- [ ] Flag off: no insight rows, no provider call, digest byte-identical to `v3`,
      analytics summary byte-identical to V4-1G.
- [ ] Flag on with a stubbed provider: one run classifies a seeded settled
      conversation, a duplicate job cannot double-claim, a failed batch retries.
      Live-provider classification follows the blocked-item rule.
- [ ] Erasure/retention cascade checks run against the real database (zero
      orphan rows) — this one is **not** blockable by provider absence.
- [ ] commit `chore(v4): V4-4G gate — conversation insights`.

---

### Wave 5 — F5 Hosted chat page (no schema change)

**Goal:** every bot gets a first-party URL, with the same guards as the embed
and no change to the third-party origin posture. **Entry:** V4-4G.

- [ ] **V4-50 · `GET /chat/{website_id}` + widget page mode** — `M`, depends: V4-4G, migration: —
  - Files: `api/routes.py` (or a new `api/chat_page.py` wired in `main.py`),
    `src/site_gpt/app/scripts/widget.js`, `tests/test_chat_page.py` (new),
    `tests/*.mjs` (extend the bootstrap test).
  - Do: a public HTML route serving a minimal first-party page (no build step,
    the widget.js precedent) that loads `/widget.js` with
    `ChatWidgetConfig = { apiUrl: <same origin>, website_id, displayMode: 'page' }`.
    `ensure_website_active` runs first — a disabled/foreign id renders the
    widget's existing unavailable state (404 for unknown, the tenant rule).
    In `widget.js`, `displayMode: 'page'` renders the chat full-viewport with
    no launcher bubble and no close-to-bubble path; **every existing key,
    localStorage key and bubble behaviour is untouched when the key is absent**
    (the node bootstrap test pins this). The page sets a proper title/favicon
    from `widget-config` (`assistant_name`, logo) and a noindex meta tag.
  - Done when: the page renders and chats end-to-end on the dev API (or the
    blocked-item rule applies to the model turn); the node suite proves the
    bubble path is byte-identical without the new key; a disabled website
    shows the unavailable state, not an error bubble.

- [ ] **V4-51 · First-party origin rule in `embed_guard`** — `S`, depends: V4-50, migration: —
  - Files: `services/embed_guard.py`, `tests/test_embed_guard.py` (extend),
    `docs/security.md`, `README.md`.
  - Do: extend `ensure_embed_allowed` (never a copy) to accept an
    Origin/Referer whose scheme+host+port equals the API's own request origin
    (D8). Document it beside the loopback exception: first-party hosted page,
    not an origin-authentication guarantee; K18's no-Origin soft acceptance is
    unchanged and stays accepted. Negative tests: a third-party origin still
    403s; a lookalike host (`evil.example` vs `example`, port mismatch,
    scheme mismatch) still 403s; the embed-token rules (V3 F4) apply to the
    hosted page exactly as to an embed.
  - Done when: the guard's test matrix covers first-party accept + every
    lookalike refusal, and `docs/security.md` §5's K18 row is updated without
    claiming K18 is closed.

- [ ] **V4-52 · Release docs + hosted link in Settings** — `S`, depends: V4-51, migration: —
  - Files: `frontend/src/pages/Settings.tsx` (copy hosted link beside the
    embed snippet), `README.md` (V4 section, upgrade notes), `AGENTS.md`
    (layout/ownership, suite counts, migration head), `plans/PLAN_V4.md`
    (dashboard + DoD evidence).
  - Do: the Settings appearance tab shows the bot's hosted URL with a copy
    button. Write the V4 release section the way V3's was written: what is
    implemented, what is off by default, what the gate could not run. All
    doc updates land **in the gate commit, before the tag** (§8).
  - Done when: build + lint pass; every doc's V4 claims match the code; the
    plan dashboard reads 25/25 with evidence lines.

#### Gate V4-5G (release gate)

- [ ] Full §9 runbook on a throwaway database: fresh DB → `alembic upgrade head`
      (M10 included) → register → website + sitemap → ingest → chat (sync +
      SSE) → analytics trend/funnel/top-questions + CSV → session cap refusal
      → sitemap scan diff + failed-fetch no-op → one import per new source →
      insights run (stubbed or live) → hosted page chat → privacy export +
      erasure (zero orphan insight rows) → **all V4 flags off** → repeat the
      V3 smoke and the digest byte-comparison to prove no regression.
- [ ] Negative checks (§9) all executed or recorded blocked with the reason.
- [ ] Both suites + widget suite + build + lint + `trail build`; counts recorded
      from the run.
- [ ] Docs (README, AGENTS, security, api-v1, this plan) updated **in this
      commit**; `grep -c "^- \[ \] \*\*V4-"` = 0.
- [ ] Merge the verified commit to `master` (fast-forward), then cut annotated
      tag `v4` **once**, on exactly that commit, and push. The tag is immutable
      from this moment (PLAN_V3 §8 policy applies verbatim); anything committed
      afterwards stays untagged on `master`.
- [ ] commit `chore(v4): V4-5G gate — hosted page + release`, then tag.

---

## 6. Dependency graph & critical path

```mermaid
graph LR
  W0[Wave 0<br/>decisions, deps, env] --> G0{V4-0G}
  G0 --> W1[Wave 1<br/>F1 analytics] --> G1{V4-1G}
  G1 --> W2[Wave 2<br/>F4 caps + scan] --> G2{V4-2G}
  G2 --> W3[Wave 3<br/>F3 sources] --> G3{V4-3G}
  G3 --> M10[M10 conversation_insights<br/>V4-40] --> W4[Wave 4<br/>F2 insights] --> G4{V4-4G}
  G4 --> W5[Wave 5<br/>F5 hosted page] --> G5{V4-5G tag v4}
```

Critical path: **W0 → W1 → W2 → W3 → M10/W4 → W5**. The listed task dependencies
are serial; do not parallelize a wave against a gate it depends on. The two
provider-cost features (F2 insights, F3 imports) sit **after** the F4 spend
guards on purpose.

---

## 7. Migration ledger

Chain from the current head. **Do not** write a revision number by hand; let
autogenerate chain it, then confirm the parent is the head above.

| ID | Revision file | Contents | Task | Chains from |
|---|---|---|---|---|
| M10 | `<rev>_v4_m10_conversation_insights.py` | `conversation_insights`: unique `conversation_id` FK CASCADE (the claim lock **and** the erasure/retention mechanism), `status`/`sentiment`/`resolution` check constraints, `summary` ≤ 280, `model`, `claimed_at`; transactional indexes on the new empty table (unique `conversation_id`, `(status, claimed_at)`) | V4-40 | `1c5516fa864d` |

Rules that still apply:

- New empty V4 tables use transactional index/constraint creation (the M7/M8
  precedent). No V4 migration touches a busy table's indexes, so no
  `CONCURRENTLY` build is expected — justify one explicitly if that changes.
- Autogenerate will propose the known drift (naive `DateTime()` ALTERs on
  `api_keys.last_used_at`/`revoked_at`, `users.reset_token_expires_at`,
  `contacts.consent_at`, and the `chat_feedback.website_id` FK drop/create).
  Remove those lines; keep only the real change.
- The downgrade drops `conversation_insights` — derived classifications only,
  no conversation data. Prefer disabling `conversation_insights_enabled` and
  rolling back app code before a destructive schema downgrade.
- No migration touches `embeddings` or `EMBEDDING_DIMENSIONS`; **no re-ingest**.
  F1 needs no new index (`idx_chat_messages_website_id_created_at` exists);
  F4's scan reuses `website_pages`' existing indexes.

---

## 8. Commit & review strategy

- Subjects: `feat(v4): …`, `fix(v4): …`, `docs(v4): …`, `perf(v4): …`,
  `chore(v4): V4-NG gate — …`. One concern per commit, body explains the *why*
  and records the measurement or the test that proves it.
- Never bundle a migration with the feature that consumes it: M10 with V4-40,
  the insight service in V4-41, the worker loop in V4-42.
- Review focus per wave: W0 = the two-deps rule + no import-time side effects,
  W1 = digest byte-compat + CSV injection/PII boundary, W2 = guard ordering +
  never-wipe-on-bad-fetch, W3 = token never stored/logged + caps + shared
  response shape, W4 = claim race + cost caps + cascade proofs, W5 = lookalike
  origin refusals + bubble-path byte-compat.
- Before each gate: re-read §4. Then `trail build` and the doc updates, in the
  gate commit — never a follow-up "docs" commit after the tag.

### Release tags are immutable (carried from PLAN_V3 §8, verbatim policy)

- A release tag is created **once**, on the exact commit the gate verified, and
  is never moved, deleted or force-pushed. `v3` stays on `2e5ab73`; `v4` will
  stay on whatever commit V4-5G verifies.
- Everything committed after the tag — docs included — lands on `master`
  untagged. That is the expected state, not drift.
- Anything that must be inside the tagged release is committed **before** the
  tag is cut; the gate commit is where the plan, README and AGENTS updates
  belong. Tagging is the last step of a release.
- A mistake already inside a tagged release is fixed by cutting a new tag
  (`v4.0.1`), never by rewriting `v4`.

---

## 9. Verification runbook

Run after **every** task's Done-when check, and in full at each gate:

```bash
source .venv/bin/activate
uv run python -c "import site_gpt.app.main"
uv run python -c "import site_gpt.app.worker"
uv run alembic upgrade head && uv run alembic current   # single head
uv run python -m unittest discover -s tests -v          # counts re-recorded at every gate
node --test tests/*.mjs                                 # widget suite, extended in V4-50
uv run uvicorn site_gpt.app.main:app --reload           # :8000
uv run python -m site_gpt.app.worker                    # + sitemap_loop (W2), insight_loop (W4)
cd frontend && npm run build && npm run lint
trail build
curl -s http://localhost:8000/health
```

**End-to-end smoke (full, at V4-5G):** fresh DB → `alembic upgrade head` →
register a company → website + sitemap → ingest → chat (sync + SSE) →
analytics: trend/funnel/top questions render, CSV downloads with a neutralized
formula cell → set `session_message_limit=3`, fourth message refused without
spending the daily counter → opt into the sitemap scan, run one diff scan and
one failed-fetch scan (zero changes) → import one YouTube video, one Notion
page, one `.pptx`, ingest, and get a cited answer from each → opt into
insights, run one bounded job, see badges in `/inbox` and outcomes in
analytics → open `GET /chat/{website_id}`, chat full-page, verify a third-party
Origin still 403s → privacy export + transactional erasure of the session
(messages, inbox row, tokens **and insight row** gone) → turn **all** V4 flags
off and repeat the V3 smoke plus the digest byte-comparison to prove no
regression.

**Negative checks:** session cap `0`/garbage → env default, unlimited; capped
refusal never resets the K4 session and never increments the daily counter;
Redis down → session cap fails open, `/health` unchanged in shape; failed or
empty sitemap fetch → zero row changes; a processing website is never
double-queued by the scan; YouTube video without captions → 400, no attachment
row; wrong Notion token → 401/400, no file under `uploads/`, token absent from
logs; oversize synthesized import → refused, nothing stored; insight claim race
→ one winner; failed insight batch → `failed`, previous classifications intact;
flag-off company → no insight rows, no provider call, V3-shaped analytics;
hosted page: lookalike host/port/scheme Origin → 403, disabled website →
unavailable state, foreign website id → 404; CSV contains no session id or
contact column; `/api/widget-config` still publishes exactly 14 keys.

**Blocked-item rule:** if this environment has no reachable LLM/embedding
provider, no YouTube/Notion network access, no SMTP or no browser, tick the
gate but record the item as **blocked and unexecuted** with the reason, exactly
as `PLAN_V3.md` §9 does. Do not tick a check that was not run. The cascade and
byte-comparison checks are database-only and are **never** blockable by
provider absence.

---

## 10. Rollback plan

| Situation | Action |
|---|---|
| A task breaks import/build | Revert that commit; gates are separate so the wave survives. |
| A migration is wrong, not yet applied | Delete the untracked revision, `alembic downgrade -1`, regenerate. |
| A migration is applied and wrong | **Do not edit it.** Write the next revision; restore from the §3 backup only if data was lost. |
| Wave gate fails | Stop. Fix inside the same wave; the next wave assumes the contract. |
| Session cap misbehaves | Set `session_message_limit=0` (per company) or `SESSION_MESSAGE_LIMIT=0` — the cap disappears with no migration. Redis outage already fails open. |
| Sitemap scan deletes wrong pages | Set `sitemap_scan_enabled=false`; the loop stops queueing. Restore pages from the pre-scan backup only if a real fetch bug caused it — the fail-safe rule means a bad fetch alone cannot. |
| Insights burn credits or mislabel | Set `conversation_insights_enabled=false`; rows stay (derived, harmless) and cascade with their conversations. No refund path exists — the caps are the control. |
| A new source imports garbage | Delete the extra document (existing path removes text + embeddings + files); disable the button per company is not needed — imports are manual, per request. |
| Hosted page origin rule too broad | Revert V4-51's guard commit; the page then 403s its own chat calls (fail-closed for the feature), embeds unaffected. |
| V4 abandoned after deployment | Prefer flags off + redeploy the last supported app. Only downgrade after a verified backup and explicit data-loss review: M10 drops derived classifications only. Reverse migrations in order, then redeploy tag `v3`. |

---

## 11. Risk register

| Risk | Trigger | Mitigation | Owner task |
|---|---|---|---|
| Insights burn provider credits | A large company with many settled conversations | Off by default; ≤ 50 conversations, ≤ 4000 transcript chars, ≤ 10 per call, ≤ 5 LLM calls per company per run, zero embedding calls; settle delay avoids classifying mid-chat | V4-41, V4-42 |
| Insight labels are wrong/misleading | Weak model, short or spammy transcript | Enums clamped, summary truncated, `model` recorded for audit, labels advisory; refresh-on-new-message; failed batches never overwrite completed rows | V4-41 |
| `youtube-transcript-api` breaks (unofficial endpoint) | YouTube changes caption internals | Pinned version (D2); a clear 400 per video, never a silent empty document; the provider is one registry class — swap without touching the pipeline | V4-31 |
| Notion integration token leaks | Logged, stored, or sent to a redirect host | Per-request token only (Drive precedent), never stored/echoed, caplog test, token sent to `api.notion.com` only — the `UrlProvider` credential-host rule reused | V4-32 |
| CSV formula injection / PII creep | A visitor question starting with `=…`, or a later "just add the email column" | Cell neutralization + aggregate-only invariant (16) + a gate test asserting the header shape; PII stays in `/api/privacy/export` | V4-11 |
| Sitemap scan wipes knowledge on a bad fetch | Transient 500, empty body, partial sitemap | Removals only after a fully successful non-empty fetch; failed fetch changes zero rows; tests pin both; ingest only via `claim_ingest` | V4-22 |
| Session cap punishes a returning visitor | Counter TTL semantics misunderstood | Idle window (TTL refreshed per accepted message), documented in Settings helper text; `0` disables; fail-open on Redis outage | V4-20, V4-21 |
| Hosted-page origin exception widens K18 | Lookalike host/port/scheme accepted | Exact scheme+host+port equality with the request's own origin; lookalike negative tests; K18 stays accepted and documented — the exception is first-party convenience, not origin authentication | V4-51 |
| Widget bubble path regresses | `displayMode` changes shared render code | Node bootstrap test pins the no-key path byte-identical; new key optional with default | V4-50 |
| Digest drifts again | F1/F2 tempted to "improve" the email | Invariant 15 + byte-comparison at every gate from V4-1G on | V4-10, V4-43 |
| Docs drift (V1 K2 / V2.1 / V3 repeats) | Gate rushed | Docs + `trail build` inside the gate commit; §13 requires it; tag immutable | All gates |
| Scope creep into a helpdesk suite | "Just add WhatsApp/iOS/billing" | §2's deferred list is the boundary; anything beyond the five features is a new plan | — |

---

## 12. Progress dashboard

| Wave | Tasks | Done | Gate |
|---|---|---|---|
| 0 — Foundation | 4 | 0 / 4 | ☐ V4-0G |
| 1 — Advanced analytics (F1) | 4 | 0 / 4 | ☐ V4-1G |
| 2 — Cost & freshness (F4) | 4 | 0 / 4 | ☐ V4-2G |
| 3 — Training sources (F3) | 4 | 0 / 4 | ☐ V4-3G |
| 4 — Conversation insights (F2) | 6 | 0 / 6 | ☐ V4-4G |
| 5 — Hosted chat page (F5) | 3 | 0 / 3 | ☐ V4-5G |
| **Total** | **25 tasks + 6 gates** | **0 / 25** | **0 / 6 gates** |

---

## 13. Definition of done — V4

- [ ] All 25 tasks ticked and all 6 gates signed off (blocked items recorded,
      not hidden); D1–D9 resolved before their waves; `grep -c "^- \[ \] \*\*V4-"` = 0.
- [ ] F1–F5 implemented; M10 applied; single head chained from `1c5516fa864d`;
      insight claims idempotent and tenant-scoped; the claim race tested.
- [ ] Zero widget backward-compatibility breaks: a V3 snippet without
      `displayMode` renders the bubble byte-identically; `WIDGET_PUBLIC_KEYS`
      is still exactly 14; every `localStorage` key unchanged.
- [ ] Digest JSON + HTML byte-identical to tag `v3` for a fixed fixture, with
      all V4 flags off **and** with insight/cluster rows present.
- [ ] Zero `EMBEDDING_DIMENSIONS` change, zero re-ingest; exactly two new
      Python dependencies, zero new JS dependencies.
- [ ] Every feature off by default; with all V4 flags off, behaviour equals
      tag `v3` (chat, ingest, worker loops, analytics shape, digest).
- [ ] Privacy guarantees hold: erasure/retention leave zero orphan insight rows
      (database-proven at the gate); the analytics CSV contains no PII and
      neutralizes formula cells; Notion tokens never stored or logged.
- [ ] K18 remains an accepted residual; the hosted-page origin exception is
      documented as first-party convenience, with lookalike refusals tested.
- [ ] Both suites green (counts recorded from the run at the tag), frontend
      build + lint green, `trail build` run, docs consistent.
- [ ] Verified release commit merged to `master`; annotated tag `v4` cut once
      on exactly that commit and pushed; README describes V4 as the current
      version; the tag is never moved afterwards (§8).

---

## Appendix — task index

| Wave | IDs |
|---|---|
| 0 | V4-01, 02, 03, 04 → gate V4-0G |
| 1 | V4-10, 11, 12, 13 → gate V4-1G |
| 2 | V4-20, 21, 22, 23 → gate V4-2G |
| 3 | V4-30, 31, 32, 33 → gate V4-3G |
| 4 | V4-40, 41, 42, 43, 44, 45 → gate V4-4G |
| 5 | V4-50, 51, 52 → gate V4-5G (release, tag `v4`) |

Companion docs: `plans/PLAN_V3.md` (§4 invariants this plan carries, §8 the
release-tag policy), `plans/PLAN_V2.md` (V2/V2.1 baseline), `plans/SPEC.md`
(requirement/design text), `plans/PLAN_V1.md` (V1 baseline), `docs/security.md`
§4–§5 (data flows and accepted risks), `docs/api-v1.md` (the additive analytics
contract).
