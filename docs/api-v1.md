# `/api/v1` — API-key API

A small, versioned surface for server-to-server callers so an integration never
needs an admin password. The admin console keeps using JWT; the two paths are
independent and the legacy `/api/...` routes are unchanged.

- Base URL: `https://your-host/api/v1`
- Auth header: `X-API-Key: sk_…`
- Interactive docs: `/docs` (the `v1` group), OpenAPI JSON: `/openapi.json`

## Creating a key

In the admin console: **Settings → API keys → Create**. Keys can also be minted
with a JWT:

```bash
curl -X POST "$BASE/api/api-keys/" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "zapier", "scopes": ["read", "chat:write"]}'
```

The response contains `key` **once**. Only a SHA-256 hash (peppered with
`API_KEY_PEPPER`) is stored, and the listed `key_prefix` is the only part shown
again. Revoke with `DELETE /api/api-keys/{id}`; a revoked key is rejected on the
next request.

Changing `API_KEY_PEPPER` invalidates every key in every deployment.

## Scopes

| Scope | Grants |
|---|---|
| `read` | `GET /settings`, `/conversations`, `/contacts`, `/analytics/summary` (V4 fields included) |
| `ingest:write` | `POST /ingest` — queue a re-crawl |
| `settings:write` | `PUT /settings` |
| `chat:write` | `POST /chat` |

A missing scope returns **403** with the scope name in the message. A missing or
revoked key returns **401**. Scopes are chosen at creation; there is no
incremental grant.

## Settings are limited on purpose

`/api/v1/settings` can read and write **only** the public widget keys
(`assistant_name`, `widget_header_color`, `widget_footer_color`, `widget_position`,
`greeting_message`, `placeholder_text`, `suggested_questions`, `widget_language`,
`widget_ui_strings`, `widget_logo_url`, `handoff_enabled`, `handoff_label`,
`require_consent`, `privacy_policy_url`) plus `llm_provider` / `llm_model`.

Internal settings — `handoff_email`, `digest_*`, `daily_message_limit`,
`retention_days`, and the V3 flags `topic_clustering_enabled`,
`topic_cluster_count` and `live_inbox_enabled` — are rejected with **400**. A
leaked API key must not be able to redirect handoff mail, subscribe an attacker
to the digest, raise a quota or switch on the live-agent inbox.

## Endpoints

### `POST /ingest` — `ingest:write`

Query params: `website_id` (UUID). Returns `{"status": "ok", "website_id": …}`.

`409` when a crawl is already running for that website (the same atomic claim the
admin button uses), `403` when the website is disabled, `404` for another
company's website.

### `GET /settings` — `read`

Returns `[{"key": …, "value": …}]` for the writable keys only.

### `PUT /settings` — `settings:write`

```bash
curl -X PUT "$BASE/api/v1/settings" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '[{"key": "assistant_name", "value": "Acme Bot"},
       {"key": "widget_position", "value": "bottom-left"}]'
```

Upserts the rows (an older company without the row gets one). Returns
`{"updated": n}`. Unknown or internal keys → `400` and nothing is written.

### `GET /conversations` — `read`

Query params: `website_id` (required), `limit` (≤200, default 50), `offset`.

Returns `{"items": [{session_id, title, message_count, created_at,
last_message_at}], "total": n, "limit": n, "offset": n}`, newest activity first.

### `GET /contacts` — `read`

Same pagination. Returns captured contacts
(`first_name`, `last_name`, `email`, `session_id`, `created_at`).

### `POST /chat` — `chat:write`

```bash
curl -X POST "$BASE/api/v1/chat" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"website_id": "…", "session_id": "s-1", "question": "Do you ship to Vietnam?"}'
```

Returns `{"answer": …, "sources": [...], "message_id": …}` — the same shape and
the same RAG path as the widget. The answer is stored, so it appears in
`/conversations` and can be rated and trained like any other. The website's
**daily message limit still applies**; when it is reached the call returns `429`
instead of spending more model credits.

### `GET /analytics/summary` — `read`

Query param `days` (1–90, default 7; clamped, and the clamped value is echoed
back as `days`). Returns `conversation_volume`, `message_count`, `new_contacts`,
`feedback_up`, `feedback_down`, `top_topics` and `unanswered_questions` (each
with a deep link into the admin transcript) — the same aggregation the weekly
digest emails — plus the three V4 fields below.

**The V4 fields are additive.** Every key above keeps its exact V3 meaning and
value, so a V3 client needs no change; `build_digest`, which produces them, is
not modified.

| Field | Shape | Meaning |
|---|---|---|
| `trend` | `[{date, conversations, messages, visitor_messages, new_contacts, feedback_up, feedback_down, unanswered}]` | one row per UTC day in the window, zeros included, oldest first; `date` is `YYYY-MM-DD` |
| `funnel` | `[{stage, sessions}]` | the five stages in order: `started`, `answered`, `lead`, `handoff`, `human` |
| `top_questions` | `[{question, count}]` | at most 10 visitor questions, most asked first |

`trend.conversations` is that day's **distinct sessions**, so the daily rows do
not sum to `conversation_volume` — a session that spans midnight counts on both
days — and the last day is partial because the window ends at the request time.
`trend.unanswered` counts answers tagged `answered = False`, the same rule as
`unanswered_questions`.

`funnel` stages are counts of **distinct sessions that overlap**, not a strict
subset chain: a session counts as `answered` with at least one bot **or** human
reply, as `lead` when a contact was captured, as `handoff` when a handoff was
requested, and as `human` when the conversation reached the inbox's `human`
state or was closed after being claimed. A lead without a handoff still counts,
and so does a handoff that never reached a human; a released session drops back
out of `human`.

`top_questions` is an exact-match grouping on the normalized question —
lowercased, whitespace collapsed, trailing punctuation stripped — so "How much
does it cost?" and "how much does it cost" are one row. It uses no embedding and
no model call, so the same rows always produce the same list.

The **CSV export** is not part of `/api/v1`: `GET /api/analytics/export.csv` is a
manager-only, JWT-authenticated download on the console surface. It carries the
same three aggregates (three sections, each with its own header row), no session
ids, contacts or transcript text, and neutralizes every cell a spreadsheet would
evaluate — see [Advanced analytics (F1)](../README.md#advanced-analytics-f1).

`top_topics` is the term-frequency list by default. For a company that opted into
V3 topic clustering (`topic_clustering_enabled=true`) and asks for a range that is
exactly whole completed digest weeks, it carries the named clusters of those
windows instead — the same substitution the digest makes — so a caller should not
assume the entries are single terms.

## Rate limits

`/api/v1` has no per-IP limiter of its own: the key is the identity, and the
per-website daily message limit is what bounds spend. The public widget routes
keep their per-IP limits, and the handoff/contact/feedback endpoints remain
public and rate-limited exactly as before.

## Errors

| Status | Meaning |
|---|---|
| 401 | missing, unknown or revoked key |
| 403 | key lacks the scope, or the website is disabled |
| 404 | unknown website **or** a website of another company |
| 400 | invalid body, unknown setting key |
| 409 | an ingest is already running |
| 429 | the website reached its daily message limit |
