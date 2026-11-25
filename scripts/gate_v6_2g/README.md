# V6-2G — reliability and observability checks (items 1–14)

`plans/PLAN_V6.md` gate V6-2G records fourteen staged observations for V6-21 and
V6-23. This directory runs them, prints one paste-ready table row per item and
counts a **blocked** item separately from a pass.

```bash
# throwaway database v6_gate_2g + Redis database 15
bash scripts/gate_v6_2g/run_all.sh

# leave the database behind for inspection
bash scripts/gate_v6_2g/run_all.sh --keep-db

# a different throwaway database or Redis server
GATE_DB=v6_gate_2g_demo GATE_REDIS=redis://127.0.0.1:6379/14 \
    bash scripts/gate_v6_2g/run_all.sh
```

`GATE_PG` overrides the PostgreSQL base URL (default
`postgresql://postgres:postgres@127.0.0.1:5432`). The database name must start
with `v6_gate_2g`: the script drops and recreates it, so never point it at data
you care about. Redis database 0 is refused because the development stack uses
it; the gate only ever flushes the index you name.

## What it starts

| Name | Database | Redis | Used by |
|---|---|---|---|
| `api-a` | gate database | gate index | every item (the reference replica) |
| `api-b` | closed port 1 | gate index | 1, 6, 7, 9, 13 (a replica that answers 500) |
| `api-c` | gate database | closed port 1 | 1, 6, 12 (a replica degraded on Redis only) |
| `api-d` | gate database | gate index | 9 (a second healthy origin) |
| `api-prod` | gate database | gate index | 2 (production profile, `OPS_STATUS_TOKEN` unset) |
| `api-e`, `api-e2` | closed port 1 | closed / gate index | 12 (fleet view unreadable vs readable) |
| `api-roster-off` | gate database | gate index | 10 (`OPS_EXPECTED_WORKERS=0`) |
| workers | gate database | gate index | 3, 4, 5, 10, 13, 14 |

Every process is a real `uvicorn` / `site_gpt.app.worker`, written to its own log
file under the run's log directory (printed at the end). Migrations run through
`alembic upgrade head`, and the script asserts `alembic_version` is
`0b22b30bf930` before the run.

## Blocked, not skipped

* **6 — dependency alerts.** The alerts are observed on the closed-port replicas
  and the clear half on a healthy one, but the item asks for a real stop and
  restart. This gate will not stop the host's shared PostgreSQL or Redis, so the
  row stays blocked; run it on staging.
* **8 — ingress-only 5xx.** Needs the ingress/CDN product named with the query
  that counts 5xx and its observed lag/sampling. There is no ingress here.
* **11 — Redis durability.** The `CONFIG GET` reading and the snapshot's
  agreement are checked, but flipping `maxmemory-policy` is a `CONFIG SET` on a
  shared server. Set `GATE_REDIS_ALLOW_CONFIG=1` only when `GATE_REDIS` is a
  disposable instance; otherwise do the mutation on staging.
* **12 — Redis interruption.** The unreadable fleet view, the `instance` label
  and its return to `fleet` are all observed through replicas, but the
  under-reporting window needs a real Redis stop/restart — staging.

## Stated shortcuts

* Item 4 backdates `ops:queue:last_pop` instead of waiting the 900 s threshold;
  the threshold itself is unchanged and is read from the snapshot.
* Item 5 needs PostgreSQL: on SQLite `"not-a-uuid"` binds without error.
* Item 13 needs a slow job, and this checkout has no network or provider, so a
  retention purge is held on an `ACCESS EXCLUSIVE` lock on `chat_messages`. The
  property under test is unchanged: a popped job finishes before the process
  exits, then `worker.stopped {"graceful":true}`. The job's duration is printed;
  set `GATE_STOP_GRACE_SECONDS` to compare it with the platform's stop window.
* Item 14 starts every process with its own libpq `application_name`
  (`gate-<process>`), so `pg_stat_activity` can be grouped per process: each one
  is checked against its own `DB_POOL_SIZE + DB_MAX_OVERFLOW`, not just the
  deployment total. It queues a database-backed `retention` job first, because an
  idle worker holds no pooled connection and replacing one would prove nothing.

## Paste the result

The run ends with the markdown table `PLAN_V6.md` asks for (also written to
`rows.md` in the log directory), for example:

```bash
bash scripts/gate_v6_2g/run_all.sh | tail -n 30
```

Exit status: `0` when nothing failed (blocked rows are expected and reported),
`1` when an item failed, `2` when the configuration was refused before any work
ran. A blocked row never counts as a pass.
