# Security and data handling

This document is written for the person who runs Site GPT for real customers. It
separates three things that are easy to blur together:

1. **What the code enforces** — controls that hold whatever the deployment does.
2. **What the operator must enforce** — transport, storage, secrets and backups,
   which live in the proxy, the database and the host, not in this repository.
3. **What is explicitly not provided** — certifications and legal agreements.

Claims in this app's own copy must stay inside these boundaries. Nothing here, and
nothing in `README.md`, should be read as a certification.

## 1. Not provided

Site GPT does **not** provide, and this repository does not implement:

- **SOC 2 Type II** — no examination, no report, no auditor involvement.
- **HIPAA** — no Business Associate Agreement, and the app is not built for PHI.
- **A signed GDPR Data Processing Agreement (DPA)** — a legal document between
  controllers and processors, not code.
- **GDPR certification** — there is no such certification body; "GDPR compliant"
  is a statement about a deployment's practices, not a product feature.

What *is* implemented is the technical half of a data-subject request: export,
erasure and recorded consent (§2, F9). Whether a given deployment is lawful
depends on the operator's notices, contracts, retention decisions and breach
processes.

## 2. What the code enforces

| Area | Control | Where |
| --- | --- | --- |
| Passwords | `argon2` hashes, never plaintext | `core/auth.py` (`pwd_context`) |
| Password reset | Only `sha256(token)` is stored and compared with `hmac.compare_digest`; the raw token exists only in the emailed link and is cleared on use | `api/user.py` |
| Sessions | HS256 JWT with an expiry (24h by default), verified on every request; a user must still be `status="active"` | `core/auth.py` |
| Roles | `get_admin_user` / `get_manager_user` on every admin route; company scoping comes from the token, never from a query parameter | `core/auth.py`, `api/*` |
| Tenant isolation | Every admin query filters on the caller's `company_id`; a foreign id answers 404, not 403, so ids cannot be probed | `api/*`, `api/privacy.py` |
| API keys | Only `sha256(pepper + raw)` is stored; comparison uses `hmac.compare_digest`; keys carry scopes, a prefix for identification and a `revoked_at`; the raw value is returned once | `services/api_keys.py`, `api/api_key.py` |
| Public config | `GET /api/widget-config` returns an explicit allowlist of 14 widget keys, never a table dump | `api/setting.py` (`WIDGET_PUBLIC_KEYS`), `api/routes.py` |
| Inbox stream | `GET /api/inbox/events` checks the JWT, manager+ and `live_inbox_enabled` **before** the response starts (a 404 or 503, never an open stream), subscribes to one pub/sub channel per company (`inbox:<company_id>`) and derives nothing from the request, so a foreign conversation id cannot be read or announced | `api/inbox.py`, `services/inbox.py`, `services/redis.py` |
| Inbox access | Every `/api/inbox` route except `GET /status` requires manager+ **and** the company's `live_inbox_enabled`; with the flag off the surface is a 404, so an installation without a console does not advertise one. A conversation is resolved by UUID through a join on that company's websites, so a foreign id is a 404, never a cross-tenant read | `api/inbox.py`, `services/inbox.py` |
| Inbox transcripts | A manager/admin of the company can read the transcript of any of its conversations — the same messages `GET /api/privacy/export` returns, including teammates' agent replies. There is no per-conversation grant and no per-read audit log: the company is the boundary, and `live_inbox_enabled` only decides whether the console exists | `api/inbox.py`, `services/inbox.py` |
| Widget live messages | `GET /api/chat/messages` and `/api/chat/messages/stream` require the **K4 session token** (a valid `X-Session-Token` for *that* website and session), an active website and the embed guard; the public embed token alone reads nothing, and the live channel is per session (`chat:<website_id>:<session_id>`) | `api/routes.py`, `services/rag.py` |
| Integration secrets | Masked as `***` on every read; a PATCH echoing the mask keeps the stored value; provider errors are scrubbed of every stored secret before they reach a client **and** before they are stored on a delivery row | `api/integration.py`, `services/integrations.py` |
| Delivery retention | Delivery rows keep the event payload (visitor contact details) for retries, but no API returns it: `/integrations/deliveries` exposes type, status, attempts and the scrubbed error only | `api/integration.py` |
| Webhooks | HMAC-SHA256 over `<timestamp>.<body>`, header `X-SiteGPT-Signature`; receivers can reject replays by checking the timestamp | `services/integrations.py` |
| Rate limits | Sliding window per client IP on public endpoints (`memory` per-process by default; shared via Redis with `RATE_LIMIT_BACKEND=redis`, see mitigated K5) | `services/ratelimit.py` |
| Session cap | Optional per-`(website_id, session_id)` visitor-message cap (`session_message_limit`, default `0` = off) in Redis with a TTL refreshed on every accepted message. A refusal is a friendly reply with no LLM call, no daily-budget spend and no session reset; checked after the per-IP limiter and **before** the daily cap | `services/quota.py`, `api/routes.py`, `api/v1.py` |
| Spend ceiling | Daily message cap per website, counted in Redis, reset at UTC midnight. The per-session cap is checked before it, so a capped session cannot spend the day's allowance | `api/routes.py`, `api/v1.py` |
| Uploads | Size capped while streaming (`MAX_UPLOAD_MB`, 413 without buffering the body) | `api/upload.py` |
| Consent | When `require_consent` is on, `POST /api/contacts` refuses without `consent: true` and stamps `contacts.consent_at` | `api/routes.py` |
| Session reads (K4) | The widget mints a per-session token and sends it as `X-Session-Token` to read its history or contact. Only `sha256(token)` is stored; a token value expires after `SESSION_TOKEN_TTL_SECONDS`, the whole chain dies after `SESSION_TOKEN_MAX_LIFETIME_SECONDS`, and rotation requires holding the current value | `services/session_tokens.py`, `POST /api/session-token` |
| Embed token (K18) | Optional per-website `X-Embed-Token`. Only `sha256(token)` is stored, the 12-character prefix is the only readable part, one token is active per website (partial unique index) and rotation is a single transaction. `compat` accepts a missing token but refuses an invalid one; `enforce` requires it; a refusal is `403 {detail, reason}` with `invalid_embed_token` / `embed_token_required`. The value is public in the page and replayable, so this is a revocation and compatibility control — not origin authentication | `services/embed_tokens.py`, `services/embed_guard.py`, `api/website.py` |
| Export / erasure | Admin-only JSON export per website and hard deletes for a conversation or a contact, both company-scoped | `api/privacy.py` |
| Retention | `retention_days` per company: the worker's daily job hard-deletes `chat_messages`, `chat_feedback`, `handoff_requests`, `contacts`, `digest_log`, `topic_clusters` and `topic_cluster_runs` rows older than the policy, scoped to that company. `POST /api/privacy/retention` previews it (`dry_run`) or runs it on demand | `services/retention.py`, `api/privacy.py`, `worker.py` |
| Sitemap scan (V4 F4) | Opt-in per company (`sitemap_scan_enabled`, off by default) and limited to that company's `active` websites. The sitemap is fetched through the SSRF-guarded crawler (`net_guard` rejects non-public hosts on every hop), and the diff — new pages, plus retiring vanished pages and deleting **every** document row for their URL — is applied **only after a fully successful, non-empty fetch**; a failed or empty fetch changes no row | `services/sitemap.py`, `services/crawler.py`, `worker.py` |
| Topic clustering (V3 F2) | Opt-in per company and off by default. One run sends at most `TOPIC_CLUSTER_MAX_MESSAGES` (500) visitor questions (1000 characters each) to the configured embedding provider in one call, and one naming request covering at most 8 clusters × 5 quoted questions to the configured chat LLM; derived rows store a label, a summary, a centroid and window counts, never question text. Erasing a conversation drops the weeks it appears in locally, without calling a provider | `services/topics.py`, `worker.py`, `api/privacy.py` |
| Logs | No raw API key, integration token or password is written to a log line; webhook bodies are not logged | `services/*` |

**The Redis guards fail open.** The session cap and the daily message cap are
both Redis counters, and both admit the message when Redis is unreachable (the
error is logged). That keeps chat available, but an outage can exceed both
ceilings — the trade-off the daily cap has always made, now shared by the
session cap. On a fresh deployment with both caps at `0` neither counter is
written at all. The per-IP limiter is different: it falls back to its
per-process window (K5), and `/health` reports Redis as `degraded`.

What the code deliberately does **not** do: encrypt values at the application
layer. Encryption at rest is a property of the database and the disk (§3).

## 3. What the deployment must enforce

These are listed because the code cannot enforce them and because the defaults in
`.env.example` are development values.

### Transport

- Terminate **TLS 1.2 or newer** at the reverse proxy or load balancer in front of
  the API and the frontend. The app itself speaks plain HTTP.
- Redirect HTTP to HTTPS and send `Strict-Transport-Security` with a long
  `max-age` once HTTPS is verified.
- Keep the widget and the API on HTTPS: the embed fetches the API from the
  visitor's browser, so a mixed-content page silently loses the widget.

### CORS and proxies

- Set `CORS_ORIGINS` to the exact frontend origin(s), comma-separated. The default
  `*` is a development convenience and disables credentialed requests.
- Behind a load balancer, set `TRUSTED_PROXY_IPS` to the public addresses of the
  proxies. Otherwise every visitor shares one rate-limit bucket (the proxy's IP).
  Loopback and private peers are trusted automatically.
- The console's event stream carries `Authorization`, which makes it a non-simple
  request: the browser preflights it with `OPTIONS` before `GET`. `api/main.py`
  answers with `allow_headers=["*"]` / `allow_methods=["*"]` and enables
  credentials only for an explicit origin list, so keep `CORS_ORIGINS` to the real
  console origins — a wildcard origin would disable the credentialed request.
- **Server-sent events** need buffering off and a timeout above the heartbeat.
  `GET /api/inbox/events` is one long-lived `text/event-stream` response that
  carries `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`
  (honoured by nginx); still disable response buffering for that path and keep
  the proxy's idle timeout above `INBOX_STREAM_HEARTBEAT_SECONDS`, which is the
  interval of the `: heartbeat` comment that keeps the connection alive. Each
  tick also renews that connection's presence lease; `INBOX_PRESENCE_TTL_SECONDS`
  (60) is the fallback for a connection that dies without closing, and is never
  allowed below two heartbeats. If Redis is down the route answers `503` before
  streaming and the console polls the queue instead, so stopping Redis degrades the
  inbox rather than breaking it. `GET /api/chat/messages/stream` is the same shape
  for a visitor's live agent replies (it additionally needs the K4 session token
  and refuses with `409` while no agent handles the session), and
  `GET /api/inbox/events` still needs `proxy_read_timeout` above the heartbeat.

### Secrets

| Variable | Requirement |
| --- | --- |
| `JWT_SECRET_KEY` | A long random value. The code falls back to a known development string when unset, which would let anyone mint tokens (accepted risk K6). Rotating it invalidates every session. |
| `API_KEY_PEPPER` | Required in production. Rotating it invalidates every issued `/api/v1` key, which must then be re-minted. |
| `INTEGRATION_WEBHOOK_SECRET` | Required for the webhook integration. Without it the signature is not verifiable; rotating it requires the receiver to update its copy. |
| `MAIL_*`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPEN_ROUTER_API_KEY`, `GROQ_API_KEY`, `OLLAMA_PASSWORD`, `REDIS_PASSWORD` | Provider credentials. Keep them out of the repository, out of the frontend bundle and out of chat transcripts; use the platform's secret store or a root-owned `.env`. |

`.env` must not be committed, and `load_dotenv()` reads it from the process's
working directory at startup only.

### Data at rest

- Enable **Postgres encryption at rest** — either the managed database's
  transparent encryption or full-disk encryption on the host. Chat transcripts,
  contact details and integration credentials all live in one database.
- Encrypt the **`uploads/`** volume as well; uploaded documents are the knowledge
  base source material.
- Restrict network access to Postgres and Redis to the application hosts, and set
  `REDIS_PASSWORD` if Redis is reachable from anywhere else.
- Take and test **backups** of the database and `uploads/`. A backup is a copy of
  the personal data too: it must be encrypted, access-controlled and covered by
  the same retention decisions. Erasing a conversation in the app does not reach
  an older backup.

### Operating

- Rotate `JWT_SECRET_KEY`, `API_KEY_PEPPER` and `INTEGRATION_WEBHOOK_SECRET` when
  anyone with access leaves, and after any suspected exposure.
- Revoke a single leaked `/api/v1` key from **Settings → API keys**; revocation is
  immediate (`revoked_at`) and the row stays for the audit trail.
- Answer an erasure request with `GET /api/privacy/export`, then
  `DELETE /api/privacy/conversations/{session_id}` and
  `DELETE /api/privacy/contacts/{session_id}`; then handle the backups as above.
- Keep `SQL_ECHO=false` — verbose SQL logging can put row values in the logs.

### 5.1 Session tokens (K4)

How the widget authenticates a session:

1. On first load it calls `POST /api/session-token` with its `website_id` and the
   session id it generated. The server mints a random `sst_…` token, stores only
   its SHA-256, and returns the raw value once.
2. The widget keeps it in `localStorage` (`chat_widget_session_token`) and sends
   `X-Session-Token` on `GET /api/conversations/{sid}` and `GET /api/contacts/{sid}`.
3. An expired token still allows **rotation** with `X-Session-Token` on the mint
   endpoint, so a returning visitor does not lose history; the token is not
   renewed by ordinary reads.
4. A session that already has data but no token row cannot be minted for at all —
   otherwise knowing an id would be enough to obtain the credential.

Two clocks bound a token, and neither one alone is enough:

| Knob | Default | What it bounds |
| --- | --- | --- |
| `SESSION_TOKEN_TTL_SECONDS` | 30 days | how long one token **value** is accepted for a read |
| `SESSION_TOKEN_MAX_LIFETIME_SECONDS` | 180 days | the **whole chain** — `created_at` to the last possible rotation |

The TTL alone would bound nothing, because rotation renews it: whoever held a
stolen token could rotate every 29 days for ever and keep reading. The absolute
lifetime closes that: it is counted from the row's `created_at`, which rotation
never moves, so a chain cannot be extended past it. After it, `verify()` rejects
the token and `mint()` refuses to rotate it (`403` *"reached its maximum
lifetime"*, not the "already has a token" message, which would invite a pointless
retry). Every session-token refusal carries a machine-readable `reason` beside its
human `detail`, because the two 403s on this endpoint mean different things:

| `reason` | Status | What the widget does |
| --- | --- | --- |
| `session_expired` | 403 | calls `newSession()` and mints **once** more — the id is dead |
| `session_claimed` | 403 | keeps the session id: another tab may hold the valid token, and resetting would make the two tabs silently lose each other's history |
| `invalid_token` | 403 | read refused; the widget re-mints (reads only) |
| `token_required` | 401 | `SESSION_TOKEN_MODE=enforce` and no token was sent |

So a dead chain leads to a fresh session, and its old transcript stays under the
old session id for admins until retention deletes them. A second refusal ends the
attempt; the widget then works without history rather than retrying for ever. A
tab that lost its token for a session another tab claimed still shows no history —
the alternative was wiping the session for the tab that holds it.

So, stated plainly: a stolen token is useful until its TTL expires, and can be
renewed only inside the session's absolute lifetime; after that it is dead. There
is still no server-side revocation UI (see §5).

`POST /api/session-token` answers `{"detail": "...", "reason": "session_expired" |
"session_claimed"}` (plus `invalid_token` / `token_required` from the read guards),
and clients should branch on `reason`, not on the prose.

`SESSION_TOKEN_MODE` (`compat` | `enforce`) controls whether a tokenless read of
an *unclaimed* session is allowed; see §5 for the trade-off.

### 5.2 Live inbox (F3)

- **Who can read a transcript.** Every `/api/inbox` route except `GET /status`
  requires manager+ **and** the company's `live_inbox_enabled` (404 when off). A
  conversation is resolved by UUID through a join on that company's websites, so a
  foreign id is a 404. Within the company there is no per-conversation grant: any
  manager/admin can open any conversation and read the same messages the privacy
  export returns, including teammates' replies. Treat an agent account as a read
  grant over the company's visitor conversations and manage access with the
  existing user roles, not a per-agent scope.
- **Stream authentication.** `GET /api/inbox/events` and
  `GET /api/chat/messages/stream` are read with `fetch()` because both need a
  header (`Authorization`, and the widget's `X-Session-Token`). The inbox stream
  checks the JWT, manager+, the flag and Redis **before** the response starts, so
  it never opens a stream it cannot feed; the widget stream additionally requires
  the K4 session token and answers `409` while no agent handles the session.
- **Reconnect.** Notifications are hints with a stable `id`; the console re-reads
  the database after `ready`, after every event and after a reconnect, so a lost
  pub/sub message costs a refetch and a duplicate `id` is droppable. Pub/sub is not
  a durable log and no payload is trusted as state.
- **Presence.** One Redis lease per connection
  (`inbox:presence:<company>:<user>:<connection>`) with
  `INBOX_PRESENCE_TTL_SECONDS` (60, never below two heartbeats), renewed each tick
  and deleted by the connection that owns it. Presence is decoration: a Redis
  outage reads as nobody online, never as an error.
- **Residual.** The embed token is public in the page and replayable (K18 stays
  accepted); it is not part of the console's authorization. Agent reads are not
  individually audited beyond the normal request logs, which do not contain
  message bodies.

## 4. Data inventory

| Table | Contents | Personal data |
| --- | --- | --- |
| `chat_messages` | Every question and answer, with `session_id` | Yes — free text, may contain anything |
| `contacts` | Name, email, `session_id`, `consent_at` | Yes |
| `chat_feedback` | 👍/👎, optional comment, reviewed answer | Yes — the comment is free text |
| `handoff_requests` | Request message, status, channel | Yes — free text |
| `conversations` | One inbox row per `(website_id, session_id)`: state (`bot`/`waiting`/`human`/`closed`), the holder while a session is being handled (cleared on release/close, by design), claim/close and last-message timestamps, first-question title from `chat_messages` | Yes — the lasting attribution of who answered is `chat_messages.author_user_id` on the `agent` rows, not the cleared assignee. Expires on `last_message_at` under `retention_days`, and the privacy erasure deletes it with that session's messages |
| `documents`, `extra_documents`, `embeddings` | Owner's knowledge base | Usually no; may quote the owner's pages |
| `users` | Name, email, argon2 password hash, reset tokens | Yes |
| `api_keys` | Prefix, peppered hash, scopes, timestamps | No raw secret |
| `session_tokens` | Per-session token **hash**, expiry, last use | A credential once removed; not personal data |
| `embed_tokens` | Per website: `sha256(token)`, 12-character prefix, issue/rotate/revoke timestamps, last use | A bearer value that ships in the customer's page by design (K18): revocable, hash-only at rest, never personal data |
| `integrations` | Provider config **including credentials** | Credentials, not personal data |
| `integration_deliveries` | Event payload (may contain a lead's name/email), status, attempts, scrubbed error | Personal data copied out of `contacts` for retry. A **dead** row's payload is cleared by the worker; settled rows are deleted after `DELIVERY_RETENTION_DAYS` (default 30). Not governed by the per-company `retention_days` |
| `digest_log` | Which weekly period was sent to whom | Recipient personal data |
| `topic_clusters` | One row per named cluster of a weekly window: `label`, `summary`, unit-mean `centroid`, long size and `sampled_messages`/`eligible_messages` | Derived from visitor questions; the text itself is not stored, but a label or summary can quote a customer's words |
| `topic_cluster_runs` | One row per `(company_id, period_start)`: status, claim/completion timestamps, bounded error text | Operational only; the error comes from a provider call over a bounded window sample |
| `uploads/` | Imported source files, one per `attachments` row | Depends on the file. An expired upload loses its row, its file, its document text and the embeddings built from it under the company's `retention_days` |

**Retention.** A company can set `retention_days` (0 or unset = keep for ever,
the default for every company created before the setting existed). The worker
queues one purge per such company daily (`RETENTION_CHECK_SECONDS`), and the purge
deletes rows **strictly older than** `now - retention_days` from `chat_messages`,
`chat_feedback`, `handoff_requests`, `contacts` and `digest_log`, always through
that company's websites. Deletion is hard, like the erasure endpoints, and runs in
bounded batches (`RETENTION_BATCH_SIZE`, 1000 rows per statement, each committed
separately) so a large tenant cannot hold one long transaction. Each of those
tables carries a `(website_id, created_at)` index (`(company_id, created_at)` for
`digest_log`) so a batch is an index scan rather than a full-table one.

**Derived cluster data (V3 F2).** `topic_clusters` and `topic_cluster_runs` are
comparably sensitive to the questions they summarise, so they are handled by the
same two policies:

- **Erasure.** `DELETE /api/privacy/conversations/{session_id}` also drops every
  cluster window that held one of the erased messages, plus its run row
  (`services/retention.invalidate_topic_windows`). Windows are matched by
  containment — any seven-day window holding a message — so it does not depend on
  the company's `digest_day`, and a conversation spanning several weeks loses only
  the weeks it has messages in, not the silent weeks between them. The call is
  local and provider-free: no embedding or naming request is made, the derived
  rows simply stop existing. With the run row gone the worker may rebuild that
  week later from the messages that remain; a week whose messages are all gone
  rebuilds to nothing rather than resurrecting erased text.
- **Retention.** Both tables are in the `retention_days` purge, scoped by
  `company_id` and keyed on each row's own `created_at` — when the window was
  clustered, not when the questions were asked. The questions themselves expire on
  their own timestamps, so a deployment that wants both gone keeps
  `retention_days` shorter than the clustering cadence allows rows to pile up
  (`topic_cluster_runs` is bounded by one row per company per week).

What the derived data is **not**: no question text, no visitor identifier, no
session id and no per-message rows are stored, which is why the digest can show a
cluster without republishing the conversation. Labels and summaries are generated
by the configured chat LLM from a bounded sample, so they can still echo a
customer's wording — treat them as visitor-adjacent data, not as aggregate
statistics.

**Delivery rows.** `integration_deliveries` holds a copy of the event payload so a
failed send can be retried, so it is cleaned on its own schedule
(`DELIVERY_RETENTION_DAYS`, default 30, deployment-wide; `0` keeps the rows):

- a row that went **dead** loses its payload immediately — it will never be
  retried, so the name/email it carried is pure exposure. The status, attempts and
  scrubbed error stay visible, and `POST /integrations/deliveries/{id}/resend`
  answers `409` because there is nothing left to send;
- **settled** rows (`delivered`/`dead`) older than the window are deleted;
  `pending` rows are never deleted because they are work that has not happened;
- both steps run in `DELIVERY_PURGE_BATCH_SIZE` (1000) id-scoped batches, each
  committed before the next, so a first run over a large backlog cannot hold one
  long transaction;
- the worker runs this on its own clock, `DELIVERY_RETENTION_CHECK_SECONDS`
  (default hourly) rather than on every retry tick — a row only becomes deletable
  days after it settled — and an admin can preview or trigger it with
  `POST /api/integrations/deliveries/purge` (`dry_run` defaults to true,
  company-scoped). `(status, created_at)` indexes the filter, so the pass is an
  index scan over the settled tail instead of a table scan;

A manual resend is claimed the same way the worker claims its rows:
`resend_claim` selects the delivery `FOR UPDATE SKIP LOCKED` and holds it until the
attempt commits, so two admins pressing Resend at once cannot send the event
twice — the second gets `409` and nothing is re-armed. The claim is deliberately
not committed before the send (that commit is what used to release it). A crash
mid-send therefore rolls the re-arm back and leaves the row `dead`, still
resendable, instead of a `pending` row nobody is working on.

Both values are set from the dashboard: **Settings → Privacy** has the
`retention_days` field and a **Preview purge** button, which calls
`POST /api/privacy/retention` with `dry_run: true` (the default) and the day count
currently in the form, then shows the per-table counts and the cutoff. The preview
never deletes, so a policy can be tried before it is saved or ever applied; the
same call accepts an arbitrary `retention_days`, so an owner can ask "what would 7
days keep?" without changing the stored policy.

The **Apply purge now** button sends the same day count with `dry_run: false`,
which deletes immediately instead of waiting for the worker. It is behind an
explicit confirmation naming the window ("everything older than N days will be
permanently deleted"), and it reports the counts it removed. Both buttons use the
same endpoint and the same scoping: an admin can only purge their own company.

**Uploads.** A file under `uploads/` is only reachable through its `attachments`
row, so the same policy removes both: `purge_attachments` deletes rows older than
the cutoff and then unlinks their files, in the same bounded batches as the rest of
the purge. The row is scoped through its `extra_documents` owner, or — for an
upload that was never attached — through the user who uploaded it. Order matters
and is deliberate: the file is removed **after** the batch commits, so a failed
commit never leaves a row pointing at bytes that are already gone; a file that is
missing or cannot be removed is logged and skipped rather than failing the purge,
and a `file_url` containing `..` is refused so a purge cannot touch anything
outside `uploads/`. Both cases show up as `attachments` in the preview's per-table
counts. Uploads with neither a document nor a user are left alone: guessing their
tenant would risk deleting another company's data.

Attached uploads follow their document rather than their own timestamp: a document
kept alive by a file attached inside the window keeps the files it already had, so
an owner who re-uses an old document does not lose half of it (and the text of the
files that were just removed would otherwise be left behind, unreachable but still
answerable). Standalone uploads — no document — still expire by their own date.

**Imported documents.** Removing the file and the `attachments` row is not enough:
the document's text lives in `extra_documents.content` and the assistant answers
from the `embeddings` built out of it, so an expired upload would keep answering
questions after the policy said its file was gone. `purge_documents` therefore
deletes the expired `extra_documents` rows themselves — text, embeddings and any
remaining attachments — and only then unlinks their files. It uses the document's
own `created_at`, which is the moment its upload arrived, and works in batches of
`RETENTION_BATCH_SIZE` like the rest of the purge. The embeddings and attachments
are deleted explicitly rather than through the foreign-key cascade, so the rule
behaves the same on SQLite in tests as on Postgres. A text-only document (typed or
pasted, no file) expires the same way: the text is the document. A document created
before the cutoff but edited since still expires — editing does not reset its
clock. The per-table preview reports this as `extra_documents`.

A document's own date is not the only test, because a document can be older than
the window and still in use: attaching a file today to a document imported 40 days
ago must not delete that fresh upload or the embeddings rebuilt from it. So a
document expires only when it is past the cutoff **and** it has no attachment at or
after the cutoff. Its remaining (older) attachments and files go with it. A
document with no attachments at all still expires by its own date.

## 5. Accepted risks

These are known, documented and deliberately deferred. They are not oversights.

- **K4 — session reads: mitigated, with a residual compatibility window.**
  `GET /api/conversations/{sid}` and `GET /api/contacts/{sid}` still exist for the
  widget, but they now check a per-session token (see §5.1). A leaked session id
  alone no longer reads anything *once the session has a token*. What remains:
  - `SESSION_TOKEN_MODE=compat` (the default) still allows a **tokenless** read of
    a session that has no token row — that is what keeps embeds served from an
    older snippet working. A session that has been claimed is protected even in
    `compat`.
  - Sessions created **before** this change have data and no token row, so they
    can never be claimed (issuing a token for them would be an oracle). They stay
    readable while `compat` is on and stop being readable to the widget when you
    switch to `enforce`; admins keep full access.
  - The token lives in the visitor's `localStorage`, so script injected into the
    *customer's* site could read it — the same exposure as any bearer credential
    in a browser. Only an XSS-free embed can prevent that.
  - A stolen token is usable until its TTL expires and can be renewed only
    inside `SESSION_TOKEN_MAX_LIFETIME_SECONDS` (default 180 days) of the session's
    creation, so the exposure is bounded but not short: an attacker who keeps
    rotating reads for up to that lifetime. There is no server-side revocation UI
    yet, which is the real gap — deleting the `session_tokens` row is the only
    immediate way to cut a token off.

  **Flip to `enforce`** once the embed snippet with token support is live on the
  customer sites you care about: set `SESSION_TOKEN_MODE=enforce` and reload.
  Nothing else changes; legacy sessions lose widget history and are still
  visible to admins.
- **K5 — the rate limiter (mitigated in V3, F1).** With `RATE_LIMIT_BACKEND=redis`
  the sliding window lives in Redis (atomic Lua over a sorted set), so N API
  processes share one budget and a restart does not reset it. Residual: the
  default `memory` backend is still per process, and when Redis is unreachable
  the `redis` backend falls back to that per-process cap — `/health` reports
  this as `rate_limiter: {backend, degraded: true}` and the status becomes
  `degraded`. During an outage, combined traffic may exceed one shared budget
  (up to N × the per-process allowance); Redis is therefore an availability
  dependency for the enforced path. Spend is bounded by the Redis message caps,
  not by the limiter: the V4 per-session cap is checked before the daily
  per-website cap, and both fail open when Redis is unreachable (§2).
- **K6 — development defaults.** `JWT_SECRET_KEY` has a known fallback and
  `CORS_ORIGINS` defaults to `*` if unset. The app does not refuse to boot with
  them. Treat §3 as the deployment checklist; a production boot that logs no
  configuration is indistinguishable from a misconfigured one.
- **K18 — the soft origin check (accepted; V3 F4 does not close it).** The
  `Origin`/`Referer` allowlist still accepts requests that carry neither header
  (non-browser clients, forged headers, `referrerpolicy="no-referrer"`) and always
  accepts loopback origins so local demos work. V3 adds an optional per-website
  `X-Embed-Token` on top: a deployed snippet becomes revocable, the token can be
  made mandatory (`EMBED_TOKEN_MODE=enforce`), and a wrong, revoked or
  another-website token is refused with `invalid_embed_token`. But the token is
  **public** — it ships in the page source and anyone who reads it can replay it —
  so it deters casual copying and gives the operator a kill switch; it is not an
  origin-authentication boundary and does not stop a determined caller from
  spending the website's credits. Closing K18 needs a genuinely origin-bound
  mechanism (for example short-lived signed requests), which is not implemented.
  Treat `enforce` as a breaking rollout: a snippet that predates the token stops
  working the moment it is switched on, and the rollback is `compat`, not a code
  change.
- **K19 — inbox reads are company-wide (accepted, V3 F3).** Any manager/admin of
  a company with `live_inbox_enabled` on can read every conversation of that
  company, including the replies a teammate wrote. There is no per-conversation
  permission, no "only while assigned" restriction on reads and no audit trail of
  who opened what (§5.2). The boundary is the company — the same one the privacy
  export and the retention purge already use — so revoking the role is how access
  is removed, and an agent account should be treated as a read grant over the
  company's visitor transcripts.
- **K8 — feedback is stored, not learned from automatically.** Ratings and
  reviewed answers feed the Q&A training document only after an admin approves
  them; nothing changes silently.
- **No application-level encryption**, no field-level tokenisation and no HSM.
  Secrets are protected by the file permissions, the secret store and the
  database's own encryption — all deployment concerns.
- **Uploads are not virus-scanned.** Only the owner's own files and admin-triggered
  imports reach `uploads/`, but a compromised admin account can import anything.
- **No admin audit log.** API keys keep a `revoked_at` and a last-used timestamp;
  other admin actions are not recorded.

## 6. Deployment checklist

Copy this into the runbook for each environment:

- [ ] `JWT_SECRET_KEY` set to a random value; `API_KEY_PEPPER` set.
- [ ] `INTEGRATION_WEBHOOK_SECRET` set before enabling any webhook.
- [ ] `CORS_ORIGINS` lists the exact frontend origin(s).
- [ ] `TRUSTED_PROXY_IPS` set if behind a load balancer.
- [ ] TLS 1.2+ terminated, HTTP redirected, HSTS enabled.
- [ ] Postgres and `uploads/` encrypted at rest; network access restricted.
- [ ] Backups of Postgres and `uploads/` encrypted and restore-tested.
- [ ] `SQL_ECHO=false`; logs do not receive `.env` values.
- [ ] Provider credentials stored in the platform's secret store.
- [ ] `GET /api/widget-config` checked to return only widget keys.
- [ ] An `/api/v1` key minted and revoked once, to confirm the flow works.
- [ ] `SESSION_TOKEN_MODE` decided: `compat` only while an old embed must keep
      working, `enforce` once the token-aware snippet is live.
- [ ] Embed tokens issued where wanted, and each snippet updated with
      `embedToken` **before** its previous token is rotated (rotation kills the old
      value immediately).
- [ ] `EMBED_TOKEN_MODE` staged: `compat` until every embed on the customer's
      sites sends the token, then `enforce`. Rollback is `compat` — missing tokens
      are accepted again, a supplied invalid one stays refused with
      `invalid_embed_token`, and no migration or data change is involved.
- [ ] Token matrix checked by hand: tokenless snippet still chats in `compat`
      after a token was issued; wrong/revoked token is `403 invalid_embed_token`;
      tokenless request in `enforce` is `403 embed_token_required`; an embed
      refusal does not reset the visitor's session.
- [ ] `live_inbox_enabled` decided per company; if it is on, the proxy keeps
      buffering off for `/api/inbox/events` and `/api/chat/messages/stream` and its
      idle timeout above `INBOX_STREAM_HEARTBEAT_SECONDS`, and the console origins
      are in `CORS_ORIGINS` (the stream's `Authorization` header is preflighted).
- [ ] Erasure rehearsed on a test session (export → delete → export is empty).
