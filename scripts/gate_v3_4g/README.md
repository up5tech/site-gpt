# Gate V3-4G — rerunnable checks

The scripts behind `plans/PLAN_V3.md` §5 **Gate V3-4G**. They run against a
throwaway database (`GATE_DB`, default `v3_gate_4g`) on the server behind
`DATABASE_URL`/`.env`, and against the real Redis from the same `.env`.
**`00_migrations.sh` drops and recreates that database**, so never point
`GATE_DB` at anything you care about.

```bash
bash scripts/gate_v3_4g/run_all.sh        # everything, in order
GATE_DB=v3_gate_scratch bash scripts/gate_v3_4g/run_all.sh
```

Prerequisites: Postgres with `pgvector`, Redis, `uv`, `curl` (and the repo's
own `.venv`; no new dependency).

| Script | Checks |
|---|---|
| `00_migrations.sh` | Empty DB → `alembic upgrade head` replaying `c9d3e5a71b28 → 76f46b510350 (M7) → afef1e91e0b5 (M8) → 1c5516fa864d (M9)`, single head, and each of M7/M8/M9 upgraded → downgraded to its parent → re-upgraded. |
| `01_db_checks.py` | 10 SQL-level checks: lazy conversation row, `(website_id, session_id)` uniqueness (and the same session id on two websites), agent author in the transcript, `delete_conversation`, atomic `erase_session` over five tables, one cluster run per `(company, window)` + status CHECK, cluster identity with a 1536-d pgvector centroid, retention expiry by `last_message_at`. |
| `02_http_smoke.py` | 11 HTTP checks in `EMBED_TOKEN_MODE=compat`: `/health`, register + admin login, website, 14 `widget-config` public keys with no internal key, tokenless embed accepted / invalid token `403 invalid_embed_token` without resetting the K4 session, session-token isolation, inbox `waiting → claim → 409 for the second agent → agent reply in the widget → closed`, privacy export with agent authors then atomic erasure, and the handoff path with `live_inbox_enabled=false` (no `conversations` row, `/api/inbox` 404). Writes `.state/smoke.json`. |
| `03_enforce.py` | `EMBED_TOKEN_MODE=enforce`: tokenless `403 embed_token_required` on `widget-config` and `session-token`, the rotated token accepted, the superseded one refused as `invalid_embed_token`. |
| `04_redis.sh` | Two uvicorn processes (`:8011`, `:8012`) with `RATE_LIMIT_BACKEND=redis` sharing one login budget (10 allowed, then 429 across both), then a third process pointed at a closed Redis port: `/health` `status:degraded` + `redis:false`, `rate_limiter.degraded:true` after one attempt, and `/api/inbox/events` answering `503` before streaming. |
| `05_clustering_opt_in.py` | `topic_clustering_enabled=false` queues nothing and writes no `topic_cluster_runs` row (so no provider call); with the flag on the window is queued, and the test removes its own job from `queue:jobs`. |

## Not covered here

The rest of §9 needs things this repo cannot supply, and the gate records them
as **blocked and unexecuted**: ingest → embed → `chat`/`chat/stream` (no LLM or
embedding provider; a real key would be spent), handoff/digest email (no SMTP),
crawling a live sitemap, and every browser step (`/inbox` UI, the widget stream
in a real page).

Logs from the Redis step land in `/tmp/v3_gate_uv{1,2,3}.log`; kill those PIDs by
hand only if a run was interrupted before its `trap` fired.
