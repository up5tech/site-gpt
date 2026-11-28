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
| Revised | 2026-11-28 — stress-test amendments: per-class retry, producer suppression, `digest` stamped before the send; then §8.3's producer clock corrected and the exclusion moved to the live-row index |

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
  `retention` / `sitemap_scan`: **no claim row at all**. The first three
  re-enqueue from the producer side; 8.4 states what each of them becomes under
  C.
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
- **The queue has exactly one copy.** V6-23's code scope reads
  `maxmemory-policy`/`appendonly`/`save` and raises `redis.durability_unsafe`
  when the instance could evict or restart the list away (`queue:jobs` is not
  recoverable from inside the app). That code is implemented and **unticked**:
  its evidence is a local rehearsal, never a real instance, so the deployed
  setting is not yet known. A flush or eviction loses queued **and** in-flight work together.
- **A durable claim-per-row pattern already runs here.**
  `integration_deliveries`: a row written before the first send, claimed with
  `SELECT … FOR UPDATE SKIP LOCKED`, one attempt recorded per send, a terminal
  state, a purge window — 41 tests. It is the working example of option C in
  this codebase.
- **What was already green when this brief was written.** 80 Python modules /
  1390 tests, 46/46 node checks, `scripts/exercise_platform_disable.py` 15/15,
  gate V6-2G **11 passed / 3 blocked / 0 failed** with box 1 blocked on D9 —
  recorded 2026-11-27 on this branch and **not re-run for this brief**. None of
  that measures delivery.

## 3. The options at a glance

| | **A — status quo** | **B — Redis ack list** | **C — durable job record** | **D — managed broker** |
|---|---|---|---|---|
| At-least-once delivery | no | yes | yes | yes |
| Survives Redis loss / eviction | no | **no** | yes | depends on vendor |
| Backlog countable and ageable | no (per-queue proxy only) | partly (`LLEN` + processing lists) | yes (query) | partly (vendor API) |
| Attempt count bounded | no | yes (in payload) | yes (column) | yes (vendor) |
| Dead letter with the payload | no | yes (Redis list) | yes (terminal row) | yes (vendor) |
| Replay from a stored record | no | yes, until the list is lost | yes | yes |
| New migration | no | 0 or 1: only if the per-recipient `digest` state is the same table (§12; the suppression half stays in Redis either way) | **yes (M14) — one revision, 2 tables: the job record and `digest_recipients`** | yes, the same record; the broker replaces the transport, not the record |
| New dependency | no | no | no | **yes (vendor)** |
| Closes V6-20's Done-when | **no** | yes, with handler fixes | yes, with handler fixes | yes, plus a record anyway |
| **Surface** (call sites, types and line counts measured in this checkout; settings and migrations are design) | one document, no code path | 11 `enqueue_job` call sites, 6 job types, the 141-line seam in `services/delivery.py`, 2 new settings, 0 or 1 migration depending on where `digest_recipients` lives for B (§12), plus the 6 producer areas the suppression rule touches and the per-recipient `digest` record | the same call sites and seam, plus 1 migration revision holding **2 tables** (the job record and `digest_recipients`) and a `job_queue` service (the closest existing pattern, `services/integrations.py`, is 772 lines) | **everything in C's column**, then a vendor account, credentials, a local emulator and a second write path next to PostgreSQL |
| Effort (judgement, **not measured**) | 1–2 days | 6–8 days | 11–15 days | **14–20 days**: C's work plus the vendor path |

Days are judgement, not measurement: no option has been built, so there is no
velocity, review time or test-run time to derive them from. They exist to rank
the options, not to schedule them; the counted row is what this brief actually
measured.

**D is not the cheap column.** D closes V6-20 "plus a record anyway" — the row
above says so — which makes its surface a superset of C's: the same 11 call
sites, the same six producer suppression sites, the same `digest_recipients`
record and the same migration, and only then a broker on top. Its effort is
therefore C's range shifted up by 3–5 days for the account, the credentials, the
emulator and the second write path (**14–20**, against C's 11–15), not a lower
number that competes with C. The 10–15 in earlier drafts priced the vendor
integration by itself and let the record be assumed; §7's verdict is that the
broker does not remove that record, so that figure undercounted D.

**Amended scope, and who pays for it.** The stress test added two pieces to the
recommendation and **both are mechanism-independent, so they raise B and C
alike**: the producer suppression rule (8.4), which needs a producer-visible
stopped key — a Redis `queue:dead:<key>` for B, the unique-index conflict for
C — and the per-recipient `digest` record with its pre-send stamp (8.7), which
changes `services/digest.py` **and** needs a durable per-recipient record
whichever mechanism delivers the job. For C that record is the
`digest_recipients` table; for B, whether it is the same table or Redis keys is
the open line in §12, not a settled detail of this section. They are
counted in both columns above and in §10. They do not change which option is
cheaper; they do mean the 4–6 and 8–12 figures in earlier drafts no longer
describe what is being signed. D pays for both as well, on top of its vendor
path.

**Job volume the options are sized for.** The loop intervals fix a per-company
rate; no recorded decision fixes the cohort size, so no absolute total exists.
With every flag on and `w` websites per company, the producers queue about
**2 + 2w + 2/7 jobs per company per day**: `insights` one per
`INSIGHT_INTERVAL_SECONDS` (86 400 s), `retention` one per
`RETENTION_CHECK_SECONDS` (86 400 s), `sitemap_scan` one per website per
`SITEMAP_SCAN_INTERVAL_SECONDS` (86 400 s), the `CRAWL_REFRESH_HOURS` (24 h)
re-crawl one per website, and `digest` and `topic_clusters` one each per week.
One website per company is therefore ≈4.3 jobs a day, a 10-company cohort ≈43
and a 100-company cohort ≈430 — arithmetic on that formula, not measurements:
D1 recorded a cohort without a size and D3 leaves capacity to the operator.
On-demand `ingest` is additional and bounded by no interval above. The rehearsal
(`worker-delivery.md`) pushed six jobs once per type, so it measures behaviour
per job, not volume.

## 4. Option A — no queue-level guarantee (today)

**What it is.** Keep `LPUSH`/`BRPOP`, rely on each handler's claim and scheduler
tick, and document the waits.

**Cost.** No migration, no new code path; judgement, not measured: ~1–2 days to
finish the per-type procedure and record the measured waits.

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

**Cost.** No new dependency, and no migration for the transport itself:
`RedisDelivery` in `services/delivery.py` against the three-call seam (~150–200
lines), a consumer change plus a reaper loop in `worker.py` (~100), two settings
(visibility timeout, max attempts), 15–20 suite cases, and V6-2G items for
redelivery and the dead list. The per-recipient `digest` record (8.7) has to
survive a restart, and **where it lives under B is a decision, not a detail**:
either the same `digest_recipients` table as C (then B takes that one migration
revision too, and the only schema-free half is suppression, because
`queue:dead:<key>` is Redis) or per-recipient keys in Redis (then B stays
schema-free, but a Redis flush or eviction can resurrect a `sending` recipient
as a duplicate send). §12 carries the choice; this brief does not pre-empt it. B absorbs both amendments: producer suppression as a
`queue:dead:<key>` check in the six producer paths (the durable alternative — a
suppression table — is C's schema anyway), and the per-recipient `digest`
record with its pre-send stamp in `services/digest.py`. Counted surface: 11
`enqueue_job` call sites, 6 job types, the existing 141-line seam, two new
settings, 0 or 1 migration (`digest_recipients`, per §12). Effort is judgement,
not measured: **6–8 days** — the
4–6 in earlier drafts excluded the amendments.

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
observed); scenario 3 (crash after an external send) is prevented per recipient
by the pre-send stamp — the same 8.7 fix C carries — provided B's record is
durable, and a Redis-only record can lose the stamp mid-flight (§12); scenario 4
needs the `ingest` claim fix. Plus a documented reaper interval and
visibility timeout, a dead-list retention rule, and the Redis-durability
statement already required by V6-23.

## 6. Option C — durable job record in PostgreSQL

**What it is.** Two tables, not one. The job record (type, payload, attempts,
max attempts, `not_before`, state, last error, lease owner/time, timestamps) is
written by the producer, in its own short transaction — **not** in the
producer's claim transaction, because the helpers that hold those claims commit
internally (§6's commit note) — and claimed by the worker with
`SELECT … FOR UPDATE SKIP LOCKED`; a partial unique index over the
job's natural key (`type` plus `company_id` and, for `digest`,
`period_start`) over the **live** states (`queued`, `processing`, `dead`) is what
makes a stopped job — or a producer tick that lands inside a retry cycle, or
beside a job that has not finished — suppress the producer's next insert for the
same key rather than letting it re-enqueue at `attempt: 0` (8.4). It constrains
`INSERT`s only, which is why every recovery path revives the row it is
recovering instead of adding a second one: a recovery cannot be suppressed by
that row (8.4). The second table is `digest_recipients` (`company_id`,
`period_start`, recipient, `state`, `attempt`, `last_error`), whose row moves to
`sending` before the SMTP call and `sent` after the server accepts it (8.7). It
is the one new store with a person in it, so the address is kept only while the
row is actionable and cleared once it settles (8.5).
A `LPUSH` remains only as a wake-up nudge so
latency stays sub-second; the row is the truth, so a lost nudge costs one poll
interval, not the job. Completion and failure are state transitions on the row;
a reaper returns rows whose lease expired; settled rows are purged on the
`DELIVERY_RETENTION_DAYS` pattern.

**Where the row is written, and the window that leaves.** The row cannot share
the claim's transaction as the helpers stand today, and the earlier draft named
the wrong producers. `ingest_claim.claim_ingest` runs `db.commit()` before it
returns, and `recover_stuck_ingests` commits its `processing → failed` flips
before `requeue_stuck_ingests` enqueues; the other two claims the draft cited are
not producer-side at all — `claim_period` runs inside `handle_digest`
(`services/digest.py`) and `claim_run` inside `handle_topic_clusters` — so the
`digest` and `topic_clusters` producers enqueue **before** any claim exists, and
`retention`, `insights`, `sitemap_scan` and the two scheduler ticks hold no work
claim. V6-20 therefore does one of two things; the brief recommends the second.

- **Change the helpers.** Add `commit=False` (or a transaction-scoped variant) to
  `claim_ingest` and `recover_stuck_ingests`, and let the four ingest call sites
  write the row in the same transaction: `api/routes.py:104`, `api/v1.py:96`,
  `worker.py:1003` (sitemap diff) and `worker.py:1188` (crawl refresh). Touches
  `tests/test_ingest_dedup.py`, the recovery cases in `tests/test_worker.py` and
  the sitemap tests; the crawl-refresh path's manual compensation
  (`processing → failed` when the enqueue fails, `worker.py:1196–1198`) becomes
  unnecessary, because a failed insert rolls the claim back.
- **Accept the window (recommended).** Claim commits, row commits, nudge after.
  A crash between the first two leaves `processing` with no row for the key, and
  that is the one case 8.4's insert path exists for: the claim's own takeover
  (`STUCK_INGEST_AFTER` 6 h, `DIGEST_CHECK_SECONDS`, 30 min for topics) flips it
  to `failed` and inserts the row, and the handler's `claim_ingest` then wins
  because the status is no longer `processing` (8.7). The window itself is two
  commits milliseconds apart; its bound is the takeover clock — stale content
  for at most 6 h on `ingest`, and nothing on `digest` or `topic_clusters`, whose
  claims are created only after their jobs exist. The compensating flip stays
  (`worker.py:1196–1198`): if the row insert fails, the producer sets the claim
  back to `failed` rather than leaving it `processing`.

**Cost.** A migration (next revision; M13 is the head), a models entry, a
`services/job_queue.py` (~300 lines), `SqlDelivery` behind the existing seam,
producer changes in six places, the consumer loop's `BRPOP` replaced by a claim
plus wait, a reaper/settle rule, the `GET /api/ops/status` counters (queued, processing,
dead, oldest age) plus `queue.suppressed` (8.4), a replay CLI, 25–35 suite
cases, and gate items for redelivery, dead-letter, suppression and replay.
Effort is judgement, not measured: **11–15 days**; the counted surface is the
same 11 call sites, 6 job types and seam, plus **one migration revision holding
two tables** (the job record and `digest_recipients`) and the six producer
suppression sites, while the case and line counts in this list are judgement
scaled from the 772-line existing pattern. No new dependency. The amendments —
suppression and the digest path — are what moved the range from the 8–12 in
earlier drafts.

**Risk.** More moving parts than B: a schema to migrate, a poll interval, row
growth and a purge rule (adjacent D7), and a lease that can expire under a
genuinely slow handler and duplicate it — the visibility timeout must exceed the
p95 handler time, or long handlers must renew their lease. Producer-side writes cannot
share the transaction that claims the work until those helpers stop committing
internally (see the commit note above), so the two can disagree for one commit
window. The dangerous direction — a claim with no record — is the one the
claim's own takeover recovers and its bound is stated there; the safe direction
— a record whose claim then fails — costs a job that re-checks the claim and
exits (8.7). The payload column holds ids and parameters, never a
transcript or a secret, and the dead rows need the same redaction and expiry
discipline as `integration_deliveries`. That includes `digest_recipients`, the
only new table holding a person: its address column is cleared in the
transaction that settles the row and its rows are deleted on
`DELIVERY_RETENTION_DAYS`, through the batched purge that already exists — no
new setting and no second retention policy (8.5).

**Evidence it would need.** All seven scenarios pass on disposable
infrastructure: kill before/during/after the handler, kill after a commit and
before the acknowledgement, provider failure with the approved backoff, poison
job reaching a terminal state, and duplicate delivery as a no-op by the type's
own key. Plus the per-type operator procedure with the replay command, its
authority and the audit row it writes.

## 7. Option D — a managed broker (SQS, Cloud Tasks, …)

**What it is.** Replace the Redis list with a queue service that provides
visibility timeouts and dead-lettering natively.

**Cost.** Judgement, not measured: **14–20 days** — C's record work (§6: 11–15)
plus 3–5 for the account, credentials, a local emulator for tests and a second
write path next to PostgreSQL that cannot share the producer's transaction —
plus per-message cost and egress. It is not a cheaper C: the broker replaces the
transport, not the record, so the floor is C's floor plus the vendor.

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

1. **It removes the single-copy failure R5 records as a P1.**
   V6-23's code scope already names a flush or an eviction as a silent delete of
   queued work; an acknowledgement list reproduces that exposure for both the
   queued and the in-flight set. A PostgreSQL row survives a Redis restart, a
   deploy and an eviction.
2. **It gives `retention` and `sitemap_scan` the claim they have never had** —
   the two types where a list entry cannot help, because the entry dies with the
   outcome it was meant to record.
3. **It closes V6-20's `sitemap_scan` window.** The row can be written in the
   same transaction as the page diff — the one transaction this producer does
   own, unlike the claim — so "pages changed, no ingest queued" stops being
   possible; that is finding 5, not a delivery detail.
4. **Backlog, age and dead jobs become queries**, which is what V6-21's
   `queue.age_high` alert currently approximates from a single `last_pop`
   timestamp.
5. **A close pattern already runs in this repository** — `integration_deliveries`
   (claim, attempt record, terminal state, purge) — so the claim/settle/purge
   vocabulary is familiar and reviewed. It is not the same shape: no lease, no
   reaper, no wake-up nudge and no suppression key. The reviewable risk is
   therefore smaller than for a new design, not absent.

The cost is one migration (the job record, the `digest_recipients` table and the
suppression index), the producer and worker edits, and a poll interval. Signing
C puts **one migration in V6-20's scope** — the existing D9 appendix requires that to be stated
explicitly — and keeps `queue:jobs` as a nudge only, so a Redis outage degrades
latency rather than delivery.

**8.2 Duplicate and loss rules: three classes.**

| Class | Types | Rule |
|---|---|---|
| **must not lose** (repeat-safe by their own key) | `ingest`, `retention`, `sitemap_scan`, `insights`, `topic_clusters` | At-least-once. A repeat is allowed and safe because each type's key makes it a no-op or a bounded refresh; a loss is not allowed beyond the attempt limit. |
| **must not duplicate a customer-visible send** | `digest` | At-least-once delivery, **at-most-once send per period per recipient**: a redelivery never re-sends a period, and a `sending` row that never confirmed is a detected, operator-resolved loss (8.7) rather than a duplicate. |
| **job types added later** | — | Default to *must not lose* and to the strictest class until the owner records otherwise. |

**8.3 Retry and terminal state — three profiles, not one table.** Bounded
attempts and backoff differ by what the job is for, then a terminal **`dead`**
state that only a replay clears:

| Profile | Types | Attempts and delays | Reason |
|---|---|---|---|
| **Interactive** | `ingest` | 6 attempts — the first, then **1 m, 5 m, 30 m, 2 h, 6 h**; 8 h 36 m end to end | someone is waiting on the crawl; the first retries are fast enough to ride out a provider blip, and the budget ends in under 9 h |
| **Periodic** | `retention`, `sitemap_scan`, `topic_clusters`, `insights` | 4 attempts — the first, then **1 m, 15 m, 2 h**; 2 h 16 m end to end | every one of these producers checks once every 24 h (`RETENTION_CHECK_SECONDS`, `SITEMAP_SCAN_INTERVAL_SECONDS`, `TOPIC_CLUSTER_INTERVAL_SECONDS` and `INSIGHT_INTERVAL_SECONDS` are all `86400`), so the whole budget sits inside one tick and the producer is a better retry clock than a fourth delay; further retries mostly spend provider credits on a cause no delay fixes |
| **Send** | `digest` | **1 attempt per job**; only the recipients still unsatisfied are retried at the next `digest_hour` (8.7) — whether a stopped job blocks that retry is the open point at the end of 8.7 | a retry at +2 h or +6 h can cross the send hour and deliver a stale weekly report at an odd time |

The numbers are tied to alerting rather than invented: on every profile a
deterministic failure trips **`JOB_FAILURE_ALERT_COUNT` (3)** inside
**`JOB_FAILURE_WINDOW_SECONDS` (60 min)** — the third failure lands at 6 min on
the interactive profile and 16 min on the periodic one — so an operator is paged
during the first retry cycle rather than after the tail. Each profile also ends
inside a day, and the shortest producer tick is 24 h, so no budget outlives its
own producer.

**`topic_clusters`: neither clock changes, because one of them was reported
wrong.** An earlier draft of this section said the type's producer runs every
30 min, so a tick lands inside a retry cycle. Both halves fail on inspection.
`TOPIC_CLUSTER_INTERVAL_SECONDS` is `86400` (`core/config.py:140–142`); the
second enqueue path, `enqueue_due_digests`, queues the week's clusters just
before the digest that reports them, but only when `now.hour` is the company's
`digest_hour` (`worker.py`), which the hourly loop reaches once a day — so that
path is daily too. The 30 minutes is `topics.STALE_RUN_AFTER`
(`services/topics.py:70`), the age at which a `running` claim is taken over: a
recovery clock, not a producer cadence. Each producer is 24 h from its own
previous tick, and the 2 h 16 m budget fits inside that with 21 h 44 m to spare.

Two *different* daily producers can still fall inside 2 h 16 m of each other —
`topic_loop`'s phase comes from when the worker started, the digest-hour path
from the company's hour — and no retry budget can rule that out: the gap can be
anything from 0 to 24 h, so the only budget change that would is shrinking it
towards zero, which is not a retry policy. So the exclusion moves out of the
clocks and into the record: the producer's insert conflicts with **any live row
for the key** — `queued`, `processing` or `dead` — not only a `dead` one (§6), so
a tick that lands inside a retry cycle writes nothing and the retry stays the
job's. The 24 h cadence, the `digest_hour` ordering and both budgets are
unchanged.

A reaper returns a row whose lease is older than **30 min**, and a handler
renews its lease while it runs: the interactive budget ends at 8 h 36 m and the
periodic one at 2 h 16 m, both well past the lease. All numbers are proposals;
the signature fixes them.

**8.4 Producer suppression: the attempt budget survives the producer.** Bounded
attempts bound a *job*, not the *work*. `enqueue_due_insights`,
`enqueue_due_digests` and the retention loop create a fresh job with
`attempt: 0` on their next tick (`worker.py:1049–1054`), so without a rule a
poison job still repeats every interval — exactly the behaviour scenario 6 is
meant to rule out. The rule: **a live row blocks a new job for the same key** — `queued`,
`processing` or `dead` (`type` plus its natural key, for example `company_id`
and `period_start`). The producer's insert conflicts with the live row, writes
nothing, and increments a `queue.suppressed` counter (on `GET /api/ops/status`,
and one log line per key at most once per tick), so a tick that lands inside a
retry cycle cannot start a second run (8.3). A `dead` row is cleared only by a
replay (8.6), so a deterministic failure costs one dead row and one provider
call, not one per tick. A row waiting on its backoff or its lease blocks its key
the same way, which puts the queue's health on `queue.suppressed` beside queue
age: a worker that stopped picking up `queued` rows shows there as suppression,
not as a growing list. If the owner
prefers automatic recovery over operator attention, the alternative is to carry
the budget instead: a suppressed tick may push `not_before` forward on the dead
row — a slow retry — but may not reset `attempt` to 0. Recommended: the dead row
suppresses, and the operator escalates. Cost: a partial unique index, the six
producer call sites, the counter and 4–6 tests, already inside C's judgement-based effort range.

**A recovery moves the row; it never inserts a second one — so no path needs a
carve-out.** The index constrains inserts, and every repair path is a transition
on the row it is repairing, which the index never sees. Naming each path, because
today all three re-enqueue:

- **The reaper is the job-level recovery**, and suppression is not in its way:
  `processing` with a lease past `now` → `queued`, lease cleared, `attempt`
  unchanged, one `UPDATE` on that same row. A dead process's row is the row that
  gets revived — which is precisely why a second insert cannot be the mechanism.
- **`requeue_stuck_ingests`** (§2) keeps its work-level half — `ingest_status`
  `processing → failed` past `STUCK_INGEST_AFTER` (6 h) — and loses
  `enqueue_job`: when a row exists for that website it re-arms it
  (`state='queued'`, `not_before=now`, `attempt` preserved) immediately after the
  claim flip commits — the two-commit window §6 names — and inserts only when the
  key has no row at all — after this section, only a claim left by a pre-D9 process. A `dead` row
  is **not** re-armed here; it belongs to 8.6.
- **The digest re-arm** in `enqueue_due_digests` (`period_settled` false because
  the claim is older than `DIGEST_CHECK_SECONDS`) is the same transition with
  `type='digest'` and the period as the key. It is what makes 8.3's "the
  unsatisfied recipients go out at the next `digest_hour`" true for a period
  whose job **completed** with rows still `pending`; a period whose job is
  `dead` is 8.6's, under whichever reading §12 signs.
- **`recover_stale_runs`** (`services/topics.py`) keeps flipping a dead
  `running` claim to `failed`; the tick then re-arms that window's job row, and
  the job's own `claim_run` takes the `failed` run over in place. The run row
  stays the work's claim, the job row the delivery's.

A re-arm preserves `attempt` and does not increment `queue.suppressed` — it did
not insert, and it resumes the same budget; only an insert conflict is counted.
What this rules out is the competing repair: a second row for the same key,
which would let one row's reaper and another row's producer run the work twice
and would make the one-live-row guarantee unenforceable. One consequence outside
the loops: `POST /api/ingest` and `/api/v1/ingest` claim
`websites.ingest_status` first, which cannot see a `dead` job row for that
website, so those routes must answer from the insert conflict instead of
reporting the crawl as accepted.

**8.5 Visibility.** The `dead` row is the dead letter: readable by an operator
CLI, counted on `GET /api/ops/status` (queued, processing, dead, oldest queued
age), never exposed through a tenant route. Retention follows the existing
delivery rule (`DELIVERY_RETENTION_DAYS`, 30 days) through the existing batched
purge; the payload column carries ids and parameters only.

**`digest_recipients` holds addresses, so it carries its own rule — the delivery
record's, not a new one.**

- **While actionable.** `recipient` is stored in plaintext only in `pending` and
  `sending`: the states in which the message still has to go out, and the only
  state an operator replay (8.6) may resend from.
- **On settle.** The address is cleared in the same transaction that stamps the
  row `sent`. Nothing downstream needs it — a settled period is never retried,
  and 8.7 already forbids re-sending a `sending` row automatically — while
  `company_id`, `period_start`, `state`, `attempt` and `last_error` stay for the
  counters and the audit.
- **Expiry.** Rows in every state are deleted past `DELIVERY_RETENTION_DAYS`
  (default 30, `core/config.py`) through the existing batched purge
  (`retention.delete_in_batches`), the same setting and path
  `integration_deliveries` already uses: no new key, no second clock. A `sending`
  row therefore has a 30-day replay window and no longer, which is what keeps a
  detected loss an operational fact with an end date.
- **Never in a log or a payload.** One line per period carries counts by state,
  never an address; `last_error` stores the provider's failure class after the
  V6-22 redactor, so an address a provider echoes back cannot land in the row or
  the log.
- **Access.** No tenant route reads the table; the operator replay CLI (8.6) is
  its only reader, and it reads a `sending` row.

**8.6 Replay authority.** Operator-only, out of band — no HTTP route.
`scripts/jobs.py replay --job-id …` (and `dead --limit`) from a host holding the
database URL; it resets the row to `queued` with `attempt` preserved and writes
one `platform_audit_logs` row (actor label, job id, type, previous state) through
the existing writer. The producer tick stays the fallback for a lost wake-up.

**8.7 Two handler fixes V6-20 must carry — and one point they leave open, because
delivery alone does not close them.**

- **`ingest` must consult `claim_ingest`.** Otherwise a re-delivery re-crawls
  and re-embeds while another worker may be crawling the same site, and scenario
  4 cannot pass for that type.
- **`digest` sends per recipient, and the row is stamped before the send.**
  Two changes, not one. Each recipient of a period gets a row in a new
  `digest_recipients` table (`company_id`, `period_start`, recipient, `state`,
  `attempt`, `last_error`); the row moves `pending → sending` **before** the
  SMTP call and `sending → sent` once the server accepts it. That closes the
  partial-send gap (only the unsatisfied recipients are retried at the next
  `digest_hour`) and it fixes the duplicate window by choosing which residual to
  keep: a crash after the server accepted leaves the row stuck in `sending`, and
  it is **never automatically re-sent**. `digest.send_unknown` counts it and an
  operator replays that one recipient (8.6, audited). The residual is therefore
  a **detected, operator-resolved non-delivery of at most the recipient whose
  row never left `sending`**, not a duplicate email — which is what the class in 8.2 requires.
  SMTP still has no idempotency key, so the opposite residual (at-least-once
  email with a counted duplicate) stays available only as an explicit class
  downgrade in the signature — not recommended, because a duplicate is
  customer-visible and unfixable after the fact, while a detected loss is both
  visible and correctable.

**The open point: what a stopped `digest` job does to the rest of its period.**
8.3 promises the recipients still unsatisfied are retried at the next
`digest_hour`; 8.4 makes a `dead` row block a new job for the same key, and a
`digest` key includes `period_start`; this section gives `digest` one attempt per
job. Read together they admit two readings, and nothing in the three sections
picks one:

- **A — 8.4 wins.** The one attempt ends in `dead`, so every later enqueue for
  that period conflicts and is suppressed, and the unsatisfied recipients go out
  only after an operator replay (8.6). 8.3's sentence then holds only for a job
  that *completed* with rows still `pending` — which requires that a
  recipient-level send failure is recorded on its row and does not end the job,
  a rule none of the three sections states today.
- **B — 8.3 wins.** `digest` is an explicit exception to 8.4 for its own period:
  a suppressed tick may still enqueue that period with `not_before` moved forward
  on the already-spent job attempt, and the recipient rows bound the repeats
  because each is sent at most once. Suppression then still stops a poison
  periodic job, but not the tick that exists to finish a partial send.

Both keep the customer-visible guarantee — neither re-sends a recipient whose row
is `sending` — and they differ in who finishes the period: the operator, or the
next tick. **A is recommended**, because the dead row is what the operator and
the counters see, whereas B's automatic finish is up to 24 h later and only
while that week is still the producer's `previous_period` — a period that has
rolled is not re-enqueued by any tick, so B falls back to the operator anyway,
later and without a dead row to page on. The `digest` retry row in §12 carries
the choice.

## 9. Evidence V6-20 and gate V6-2G box 1 need, per option

| Scenario (per job type) | A | B | C |
|---|---|---|---|
| 1 crash before the handler | ✗ nothing re-delivers | ✓ reaper returns the entry | ✓ lease expiry re-queues the row |
| 2 crash during the handler | ✗ | ✓ retry, partial state as documented | ✓ |
| 3 crash after an external send, before ack | ✗ | ✓ prevented per recipient by the same 8.7 stamp, **if** the record is durable; a Redis-only record can lose it (§12) | ✓ prevented per recipient: a `sending` row is never re-sent, the loss is detected (8.7) |
| 4 crash after the commit, before ack | ✗ | ✓ no-op by the type's key (needs 8.7 for `ingest`) | ✓ |
| 5 transient provider/DB failure | ✗ next tick only | ✓ approved backoff | ✓ |
| 6 poison job | ✗ repeats every tick | ✓ dead list (with producer suppression) | ✓ `dead` row + producer suppression (8.4) |
| 7 duplicate delivery | ✗ measured repeats | ✓ the job's own key; for `digest`, the recipient row (8.7) | ✓ the job's own key; for `digest`, the recipient row (8.7) |
| Operator procedure (replay + audit) | producer tick only, unaudited | Redis dead list + CLI | row + CLI + audit |
| Gate V6-2G box 1 | **not signable** | signable after the matrix | signable after the matrix |

Under **B or C**, V6-20's deliverable is: the seven-scenario matrix run per type
on disposable infrastructure, one row per type (command, output, timestamp,
commit) pasted into `plans/PLAN_V6.md` in the V6-40 table shape, the operator
procedure per type, and suite tests that pin the attempt counter, the terminal
state, the replay transition, a `dead` row suppressing its producer (8.4) and a
`sending` recipient row never being re-sent (8.7). Under **A**, the deliverable is a reworded
V6-20 plus a recorded R5 residual — a separate decision, not this one.

## 10. Cost summary

| | A | B | C (recommended) | D (not recommended) |
|---|---|---|---|---|
| Counted surface | one document | 11 call sites, 6 types, seam + 2 settings + 6 producer areas + 0–1 revision (`digest_recipients`, per §12) | + 1 revision, 2 tables, `job_queue`, 6 producer areas, `digest` record | C's surface, then a vendor account, credentials, emulator and second write path |
| Effort (judgement, not measured) | 1–2 days | 6–8 days | 11–15 days | 14–20 days |
| Migration | — | 0 or 1 (`digest_recipients`, per §12) | 1 (next revision, 2 tables) | 1 (the same record; the broker does not replace it) |
| New dependency | — | — | — | yes (vendor) |
| New settings | — | visibility timeout, max attempts | poll interval, visibility timeout, max attempts (retention reuses `DELIVERY_RETENTION_DAYS`; the suppression rule and the `digest_recipients` stamp add **no** key — they are a partial unique index and a table) | C's, plus endpoint, credentials and the dead-letter queue |
| Closes R5 | no | partly (Redis loss remains) | yes, with the `digest` residual 8.7 bounds | yes, through the record, not the broker |
| Closes V6-2G box 1 | no | yes | yes | yes, after the record work |

D is C's range shifted up, not a rival to it: **14–20 against 11–15**, because
the vendor path is added to the record work rather than substituted for it. It
is in this table only so the comparison cannot be read as "D is cheaper"; §7
gives the verdict against it.

## 11. What this brief does not do

- It implements nothing and changes no flag, queue, handler or schema.
- It does not tick V6-20 or gate V6-2G box 1: those need the matrix run after
  the signature, on disposable infrastructure.
- It does not choose `digest`'s class for the owner beyond the recommendation:
  8.7 keeps the strict class by stamping before the send and accepting a
  detected loss; signing the duplicate instead would be an explicit downgrade.
- It does not decide where B's per-recipient `digest` record lives: §5 states
  both branches and the `digest_recipients` row in §12 asks the owner to pick.
- It does not choose between the two readings of `digest` retries against
  suppression (the end of 8.7): it recommends reading A, and the `digest` retry
  row in §12 settles it.
- It does not authorise a production change: V6-20 is a Wave 2 task and this
  launch gate (V6-5G) is unrelated to it.

## 12. Signature

**What is still open, row by row.** Ten decisions and three fields. "Gates"
names what cannot proceed without that answer; V6-20 starts only once the whole
row is signed, and box 1 of gate V6-2G cannot be signed before V6-20's matrix
runs, whatever is chosen here.

| Row | Recommended | If you choose otherwise | Gates |
|---|---|---|---|
| Mechanism | C, durable job record | **B**: same at-most-once `digest` and the same seven scenarios, but the queued and in-flight work stay on one Redis, so R5 stays half-closed and a flush can still lose a `sending` stamp unless B also takes the table. **A**: V6-20 is reworded and R5 becomes a launch residual; box 1 stays unsignable | V6-20 start · box 1 |
| Duplicate/loss rule | three classes (8.2) | one rule: `digest` loses its at-most-once send and §9's scenarios 3 and 7 can no longer be claimed per type. Six answers: no default for job types added later | box 1 |
| Retry | per-class (8.3): `ingest` 6 attempts / 8 h 36 m, periodic 4 / 2 h 16 m, `digest` 1 per period | one table for every type: either `ingest` waits on a clock sized for a weekly job, or `digest` retries across its send hour and mails a stale week at an odd time | box 1 · V6-20 Done-when |
| `digest` retry vs suppression | **A** — the dead period waits for a replay, and a recipient-level failure is written on its row without ending the job | **B**: the next `digest_hour` finishes the period by itself, but that is up to 24 h later and only while the week is still the "previous" one; it also needs an exception to 8.4 and a second way into a send | box 1 · V6-20 Done-when |
| Producer suppression | a live row blocks the key, and recoveries re-arm that row (8.4) | only `dead` blocks: a tick inside a retry cycle starts a second run, one extra provider call per daily tick. Carry the budget: no operator step, slower recovery. None: repeats every tick, scenario 6 fails | box 1 |
| Visibility | `dead` rows + ops counters + 30-day purge; address cleared at `sent` | keeping addresses after settle widens what a dump exposes for no operational gain; a shorter window undercuts the purge rule `integration_deliveries` already uses | box 1 · V6-20 Done-when |
| Replay | operator CLI + `platform_audit_logs` | an HTTP route needs auth and scoping this replay has no use for; no audit row leaves no record of who resent a period | box 1 · V6-20 Done-when |
| `digest` duplicate | stamp `sending` before the send + per-recipient row (detected loss) | accepting duplicates is customer-visible and unfixable afterwards; there is no guard to sign instead, because SMTP has no idempotency key | box 1 · V6-20 Done-when |
| `digest_recipients` under B | the same PostgreSQL table | Redis keys only: B stays schema-free, but a flush resurrects a `sending` recipient as a duplicate email | only if B is signed |
| Migration in V6-20 scope | yes — 2 tables | "not applicable" is honest only if B runs its per-recipient record in Redis; otherwise V6-20 ships without the record the rest of this brief is built on | V6-20 scope |
| Approver / role, Date, Evidence link | fill in | a signature with no evidence link cannot be checked by the next reader | closes D9 |

To sign, record on this row (and copy into `plans/PLAN_V6.md` §4 and
[risk R5](risk-register-v6.md#r5)):

| Field | Value |
|---|---|
| Mechanism | ☐ C durable job record (recommended — accepts §6's one-commit claim/record window, bounded by the claim's own takeover) ☐ B Redis ack list ☐ A status quo + reword V6-20 |
| Duplicate/loss rule | ☐ three classes as in 8.2 (recommended) ☐ one rule ☐ six answers |
| Retry | ☐ per-class (recommended): `ingest` 6 attempts (first + 1 m / 5 m / 30 m / 2 h / 6 h, 8 h 36 m), periodic 4 attempts (first + 1 m / 15 m / 2 h, 2 h 16 m) against a 24 h producer tick, `digest` 1 per period, then `dead` ☐ other: |
| `digest` retry vs suppression (8.3 × 8.4, open point at the end of 8.7) | ☐ A (recommended): a `dead` period waits for replay, and a recipient-level failure is recorded on its row without ending the job ☐ B: `digest` is exempt from suppression for its own period, so the next `digest_hour` re-enqueues with `not_before` advanced ☐ other: |
| Producer suppression | ☐ a live row (`queued`, `processing` or `dead`) blocks a new job for the same key until it settles or is replayed, and every recovery re-arms that row instead of inserting (recommended — this is also what keeps a tick out of a retry cycle, 8.3) ☐ only a `dead` row blocks ☐ carry the attempt budget across re-enqueues ☐ none (repeats every tick) |
| Visibility | ☐ `dead` rows + ops counters + 30-day purge, `digest_recipients` cleared at `sent` (recommended) ☐ other: |
| Replay | ☐ operator CLI + `platform_audit_logs` (recommended) ☐ other: |
| `digest` duplicate | ☐ stamp `sending` before the send + per-recipient record (recommended: at-most-once per recipient, detected loss) ☐ accept and count duplicates (class downgrade) ☐ guard: |
| `digest_recipients` under B — only if B is signed | ☐ the same PostgreSQL table (recommended: a `sending` row has to survive a restart) ☐ Redis keys only, accepting that a Redis loss can re-send a `sending` recipient ☐ not applicable (C signed) |
| Migration in V6-20 scope | ☐ yes — C's record, or B's if the row above chooses the table ☐ not applicable |
| Approver / role | |
| Date | |
| Evidence link | |

Until that row is filled, D9 stays **UNAPPROVED**, V6-20 stays blocked, and R5
stays open with its owner recorded.
