# SPEC — SiteGPT feature parity upgrade

| | |
|---|---|
| Version | **V2** — the next version. The current code is **V1** (`plans/PLAN_V1.md`). |
| Status | Draft — awaiting review |
| Created | 2026-11-14 |
| Scope | `site-gpt` monorepo (FastAPI backend + React admin + embeddable `widget.js`) |
| Reference | <https://sitegpt.ai/features> (19 listed features) |
| Companion | `plans/PLAN_V2.md` (**execution plan** — 39 tasks, 5 waves, 5 gates), `plans/PLAN_V1.md` (V1 baseline + stabilization), `.workbuddy-ai/memory/2026-11-14.md` (gap analysis) |
| Supersedes | Nothing. Additive to V1; it does not rewrite V1. |
| V1 baseline | commit `e23faba` (the current `v1` tag; three commits past the original `f571f95` freeze), schema head `07f83918a289` |

---

## 1. Goal

Close the functional gap between this project and the SiteGPT features page while
preserving everything the project already does better (citations, streaming,
self-hosting, multi-provider LLM support). Bring the **9 non-parity features**
(3 missing, 6 partial) to parity or to an explicitly scoped equivalent, plus the
technical groundwork for the compliance claims.

**Explicit non-goals:** SOC 2 Type II certification, HIPAA/BAA, a signed GDPR DPA,
a 7-day trial, pricing tiers and personalized onboarding. Those are legal, audit
and commercial deliverables, not code. §7 records what *technical* groundwork is
in scope instead.

**Language note:** this spec follows the repo's existing English documentation
(`README.md`, `AGENTS.md`, `.trail/`). No runtime UI text is changed by this
document; F1 introduces localizable widget strings.

---

## 2. Baseline (verified against code, 2026-11-14)

Legend: ✅ full · ⚠️ partial · ❌ missing · ➖ N/A (not code)

| # | SiteGPT feature | Status | Evidence |
|---|---|---|---|
| 1 | Import training content | ✅ | sitemap + `trafilatura` crawl, `services/parse.py`, `services/sources.py` (URL / Google Drive), `ExtraDocument.content` raw text |
| 2 | Q&A training | ✅ | approved corrections rebuild one `__qa_training__` extra document (`services/qa_training.py`, `POST /api/feedback/rebuild`) and are retrieved like any other chunk |
| 3 | GPT-4.1-mini & GPT-4.1 | ✅ | env defaults plus a runtime pair from Settings → Model, resolved only through `services/llm.py::ALLOWED_CHAT_MODELS` (`services/model_settings.py`) |
| 4 | Embed on sites | ✅ | `GET /widget.js`, `window.ChatWidgetConfig`, per-site `/api/widget-config` |
| 5 | Customize appearance | ✅ | 14 public widget keys, including `widget_logo_url` (https/raster only) with the 🤖 fallback preserved |
| 6 | Quick prompts | ✅ | `suggested_questions` → `renderSuggestions()` (`widget.js:574`) |
| 7 | Chat history | ✅ | `services/conversations.py`, `/api/conversations`, widget `loadServerHistory()` |
| 8 | Escalate to a human | ✅ | notify-and-callback: `POST /api/handoff` + `/handoffs` queue + `handoff.requested` event |
| 9 | Language support (95+) | ✅ | `SYSTEM_PROMPT` answers in the question's language; widget ships English + Vietnamese labels with `widget_ui_strings` overrides for any other language |
| 10 | Lead generation | ✅ | `showContactForm` → `POST /api/contacts` → `contacts` table → `/contacts` page |
| 11 | Weekly email digest | ✅ | `services/digest.py` + `/api/digest/preview`/`send-now` + `/analytics`, at-most-once through a claim row in `digest_log` |
| 12 | API | ✅ | scoped `X-API-Key` keys (`/api/api-keys`) + versioned `/api/v1` + `docs/api-v1.md`, published in `/docs` with the `ApiKeyAuth` scheme |
| 13 | Integrations | ✅ | webhook (HMAC-signed), Slack, Zendesk and Crisp in `services/integrations.py`, configured at `/integrations` |
| 14 | SOC 2 Type II | ➖ | certification |
| 15 | GDPR compliant | ⚠️ | technical half only: export, erasure and recorded consent (F9). Certification and legal documents remain out of scope — `docs/security.md` says so explicitly |
| 16 | HIPAA compliant | ➖ | certification / BAA |
| 17 | Data encryption | ✅ | argon2, hashed API keys and reset tokens, signed webhooks, secret masking; TLS 1.2+ and at-rest encryption are documented deployment controls (`docs/security.md`) |
| 18 | Role-based access | ✅ | `get_admin_user` / `get_manager_user` (`core/auth.py:80-99`) across ~39 endpoints |
| 19 | Data processing agreement | ➖ | legal |

**Net target:** 15 full, 4 explicitly out-of-scope (14, 15*, 16, 19). `*` = technical
controls in scope, certification out.

---

## 3. Invariants (must not break)

These come from `AGENTS.md` and are hard constraints on every phase:

1. **Widget backward compatibility** — `ChatWidgetConfig` keys and `localStorage`
   keys (`chat_widget_session`, `chat_widget_history`, `chat_widget_contact`,
   `chat_widget_initialized`) stay valid. New keys are optional with defaults.
2. **RAG search lives only in `services/rag.py::search`** — extend that one SQL
   query; never duplicate the pgvector `<->` search.
3. **Chunking** stays `RecursiveCharacterTextSplitter(1000, 200)` via
   `services/ingest.py::split_text`.
4. **Embedding dimension** stays `EMBEDDING_DIMENSIONS` (default 1536). Nothing in
   this spec changes it, so **no re-ingest of existing vectors is required**.
5. **Reuse helpers** — `get_llm`, `get_embedding_model`, `embed_texts`,
   `enqueue_job`, `rate_limit`, `send_email`. No new SDK clients.
6. **Auth** stays JWT (`core/auth.py`, `python-jose`). API keys are an *additional*
   auth path, not a replacement. No new auth library.
7. **Frontend** stays React 18 + Vite + TS + Ant Design + axios. `frontend/package.json`
   has **no chart library** — F6 analytics uses `Statistic` / `Progress` / `Table`
   and CSS bars only.
8. **Deps** — `httpx` and `redis` are already installed and cover outbound
   integrations and job dispatch. No new Python dependency is required by this
   spec (see ADR-6 for the one optional exception).
9. **Migrations** — `uv run alembic revision --autogenerate`, review the diff,
   `uv run alembic upgrade head`. Never edit an applied migration. Keep a single
   head. `a1b2c3d4e5f6` is the **merge** migration; the current V1 head that
   M1 chains from is `07f83918a289` (`07f83918a289_contacts.py`).
10. **Docs sync** — any new env var goes into `core/config.py` **and** `.env.example`
    **and** the `README.md` env table. Any CORS change updates `README.md`.
11. **Run `trail build`** after each phase so the context graph matches the code.

---

## 4. Architecture decisions

### ADR-1 — Whitelist the public widget config before adding any secret-bearing setting

`GET /api/widget-config` (`api/routes.py:391-441`) is **public and
unauthenticated**. It used to return `{s.key: s.value}` for *every* row in
`settings`; it now filters on `WIDGET_PUBLIC_KEYS`, and the registry is split into
`DEFAULT_SETTINGS` (appearance) and `INTERNAL_SETTINGS` (server-side). This spec
adds **14** settings keys (7 public, 7 internal), some holding recipient
addresses and integration config. Returning all of them would leak data.

**Decision (implemented during V1 stabilization):** `WIDGET_PUBLIC_KEYS` in
`api/setting.py` is an explicit literal tuple, deliberately **not** derived from a
registry dict, so registering a settings row can never publish it. New internal
keys (`digest_*`, `handoff_email`, `llm_*`) live in `INTERNAL_SETTINGS` and are
never exposed. V2 only grows the tuple with the keys that features actually need.

### ADR-2 — Single source of truth for default settings

`api/setting.py` used to duplicate the default keys in `_default_setting_rows()`
and again inside `create_settings()`. With 14 new keys that guarantees drift.

**Decision (implemented during V1 stabilization):** one registry —
`DEFAULT_SETTINGS` (appearance/widget keys), `INTERNAL_SETTINGS` (server-side
keys) and `ALL_SETTINGS` as their union (`api/setting.py:16-68`).
`_default_setting_rows()` (`api/setting.py:70`) and `create_settings()`
(`api/setting.py:148`) both consume it; `PUT /api/settings` upserts missing keys
(`api/setting.py:117`), so existing companies pick up new defaults lazily without
a data migration. `WIDGET_PUBLIC_KEYS` stays a separate explicit literal.

### ADR-3 — Q&A training reuses `ExtraDocument`, not a third embedding FK

`embeddings` has `check_one_source_only` (`models.py:192-196`) requiring exactly
one of `document_id` / `extra_document_id`. A third FK means dropping/recreating
that CHECK constraint and touching `rag.py::search`'s UNION.

**Decision:** approved Q&A pairs are rendered as text
(`"Q: ...\nA: ...\n"`) into **one synthetic `ExtraDocument` per website** (named
`__qa_training__`) and re-ingested with the existing
`services/ingest.py::ingest_extra_document`. `rag.py::search` already includes
`extra_documents` scoped by website *or* company, so **no SQL and no embedding
schema change is needed**. A `qa_pairs` table is not needed either: `chat_feedback`
(with new review columns) is the source of truth and the document is regenerated
from its approved rows.

### ADR-4 — "Escalate to a human" = notify-and-callback, not a live agent inbox

**Decision:** F5 records a handoff request, emails the configured team address and
emits a `handoff.requested` integration event (F7 pushes it to Slack / Crisp /
Zendesk). The widget shows a confirmation state. There is **no real-time agent
console** in this spec — building one is a separate product. This matches
SiteGPT's button semantics when combined with its integrations, and is stated
honestly in the UI copy ("We'll get back to you by email").

### ADR-5 — Digest scheduling rides the existing worker + Redis queue

`worker.py::worker()` already starts `scheduler_loop()` via `asyncio.create_task`
(`worker.py:109`) and dispatches on `data["type"]` from `queue:jobs`.

**Decision:** add a `digest_loop()` task alongside it that enqueues
`{"type": "digest", "company_id": ..., "period_start": ..., "period_end": ...}`;
`worker()` gains an `elif` branch calling `handle_digest(data)`. No new scheduler,
no cron, no extra infrastructure. A `digest_log` table with
`UniqueConstraint(company_id, period_start)` on a row **claimed before** the send
(see `PLAN_V2.md` V2-28) makes sends idempotent across restarts and workers.

### ADR-6 — Secrets are hashed or deployment-encrypted, not app-encrypted

`pyproject.toml` has no reversible-encryption library.

**Decision:** API keys are stored only as a SHA-256 hash + short prefix (F8);
webhook signing uses a server-side env secret (`INTEGRATION_WEBHOOK_SECRET`).
Integration credentials in `integrations.config` are **masked in all API
responses** and encryption-at-rest is a documented deployment requirement (disk /
Postgres TDE) — see F10. If the team later wants app-level encryption, that is
one deliberate `cryptography` dependency and a separate migration; it is not
smuggled into this spec.

### ADR-7 — Answers are tagged `answered`, not parsed from text

Detecting "unanswered questions" by string-matching the assistant's fallback
phrase is fragile and multilingual-hostile.

**Decision:** add nullable `answered: Boolean` to `chat_messages`; `rag.py::ask`
and `ask_stream` set it on assistant messages from `bool(results)` (i.e. did
vector search return any chunk). Digest/analytics query the flag. Old rows stay
`NULL` and are excluded from unanswered counts.

---

## 5. Phase 0 — Foundation (blocking, do first)

### P0.1 Fix email delivery — **done in V1 (S1)**

This was a real bug: `services/mail.py` called `fm.send_message(message)`
**without awaiting it** (`FastMail.send_message` is `async def`), so the coroutine
was created and discarded and **no email was ever sent**.

- **Already implemented:** `async def send_email_async(...)` (`services/mail.py:65`)
  awaits `fm.send_message(...)` (`services/mail.py:83`).
- `send_email(...)` (`services/mail.py:86`) remains the sync wrapper for
  `api/user.py::forgot_password`: `asyncio.run(...)` when no loop is running,
  otherwise `create_task` with a strong reference. Never call `asyncio.run` inside
  a running loop.
- Remaining V2 work: new digest/handoff callers must `await send_email_async`.
- **Acceptance:** a password reset and a digest preview both produce a delivered
  message against a test SMTP server; no `RuntimeWarning: coroutine was never
  awaited`.

### P0.2 Public config allowlist — **done in V1 (S3), extended in V2**

- **Already implemented:** `api/routes.py::widget_config` filters on
  `WIDGET_PUBLIC_KEYS` (`api/setting.py`), an explicit literal tuple rather than a
  view of `DEFAULT_SETTINGS`.
- **Already implemented:** the 7 internal V2 keys are registered in
  `INTERNAL_SETTINGS` and seeded through `ALL_SETTINGS`.
- **Landed:** the tuple already holds all **14** entries — the 7 appearance keys
  published in V1 plus the 7 widget-facing keys from F1/F2/F5/F9
  (`widget_language`, `widget_ui_strings`, `widget_logo_url`, `handoff_enabled`,
  `handoff_label`, `require_consent`, `privacy_policy_url`). What remains is the
  widget code that reads them (§9 notes they are inert until then).
- **Acceptance:** `GET /api/widget-config?website_id=…` returns exactly the 14
  allowlisted keys and never `digest_*`, `handoff_email`, `llm_*` or any
  integration/API-key value.

### P0.3 Unify default settings — **done in V1 (S3)**

- **Already implemented** (`api/setting.py:16-68`): `DEFAULT_SETTINGS` (appearance)
  and `INTERNAL_SETTINGS` (server-side) with `ALL_SETTINGS` as the union;
  `_default_setting_rows()` (`api/setting.py:70`) and `create_settings()`
  (`api/setting.py:148`) both consume it, and `POST /api/settings` inserts only
  missing keys and returns `created` / `skipped`.
- `tests/test_settings.py` pins the registry split and the allowlist.

### P0.4 Config + env plumbing

Add to `core/config.py`, `.env.example` and the `README.md` env table (see §8).
All new flags default to **off**, so an upgraded install behaves identically
until an admin opts in.

### P0.5 Router registration template

New routers are registered in `main.py` with `/api/...` prefixes, matching
`app.include_router(setting_router, prefix="/api/settings")`. New routers in
this spec: `integration`, `handoff`, `digest`, `analytics`, `privacy`, `api_key`,
`v1`.

---

## 6. Feature specs

### F1 — Multilingual support (⚠️ → ✅)

**Target:** SiteGPT's "95+ languages". Honest parity: the bot detects and replies
in the visitor's language, and widget UI strings are localizable. We do **not**
claim to have verified 95 languages.

**Gap:** no i18n; `SYSTEM_PROMPT` (`rag.py:168-174`) is English-only; widget
strings are hardcoded (`widget.js:3-20` plus the literals inside
`showContactForm` (`widget.js:635`) and `renderSuggestions` (`widget.js:574`)).

**Design**
1. `rag.py::SYSTEM_PROMPT` gains: *"Detect the language of the user's question
   and always answer in that same language. If the context is in another
   language, translate the relevant information rather than answering in the
   context's language."* Applied to **both** `ask` (`rag.py:177`) and `ask_stream`
   (`rag.py:224`) so sync and SSE stay consistent.
2. `widget_language` setting (`auto` | ISO 639-1 code, default `auto`). `auto`
   resolves from `navigator.language` on the host page; explicit codes force a
   locale.
3. `widget_ui_strings` setting: JSON map overriding UI labels (greeting,
   placeholder, "Start chat", "Talk to a human", "Sources", "Send", error
   strings). Fallback to the current English literals — **no key removal**, so
   `ChatWidgetConfig` stays compatible.
4. `loadServerConfig()` (`widget.js:851`) maps the two new keys; a small
   `t(key)` helper replaces hardcoded strings in `showContactForm`,
   `renderSuggestions`, `addMessage` error paths and the new handoff button.
5. Admin: Appearance tab → language `Select` + a JSON/text editor for overrides.

**Files:** `services/rag.py`, `scripts/widget.js`, `api/setting.py`,
`api/routes.py`, `pages/Settings.tsx`, `components/WidgetPreview.tsx`,
`types/api.ts`.

**Acceptance:** a question in Vietnamese/Spanish/French produces an answer in
that language from an English knowledge base; widget with `widget_language=vi`
renders Vietnamese UI strings; `auto` follows `navigator.language`; existing
embeds with no new keys behave exactly as before.

---

### F2 — Custom logo & branding (⚠️ → ✅)

**Target:** "custom logos and colors".

**Gap:** colors/name/position/greeting/placeholder exist; avatar is hardcoded
`role === 'user' ? '👤' : '🤖'` (`addMessage`, `widget.js:452`) and the header is
text-only.

**Design**
- `widget_logo_url` setting (https URL, validated). `widget.js` renders an `<img>`
  in the chat header and uses the same URL for bot-message avatars, falling back
  to 🤖 when absent/invalid (onerror handler). Sanitize: only `https:` / `data:image/`
  schemes, set `referrerpolicy="no-referrer"`, no inline SVG from user input.
- `WidgetPreview` gets `logoUrl?` prop so Settings shows the real branding.
- `APPEARANCE_KEYS` in `Settings.tsx` gains the key; `fetchAppearance` /
  `handleAppearanceSubmit` pass it through automatically once added.
- `WIDGET_PUBLIC_KEYS` gains `widget_logo_url`.

**Acceptance:** setting a logo changes header + bot avatars in the live widget and
in the preview; clearing it restores 🤖; an invalid URL never breaks the widget.

---

### F3 — Runtime model switching (⚠️ → ✅)

**Target:** "choose between two models and switch anytime".

**Gap:** `services/llm.py::get_llm()` (L70-104) takes **no arguments** and reads
module-level `LLM_AI` / `LLM_MODEL`; switching requires editing `.env` + restart.

**Design**
- `get_llm(provider: str | None = None, model: str | None = None,
  temperature: float = 0.5)` — `None` falls back to the current env globals, so
  every existing caller is unchanged.
- Two per-company settings: `llm_provider` and `llm_model`, both optional. A
  narrow `ALLOWED_CHAT_MODELS` catalogue in `services/llm.py` maps a short label
  (e.g. `fast`, `accurate`) to `(provider, model)` — admins pick a label, not an
  arbitrary user-supplied model name. Unknown/empty value → env default.
- `rag.py::ask` / `ask_stream` resolve the company from `website_id` (the
  `Website` row is already loaded in `search()`; cache it) and pass the override
  into `get_llm`. Add a small `services/model_settings.py` helper so this lookup
  is not duplicated.
- Admin: new **Model** tab in Settings with a `Select` and a note about API key
  requirements per provider.
- `llm_*` keys are **not** in `WIDGET_PUBLIC_KEYS`.

**Risk:** switching provider without its API key configured must fail gracefully
at the chat boundary with the existing SSE `{"error": ...}` event, not a 500
traceback. Embedding provider (`EMBEDDING_AI`) is intentionally **not** switched
here — changing it still requires a migration + re-ingest (§3.4).

**Acceptance:** admin switches from `accurate` to `fast`, the next chat uses the
new model without a restart; unsetting returns to env config; a provider with no
credentials yields a friendly chat error.

---

### F4 — Q&A training from chat history (⚠️ → ✅)

**Target:** "use real chat history to refine and improve the chatbot".

**Gap:** `ChatFeedback` (`models.py:224-234`), `POST /api/chat/feedback`
(`routes.py:219-252`) and 👍/👎 buttons exist, but feedback has no effect on
answers and no admin surface.

**Design**
1. **Link a rating to the exact answer.** `save_message` (`rag.py:142`) is
   changed to return the persisted `ChatMessage`. `ChatResponse` and the SSE
   `done` event gain `message_id`; `attachExtras` (`widget.js:482`) and
   `Chat.tsx` keep that id per assistant bubble and send it in
   `FeedbackRequest.message_id` (new optional `UUID` field). The server resolves
   the question from the preceding user message in the same session — **never
   trust question/answer text from the client**.
2. `chat_feedback` gains `message_id` (UUID, nullable), `status`
   (`pending` | `approved` | `rejected`, default `pending`), `reviewed_answer`
   (Text, nullable). Migration backfills `status='pending'`; old rows have no
   `message_id` and are reviewable but not auto-trainable.
3. Admin **Training** page (`/training`): table of 👎 items with the question,
   the original answer, a corrected-answer textarea, Approve / Reject. Approve
   writes `reviewed_answer` + `status='approved'`.
4. A `services/qa_training.py::rebuild_qa_document(db, website_id)` renders all
   approved rows into `"Q: …\nA: …\n\n"`, upserts the single
   `ExtraDocument(name="__qa_training__", website_id=…, company_id=…)` and calls
   `ingest_extra_document(...)` (ADR-3). Called on approve/reject and on the
   admin's "Rebuild" button, never inside the chat request path.
5. `👍` ratings are stored but do not enter the corpus (positive signal only).

**Files:** `models.py`, `schemas/chat.py`, `schemas/feedback.py` (new),
`api/routes.py`, `api/feedback.py` (new admin router), `services/qa_training.py`
(new), `services/rag.py`, `scripts/widget.js`, `pages/Training.tsx` (new),
`components/Chat.tsx`, `App.tsx`, `utils/api.ts`, `types/api.ts`, one migration.

**Acceptance:** 👎 → approve with a corrected answer → asking the same question
again returns the corrected answer with the Q&A document listed in Sources;
rejecting removes that pair on the next rebuild; no extra vector table or
dimension change; existing 👍/👎 calls without `message_id` still return 200.

---

### F5 — Escalate to a human (❌ → ✅)

**Target:** "transition the conversation to a live agent at the push of a button".
Scope per ADR-4: notify-and-callback, with integration delivery from F7.

**Gap:** no handoff code anywhere.

**Design**
- New `HandoffRequest` model: `website_id` (FK cascade), `session_id`,
  `contact_id` (nullable FK to `contacts`), `message` (Text, optional visitor
  note), `status` (`pending` | `accepted` | `closed`, default `pending`),
  `channel` (String, e.g. `email` / `slack`), plus BaseModel timestamps.
  Index on `website_id`, `status`.
- `POST /api/handoff` — **public, rate-limited** (`rate_limit("chat", 10, 60)`),
  body `{website_id, session_id, message?}`. Resolves the `Contact` by
  `(website_id, session_id)` for the visitor's name/email, creates the request,
  emits `handoff.requested` (F7) and emails `handoff_email` (fallback: all active
  admin/manager emails of the company). Email body includes the last 10 messages
  of the session via `get_chat_history`.
- `GET /api/handoffs` (manager) — paginated list; `PATCH /api/handoffs/{id}`
  (manager) — status change. Responses in `schemas/handoff.py`.
- Widget: a "Talk to a human" button in the chat header, shown only when
  `handoff_enabled` is on. On click → POST → replace the composer with an
  acknowledgement using the F1 `t()` helper. No new `localStorage` keys.
- Admin: `/handoffs` page mirroring `pages/Contacts.tsx`.
- Settings: `handoff_enabled` (`false`), `handoff_email` (internal, **not**
  widget-public), `handoff_label` (widget-public, localizable).

**Files:** `models.py`, `schemas/handoff.py` (new), `api/handoff.py` (new),
`main.py`, `scripts/widget.js`, `pages/Handoffs.tsx` (new), `App.tsx`,
`utils/api.ts`, `types/api.ts`, `api/setting.py`, one migration.

**Acceptance:** with the feature off, no button renders and the endpoint returns
404/409; with it on, a click creates one row, sends one email and one
`handoff.requested` event; repeated clicks in one session upsert rather than
spam; an integration failure never fails the visitor's request.

---

### F6 — Weekly email digest + analytics (❌ → ✅)

**Target:** "weekly analytics digest: conversation volume, top topics, and the
questions your content could not answer yet".

**Gap:** `mail.py` is used only by `forgot_password`; `DashboardStats`
(`schemas/app.py:21-29`) is just 6 counts.

**Design**
1. `ChatMessage.answered` nullable Boolean (ADR-7), set in `rag.py::ask` /
   `ask_stream` on assistant rows from `bool(results)`.
2. `services/digest.py::build_digest(db, company_id, start, end) -> dict`:
   - `conversation_volume` (distinct `session_id`), `message_count`,
     `new_contacts`, `feedback_up` / `feedback_down` from `chat_feedback`;
   - `top_topics` — `collections.Counter` over user messages with a small
     stopword list, top 10 (stdlib only, deterministic, no LLM call);
   - `unanswered_questions` — user messages whose paired assistant message has
     `answered = False`, top 10 with `website_name` and `session_id` deep-links
     (`FRONTEND_URL` + `?website=<id>&focus=<session>`).
   - All queries join `Website` and filter `Website.company_id == company_id`.
     Reuse `services/conversations.py` patterns; do not duplicate aggregation
     helpers unnecessarily.
3. `services/digest.py::render_digest_html(data) -> str` — plain f-string HTML
   (no templating dependency). Previewable.
4. Scheduling (ADR-5): `worker.py` gains `digest_loop()` started alongside
   `scheduler_loop()` in `worker()`; it wakes every `DIGEST_CHECK_SECONDS`, and
   for companies with `digest_enabled=true` whose `digest_hour` matches (UTC),
   enqueues `{"type": "digest", ...}` if `digest_log` has no row for that
   `period_start`. `handle_digest(data)` builds, renders, sends via
   `send_email_async` to `digest_recipients` (fallback: active admins/managers)
   and inserts the `digest_log` row **after** a successful send.
5. `DigestLog` model: `company_id` (FK cascade), `period_start`, `period_end`,
   `sent_at`, `recipient_count`, `UniqueConstraint(company_id, period_start)`.
6. Admin `/analytics` page (Ant Design `Statistic`, `Progress`, `Table` — no new
   chart lib) reading `GET /api/analytics/summary?days=7`, plus
   `POST /api/digest/preview` (returns HTML, sends nothing) and
   `POST /api/digest/send-now` (admin, same idempotency guard).
7. Settings: `digest_enabled` (`false`), `digest_hour` (`9`),
   `digest_day` (`monday`), `digest_recipients` (comma-separated, internal).

**Files:** `models.py`, `services/digest.py` (new), `services/rag.py`,
`worker.py`, `api/digest.py` (new), `api/analytics.py` (new), `schemas/digest.py`
(new), `main.py`, `pages/Analytics.tsx` (new), `App.tsx`, `components/Layout.tsx`
(nav entry), `utils/api.ts`, `types/api.ts`, one migration (shared with F5).

**Acceptance:** preview renders counts/topics/unanswered for a seeded week;
`send-now` delivers exactly once and a second call is a no-op for the same
period; restarting the worker does not resend; with `DIGEST_ENABLED=false` no
loop runs; a company with no activity gets no email.

---

### F7 — Integrations & outbound webhooks (❌ → ✅)

**Target:** "native integrations into platforms like Crisp, Slack and Zendesk".

**Gap:** none exist.

**Design**
- `Integration` model: `company_id` (FK cascade), `type`
  (`webhook` | `slack` | `zendesk` | `crisp`), `name`, `config` (Text, JSON),
  `events` (Text, JSON array), `enabled` (Boolean, default true), timestamps.
  Index on `(company_id, enabled)`.
- `services/integrations.py` mirrors the existing provider-registry pattern in
  `services/sources.py`: one class per provider, `PROVIDERS` dict, and
  `emit_event(db, company_id, event_type, payload)`. All outbound HTTP uses the
  already-installed `httpx` with a 5s timeout; **every failure is caught and
  logged, never propagated to the request path**.
- `WebhookProvider`: POST JSON with `X-SiteGPT-Signature: sha256=<hmac>` using
  `INTEGRATION_WEBHOOK_SECRET`, plus `X-SiteGPT-Event` and a UTC timestamp header
  (replay-window check optional v2).
- `SlackProvider` (Incoming Webhook), `ZendeskProvider` (create ticket),
  `CrispProvider` (send message) — minimal REST calls, no third-party SDKs.
- Events: `lead.captured` (hook `routes.py::upsert_contact`),
  `feedback.received` (`chat_feedback`), `handoff.requested` (F5),
  `digest.generated` (F6).
- `GET/POST/PATCH/DELETE /api/integrations` (admin only) in `api/integration.py`.
  `config` secrets are **masked** (`"***"`) on every read; a PATCH without the
  secret field preserves the stored value. Add a `POST /api/integrations/{id}/test`
  that emits a synthetic `ping` event.
- Admin: **Integrations** tab in Settings (or `/integrations` page).

**Files:** `models.py`, `services/integrations.py` (new), `api/integration.py`
(new), `schemas/integration.py` (new), `api/routes.py` (2 hooks), F5/F6 hooks,
`main.py`, `pages/Integrations.tsx` (new), `App.tsx`, one migration.

**Acceptance:** configuring a webhook and capturing a lead delivers a signed
event; a dead endpoint logs an error and the lead is still saved; GET never
returns a stored token; disabling an integration stops delivery.

---

### F8 — Public API with keys + versioned docs (⚠️ → ✅)

**Target:** "connect to any other app, automatically retrain with new content,
and update settings programmatically"; SiteGPT documents a v2 API reference.

**Gap:** FastAPI auto-OpenAPI exists but auth is JWT-only (session-oriented),
there are no customer-scoped API keys, no `/v1` surface and no published docs.

**Design**
- `ApiKey` model: `company_id` (FK cascade), `name`, `key_prefix` (String 12,
  indexed), `key_hash` (SHA-256 of peppered key, String 255), `scopes`
  (Text JSON), `last_used_at`, `revoked_at`, timestamps. The raw key is returned
  **once** on creation and never stored.
- `core/auth.py::get_api_key_user` reads `X-API-Key`, hashes with
  `API_KEY_PEPPER`, compares with `hmac.compare_digest`, rejects revoked keys,
  resolves the owning company, updates `last_used_at`. JWT dependencies remain
  untouched.
- `api/v1.py` — versioned router `prefix="/api/v1"`, `tags=["v1"]`, reusing
  **existing service functions** (no duplicated RAG/ingest logic):
  `POST /ingest`, `GET|PUT /settings`, `GET /conversations`, `GET /contacts`,
  `POST /chat`, `GET /analytics/summary`. Scope-check per endpoint
  (`ingest:write`, `settings:write`, `chat:write`, `read`).
- `main.py`: explicit `docs_url` / `redoc_url`, `openapi_tags` with a v1
  description, and a documented `ApiKeyAuth` security scheme. Publish
  `docs/api-v1.md` describing auth, scopes, rate limits and examples.
- Admin: **API keys** tab in Settings — create (show-once modal), list (prefix,
  scopes, last used), revoke.
- **Security follow-up (documented, not silently changed):** `/api/chat`,
  `/api/contacts`, `/api/conversations/{session_id}` and
  `/api/widget-config` are public by design for the widget. `/api/conversations/
  {session_id}` returning full history for any guessed `session_id` is a privacy
  risk; recommend a signed session token in a later, explicitly breaking change.

**Files:** `models.py`, `core/auth.py`, `api/v1.py` (new), `api/api_key.py` (new),
`schemas/api_key.py` (new), `main.py`, `pages/Settings.tsx`, `utils/api.ts`,
`docs/api-v1.md` (new), one migration.

**Acceptance:** a created key can retrain a website and read conversations; a
revoked/unknown key returns 401; a scoped key cannot call out-of-scope endpoints;
`/docs` shows the v1 group and the `X-API-Key` scheme; all existing JWT admin
routes still pass.

---

### F9 — Privacy & data controls (technical GDPR groundwork)

**Target:** make the technical half of "GDPR compliant" real without claiming
certification.

**Design**
- `GET /api/privacy/export?website_id=` (admin) → JSON of `chat_messages`,
  `contacts`, `chat_feedback`, `handoff_requests` for that website, strictly
  company-scoped.
- `DELETE /api/privacy/conversations/{session_id}` → reuses
  `services/conversations.py::delete_conversation` and cascades the contact and
  handoff rows; `DELETE /api/privacy/contacts/{session_id}`.
- `contacts.consent_at` (nullable datetime) + settings `require_consent`
  (`false`) and `privacy_policy_url`. When on, `showContactForm`
  (`widget.js:635`) renders a required checkbox with a link; the POST body
  gains `consent: bool`, rejected with 400 when required but false.
- Document a data-retention setting `retention_days` and a `purge` worker job as
  a **v2** item (not built here).

**Acceptance:** export contains no rows from another company; deletion removes the
session everywhere; with consent required, the form cannot be submitted without
the checkbox; with it off, the form is unchanged.

---

### F10 — Encryption & transport hardening (⚠️ → ✅, scoped)

**Target:** "encrypted in transit with TLS 1.2+ and at rest" — achievable in code
only partially; the rest is deployment.

**Design**
- Code: API keys hashed (F8), webhook signatures (F7), `argon2` password hashes
  (existing), secrets absent from logs and from public config (ADR-1),
  `hmac.compare_digest` for comparisons.
- Docs (`README.md` + `docs/security.md`): enforce TLS 1.2+ at the reverse
  proxy, set an explicit `CORS_ORIGINS` list (default `*` is dev-only), rotate
  `JWT_SECRET_KEY`, enable Postgres/disk encryption at rest, back up `uploads/`,
  set `INTEGRATION_WEBHOOK_SECRET` and `API_KEY_PEPPER`.
- **Explicitly out of scope:** SOC 2 Type II examination, HIPAA BAA, a signed
  DPA, independent audits. The spec must not let the marketing page's wording
  imply these exist.

**Acceptance:** `GET /api/widget-config` leaks no secret; no raw API key or
integration token appears in DB columns or application logs; security doc lists
every deployment control the code cannot enforce.

---

## 7. Consolidated data model changes

| Table | Change | Migration |
|---|---|---|
| `chat_messages` | `+ answered` (Boolean, nullable) | M1 |
| `handoff_requests` | **new** — website_id, session_id, contact_id?, message?, status, channel | M1 |
| `digest_log` | **new** — company_id, period_start, period_end, sent_at, recipient_count, UQ(company_id, period_start) | M1 |
| `chat_feedback` | `+ message_id` (UUID?), `+ status` (String 20, default `pending`), `+ reviewed_answer` (Text?) | M2 |
| `integrations` | **new** — company_id, type, name, config(Text JSON), events(Text JSON), enabled(Boolean) | M3 |
| `api_keys` | **new** — company_id, name, key_prefix, key_hash, scopes(Text JSON), last_used_at?, revoked_at? | M4 |
| `contacts` | `+ consent_at` (datetime?) | M5 |
| `settings` | **no schema change** — new keys are rows | none |
| `extra_documents` | **no schema change** — one `__qa_training__` row per website | none |
| `embeddings` | **no change** (ADR-3) | none |

All new FKs use `ForeignKey(..., ondelete="CASCADE")` + `relationship(...,
cascade="all, delete-orphan", passive_deletes=True)` following `models.py`.
All new tables inherit `BaseModel` (uuid `id`, `created_at`, `updated_at`).
`Company` / `Website` gain matching relationships where child rows are listed.

**Migration order:** M1 (F5+F6+F7 signal) → M2 (F4) → M3 (F7) → M4 (F8) →
M5 (F9). `api_keys` (M4) landed **early**, as `c41d7e8a9f20` from the frozen V1
head `07f83918a289`, because `/api/v1` needs a key store before it can
authenticate; the remaining migrations chain in order from the then-current head.
Each generated with `uv run alembic revision --autogenerate`, diff reviewed, then
`uv run alembic upgrade head`. Never edit an applied migration; keep one head.
**No change to `EMBEDDING_DIMENSIONS`, therefore no re-ingest.**

---

## 8. New environment variables

Add to `core/config.py`, `.env.example` and the `README.md` env table.

| Key | Default | Purpose |
|---|---|---|
| `DIGEST_ENABLED` | `false` | Global kill switch for the digest loop |
| `DIGEST_CHECK_SECONDS` | `3600` | Digest loop wake interval |
| `DIGEST_HOUR` | `9` | Default UTC hour when a company has no `digest_hour` setting |
| `INTEGRATION_WEBHOOK_SECRET` | — | HMAC secret for outbound webhook signatures (required if webhooks enabled) |
| `API_KEY_PEPPER` | — | Pepper for API key hashing (required if API keys enabled) |
| `DEFAULT_WIDGET_LANGUAGE` | `auto` | Fallback when `widget_language` is unset |

Follow the existing pattern: env-only, no secret defaults, booleans parsed with
`.lower() in ("1", "true", "yes", "on")`.

---

## 9. New settings keys

**14 new settings keys** in total: 7 widget-facing (✅) and 7 server-side (❌).
Split by visibility (ADR-2): the ✅ rows go into `DEFAULT_SETTINGS`, the ❌ rows
into `INTERNAL_SETTINGS` — never into the public allowlist. Both are seeded
through `ALL_SETTINGS`, and `PUT /api/settings` upserts, so existing companies
get them lazily.

| Key | Default | Public to widget? | Feature |
|---|---|---|---|
| `widget_language` | `auto` | ✅ | F1 |
| `widget_ui_strings` | `""` | ✅ | F1 |
| `widget_logo_url` | `""` | ✅ | F2 |
| `llm_provider` | `""` | ❌ | F3 |
| `llm_model` | `""` | ❌ | F3 |
| `handoff_enabled` | `false` | ✅ | F5 |
| `handoff_label` | `Talk to a human` | ✅ | F5 |
| `handoff_email` | `""` | ❌ | F5 |
| `digest_enabled` | `false` | ❌ | F6 |
| `digest_hour` | `9` | ❌ | F6 |
| `digest_day` | `monday` | ❌ | F6 |
| `digest_recipients` | `""` | ❌ | F6 |
| `require_consent` | `false` | ✅ | F9 |
| `privacy_policy_url` | `""` | ✅ | F9 |

**Public allowlist: 7 keys in V1, 14 only once the widget keys land.** The V1
baseline (`v1` = `e23faba`) publishes **7** keys — the seven appearance rows and
nothing else. The 7 ✅ rows above join `WIDGET_PUBLIC_KEYS` with the features that
read them: `widget_language` and `widget_ui_strings` with F1 (V2-11/V2-12),
`widget_logo_url` with F2 (V2-13), `handoff_enabled` and `handoff_label` with F5
(V2-25/V2-26), and `require_consent` and `privacy_policy_url` with F9 (V2-42) —
**14 public keys** in total at the end. Everything ❌ stays server-side, so
`ALL_SETTINGS` finishes at **22 keys** (14 public + 8 internal, the eighth being
the existing `daily_message_limit`).

Read "14 public keys" as the target contract, not as evidence that the framework
is already serving a working multilingual/branded/handoff/consent widget. V2-04
has already landed the registry split and the 14-entry literal in
`api/setting.py`, so the code serves all 14 keys with their defaults; the seven
extra keys are **inert** until their feature ships — the V1 widget ignores
unknown keys and a V1 embed behaves exactly as before. The gate for each wave is
the widget (or the handoff/consent path) actually reading the key, not the key
existing in the tuple.

---

## 10. New API surface

| Method | Path | Auth | Feature |
|---|---|---|---|
| POST | `/api/handoff` | public + rate limit | F5 |
| GET / PATCH | `/api/handoffs`, `/api/handoffs/{id}` | manager | F5 |
| GET | `/api/analytics/summary?days=7` | manager | F6 |
| POST | `/api/digest/preview` | admin | F6 |
| POST | `/api/digest/send-now` | admin | F6 |
| GET / POST / PATCH / DELETE | `/api/integrations` | admin | F7 |
| POST | `/api/integrations/{id}/test` | admin | F7 |
| GET / POST / DELETE | `/api/api-keys` | admin | F8 |
| POST | `/api/v1/ingest`, `/chat` | `X-API-Key` | F8 |
| GET / PUT | `/api/v1/settings`, `/conversations`, `/contacts`, `/analytics/summary` | `X-API-Key` | F8 |
| GET | `/api/privacy/export` | admin | F9 |
| DELETE | `/api/privacy/conversations/{sid}`, `/contacts/{sid}` | admin | F9 |
| GET | `/api/feedback` (admin review list) | manager | F4 |
| PATCH | `/api/feedback/{id}` (approve/reject) | manager | F4 |
| POST | `/api/feedback/rebuild?website_id=` | manager | F4 |

All new responses live in matching `schemas/` modules. Paginated lists use
`PaginatedResponse`. Public endpoints use `Depends(rate_limit(...))`.

---

## 11. Frontend / widget change matrix

| File | Change |
|---|---|
| `src/site_gpt/app/main.py` | register 7 new routers, OpenAPI tags/security scheme |
| `src/site_gpt/app/scripts/widget.js` | `t()` i18n helper, logo rendering, handoff button, consent checkbox, `message_id` on feedback, new config keys — all optional/backward-compatible |
| `frontend/src/App.tsx` | routes `/training`, `/handoffs`, `/analytics`, `/integrations` |
| `frontend/src/components/Layout.tsx` | nav entries for new pages |
| `frontend/src/pages/Settings.tsx` | Model / API keys / Language / Branding / Integrations tabs; `APPEARANCE_KEYS` extended |
| `frontend/src/components/WidgetPreview.tsx` | `logoUrl`, `language`, handoff button in preview |
| `frontend/src/components/Chat.tsx` | carry `message_id` per assistant bubble for feedback |
| `frontend/src/utils/api.ts` / `types/api.ts` | typed helpers + interfaces for every new endpoint |
| `frontend/src/pages/{Training,Handoffs,Analytics,Integrations}.tsx` | new Ant Design pages, no new UI framework |

New pages must be wrapped in `ProtectedRoute` like the existing ones.

---

## 12. Migration & rollout

1. **Phase 0** (P0.1–P0.5) — no schema change. P0.1 (email), P0.2 (public
   allowlist) and P0.3 (unified defaults) landed as V1 stabilization S1/S3 and are
   **already in the code**: the internal V2 keys are registered in
   `INTERNAL_SETTINGS`, and `WIDGET_PUBLIC_KEYS` is an explicit 14-entry literal
   (7 appearance + 7 widget keys, the latter inert until their feature ships).
   What remains is P0.4 (config/env), P0.5 (routers) and the F1/F2/F5/F9 widget
   code that consumes the new keys.
2. **Phase 1** — F1, F2, F3 (settings-only, no migration). Lowest risk, highest
   visible value.
3. **Phase 2** — F4 + F5 + F6 with migrations M1, M2. These share the feedback
   and conversation plumbing; build together.
4. **Phase 3** — F7 + F8 with M3, M4 (integrations and API keys both introduce
   secrets; do them after ADR-1 is in place).
5. **Phase 4** — F9 + F10 with M5 and the security documentation.
6. After each phase: `trail build`, then update `README.md` (features, env vars,
   endpoint list) and `AGENTS.md` if ownership/conventions changed.

**Rollout safety:** every feature is off by default via a `Setting` row or an env
flag. An upgraded deployment with an untouched `.env` and no new settings behaves
like today, with one exception: F1's language rule changes `SYSTEM_PROMPT`
unconditionally (it has no flag), so answers may switch to the visitor's language
— see `PLAN_V2.md` §4 invariant 10. No data backfill is required except
`chat_feedback.status` (`pending`) and `chat_messages.answered` (leave `NULL` for
old rows).

---

## 13. Verification

`tests/` is **not** empty: it holds 31 `unittest` modules (settings registry,
RAG search, ingest, quotas, rate limits, widget config/asset/snippet, worker,
and the V2 services: digest, Q&A training, integrations, API keys) running 277
tests, plus 5 widget `.mjs` files with 18 `node:test` checks. `AGENTS.md`
documents both commands; there is no npm `test` script.

```bash
source .venv/bin/activate
uv run python -c "import site_gpt.app.main"
uv run alembic upgrade head
uv run python -m unittest discover -s tests -v     # 31 modules / 277 tests today
node --test tests/*.mjs                            # 5 widget files / 18 checks
uv run uvicorn site_gpt.app.main:app --reload      # :8000
uv run python -m site_gpt.app.worker               # ingest + digest loops
cd frontend && npm run build && npm run lint
trail build
```

End-to-end smoke per phase: register a company → add a website + sitemap →
`POST /api/ingest` → chat (sync and SSE) with citations → 👎 → approve a
corrected answer → re-ask → trigger a handoff → `POST /api/digest/preview` then
`send-now` → create an API key and call `/api/v1/settings` → export and delete a
conversation → verify `GET /api/widget-config` contains no internal keys.

**New tests for V2:** the suite exists, so extend it rather than seed it — unit
test `services/digest.py`, `services/qa_training.py`, `services/integrations.py`
and the `get_api_key_user` dependency, and keep `tests/test_settings.py` in sync
as the allowlist grows. These are the highest-risk new code; `PLAN_V2.md` V2-46
covers them.

---

## 14. Risks, dependencies & open questions

**Risks**

| Risk | Mitigation |
|---|---|
| `send_email` bug (P0.1) silently breaks F5/F6 and existing password reset | Fix and smoke-test first |
| Public `/api/widget-config` leaking new internal settings | ADR-1 allowlist, before any new key |
| `rate_limit` is in-memory, per-IP, per-process — new public endpoints (`/api/handoff`) are not protected across multiple workers | Document; Redis-backed limiter is a follow-up |
| Integration credentials stored in `integrations.config` (Text) | Mask on read, deployment-level encryption at rest (ADR-6) |
| Public `/api/conversations/{session_id}` allows history lookup by guessed session id | Documented security follow-up; needs a breaking widget change |
| F3 model overrides could break chat when a provider has no API key | Fail gracefully through the existing SSE `error` event, never a 500 |
| Digest "top topics" from keyword counting is naive | Ship deterministic v1; LLM-based clustering is an explicit v2 |
| Digest email volume / duplicates at scale | `digest_log` unique constraint + per-company opt-in |
| `SYSTEM_PROMPT` changes affect every answer, including existing embeds | Apply to both `ask` and `ask_stream`; smoke-test in ≥3 languages |

**Dependencies between features:** P0 → all. F1 (`t()`) → F5 widget copy.
F4 (`message_id`) → F6 feedback stats. F5 → F7 events. F6 → F7 events.
ADR-1 → F8 secrets. F8 API keys → F9 export auth review.

**Open questions for the reviewer**

1. **Handoff depth:** is notify-and-callback (ADR-4) enough, or is a real-time
   agent inbox required? The latter is a separate product-sized spec.
2. **Language claim:** do we market "95+ languages" or the honest "replies in
   the visitor's language"? This spec assumes the latter.
3. **Digest schedule:** UTC hour + weekly `digest_day` as specified, or per-user
   timezone? Timezones need a `users.timezone` column.
4. **Integration scope:** all four providers in v1, or just generic webhook +
   Slack (which covers most of SiteGPT's value at a fraction of the work)?
5. **API versioning:** a real `/api/v1` router, or just API keys on the existing
   endpoints? This spec chooses `/api/v1` to match SiteGPT's documented API.
6. **Secret encryption:** is deployment-level encryption at rest acceptable, or
   should we add `cryptography` (the only new Python dependency) for
   app-level encryption of `integrations.config`?
7. **Pricing/trial/onboarding:** confirm these stay out of scope (they are SaaS
   commercial features, not applicative ones).

---

## Appendix — What we deliberately keep

These are already in the repo and are **not** on SiteGPT's features page. Do not
regress them while implementing the above: answer citations (title/URL/source
type), SSE streaming (`/api/chat/stream`), the Playground, Google Drive / URL
source providers, scheduled re-crawl (`CRAWL_REFRESH_HOURS`), six chat providers
with an independent embedding provider (including fully local Ollama),
multi-tenancy, idempotent re-ingest with stale-chunk cleanup, rate limiting, the
`/health` dependency probe, and full self-hosted source ownership.
