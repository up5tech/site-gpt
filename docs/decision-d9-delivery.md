# D9 — background-job delivery: signable brief

| | |
|---|---|
| Decision | **D9** — the delivery guarantee for jobs on `queue:jobs` (`ingest`, `digest`, `retention`, `topic_clusters`, `sitemap_scan`, `insights`), the duplicate/loss rule per type, retry and terminal state, where a failed job is visible, and who may replay it |
| Blocks | **V6-20** (Wave 2) and **gate V6-2G box 1** |
| Risk | [R5](risk-register-v6.md#r5) — fix-before-launch |
| Status | **UNAPPROVED — awaiting the owner's signature.** This document is a proposal; no option is implemented and no code, migration or flag changes with it |
| Neutral record | The full option menu, per-type consequences and the scenario matrix are [`preflight-v6.md` §Appendix — D9](preflight-v6.md#appendix--d9-decision-brief). This brief adds the one thing that appendix deliberately withholds: a named combination and the reasons for it |
| Evidence base | [`worker-delivery.md`](worker-delivery.md) (per-type matrix, findings 2–7, the 2026-11-26 crash/duplicate/unknown rehearsal), `services/delivery.py` (the seam, `NullDelivery`), `services/redis.py`, `worker.py`, `services/integrations.py`, `scripts/gate_v6_2g/` |
| Date written | 2026-11-27 |

## 1. What the signature has to answer

1. **Where the guarantee lives** — no queue-level guarantee (today), a Redis
   acknowledgement list, or a durable job record in PostgreSQL.
2. **Which duplicate and loss cases are acceptable, per job type** — one rule,
   three classes, or six answers.
3. **Retry and terminal state** — attempt limit or elapsed deadline, backoff,
   and what clears a stopped job.
4. **Where a failed job is visible** — log, dead-letter destination, or the job's
   own state row — with its retention, access and redaction.
5. **Who may replay, and how** — and where that replay is recorded.
6. **For `digest` only** — whether a duplicate email is accepted for the launch
   cohort, and what, if anything, guards the window between the mail server
   accepting and `sent_at` committing.
7. **The pass conditions V6-20 will be judged by** — the crash-window scenarios
   on disposable infrastructure; the results are the evidence, not this
   signature.

## 2. What the code does today (evidence, not a proposal)

- **The queue is a bare list.** `enqueue_job` is `LPUSH queue:jobs`
  (`services/redis.py`); the consumer is `BRPOP queue:jobs` (`worker.py:268`)
  then dispatch. No acknowledgement, visibility timeout, attempt counter or
  dead-letter list exists. Once `BRPOP` returns, the message lives only in the
  worker's memory; a handler raise is logged with a traceback and the message is
  gone.
- **The seam exists and records nothing.** `services/delivery.py` ships
  `envelope()` (`job_id`, `attempt`) and `NullDelivery.claim/complete/fail`;
  `worker.worker()` calls it around `await handler(data)` and nowhere else. 24
  suite cases pin that only a handler raise produces a failure — a `kill -9`
  produces nothing.
- **Recovery is per type, and uneven.** `ingest`: `claim_ingest` with a 6 h
  `STUCK_INGEST_AFTER` takeover plus `recover_stuck_ingests` — taken by the
  **producers**, never consulted by `handle_ingest`. `digest`: a unique
  `digest_log` row claimed before the mail; a claim older than
  `DIGEST_CHECK_SECONDS` is re-queued in the company's `digest_hour`.
  `topic_clusters` / `insights`: unique rows, 30 min stale takeover.
  `retention` / `sitemap_scan`: **no claim row at all**.
- **Measured behaviour (2026-11-26 rehearsal, disposable Redis + PostgreSQL).**
  `kill -9` mid-job for all six types, then a fresh worker for 8 s: **no
  redelivery, no failure line, no compensation** for any type — the only
  recovery was the type's own rule or loop tick, at 6 h (`ingest`), 1 h plus the
  next send hour (`digest`), 30 min (`topic_clusters`), and 24 h (`retention`,
  `sitemap_scan`, `insights`). A byte-identical payload pushed twice: `ingest`
  re-crawls and re-embeds, `digest` rebuilds, `retention` deletes nothing twice,
  `topic_clusters` is suppressed by its run row, `sitemap_scan` re-fetches,
  `insights` re-runs whatever it left `failed`. An unknown `type` is dropped
  with one `worker.job.unknown` line and **no** counter movement.
- **Nothing bounds repeats.** `digest` / `topic_clusters` / `insights` re-queue
  on a timer with no attempt count, so a deterministic failure repeats every
  tick and its provider spend repeats with it.
- **The queue has exactly one copy.** V6-23 already reads
  `maxmemory-policy`/`appendonly`/`save` and alerts when the instance could
  evict or restart the list away (`queue:jobs` is not recoverable from inside
  the app). A flush or eviction loses queued **and** in-flight work together.
- **A durable claim-per-row pattern already runs here.**
  `integration_deliveries`: a row written before the first send, claimed with
  `SELECT … FOR UPDATE SKIP LOCKED`, one attempt recorded per send, a terminal
  state, a purge window — 41 tests. It is the working example of option C in
  this codebase.
- **What is already green.** 80 Python modules / 1390 tests, 46/46 node checks,
  `scripts/exercise_platform_disable.py` 15/15, gate V6-2G **11 passed / 3
  blocked / 0 failed** with box 1 blocked on D9. None of that measures delivery.

## 3. The options at a glance

| | **A — status quo** | **B — Redis ack list** | **C — durable job record** | **D — managed broker** |
|---|---|---|---|---|
| At-least-once delivery | no | yes | yes | yes |
| Survives Redis loss / eviction | no | **no** | yes | depends on vendor |
| Backlog countable and ageable | no (per-queue proxy only) | partly (`LLEN` + processing lists) | yes (query) | partly (vendor API) |
| Attempt count bounded | no | yes (in payload) | yes (column) | yes (vendor) |
| Dead letter with the payload | no | yes (Redis list) | yes (terminal row) | yes (vendor) |
| Replay from a stored record | no | yes, until the list is lost | yes | yes |
| New migration | no | no | **yes (M14)** | no |
| New dependency | no | no | no | **yes (vendor)** |
| Closes V6-20's Done-when | **no** | yes, with handler fixes | yes, with handler fixes | yes, plus a record anyway |
| Engineering estimate | 1–2 days (docs only) | 4–6 days | 8–12 days | 10–15 days + account |

Estimates are engineering judgement from the surface each option touches, not
measurements.

## 4. Option A — no queue-level guarantee (today)

**What it is.** Keep `LPUSH`/`BRPOP`, rely on each handler's claim and scheduler
tick, and document the waits.

**Cost.** No migration, no new code path; ~1–2 days to finish the per-type
procedure and record the measured waits.

**Risk.** R5 stays exactly as it is: a lost message loses that job, recovery is
a day for `retention`/`sitemap_scan`/`insights`, and two types have no claim to
resume from. V6-20's Done-when asks for crash-before-ack and crash-during-handler
to **pass**, and box 1 of gate V6-2G asks for tested delivery behaviour; under A
those rows can only be recorded as *not satisfied*. Signing A is therefore a
decision to **reword V6-20 and accept R5 as a launch residual**, not a cheaper
way to close it.

**Evidence it would need.** Per-type rehearsal rows (already exist for the
crash/duplicate/unknown cases), a written producer-replay runbook per type
(drafted, authority blank), and an explicit statement that scenarios 1–3 and 6
cannot pass. Gate box 1 stays unsignable.

## 5. Option B — Redis acknowledgement list

**What it is.** Keep `LPUSH queue:jobs`; replace the consumer's `BRPOP` with
`LMOVE queue:jobs queue:processing:<worker>` and `LREM` after the handler
returns; a reaper returns entries whose worker stopped once a visibility
timeout elapsed; `attempt` rides in the existing envelope and a terminal attempt
lands in `queue:dead`.

**Cost.** No migration and no new dependency: `RedisDelivery` in
`services/delivery.py` against the three-call seam (~150–200 lines), a consumer
change plus a reaper loop in `worker.py` (~100), two settings (visibility
timeout, max attempts), 15–20 suite cases, and V6-2G items for redelivery and
the dead list. ~4–6 engineering days.

**Risk.** The failure R5 names is unchanged at the storage layer: the queued and
in-flight entries sit on the **same single-copy Redis**, so a flush, an eviction
or a restart without persistence loses both lists, and the app cannot tell
afterwards. A dead list inherits that same risk and carries tenant ids and
parameters, so it needs a redaction and expiry rule of its own. Reaper
correctness becomes a new failure mode: too short a timeout duplicates a slow
handler, too long delays recovery. A re-delivered `ingest` re-crawls until the
handler consults `claim_ingest`, and `retention`/`sitemap_scan` still have no
durable record of their own — the list entry dies with the outcome it was
supposed to record.

**Evidence it would need.** Scenarios 1, 2, 5, 6 and 7 of the matrix pass on
disposable infrastructure (kill → reaper → retry; attempts bounded; dead list
observed); scenario 3 (crash after an external send) can only be *counted*, and
scenario 4 needs the `ingest` claim fix. Plus a documented reaper interval and
visibility timeout, a dead-list retention rule, and the Redis-durability
statement already required by V6-23.

## 6. Option C — durable job record in PostgreSQL

**What it is.** One table (type, payload, attempts, max attempts, `not_before`,
state, last error, lease owner/time, timestamps) written by the producer —
inside the producer's transaction where one exists (`claim_ingest`, the
`digest_log` claim, the privacy purge) — and claimed by the worker with
`SELECT … FOR UPDATE SKIP LOCKED`. A `LPUSH` remains only as a wake-up nudge so
latency stays sub-second; the row is the truth, so a lost nudge costs one poll
interval, not the job. Completion and failure are state transitions on the row;
a reaper returns rows whose lease expired; settled rows are purged on the
`DELIVERY_RETENTION_DAYS` pattern.

**Cost.** A migration (next revision; M13 is the head), a models entry, a
`services/job_queue.py` (~300 lines), `SqlDelivery` behind the existing seam,
producer changes in six places, the consumer loop's `BRPOP` replaced by a claim
plus wait, a reaper/settle rule, two counters on `GET /api/ops/status`, a replay
CLI, 25–35 suite cases, and gate items for redelivery, dead-letter and replay.
~8–12 engineering days. No new dependency.

**Risk.** More moving parts than B: a schema to migrate, a poll interval, row
growth and a purge rule (adjacent D7), and a lease that can expire under a
genuinely slow handler and duplicate it — the visibility timeout must exceed the
p95 handler time, or long handlers must renew their lease. Producer-side writes
must share the transaction that already claims the work, or the record can
disagree with the claim. The payload column holds ids and parameters, never a
transcript or a secret, and the dead rows need the same redaction and expiry
discipline as `integration_deliveries`.

**Evidence it would need.** All seven scenarios pass on disposable
infrastructure: kill before/during/after the handler, kill after a commit and
before the acknowledgement, provider failure with the approved backoff, poison
job reaching a terminal state, and duplicate delivery as a no-op by the type's
own key. Plus the per-type operator procedure with the replay command, its
authority and the audit row it writes.

## 7. Option D — a managed broker (SQS, Cloud Tasks, …)

**What it is.** Replace the Redis list with a queue service that provides
visibility timeouts and dead-lettering natively.

**Cost.** 10–15 engineering days plus an account, credentials, per-message
cost, egress, a local emulator for tests, and a second write path next to
PostgreSQL that cannot share the producer's transaction.

**Risk.** Vendor lock-in and a credential to scope and rotate (D2 chose managed
containers, Postgres and Redis); the broker's record cannot answer "what is the
backlog and how old" without the queue's own table anyway, and the dead-letter
payload would still need this project's redaction and retention rules. It buys
visibility timeouts, which B already provides, at the price of B's single-copy
problem plus a third party.

**Verdict.** Not recommended: it does not remove the need for the durable
record, and it adds the one thing the approved topology does not have.

## 8. Recommendation — sign C, with these settings

**8.1 Mechanism: C, a durable job record, with the Redis push kept as a
wake-up nudge.** Reasons, in order of weight:

1. **It removes the single-copy failure that makes R5 a P0-adjacent P1.**
   V6-23 already tells operators that a flush or an eviction silently deletes
   queued work; an acknowledgement list reproduces that exposure for both the
   queued and the in-flight set. A PostgreSQL row survives a Redis restart, a
   deploy and an eviction.
2. **It gives `retention` and `sitemap_scan` the claim they have never had** —
   the two types where a list entry cannot help, because the entry dies with the
   outcome it was meant to record.
3. **It closes V6-20's `sitemap_scan` window.** The row can be written in the
   same transaction as the page diff, so "pages changed, no ingest queued"
   stops being possible; that is finding 5, not a delivery detail.
4. **Backlog, age and dead jobs become queries**, which is what V6-21's
   `queue.age_high` alert currently approximates from a single `last_pop`
   timestamp.
5. **The pattern is already proven in this repository** by
   `integration_deliveries` (claim, attempt record, terminal state, purge), so
   the reviewable risk is integration, not design.

The cost is a migration and a poll interval. Signing C puts **one migration in
V6-20's scope** — the existing D9 appendix requires that to be stated
explicitly — and keeps `queue:jobs` as a nudge only, so a Redis outage degrades
latency rather than delivery.

**8.2 Duplicate and loss rules: three classes.**

| Class | Types | Rule |
|---|---|---|
| **must not lose** (repeat-safe by their own key) | `ingest`, `retention`, `sitemap_scan`, `insights`, `topic_clusters` | At-least-once. A repeat is allowed and safe because each type's key makes it a no-op or a bounded refresh; a loss is not allowed beyond the attempt limit. |
| **must not duplicate a customer-visible send** | `digest` | At-least-once delivery, **at-most-once send per period**: the period is never re-sent by a redelivery; see 8.6 for the residual window. |
| **job types added later** | — | Default to *must not lose* and to the strictest class until the owner records otherwise. |

**8.3 Retry and terminal state.** Bounded attempts: **5** (the first plus four
retries), backoff **1 min, 5 min, 30 min, 2 h, 6 h**, then a terminal **`dead`**
state that only a replay clears. A reaper returns a row whose lease is older
than **30 min**, and `ingest` renews its lease while it crawls, because a full
crawl can exceed that. All four numbers are proposals; the signature fixes them.

**8.4 Visibility.** The `dead` row is the dead letter: readable by an operator
CLI, counted on `GET /api/ops/status` (queued, processing, dead, oldest queued
age), never exposed through a tenant route. Retention follows the existing
delivery rule (`DELIVERY_RETENTION_DAYS`, 30 days) through the existing batched
purge; the payload column carries ids and parameters only.

**8.5 Replay authority.** Operator-only, out of band — no HTTP route.
`scripts/jobs.py replay --job-id …` (and `dead --limit`) from a host holding the
database URL; it resets the row to `queued` with `attempt` preserved and writes
one `platform_audit_logs` row (actor label, job id, type, previous state) through
the existing writer. The producer tick stays the fallback for a lost wake-up.

**8.6 Two handler fixes V6-20 must carry, because delivery alone does not close
them.**

- **`ingest` must consult `claim_ingest`.** Otherwise a re-delivery re-crawls
  and re-embeds while another worker may be crawling the same site, and scenario
  4 cannot pass for that type.
- **`digest` sends per recipient.** The partial-send gap (some accepted, the
  period stamped, the failures never retried) is closed by recording each
  recipient's outcome and retrying only the missing ones. The remaining
  duplicate window — the mail server accepted, the process died before the
  record committed — cannot be closed: SMTP has no idempotency key, and adding
  a provider API is out of scope for this launch. **Recommendation: accept that
  window, count it, and alert on it** (`digest.duplicate_window`), rather than
  build a second delivery channel to avoid one email per company per period.

## 9. Evidence V6-20 and gate V6-2G box 1 need, per option

| Scenario (per job type) | A | B | C |
|---|---|---|---|
| 1 crash before the handler | ✗ nothing re-delivers | ✓ reaper returns the entry | ✓ lease expiry re-queues the row |
| 2 crash during the handler | ✗ | ✓ retry, partial state as documented | ✓ |
| 3 crash after an external send, before ack | ✗ | ✓ counted, not prevented | ✓ counted; `digest` per 8.6 |
| 4 crash after the commit, before ack | ✗ | ✓ no-op by the type's key (needs 8.6 for `ingest`) | ✓ |
| 5 transient provider/DB failure | ✗ next tick only | ✓ approved backoff | ✓ |
| 6 poison job | ✗ repeats every tick | ✓ dead list | ✓ `dead` row |
| 7 duplicate delivery | ✗ measured repeats | ✓ idempotency key | ✓ |
| Operator procedure (replay + audit) | producer tick only, unaudited | Redis dead list + CLI | row + CLI + audit |
| Gate V6-2G box 1 | **not signable** | signable after the matrix | signable after the matrix |

Under **B or C**, V6-20's deliverable is: the seven-scenario matrix run per type
on disposable infrastructure, one row per type (command, output, timestamp,
commit) pasted into `plans/PLAN_V6.md` in the V6-40 table shape, the operator
procedure per type, and suite tests that pin the attempt counter, the terminal
state and the replay transition. Under **A**, the deliverable is a reworded
V6-20 plus a recorded R5 residual — a separate decision, not this one.

## 10. Cost summary

| | A | B | C (recommended) |
|---|---|---|---|
| Days (estimate) | 1–2 | 4–6 | 8–12 |
| Migration | — | — | 1 (next revision) |
| New dependency | — | — | — |
| New settings | — | visibility timeout, max attempts | poll interval, visibility timeout, max attempts, retention |
| Closes R5 | no | partly (Redis loss remains) | yes |
| Closes V6-2G box 1 | no | yes | yes |

## 11. What this brief does not do

- It implements nothing and changes no flag, queue, handler or schema.
- It does not tick V6-20 or gate V6-2G box 1: those need the matrix run after
  the signature, on disposable infrastructure.
- It does not decide `digest`'s duplicate window for the owner — 8.6 recommends
  accepting and counting it; the signature is where that is accepted.
- It does not authorise a production change: V6-20 is a Wave 2 task and this
  launch gate (V6-5G) is unrelated to it.

## 12. Signature

To sign, record on this row (and copy into `plans/PLAN_V6.md` §4 and
[risk R5](risk-register-v6.md#r5)):

| Field | Value |
|---|---|
| Mechanism | ☐ C durable job record (recommended) ☐ B Redis ack list ☐ A status quo + reword V6-20 |
| Duplicate/loss rule | ☐ three classes as in 8.2 (recommended) ☐ one rule ☐ six answers |
| Retry | ☐ 5 attempts, 1 m / 5 m / 30 m / 2 h / 6 h, `dead` (recommended) ☐ other: |
| Visibility | ☐ `dead` rows + ops counters + 30-day purge (recommended) ☐ other: |
| Replay | ☐ operator CLI + `platform_audit_logs` (recommended) ☐ other: |
| `digest` duplicate | ☐ accept, count and alert (recommended) ☐ guard: |
| Migration in V6-20 scope | ☐ yes (required by C) ☐ not applicable |
| Approver / role | |
| Date | |
| Evidence link | |

Until that row is filled, D9 stays **UNAPPROVED**, V6-20 stays blocked, and R5
stays open with its owner recorded.
