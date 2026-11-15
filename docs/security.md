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
| Integration secrets | Masked as `***` on every read; a PATCH echoing the mask keeps the stored value; provider errors are scrubbed of every stored secret before they reach a client **and** before they are stored on a delivery row | `api/integration.py`, `services/integrations.py` |
| Delivery retention | Delivery rows keep the event payload (visitor contact details) for retries, but no API returns it: `/integrations/deliveries` exposes type, status, attempts and the scrubbed error only | `api/integration.py` |
| Webhooks | HMAC-SHA256 over `<timestamp>.<body>`, header `X-SiteGPT-Signature`; receivers can reject replays by checking the timestamp | `services/integrations.py` |
| Rate limits | Fixed window per client IP on public endpoints (in-memory, see accepted risk K5) | `services/ratelimit.py` |
| Spend ceiling | Daily message cap per website, counted in Redis, reset at UTC midnight | `api/routes.py` |
| Uploads | Size capped while streaming (`MAX_UPLOAD_MB`, 413 without buffering the body) | `api/upload.py` |
| Consent | When `require_consent` is on, `POST /api/contacts` refuses without `consent: true` and stamps `contacts.consent_at` | `api/routes.py` |
| Session reads (K4) | The widget mints a per-session token and sends it as `X-Session-Token` to read its history or contact. Only `sha256(token)` is stored; a token value expires after `SESSION_TOKEN_TTL_SECONDS`, the whole chain dies after `SESSION_TOKEN_MAX_LIFETIME_SECONDS`, and rotation requires holding the current value | `services/session_tokens.py`, `POST /api/session-token` |
| Export / erasure | Admin-only JSON export per website and hard deletes for a conversation or a contact, both company-scoped | `api/privacy.py` |
| Retention | `retention_days` per company: the worker's daily job hard-deletes `chat_messages`, `chat_feedback`, `handoff_requests`, `contacts` and `digest_log` rows older than the policy, scoped to that company's websites. `POST /api/privacy/retention` previews it (`dry_run`) or runs it on demand | `services/retention.py`, `api/privacy.py`, `worker.py` |
| Logs | No raw API key, integration token or password is written to a log line; webhook bodies are not logged | `services/*` |

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
retry), and the visitor's widget carries on **without history** — the messages
stay under the old session id for admins until retention deletes them, and a
returning visitor needs a new session to get history again.

So, stated plainly: a stolen token is useful until its TTL expires, and can be
renewed only inside the session's absolute lifetime; after that it is dead. There
is still no server-side revocation UI (see §5).

`SESSION_TOKEN_MODE` (`compat` | `enforce`) controls whether a tokenless read of
an *unclaimed* session is allowed; see §5 for the trade-off.

## 4. Data inventory

| Table | Contents | Personal data |
| --- | --- | --- |
| `chat_messages` | Every question and answer, with `session_id` | Yes — free text, may contain anything |
| `contacts` | Name, email, `session_id`, `consent_at` | Yes |
| `chat_feedback` | 👍/👎, optional comment, reviewed answer | Yes — the comment is free text |
| `handoff_requests` | Request message, status, channel | Yes — free text |
| `documents`, `extra_documents`, `embeddings` | Owner's knowledge base | Usually no; may quote the owner's pages |
| `users` | Name, email, argon2 password hash, reset tokens | Yes |
| `api_keys` | Prefix, peppered hash, scopes, timestamps | No raw secret |
| `session_tokens` | Per-session token **hash**, expiry, last use | A credential once removed; not personal data |
| `integrations` | Provider config **including credentials** | Credentials, not personal data |
| `integration_deliveries` | Event payload (may contain a lead's name/email), status, attempts, scrubbed error | Personal data copied out of `contacts` for retry; **not** covered by `retention_days`, no pruning yet |
| `digest_log` | Which weekly period was sent to whom | Recipient personal data |
| `uploads/` | Imported source files | Depends on the file |

**Retention.** A company can set `retention_days` (0 or unset = keep for ever,
the default for every company created before the setting existed). The worker
queues one purge per such company daily (`RETENTION_CHECK_SECONDS`), and the purge
deletes rows **strictly older than** `now - retention_days` from `chat_messages`,
`chat_feedback`, `handoff_requests`, `contacts` and `digest_log`, always through
that company's websites. Deletion is hard, like the erasure endpoints.

What a policy does *not* cover yet: `integration_deliveries` payloads (they keep
contact details until an admin deletes the row) and uploaded files under
`uploads/`. `POST /api/privacy/retention` with `dry_run: true` (the default)
counts what would go without deleting anything, and accepts `retention_days` as an
override for a what-if preview.

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
- **K5 — the rate limiter is per process.** The fixed window lives in memory, so
  N workers allow N times the configured rate, and a restart resets the counters.
  It stops accidents, not a determined attacker. Redis-based limiting is a V3
  item; the Redis daily message cap is the hard spend ceiling today.
- **K6 — development defaults.** `JWT_SECRET_KEY` has a known fallback and
  `CORS_ORIGINS` defaults to `*` if unset. The app does not refuse to boot with
  them. Treat §3 as the deployment checklist; a production boot that logs no
  configuration is indistinguishable from a misconfigured one.
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
- [ ] Erasure rehearsed on a test session (export → delete → export is empty).
