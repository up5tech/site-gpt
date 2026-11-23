# V6 pre-flight decision and owner record

| | |
|---|---|
| Status | **Draft, and every decision below is UNAPPROVED.** No approver, date or evidence has been recorded for any row. |
| Scope | The decisions `plans/PLAN_V6.md` §4 marks as blocking for Wave 0 and Wave 1: D1/D3/D7/D11 (launch scope, operations, data handling, support) and D2/D4/D5/D6/D8/D13 (topology, security profile, operator authentication, uploads, telemetry, session/embed posture). |
| Snapshot | `master` at `66dd197`, branch `feat/v6` (2026-11-23), Alembic head `0b22b30bf930`. |
| Rule | A proposed default, an engineering preference or this document is **not** an approval. An approval exists only when a named approver, a date and the evidence are recorded in the row. |

This record decides nothing. It contains no invented SLO, RPO/RTO, price, region,
customer commitment or owner: an empty cell is the finding, and those empty cells
are why gate V6-0G is unsigned and Wave 1 has not started.

## Decisions

| ID | Question | Who must approve | Evidence needed before approval | Status |
|---|---|---|---|---|
| **D1** | Track A (hosted core, billing off), Track B (paid SaaS + operator console), or both? Which customer cohort, regions, data types, and is public registration open or invite-only? | Product/business owner — **not yet named** | A signed scope statement naming the track, cohort, regions, data categories and registration mode, plus whether an empty public plan catalog is acceptable for that launch. | **UNAPPROVED** — no approver recorded. Blocks V6-01/V6-02. |
| **D2** | What hosting/runtime topology: API, worker, Postgres/pgvector, Redis, upload storage, frontend/CDN, TLS termination, network boundaries, deploy and rollback mechanism? | Infrastructure/deployment owner with the engineering lead — **not yet named** | A topology description or diagram covering each component and whether it is self-managed or a managed service, the network boundaries, and the deploy/rollback mechanism, accepted by the owner who will operate it. | **UNAPPROVED** — no approver recorded. Blocks V6-02/V6-10/V6-40. |
| **D3** | What availability/support promise applies, with which measurable SLOs, database/upload RPO and RTO, capacity assumptions and maintenance window? | Business owner for the promise, operations for the recovery targets — **not yet named** | An approved service statement and recovery objectives expressed as measurable targets, with the assumptions they rest on. Engineering supplies measurements; it does not set these numbers. | **UNAPPROVED** — no approver recorded. Blocks V6-02/V6-21/V6-42. |
| **D4** | What is the production security profile: secret/config policy, trusted proxy addresses, exact CORS origins, rate-limit backend, docs exposure, environment separation? | Security owner with engineering — **not yet named** | An inventory of the required settings for the chosen environment, each with its source (secret store, environment, config), approved by the security owner against the actual ingress, not a template. | **UNAPPROVED** — no approver recorded. Blocks V6-02/V6-10. |
| **D5** | Which enforceable control protects platform-owner access: MFA/SSO, or a private operator-only network? Who owns bootstrap, recovery and revocation? | Security owner with the operator — **not yet named** | The selected control, proof it is enforced at the ingress (not only in the application), the named bootstrap/recovery/revocation owner, and a recorded exercise of emergency disable. | **UNAPPROVED** — no approver recorded. Blocks V6-02 and any platform-console exposure (V6-11). |
| **D6** | What is the upload policy for untrusted files: approved scanner/vendor, supported formats and size limits, quarantine behaviour, scanner-outage behaviour — or is the upload surface restricted/disabled? | Security owner with product owner — **not yet named** | The approved policy for each case (malicious file, unsupported type, scanner unavailable, oversize), or a signed decision to restrict or disable uploads for the launch cohort. | **UNAPPROVED** — no approver recorded. Blocks V6-13. |
| **D7** | What data handling applies: retention defaults, audit retention, backup expiry, and deletion/restore semantics for users, companies and backups? | Privacy/legal owner — **not yet named** | The approved retention and deletion rules including how backups are handled, the audit-retention period, and the owner who answers data-subject requests. | **UNAPPROVED** — no approver recorded. Blocks V6-41/V6-42 (and V6-14/V6-15 where they touch retention). |
| **D8** | Which logs, error tracking, metrics and alerting are used; what data goes to which vendor; what is redacted; who has access and for how long? | Security/privacy owner with engineering — **not yet named** | The chosen tools (or an explicit decision to defer), the exact data each receives, the redaction rules, and access/retention terms approved by the privacy owner. | **UNAPPROVED** — no approver recorded. Blocks V6-21/V6-22. |
| **D11** | Who owns customer support, through which channel, with what coverage window, escalation target and response expectation? | Support owner (business) — **not yet named** | A named owner, contact channel, coverage window, escalation path and response expectation that the owner accepts — no engineering default promoted into a promise. | **UNAPPROVED** — no approver recorded. Blocks V6-02/V6-41. |
| **D13** | Are tenant MFA/SSO, broader admin audit, a session-revocation UI and origin-bound widget authentication required for this cohort, or explicitly deferred? | Security owner with product owner — **not yet named** | An explicit require/defer decision per item with rationale, affected tasks and — for deferrals — the accepted residual risk and an expiry or review date. | **UNAPPROVED** — no approver recorded. Blocks V6-12/V6-14/V6-15. |

## Decision register — one page to sign

An index of the ten decisions in this record: each question in a line, the risk rows it moves, and a sign-off slot in the same row. The options, their consequences and the exact evidence an approver must supply are in that row's appendix below; nothing here restates, narrows or recommends them, and an empty sign-off cell is not an approval. D9 (background-job delivery), D10 (CI and browser execution) and D12 (Track B commercial readiness) are deliberately absent: they have no appendix here and block later tasks or apply only to Track B.

| ID | Question | Status | Risk rows | Approver | Role | Date | Evidence path |
|---|---|---|---|---|---|---|---|
| **D1** | Which launch track, cohort, regions, data types and registration mode? | **UNAPPROVED** | R3 |  |  |  |  |
| **D2** | Which hosting/runtime topology, network boundaries and deploy/rollback mechanism? | **UNAPPROVED** | R4, R6, R8 |  |  |  |  |
| **D3** | Which availability/support promise, SLOs, RPO/RTO and capacity assumptions? | **UNAPPROVED** | R4, R6, R8 |  |  |  |  |
| **D4** | Which production security profile — secrets/config, proxy trust, CORS, limiter backend, docs exposure? | **UNAPPROVED** | R1 |  |  |  |  |
| **D5** | Which enforceable control protects platform-owner access, and who owns bootstrap, recovery and revocation? | **UNAPPROVED** | R2 |  |  |  |  |
| **D6** | Which upload policy for untrusted files — scanning, formats, quarantine, outage behaviour — or restriction/disablement? | **UNAPPROVED** | R9 |  |  |  |  |
| **D7** | Which retention, audit-retention, backup-expiry and deletion semantics, and which privacy/legal owner? | **UNAPPROVED** | R8, R10 |  |  |  |  |
| **D8** | Which logs, error tracking, metrics and alerting; what reaches which vendor; redaction, access and retention? | **UNAPPROVED** | R6 |  |  |  |  |
| **D11** | Who owns customer support, through which channel, with what coverage, escalation and response expectation? | **UNAPPROVED** | R4 |  |  |  |  |
| **D13** | Are tenant MFA/SSO, broader admin audit, a session-revocation UI and origin-bound widget auth required or deferred? | **UNAPPROVED** | R10, R11, R12 |  |  |  |  |

**Signing a row.** Put the approver's name, role and date in the row, put the evidence path or link in the last cell, and change the status cell from **UNAPPROVED** to **APPROVED**. Then copy the same four facts into `plans/PLAN_V6.md` §4 and into the risk rows named in the register, as “How an approval gets recorded” below describes. A row that is PROPOSED or BLOCKED stays unsigned, and no task whose decision is unsigned may start.

## Status vocabulary

- **UNAPPROVED** — no approver, date or evidence recorded. The state of every row today.
- **PROPOSED** — a candidate exists but no approver has accepted it. Still not an approval, and no dependent task may start.
- **BLOCKED** — an external party (merchant, legal, vendor, customer) has not supplied what the decision needs.
- **APPROVED** — approver named, date recorded, evidence linked. Only then may the dependent task start.

## What stays off while these are unapproved

- Gate V6-0G stays unsigned and Wave 1 does not start: no production-config validator (V6-10), no platform-console work (V6-11), no session, upload or audit work (V6-12…V6-15).
- `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false`; `/api/platform` remains a 404.
- No production deployment, no release tag, and no SLO, support promise or pricing statement is published.
- Wave 0's only completed task remains V6-04, whose baseline and gate evidence are recorded in `plans/PLAN_V6.md`.

## Out of scope of this record

D9 (background-job delivery), D10 (CI/browser execution) and D12 (Track B commercial and Stripe readiness) are listed in `plans/PLAN_V6.md` §4 and are not duplicated here; D12 applies only if Track B is chosen.

## How an approval gets recorded

1. The named approver supplies the decision, the date and the evidence (path or link) in the row.
2. The row's status changes from UNAPPROVED to APPROVED, and the same facts are copied into `plans/PLAN_V6.md` §4.
3. Only then may the dependent task start; a task whose dependency is PROPOSED or BLOCKED stays unticked.

## Appendix — D1 decision brief

**Status: D1 remains UNAPPROVED.** This appendix sets out the choice; it does not make it, and it supplies no cohort, region, price or customer commitment.

### The question

Which launch is being approved — **Track A** (hosted core, billing and platform console off), **Track B** (paid SaaS plus the operator console), or **both** — and, for whichever is chosen: which customers, in which regions, with which data types, and with public registration open or invite-only? The answer decides whether V6-01 has a scope to record, and whether gate V6-6G (paid activation) is in scope at all.

### Options and consequences

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — hosted core, billing off** | `plans/PLAN_V6.md` §3's Track A: the approved core product, launched to a controlled cohort, with `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false`. | Gate **V6-5G** is the only launch gate; V6-6G does not apply. No Stripe merchant account, plan catalog, price, refund/trial policy or billing legal copy is needed. The public pricing surface renders its being-finalised state, so the approver must accept that state for the cohort or approve content before launch. V5's commercial decisions (D2–D12) stay open; enabling billing later is a separate authorized change with its own gate and a decision about existing companies. Core support, privacy and retention content is still required (D7/D11, V6-41). |
| **B — paid SaaS and platform operations** | Track B: the core launch plus self-serve paid plans and the operator console. | Requires everything in A **and** the V5 prerequisites: an approved catalog/limits/terms set, legal and support copy, a merchant account with test-mode access, a real Stripe test-mode rehearsal, and the D5 control actually enforced at the ingress before the console is exposed. Gate **V6-6G** must pass independently of V6-5G, and live activation is a separate staged change with monitoring, abort thresholds and a rollback owner. This is the longest path to any launch, because core and commercial readiness must both land. |
| **Both — core first, paid later** | Approve Track A now and Track B as a later, separately gated step. | The core launch is not held behind commercial work, but there are two go/no-go records, two sets of customer-facing promises to keep consistent, and a decision about whether the first cohort is grandfathered or price-protected when paid plans go live. The pricing-state question from A must still be answered for the first cohort, and B's prerequisites still apply before any payment. |

### Exact evidence an approver must sign

1. The track chosen, stated explicitly (A, B, or both, with the order).
2. The cohort: who is invited, roughly how many, and whether it is internal, beta or external — supplied by the approver.
3. Registration policy: open or invite-only, and how an invitation is issued.
4. The regions where data is stored and processed, and the data types accepted, listed per category (for example chat transcripts, uploaded files, contact details).
5. The included features, and the features or flags that stay off at launch.
6. For the cohort's pricing surface: accept the empty-catalog being-finalised state, or approve plan content before launch (required for B or both).
7. For B or both: confirmation that each V5 decision has an owner, that the V6-6G conditions are accepted, and the named merchant-account owner and live-activation authority.
8. Sign-off on launch copy: no price, guarantee, SLO, certification or feature claim beyond the approved scope.
9. The approver's role, the date, and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R3 (the track a paid launch still waits on) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D1 row moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-01 and the scope half of V6-02. Gate V6-0G still needs D3, D7, D11 and the architecture decisions, so Wave 1 stays closed.

## Appendix — D3 decision brief

**Status: D3 remains UNAPPROVED.** This brief lays out the choices; it names no target, no coverage window, no recovery time and no owner. Every number in a real answer has to come from the approver.

### The question

What availability and support promise applies to this launch, expressed as measurable objectives — service levels, database and upload recovery points and times, capacity assumptions and a maintenance-window policy — and is any of it customer-facing or internal only? The answer fixes the numbers V6-21 alerts on and the targets V6-42's restore is measured against; without it both tasks can be built but not accepted.

### Options and their consequences

#### 1. Availability and support promise

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — no external promise** | The launch makes no customer-facing availability or support commitment; operation continues on a best-effort basis. | No remedy or credit obligation is created and no uptime evidence has to be published, but support expectations are undefined, so the launch copy and the support path must avoid implying a promise. Internal monitoring is still needed to notice an outage, and a later move to B or C becomes a customer-visible improvement. |
| **B — internal targets, public status only** | Engineering objectives are set and measured internally; customers get status communication (an incident notice or status page) but no contractual commitment. | Requires the measurement definitions in the evidence list, an alerting path, and a decision about where status is published. It creates an operational expectation without a remedy, so the wording of the status page and support replies must stay inside it. |
| **C — contractual availability and support commitment** | A customer-facing commitment with defined measurement, exclusions and remedies, plus a support response expectation. | Adds legal review, a remedies or credit policy, an incident and evidence trail that can be audited, and a support process that can be staffed continuously. It cannot be met by the application alone: third-party model, email and infrastructure dependencies have to be disclosed as exclusions or covered by the chosen topology. |

#### 2. Recovery objectives and backup shape (answered separately for the database and the upload volume)

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — backup and restore** | Periodic encrypted backups, restored into a fresh instance when needed. | The recovery point and recovery time are bounded by the backup interval and by how long a full restore takes; both have to be measured (V6-42), not estimated. Restoring to a point between backups is not possible. |
| **B — point-in-time recovery** | Backup plus continuous log shipping, allowing restore to a chosen moment. | Narrows the recovery point considerably, but requires the database configuration and the storage for logs, and the restore procedure is longer and has to be rehearsed rather than assumed. The upload volume needs its own answer, since it is not covered by database logs. |
| **C — standby or replicated copy** | A continuously replicated copy that can take over, plus backups for the remaining cases. | Shortest recovery time, highest operational cost and complexity: a failover procedure, split-brain and data-loss rules, and a rehearsal of failover and of fail-back. It presumes the topology choice in D2 and cannot be promised before D2 is decided. |

For uploads the same three options exist only in weaker forms — snapshot or object-store versioning, replication, or backup-and-restore — so the approver answers this dimension twice and the two answers may differ.

#### 3. Support coverage and channel

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one named contact, business hours** | A single owner and channel reaches an answer during a defined window. | Cheapest and adequate for a small cohort, but out-of-hours incidents wait, so the option only works if the availability promise in §1 is low or absent. |
| **B — shared channel with a rota and an escalation target** | A team inbox or chat with more than one responder and a named escalation. | Covers more hours and survives one person being away, but requires the rota and escalation path to be documented and tested; the response expectation has to be expressed in the same terms as §1. |
| **C — contracted continuous cover** | An on-call arrangement covering every hour the promise claims. | Only consistent with option C in §1; it needs staffing evidence, an escalation tree and a tested alert path, and it is a business commitment rather than an engineering configuration. |

#### 4. Maintenance window

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — announced window** | Changes happen in a window the approver picks, announced in advance. | Predictable and easy to communicate; it constrains when deploys and migrations may run and needs a notice channel. |
| **B — rolling changes, per-change approval** | No fixed window; each change is approved and executed individually. | More flexible, but every change needs a rollback plan and the availability promise must tolerate short interruptions; it also needs the incident and rollback runbooks to exist first. |
| **C — freeze for the first cohort** | No functional change during the initial period; only security fixes. | Lowest risk for a first cohort, at the cost of deferring fixes and features; the freeze has to have an end condition the approver states. |

### Exact evidence an approver must sign

1. The §1 option chosen, with the customer-facing wording if there is one, or an explicit statement that no external promise is made.
2. For each service level claimed: what counts as available, over which measurement window, measured from where, and who reads the result. The values themselves are supplied by the approver.
3. A recovery point and recovery time for the database **and** separately for the upload volume, plus who measures them and where the measurement is recorded.
4. The backup mechanism, its retention and expiry, and confirmation that a restore rehearsal is required before launch (the rehearsal itself is V6-42's evidence, not this signature).
5. Capacity assumptions the promise rests on: expected peak demand, provider rate limits and the headroom assumed in database, Redis and worker sizing — as supplied by business/operations, not derived by engineering.
6. The §4 maintenance-window policy, including the notice channel and the freeze end condition if option C is chosen.
7. The §3 support coverage: who answers, through which channel, in which hours, and the escalation target. (D11 names the support owner; this decision records the coverage the promise needs.)
8. The exclusions the promise relies on: which third-party dependencies, customer-side causes and events are outside it.
9. Where status and incidents are communicated, if the promise includes any.
10. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R4 (operational ownership), R6 (the alert thresholds) and R8 (the approved RPO/RTO) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D3 row moves from **UNAPPROVED** to **APPROVED**, which unblocks the objective half of V6-02 and gives V6-21 its alert thresholds and V6-42 its restore targets. Gate V6-0G still needs D1, D7, D11 and the architecture decisions, so Wave 1 stays closed.

## Appendix — D7 decision brief

**Status: D7 remains UNAPPROVED.** This brief lays out the choices; it supplies no retention period, audit period, backup window, deletion promise or owner.

### The question

What data-handling policy applies: the default retention for a company and its conversations, how long audit rows and backups live, and what deletion means for a user, a company and the data derived from them. The answer decides the privacy-notice wording in V6-41, what V6-42's restore is allowed to bring back, and whether the existing erasure endpoints and the retention worker keep their current behaviour.

### What the code does today (evidence, not a decision)

- Retention is **off unless a company opts in**: `retention_days` defaults to `0` (`api/setting.py:69`), and `retention.companies_with_policy` selects only companies above zero.
- A purge deletes `chat_messages`, `chat_feedback`, `handoff_requests`, `contacts`, `digest_log`, `conversations`, `attachments` rows plus their files, and expired `extra_documents` with their embeddings (`services/retention.py::purge_company`); the company admin can preview it with the dry-run `POST /api/privacy/retention`.
- Conversation erasure and contact erasure exist as endpoints (`api/privacy.py`), and an export is available before deletion.
- `platform_audit_logs` is append-only and **has no pruning path** in the code today.
- Backups are an operator responsibility; nothing in the application expires them, and a restore is not currently reconciled against deletions.

### Options and consequences

#### 1. Default retention for a new company

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — off by default (current behaviour)** | Every company starts with retention disabled and opts in per company. | No data is ever deleted by accident and no migration is needed, but personal data is kept indefinitely unless someone configures a policy, which is the largest privacy exposure of the three and has to be stated honestly in the notice. |
| **B — one default applied to every company** | New companies start with the approver's retention period and may adjust it within limits. | Data minimisation happens without a customer action, but the deletion is irreversible, so a period that is too aggressive destroys transcripts and knowledge customers may rely on; existing companies need an explicit grandfathering decision. |
| **C — default by plan or cohort** | Different starting periods per plan or cohort. | Aligns retention with commercial terms, but it requires the approved plan set (Track B) and makes the public notice, export and erasure copy conditional; mixing policies also complicates any later consolidation. |

#### 2. Audit retention

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — keep the audit log indefinitely** | The append-only `platform_audit_logs` is never pruned. | Best evidence for an incident investigation and the least engineering, but unbounded growth and a long-lived record of operator actions that the privacy notice must disclose. |
| **B — fixed expiry** | Audit rows older than the approved period are removed by a scheduled job. | Bounded storage and a shorter disclosure, but the job needs implementing (none exists), and an expiry that is too short can destroy the evidence of an incident that is still open — so the rule for an open investigation must be part of the decision. |
| **C — expiry by action class** | Security-relevant actions are kept longer than routine ones. | Preserves the evidence that matters while bounding volume, at the cost of a classification the code does not have today and a rule for reclassifying an action later. |

#### 3. Backup expiry and restore semantics

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — backups expire before the data would** | Backup retention is shorter than the data-retention period. | A deleted record leaves the backup estate quickly and the promise "deleted means deleted" is nearly true, but the recovery window is short and an incident older than the backup window cannot be investigated from backups. |
| **B — backups outlive retention, with restore reconciliation** | Backups are kept longer than the data, and a restore is followed by re-applying deletions. | Recovery stays strong, but a restore can resurrect erased data unless the re-deletion step is defined, owned and rehearsed — this is the option that requires the most evidence, not the least. |
| **C — long-term archive with restricted access** | A separate, tightly access-controlled archive kept beyond normal backups. | Supports legal or contractual holds, but adds an access-review obligation and a second place where deletion has to be enforced; it is only coherent if the deletion exceptions are written down. |

#### 4. Deletion of a user or a company

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — soft delete, then scheduled purge** | Deactivation first, physical removal on the retention schedule. | Mistakes are reversible and support can restore an account, but deletion is not immediate and the promise has to say so; a company with several users needs a rule for what one admin's action does to the others. |
| **B — immediate hard delete** | The request deletes the data at once. | Strongest promise and simplest copy, but it is irreversible, must still define what happens to billing records and audit rows, and cannot undo a wrong request. |
| **C — export-then-delete with a verification window** | The data is exported, then deleted after a window the approver sets. | Safer for account closure and gives the customer a record, but needs a cancel path, a status the customer can see, and a decision about what happens if the export fails. |

#### 5. Derived data and shared records

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — cascade everything derived** | Deleting the source also deletes embeddings, topic clusters, insight labels and delivery payloads. | Matches the current foreign-key cascades and needs no new job, but it removes analytics history along with the personal data and can change a company's reports retroactively. |
| **B — keep aggregates without content** | Counts and labels without transcript text survive. | Preserves reporting, but the claim that an aggregate is no longer personal data has to be justified per field and stated in the notice, and some labels (a summary of one conversation) are themselves content. |
| **C — bounded retention for derived data** | Derived rows expire on their own clock after the source is gone. | A middle path, at the cost of a second schedule and a rule for what a report shows once its derived rows have expired. |

### Exact evidence an approver must sign

1. The default retention for a new company (on or off, and the period if on), who may change it, and whether existing companies are migrated or left as they are.
2. A per-class deletion map: for transcripts, contact details, inbox state, feedback, handoffs, uploaded files and extracted text, embeddings, topic clusters, insight labels, integration delivery payloads, audit rows and billing records — deleted, kept, or aggregated.
3. The audit-retention period, who may read the log, and how expiry is executed and verified (noting that no pruning path exists in the code today).
4. Backup expiry, backup access control, and the restore-time rule for data deleted after the backup was taken — with evidence that the re-deletion step was practised, not just described.
5. The deletion path and actor for a user and for a company (tenant admin, support, platform owner), whether it is immediate or pending, and the evidence a customer receives.
6. The legal or contractual exceptions that outlive deletion, stated explicitly rather than implied.
7. The privacy-notice wording that matches the behaviour above (V6-41), with no promise the code cannot keep.
8. The owner and channel for data-subject requests and how they are recorded (adjacent to D11).
9. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R8 (backup expiry and restore) and R10 (audit retention) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D7 row moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-41 and the retention side of V6-42, and settles the retention questions inside V6-14 and V6-15. Gate V6-0G still needs D1, D3, D11 and the architecture decisions, so Wave 1 stays closed.

## Appendix — D11 decision brief

**Status: D11 remains UNAPPROVED.** This brief supplies no support owner, channel, coverage window, escalation target, response time or contact address. Every option below is a shape to choose, not a proposal.

### The question

Who answers a customer when the service is broken or unclear, through which channel, during what window, to whom it escalates, and what the customer may expect in return. The answer supplies the support details V6-41 must publish and the support-ownership half of V6-02, and it is a commitment the business makes, not an engineering setting.

D3 §3 chooses the **shape** of coverage (one named contact / a shared rota / contracted continuous cover). D11 names who operates it and records the mechanics. The two rows must agree: a D3 promise with no D11 owner is unstaffed, and a D11 window wider than D3's coverage is an unpriced commitment.

### What exists today (evidence, not a decision)

- There is **no support address configured**: `support_contact_email` is a typed platform setting whose default is `""` ("Leave blank to hide it") and whose value is published anonymously through `GET /api/public/config`; `PublicLayout` renders a `mailto:` link in the footer **only** when it is set. So an approved address needs no deploy — but today the footer shows nothing and no owner exists to read a message sent there.
- **No operator surface is live** to work a support queue: `PLATFORM_CONSOLE_ENABLED=false` makes the whole `/api/platform` surface a 404. `platform_audit_logs` records operator mutations and holds no customer conversation.
- **The inbox is not a support channel.** `/api/inbox` is the tenant's own live-agent console over that tenant's conversations; pointing service-level support traffic at it would expose one customer's transcripts to staff answering another.
- Nothing in the repo names a support owner, rota, paging tool or ticket system; `docs/release-v5.md` records support ownership as NO-GO and `docs/risk-register-v6.md` R4 lists named support and incident ownership as unevidenced.

### Options and consequences

#### 1. Who is accountable for support

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one named individual** | The accountable owner answers support themselves and is the only escalation entry point. | Cheapest and clearest to publish, but coverage ends whenever that person sleeps, travels or leaves, and there is no second reader for a security-sensitive report; the row must name a deputy or state the gap. |
| **B — a named internal rota** | Several named staff share a queue under one accountable owner. | Load is spread and absence is covered, but it needs a shared queue, a written handover and defined shifts — otherwise "the rota" is a mailing list where each assumes another answered. |
| **C — contracted external provider** | A support vendor answers first line under a contract. | Cover can be wider than the team's own hours, at the cost of a contract, onboarding material and a written boundary for what the vendor may not decide; customer conversations reach a third party, so D7's deletion map and D8's vendor terms must cover it before it handles a single message. |

#### 2. Channel

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one email alias** | A published address that forwards to the owner. | Zero infrastructure and works for a signed-out customer, but gives no status, no assignment and no history beyond a mailbox, and a message can sit unseen with nobody able to prove when it arrived. |
| **B — a ticketing or shared-inbox tool** | Requests land in a queue with assignment and state. | Makes ownership and response measurable, but adds a vendor that stores customer data and an access list that has to be reviewed; it is only as good as the rota behind it. |
| **C — an in-app contact form plus email fallback** | A form inside the product feeds the queue, with the published address for everyone else. | Best context (the tenant, the page, the error) and a natural place to state the coverage window, but it needs a route, a table and abuse handling that do not exist today, and a customer who cannot sign in still needs the fallback. |

#### 3. Coverage window

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — business hours on stated days** | A published window in a stated timezone, with everything else queued. | Sustainable for a small team and honest if published, but an outage outside the window is answered the next working day, which must be said plainly on the site and in the notice. |
| **B — extended hours with an on-call rotation** | Longer daily coverage plus a paged on-call engineer. | Covers most customer working days, but needs a roster, a paging tool, a compensation decision and a rule for who is woken for what; an on-call that is never exercised is not coverage. |
| **C — continuous cover** | Somebody is reachable at every hour. | Matches an "always available" product claim, but requires follow-the-sun staffing or an external provider under contract, and it must not be published before it is actually staffed. |

#### 4. Escalation target and path

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — single tier** | The support owner handles everything and asks engineering informally when stuck. | Simplest to start, but no bound applies when the owner cannot solve it and no engineer is accountable for the answer; an incident then has no named owner. |
| **B — support owner then on-call engineer** | A written trigger moves a request to a named on-call engineer, with a named incident owner. | Bounds the answer and gives incidents an owner, but needs the trigger written down (what cannot be resolved from the runbook), a roster, and a hand-back rule so the on-call is not the permanent owner. |
| **C — three tiers adding business, security and legal** | On top of B, a named path for a suspected breach, a legal or contractual question and a payment dispute. | Required if the service handles personal data or paid subscriptions, but every tier must name a person and a contact method; a path that ends at "the founders" is not an escalation target. |

#### 5. Response expectations

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — acknowledgement only** | The customer is told the request arrived; no time to a substantive answer. | Honest and cheap, and it is the only option that cannot be broken by a small team, but it gives the customer nothing to plan around and reads as thin beside a paid plan. |
| **B — acknowledgement plus per-severity response targets** | Severity classes (service down / degraded / question) each get a target time to first substantive response. | Useful and publishable, but it needs severity definitions the customer can apply, and the target only holds if the coverage window can actually meet it; a target inside a window nobody staffs is a false promise. |
| **C — response plus resolution targets tied to D3** | Resolution commitments per severity, aligned with D3's availability promise. | Strongest commercial position, but it overlaps D3 and must be approved by the same owner with the same numbers — two documents promising different things is worse than one modest promise, and a resolution commitment carries commercial weight. |

### Cross-checks an approval must satisfy

- **D3 §3 must match the D11 window.** If the availability statement promises cover the support row does not staff, the published sentence is the one that binds; correct the other row rather than reinterpreting it.
- **Support access to tenant data is a data grant.** Whatever the channel stores — a ticket with a transcript attached, a mailbox, a vendor portal — falls under D7's deletion rules and D8's access and retention terms; support staff reading a tenant's conversations need that access named and audited.
- **A third-party channel adds a subprocessor** to V6-41's list, with its DPA and retention period, before the first customer message arrives.
- **The published address is a setting, not a deploy:** the approved address goes into `platform_settings.support_contact_email` (public, footer-visible) and the same text appears in the app and the privacy notice.

### Exact evidence an approver must sign

1. The accountable support owner, by name, with a named deputy for absence — and the owner's acceptance of the role.
2. The channel: exact address or URL, who monitors it, and what the customer sees before anyone answers.
3. The coverage window: days, hours and timezone, and the stated behaviour outside it (queued with an acknowledgement, or explicitly not covered).
4. The escalation path: the trigger, the next tier by name, the contact or paging method, and the named incident owner for a service-down event.
5. The response expectations per severity class, with the severity definitions and confirmation that the approved window can meet them.
6. The support-side data access: which staff or vendor may read which tenant data, through which tool, and how that access is audited.
7. The exact published text for the marketing footer, the app and the privacy notice, containing no promise the owner has not accepted.
8. The value to set in `platform_settings.support_contact_email`, and the person who maintains it; until it is set the footer correctly shows no address.
9. The approver's role, date and evidence path — recorded in the D11 row, copied into `plans/PLAN_V6.md` §4 and into risk R4 (named support and incident ownership) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D11 row moves from **UNAPPROVED** to **APPROVED**, which supplies the support details V6-41 publishes and the support-ownership half of V6-02. Gate V6-0G still needs D1, D3, D7 and the architecture decisions, so Wave 1 stays closed.

## Appendix — D2 decision brief

**Status: D2 remains UNAPPROVED.** This brief lays out the hosting, network, deploy and rollback choices; it names no provider, region, instance size, hostname, certificate issuer or operator, and it recommends none of the options.

### The question

Which runtime shape runs this application in production: where the API process, the worker process, PostgreSQL with pgvector, Redis and the uploaded bytes live, what terminates TLS, what is reachable from the public internet and what is not, and how a change is deployed — and undone — so that V6-10's production-config validator and V6-40's deploy/rollback runbook have a concrete target. D2 is not a vendor choice by itself; it is the set of properties a vendor or a self-hosted arrangement has to satisfy.

### What the code requires today (evidence, not a decision)

- **Three runtime units, not one.** The API is the FastAPI app in `main.py` served by an ASGI server; the worker is a separate process (`python -m site_gpt.app.worker`) that consumes `queue:jobs`; the admin UI is a Vite build (`frontend/`) whose `VITE_BACKEND_URL` is baked in at build time. The API and the worker share `DATABASE_URL`, `REDIS_*`, `MAIL_*` and the model-provider keys, and the worker has no HTTP ingress of its own.
- **PostgreSQL must carry pgvector.** The initial migration runs `CREATE EXTENSION IF NOT EXISTS vector`, RAG uses the `<->` operator, and embeddings are `Vector(EMBEDDING_DIMENSIONS)` (default 1536). The chain is linear with a single head, `0b22b30bf930`, applied out of band with `uv run alembic upgrade head`.
- **Redis is on the request path, not only behind the worker.** The queue is `LPUSH queue:jobs` / `BRPOP` (`services/redis.py`, `worker.py`); `RATE_LIMIT_BACKEND=redis` shares the per-IP limiter across processes; the per-session and daily message caps are Redis counters that fail open on an outage; the inbox stream and presence leases are Redis pub/sub and keys. With Redis unreachable the worker consumes nothing and the inbox degrades, even though chat keeps answering until a cap check fails open.
- **Uploaded bytes live on the local filesystem.** `api/upload.py` writes under `uploads/` relative to the process working directory, `services/retention.py::UPLOAD_ROOT` unlinks from the same place, and **no route serves those files** — there is no object-storage adapter and no static mount.
- **The API origin is public and serves the widget surface.** `/widget.js` is a `FileResponse` from `./src/site_gpt/app/scripts/widget.js` (a path relative to the working directory, versioned by a content hash query), `GET /chat/{website_id}` returns the hosted page, and `/api/widget-config` serves embeds — so the API must be reachable from customer sites, not just from the admin app.
- **The app never terminates TLS.** `README.md` §2 requires a TLS-terminating proxy, forwards `Host`/`X-Forwarded-For`/`X-Forwarded-Proto`, lists public proxy addresses in `TRUSTED_PROXY_IPS` (otherwise the limiter keys every visitor on the proxy's address), and disables response buffering for `/api/chat/stream`, `/api/chat/messages/stream` and `/api/inbox/events`.
- **Some checks depend on the external origin, not the internal one.** The embed allowlist compares a request's `Origin`/`Referer` host with the website's and the hosted page's origin with `request.base_url` **exactly on scheme, host and port**, so what the proxy presents to the app is part of the security boundary, not cosmetics.
- **No deployment artifact is tracked.** `git ls-files` contains no Dockerfile, compose file, Procfile, orchestration manifest or CI workflow; the only executable precedent is `scripts/gate_v5_5g/run_all.sh`, which starts a real `uvicorn` against a throwaway database for the gate. Deployment and rollback are therefore entirely a D2 answer, not an existing script to follow.
- **Some migrations are not reversible in practice.** M11/M12 downgrades discard billing and operator state (documented in `README.md` §3), so a rollback that relies on `alembic downgrade` has a data cost that the approver must accept or exclude.

### Options and consequences

#### 1. Placement of the API and the worker

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one host for API and worker** | Both processes (and, in the smallest shape, the data services) run on one machine. | Fewest moving parts and one deploy unit, but everything shares one failure domain and one restart: a worker crash-loop and an API restart are the same event, and capacity is raised by resizing rather than scaling out. Local upload bytes are trivially shared. |
| **B — separate API and worker hosts** | The API serves requests on one host, the worker consumes the queue on another, both reading the same database and Redis. | A worker restart no longer interrupts requests, and each unit is sized separately, at the cost of two deploy units and a version-skew window: during a deploy the worker can see a job payload written by a newer API, so payload compatibility must hold in both directions for at least one release. |
| **C — several API instances behind a load balancer** | More than one API process serves traffic; one or more workers consume the queue. | Forces `RATE_LIMIT_BACKEND=redis` (the memory limiter is per process, so limits would be multiplied by the instance count), forces the upload volume to be shared or uploads to be restricted (local disk on one instance is not visible to the others), and every instance needs the same `/widget.js` source path. SSE connections pin to one instance, so each instance and the proxy must keep buffering off. Two workers are safe for the claimed job types but duplicate the loop-driven producers (both `retention_loop` and `topic_loop` would queue the same work, which the claims make idempotent rather than free). |

#### 2. PostgreSQL with pgvector

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — self-managed database server** | A database on a host the team operates, reached over the private network. | Extension availability and version upgrades are the team's responsibility; backups, restore rehearsal and point-in-time choices become D3/D7 obligations rather than a service feature; the host is another thing to patch. |
| **B — managed database service** | A provider runs PostgreSQL with the pgvector extension. | Removes patching and some backup work, but the extension and its version must be confirmed available before the choice is signed, connection limits and pooling become a sizing decision that the API and worker share, and the provider's maintenance windows and backup retention constrain what D3 and D7 may promise. |
| **C — primary plus a replica or standby** | A second copy exists for reads or for failover. | Bounds recovery time (D3) but adds a failover procedure with its own split-brain and data-loss rules, a decision about which reads may hit the replica (RAG search, analytics), and a rehearsal of both failover and fail-back — none of which exists in the code today. |

#### 3. Redis

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — Redis on the API host** | A local instance serves the queue, caps, limiter and inbox. | Cheapest, but the queue shares the API's failure domain: restarting the host loses whatever is queued (the queue is a list in memory), and every chat message's cap check adds no network hop. |
| **B — a separate Redis instance** | One Redis service reached over the private network by both API and worker. | Isolates the queue from an API restart and lets it be sized separately, at the cost of one more host to protect and back up decisions about persistence. |
| **C — a managed Redis-compatible service** | A provider runs Redis. | Adds provider limits and a memory/eviction policy that matters: an eviction policy that drops queue keys loses jobs even though the process is healthy. Provider latency sits in front of every quota check, and a provider outage degrades the inbox and stalls the worker exactly like a local failure. No option removes Redis — the queue, the caps, the shared limiter and the inbox stream all require it. |

#### 4. Where the uploaded bytes live

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — local directory on the API host** | The current code path: `uploads/` on the machine serving requests. | Works unchanged and keeps purge simple, but it pins the deployment to one API instance, the bytes must sit on a volume that survives a host replacement, and the backup story has to cover a directory as well as the database (D3/D7). A rebuild that discards the disk loses documents whose rows still exist. |
| **B — a shared filesystem mounted on every instance** | The same `uploads/` path, backed by shared storage. | Preserves the code and allows several API instances, at the cost of a network dependency on every upload, read and purge, and a requirement that the share's semantics match what the code assumes (`os.unlink`, `..` rejection, batch-committed deletes). |
| **C — object storage** | Bytes move to a bucket and the application addresses them by key. | **Requires code changes**: `api/upload.py` writes locally, `services/retention.py` unlinks locally, and nothing serves the files today. It also adds a credential, a new egress boundary and a second deletion path that D7 must describe — so this is a V6 task implied by D2, not a D2 setting. |

#### 5. How the admin UI is delivered

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — the same proxy serves the built SPA** | `frontend/dist` is served under the API's origin. | One origin for CORS, one certificate, one deploy; but the build's baked `VITE_BACKEND_URL` must be that origin, and rolling the API back without rolling the frontend back (or the reverse) has to be tolerated or forbidden explicitly. |
| **B — a separate static host or CDN** | The SPA is served from its own hostname. | Adds a second origin to `CORS_ORIGINS` and a second certificate, and makes cache invalidation for `index.html` a deployment step; the baked API URL becomes a recorded environment fact that changes with the topology. |
| **C — the API serves the build itself** | A static mount in the application serves `dist/`. | One origin total and no second deploy system, but it is a code change, every API instance must carry the build artifact, and a static mount widens what the process serves — which V6-10's validator would have to cover. |

#### 6. Ingress, TLS termination and network boundaries

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — proxy on the same host, app on loopback** | TLS terminates in a local reverse proxy; the ASGI server listens on loopback only. | Matches `README.md` §2 and needs no `TRUSTED_PROXY_IPS` entry (loopback is trusted already); one certificate to renew, and the proxy's forwarded-proto behaviour must be correct because the hosted page's origin is compared exactly. An SSE timeout at the proxy shorter than the stream's heartbeat silently breaks live replies. |
| **B — load balancer or edge in front of private instances** | TLS terminates at a separate ingress; app instances are private. | Scales out cleanly, but the ingress addresses must be listed in `TRUSTED_PROXY_IPS` when they are public, or every visitor shares one rate-limit bucket; health checks need a path and readiness semantics (`/health` today returns a JSON body with `db`, `redis` and limiter state); and idle/streaming timeouts, buffering and body-size limits all move to the edge, where the upload limit and the SSE endpoints have to be kept consistent. |
| **C — the application terminates TLS** | The ASGI server holds the certificate. | No proxy to configure and no forwarded headers, at the cost of certificate storage and reload in the app's environment, losing the proxy-level buffering controls the SSE endpoints depend on, and still needing an HTTP-to-HTTPS story. |

Whichever shape is chosen, the boundary description has to say which of these is public: the API origin (including `/widget.js`, `/chat/{id}`, `/api/widget-config` and the chat endpoints), the admin SPA origin, and — for Track B only — the payment provider's webhook ingress. PostgreSQL, Redis and the upload volume should not be publicly reachable, and the worker should have no inbound path at all.

#### 7. How a change is deployed

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — replace in place** | Stop, deploy, start. | Simplest and needs no extra machinery, but it accepts downtime and drops in-flight SSE connections; the API and worker restart together, so a slow migration is a visible outage. |
| **B — rolling replacement** | Instances are replaced one at a time behind the health check. | Little or no visible downtime, at the cost of two versions serving simultaneously: every migration must be backward compatible for one release, the worker must tolerate jobs written by either version, and readiness has to mean something the ingress can act on. |
| **C — immutable artifact promoted per environment** | One build is promoted from a non-production environment to production (blue-green or an equivalent switch). | Rollback becomes a switch back to the previous artifact and the rehearsed environment matches production, but it requires artifact storage, a promotion procedure and a rule that the database, Redis and upload volume are not part of the artifact — so a schema change can still make the old artifact unusable. |

#### 8. Migrations and rollback

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — roll back the schema too** | `alembic downgrade` to the previous revision as part of the rollback. | Restores the matching schema, but M11/M12 downgrades discard billing and operator state, so the data cost must be accepted explicitly; the chain is linear, so the only target is the immediately previous revision; and the downgrade has to be rehearsed on a copy, not assumed. |
| **B — restore code only, fix the schema forward** | Rollback redeploys the previous build; migrations are never reversed. | No data is discarded, but every migration must be safe for the previous code for at least one release (expand now, contract later), which is a review rule imposed on all future V6 work. |
| **C — restore the database from a backup** | Rollback is a restore. | Only for a catastrophic change: it loses everything after the backup point (D3's recovery point), and it has to be reconciled against the upload volume, Redis state and any external side effects (sent email, provider calls, payments). |

### Cross-checks an approval must satisfy

- **D3 must promise against this topology.** A single-host option makes the availability statement a function of one machine; a standby option changes what recovery time is even measurable; worker restarts lose queued jobs unless something else covers them.
- **D4's required settings follow from the topology.** `TRUSTED_PROXY_IPS`, whether `RATE_LIMIT_BACKEND=redis` is mandatory, the `CORS_ORIGINS` list and where secrets live are all consequences of the shape chosen here, not independent choices.
- **D5 is not satisfied by a private network alone.** A separate operator ingress reduces exposure but the approved control (MFA/SSO or an operator-only network, enforced before the application) still has to be recorded and exercised.
- **D6 and option 4C interact.** Scanning has to sit wherever the bytes actually land; choosing object storage moves the upload surface into a new code path and a new boundary.
- **D7 needs the deletion map for wherever bytes live**, including a shared filesystem or a bucket whose own versioning or lifecycle rules may outlive the application's purge.
- **D8 needs to know where logs and metrics are collected from** — which process writes them, whether the worker's `print` output is captured, and which ingress or host layer supplies request logs.
- **D9 owns queue survivability**, but this row decides whether Redis persists, whether eviction can drop keys and whether a restart loses queued work; those facts belong in D9's answer.
- **D1 decides whether Track B is in scope**, which adds the payment provider's webhook ingress and the operator console's origin to the boundary description.

### Exact evidence an approver must sign

1. A component inventory — API process, worker process, PostgreSQL with pgvector, Redis, upload volume, admin build, ingress/TLS — each marked self-managed or managed, with the operator who owns it. Any provider name, region and account belongs in this signed evidence; this brief deliberately contains none.
2. The network boundary description: what is reachable from the public internet and on which paths, what is private, and the egress destinations required (model/embedding provider, SMTP, and for Track B the payment provider and its webhook ingress).
3. The TLS termination point, certificate source and renewal owner, and the exact external scheme, host and port the application sees — because `GET /chat/{id}`'s embed allowlist compares `request.base_url` exactly.
4. The `TRUSTED_PROXY_IPS` value and confirmation that `Host`, `X-Forwarded-For` and `X-Forwarded-Proto` are forwarded; without it the limiter keys on the proxy and every visitor shares a bucket.
5. The `CORS_ORIGINS` list and the admin app's public URL (`FRONTEND_URL`), consistent with option 5.
6. Sizing and capacity, as supplied by the operator and consistent with D3: API instance count, worker count, database size and connection budget, Redis memory and eviction policy, upload volume size and headroom.
7. The upload volume's identity — local path, shared mount or bucket — whether it survives a host replacement, who backs it up, and, if it stays local, confirmation that only one API instance serves and purges it.
8. The frontend pipeline: where the build is served, the `VITE_BACKEND_URL` baked into it, and how `index.html` and `/widget.js?v=…` are invalidated after a deploy.
9. The deploy procedure: the artifact, the commands, the order relative to `alembic upgrade head`, whether requests are served during it, who executes it, and the record of a rehearsal in a non-production environment.
10. The rollback procedure: how many previous artifacts are retained, the migration policy (downgrade, forward-fix or restore), the mixed-version rule for the API, worker and schema, and the record of a rehearsal — not a description.
11. The environment list: production and whatever non-production environment exists, how secrets and data differ, and which data may never appear outside production (D7/D8).
12. The health contract the ingress uses — `/health` as it exists today (JSON with `db`, `redis` and limiter state) or a separate readiness path — plus the proxy's buffering and idle-timeout settings for the three SSE endpoints.
13. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R4 (topology verification), R6 (the deployment workflow behind `/health`) and R8 (TLS, private networking, backups) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D2 row moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-10 (the validator needs to know which settings are required in this environment) and V6-40 (a deploy/rollback runbook needs a mechanism to describe), and supplies the topology half of V6-02's operating model. Gate V6-0G still needs D1, D3, D7, D11 and the remaining architecture decisions, so Wave 1 stays closed.

## Appendix — D4 decision brief

**Status: D4 remains UNAPPROVED.** This brief lays out the security-profile choices; it supplies no key length, no origin list, no proxy address, no provider, no region and no owner, and it recommends none of the options.

### The question

Which settings a production deployment must have, where each value comes from, and what the application does when one is missing — the secret and configuration policy, which peers may supply a forwarded client address, which browser origins are allowed, whether rate limits are shared across processes, whether the API documentation is reachable, and how far one environment is separated from another. The answer is what V6-10's production-mode validator enforces; today the only fail-closed check in that area is `validate_billing_config`, and it returns immediately while billing is off.

### What the code requires today (evidence, not a decision)

- **The application has no notion of its own environment.** Nothing in `core/config.py` or `main.py` distinguishes development from production (`ENV`, `APP_ENV` and an equivalent flag do not exist), so every behaviour below is the same everywhere and only the values differ.
- **One secret has a working fallback.** `JWT_SECRET_KEY` defaults to `"your-secret-key-change-this-in-production"` (`core/config.py:8`), and nothing refuses to start with it. Tokens signed with the fallback are valid to anyone who reads this repository.
- **Two secrets fail open rather than fail closed.** `API_KEY_PEPPER` defaults to `""` and is only concatenated into the SHA-256 of a minted key (`services/api_keys.py:43`), so an unset pepper silently salts nothing; `INTEGRATION_WEBHOOK_SECRET` defaults to `None` and the outbound signature is computed with `config.INTEGRATION_WEBHOOK_SECRET or ""` (`services/integrations.py:144`), so an unset secret produces a signature anyone can recompute. Neither is required, and neither raises.
- **The remaining credentials are optional by construction.** Model-provider keys, `MAIL_*` values (read in `services/mail.py`, with placeholder defaults), and the `STRIPE_*` group only matter on the paths that use them. `validate_billing_config()` fails closed **only** when `BILLING_ENABLED=true`, and returns immediately otherwise.
- **Trusted-forwarding is implicitly permissive for private peers.** `_client_ip` honours `X-Forwarded-For` whenever the direct peer is loopback or RFC 1918 private, and for a public peer only when it matches `TRUSTED_PROXY_IPS` (`services/ratelimit.py:~150–205`). Loopback and private addresses need no configuration, and an invalid header entry falls back to the socket address.
- **CORS is a parsed comma list with a credentials rule.** `CORS_ORIGINS` defaults to `*`; the list is split on commas, and `allow_credentials` is enabled only when it is not exactly `["*"]` (`main.py:91–93`). `allow_methods` and `allow_headers` are wildcards, and `X-Widget-Version` is exposed.
- **The rate limiter has two backends and a documented fallback.** `RATE_LIMIT_BACKEND` defaults to `memory` (per process, reset on restart); `redis` shares one sliding window across processes and, when Redis is unreachable, falls back to the in-process cap and reports `rate_limiter.degraded` on `/health` (`services/ratelimit.py`). The per-session and daily message caps are separate Redis counters that fail open during an outage.
- **API documentation is always on.** `FastAPI(...)` sets `docs_url="/docs"` and `redoc_url="/redoc"` with no condition (`main.py:74–75`), and the default schema is served at `/openapi.json`; nothing in the deployment gates them.
- **Session and embed posture are settings, not constants.** `SESSION_TOKEN_MODE` and `EMBED_TOKEN_MODE` default to `compat`, which keeps legacy tokenless reads working (K4/K18 remain accepted).
- **No log configuration exists.** Neither `main.py` nor `worker.py` calls `logging.basicConfig` or `dictConfig`; the worker reports with `print`, so level, format and destination are whatever the process's stdout is attached to.

### Options and consequences

#### 1. Where configuration and secrets live

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — environment variables injected at deploy** | The operator supplies every value on the process environment of the API and the worker. | No new dependency and no code change; but nothing records which values are required, rotation is a redeploy, the worker and API can silently disagree, and a shell history or a plain env file becomes a credential store unless the deploy tooling keeps it out of one. |
| **B — a secret manager read at start-up** | Values are fetched from a managed store and injected into the process. | Rotation and access review become auditable and the values leave the host's disk, at the cost of a boot-time dependency on the store (and its own availability), a bootstrap credential for that store, one more egress destination, and a decision about what happens when the store is unreachable at start. |
| **C — files on disk, mounted per environment** | A root-owned file (or per-secret files) is mounted and parsed at start. | Simple and works without a network at boot; but file permissions become the control, rotation is a redeploy plus a file change, and the same file can be copied between hosts and environments unless something prevents it. |

#### 2. How a missing or placeholder value is handled

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — advisory only (today)** | Missing values fall back to defaults and the service starts. | Nothing breaks during development and no operator workflow changes, but a production start with the fallback JWT key, an empty pepper or an empty webhook secret succeeds silently, and the weakness is discovered only by an attacker or an audit. |
| **B — fail closed in production, keep development usable** | A start-up validator refuses to run when a required value is missing, empty or a known placeholder, keyed on an explicit environment signal. | Turns every silent weakness into a failed boot and forces the environment signal in §6; it must name settings without printing values, must not break the suites or the gate scripts, and requires the exact required-set to be decided rather than guessed. |
| **C — fail closed always, no environment signal** | The validator runs unconditionally. | Strongest and simplest to reason about, but it breaks local development, `tests/` and `scripts/gate_v5_5g` unless every one of them supplies the full production set — a large change to the developer workflow that the approver would be accepting. |

#### 3. Trusted proxies and the client address

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — private peers trusted implicitly (today)** | Loopback and RFC 1918 peers may supply `X-Forwarded-For`; public peers only when listed. | Correct for a proxy on the same host or VPC and requires no configuration; but any container or process that can reach the API from a private address can choose the client IP the limiter keys on, and a public load balancer is ignored until it is listed. |
| **B — explicit operator list plus private defaults** | The edge addresses are recorded in `TRUSTED_PROXY_IPS` and the private-address trust is kept. | Fixes the public-load-balancer case (otherwise every visitor shares one bucket), at the cost of maintenance when the edge's addresses change and a documented rule that only that edge may forward. |
| **C — never trust a forwarded header** | The socket address is always the client address. | Cannot be spoofed, but behind any proxy every request carries the proxy's address, so the limiter collapses to one bucket and the approach only works with a per-connection edge that terminates the TCP session itself. |

#### 4. CORS origins

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — wildcard (today's default)** | `CORS_ORIGINS=*`; credentials are disabled automatically. | Zero configuration, but any site may call the API from a browser, and the moment someone needs credentialed requests the wildcard has to go — so the deployed value is a security decision, not a convenience. |
| **B — an explicit list of the console and marketing origins** | Exactly the origins that host the SPA. | Restricts browser callers to the approved surfaces and enables the credentials path; it must be updated whenever the frontend moves, and it does **not** restrict the widget, whose authorization is the origin/host check and the embed token rather than CORS. |
| **C — explicit list plus a separate rule for embeds** | B, with a stated policy that widget endpoints are governed by the website-origin check and are not added to the CORS list. | Keeps the two mechanisms from being confused and documents why the widget keeps working while CORS is narrow; requires the distinction to be written down where frontend work will read it. |

#### 5. Rate-limit backend

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — per-process memory** | The limiter counts in each process. | No Redis dependency for the limit itself and no shared state to operate, but limits multiply by the process count, reset on every restart, and differ per API instance — only coherent if there is exactly one API process. |
| **B — shared Redis window** | One budget across processes, surviving restarts. | Correct with more than one instance, at the cost of Redis being on every limited request's path; during a Redis outage the code falls back to the per-process cap and reports the degradation on `/health`, which the approver must accept as the documented behaviour rather than assume a hard failure. |
| **C — shared Redis window with a fail-closed rule** | B, but a Redis outage refuses traffic instead of falling back. | A predictable guarantee and no silent softening of the limit, at the cost of turning a Redis incident into a full outage — a change of behaviour that needs a code change, not a setting, and has to be weighed against D3. |

#### 6. API documentation exposure

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — open on the public origin (today)** | `/docs`, `/redoc` and `/openapi.json` answer anyone. | Convenient for integrators and free to operate; it also publishes the full route and schema surface — including the admin API — to anonymous callers, and nothing about the routes is secret enough to make that fatal, but it is exposure the approver should accept knowingly. |
| **B — disabled in the production process** | `docs_url`, `redoc_url` and `openapi_url` are switched off by configuration. | Removes the surface from the public origin, at the cost of a code change (the values are currently hard-coded) or a deployment-time conditional, and integrators lose the live reference — an offline copy then has to be published deliberately. |
| **C — reachable only through the operator path** | Documentation stays enabled but is not exposed by the public ingress. | Keeps the reference for the team without publishing it, at the cost of a route the ingress must special-case and a dependence on D2's ingress shape and D5's operator control. |

#### 7. Environment separation

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one deployment, production values only** | No separate non-production environment; changes are rehearsed locally and shipped. | Cheapest to operate, but there is nowhere to rehearse a deploy, a rollback, a migration or a restore (V6-40/V6-42 need exactly that), and any test pointed at it is production. |
| **B — a separate non-production environment with its own secrets and data** | A second deployment, same artifact, different values and no production data. | Makes the rehearsals possible and keeps production credentials out of tests; it doubles the configuration surface, so every required value has to be recorded per environment and the validator has to know which set applies where. |
| **C — B plus an explicit environment signal in the application** | The process is told which environment it runs in and can key validation, docs exposure and other behaviour on it. | Enables §2's fail-closed-in-production option without breaking development; it introduces a value that must never be wrong (a production process believing it is development is the failure mode), so the signal's source and default need to be part of the approval. |

### Cross-checks an approval must satisfy

- **D2 decides the shape these settings describe.** Whether `RATE_LIMIT_BACKEND=redis` is mandatory follows from the instance count; whether `TRUSTED_PROXY_IPS` must be set follows from where TLS terminates; option 6C needs an ingress that can special-case a path.
- **D5 is not replaced by any of it.** Narrowing docs, CORS or proxies does not authenticate the operator boundary; the approved MFA/SSO or private-network control still has to be enforced before the application.
- **D8 inherits the redaction rule and the destination.** This row decides where logs come from and whether a log configuration exists at all; it must not put a secret in a start-up error message.
- **D1 decides whether the Stripe group is required**, because `validate_billing_config` is the only fail-closed check today and it only fires with billing on.
- **D13 owns the session and embed posture.** `SESSION_TOKEN_MODE` and `EMBED_TOKEN_MODE` are configuration, but whether `enforce` is required for the launch cohort is that row's decision.
- **D7 covers anything these settings cause to be retained** — a secret manager's audit trail and an edge's request logs are personal-data stores in their own right.

### Exact evidence an approver must sign

1. The complete required-value inventory for the production process, by name (JWT signing key, API-key pepper, model-provider credentials, mail credentials, integration webhook secret, session/embed modes, CORS list, trusted proxies, rate-limit backend, and — only with billing on — the Stripe group), each marked required, optional or must-be-empty.
2. For each required value: where it lives, who can read it, how it is rotated and what a rotation interrupts — with the confirmation that no value is printed in a start-up error, a log line or `/health`.
3. The behaviour on a missing, empty or placeholder value in production: refuse to start, warn, or proceed — stated per value, with the environment signal that decides it (§2, §7).
4. The `TRUSTED_PROXY_IPS` value and the rule behind it: which peers may forward, what happens to an unlisted public edge, and the accepted consequence for the limiter during a Redis outage.
5. The exact `CORS_ORIGINS` value and the statement that credentialed browser access is enabled only if the list is explicit; plus whether widget endpoints are governed by CORS or by the website-origin and embed-token checks.
6. The rate-limit backend for this deployment and the accepted failure mode (§5), consistent with the instance count in D2.
7. The documentation decision (§6): which paths answer, from where, and — if disabled — where the reference lives instead.
8. The environment list and separation rule: which environments exist, which values differ, and the guarantee that no production data or credential appears in a non-production one.
9. Confirmation that development, the unit suites and `scripts/gate_v5_5g` still run under the approved policy — a validator that breaks them is not signable as written.
10. The names of the settings whose absence the deployment must treat as fatal, agreed with the operator who will run the start-up, so the validator can be written against a signed list rather than an engineering guess.
11. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R1 (secure boot) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D4 row moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-10 (the production-mode validator needs a signed required-set and a defined failure mode) and supplies the configuration half of V6-02's operating model. Gate V6-0G still needs D1, D2, D3, D7, D11 and the remaining decisions, so Wave 1 stays closed.

## Appendix — D5 decision brief

**Status: D5 remains UNAPPROVED.** This brief lays out the choices for authenticating platform owners; it names no identity provider, no second factor, no network range, no timeout, no bootstrap actor and no owner, and it recommends none of the options.

### The question

Which enforceable control protects the platform-owner boundary — a second factor or federated single sign-on on the operator's login, a private operator-only network path, or a combination — **where** that control is enforced (at the edge, in front of the application, or inside it), and who owns bootstrap, recovery and revocation. The answer decides whether the operator console may be exposed at all, which is the condition `PLATFORM_CONSOLE_ENABLED=false` currently stands in for.

### What the code enforces today (evidence, not a decision)

- **Two gates, neither of them authentication strength.** `PLATFORM_CONSOLE_ENABLED` (default `false`) makes the whole `/api/platform` surface a **404** before any auth runs (`api/platform.py::platform_console_enabled`); with it on, every route depends on `require_platform_owner`.
- **The operator is an ordinary tenant account with a grant.** `require_platform_owner` (`core/auth.py:141`) composes `get_current_user` — the same email/password JWT login a tenant uses — and then re-reads an active grant per request, answering **403** when there is none. There is no separate operator login, no second factor, no re-authentication and no step-up for a destructive action.
- **The grant is the only operator-specific control, and it is out-of-band only.** `scripts/platform_owner.py grant|revoke|list` is the whole provisioning path; the CLI needs the deployment's `DATABASE_URL` and a required `--actor` label that lands in the audit row. No HTTP route can mint, extend or remove a grant, and `users.role='admin'` never implies one.
- **Revocation is a timestamp, not a session kill.** `revoke_owner` stamps `revoked_at`, so the next request is refused (the grant is re-read every time), but the account's ordinary JWT remains valid for tenant routes — the application has no server-side JWT revocation, and `docs/platform.md` tells an operator to rotate the JWT secret if a token may have been stolen.
- **The break-glass path is database access.** `docs/platform.md` records that a locked-out operator is replaced with the CLI and that total lockout is recovered by running the CLI against the deployment database, which means whoever holds database credentials is the real root of this boundary.
- **The UI's safeguards are procedural.** The `/platform` shell is a `ProtectedRoute` plus a `GET /api/platform/session` read (a signed-in tenant admin gets a 403 state), and the confirmation checkbox and the API's `confirm` flag are confirmations, not authentication — `docs/platform.md` says so plainly and lists strong authentication, re-authentication prompts and an IP allowlist as **not built**.
- **Mutating actions are audited; session checks are not.** `platform_audit_logs` records actor, action, target and time for every grant/revoke, subscription action, catalog change and setting change. It has no record of a successful or failed console sign-in, and it is append-only with no pruning path.

### Options and consequences

#### 1. Which control protects the boundary

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — a second factor on the operator's login** | The existing account login gains a factor beyond the password, required for the operator account (or for everyone). | Needs no separate operator identity and keeps one login system, but it is an application-level change the codebase does not have, it must be enforced server-side (a client-side challenge is theatre), and it does nothing for a stolen session token — the JWT remains valid until it expires or the secret is rotated. |
| **B — federated single sign-on for operators** | Operator authentication is delegated to an identity provider the organisation already controls, with the grant mapping the federated identity to the operator. | Centralises deactivation and device policy where the organisation already manages them and makes revocation at the provider effective for new logins; it requires an identity provider, a protocol integration, a claim-to-user mapping and a decision about whether tenants keep the existing login — so it is the largest engineering option, and it still does not revoke an already-issued JWT. |
| **C — a private operator-only network path** | The console is reachable only from a network the operator controls (VPN, private link, bastion, or an internal-only ingress), with the existing grant check unchanged. | No authentication code and no new dependency; the network boundary does the work. But it puts the entire control outside the application, so a misconfigured ingress or a broadly routed VPN silently removes it, and it makes the console unusable from anywhere the path is absent — including during certain incidents. |
| **D — C plus one of A or B** | The console is only reachable over the private path **and** the login is strengthened. | Defence in depth: neither a leaked token nor a routing mistake is sufficient alone. It also doubles the operational surface (network path, provider or factor, and their recovery stories) and is the slowest to stand up. |

#### 2. Where the control is enforced

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — at the network edge** | The ingress refuses the platform path from outside the approved network, before any application code runs. | Enforced for every route under that path, cannot be bypassed by a client, and needs no code; it depends entirely on D2's ingress shape and on the edge's configuration being reviewed like code, and it fails open if a later rule widens the path. |
| **B — in front of the application, in an identity-aware proxy** | A proxy authenticates the operator and forwards an identity the application trusts. | Enforced before the app sees the request and reusable for other internal surfaces; the application must trust the forwarded identity only from that proxy (which is a D4 trusted-proxy decision), and a direct path to the app would bypass it entirely. |
| **C — inside the application** | The check lives in `require_platform_owner` and its login path. | Visible to tests and review, portable across environments, and it travels with the code; but it can only be as strong as what the app can verify, it cannot protect a route added later without the same dependency, and it is the option that most needs the platform switch kept off until it is proven. |
| **D — edge or proxy, with the application check retained** | The stronger path is external and the grant check stays. | Nothing in the app regresses if the external control changes, at the cost of two places to keep correct and a documented statement of which one is authoritative. |

#### 3. Identity and session model

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — tenant account plus grant (today)** | The operator signs in as an ordinary user and the grant adds operator rights. | One identity system, no new tables, and tenant and operator duties can share one account; but the operator's session is an ordinary session — its lifetime, storage and revocation are the tenant ones. The two are separable in one direction only: revoking the grant ends operator access on the next request while the tenant login keeps working, but suspending the tenant account also removes the operator's login, and an already-issued token stays valid for tenant routes until it expires or the signing secret is rotated. |
| **B — a separate operator identity realm** | Operators are a distinct identity class, even if backed by the same login. | Cleaner separation and clearer audit attribution, at the cost of a second provisioning and recovery path (and a second thing that can be locked out). |
| **C — short-lived, out-of-band credentials for the console** | Access is granted per session, from the operator's own tooling, with a short validity. | Shrinks the window a leaked credential is useful and makes every elevation a deliberate act; but it needs an issuance mechanism, a store, and a story for the incident where issuance is unavailable — and it is the most code of the three. |

#### 4. Re-authentication for high-impact actions

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — none beyond the login (today)** | Every action is authorised by the session plus the grant. | Nothing to build and no additional friction; a stolen session can perform any operator action for its lifetime, which is why revocation depends on rotating the signing secret. |
| **B — an explicit re-authentication step** | The destructive or commercial actions require the operator to authenticate again, or present a fresh proof, shortly before acting. | Narrows the stolen-session window for exactly the actions that matter, at the cost of a flow the console does not have and a decision about how long a fresh proof remains fresh — a period this brief deliberately does not set. |
| **C — per-action approval by a second person** | A second named operator confirms the action. | Strongest control for a payment-affecting action, but it needs more than one trained operator (which D11 and the roster decide) and a queue that holds the pending action, so it is an operational commitment as much as a feature. |

#### 5. Bootstrap

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — CLI on a host that holds the deployment database credentials (today)** | The first grant is created by running the script with `DATABASE_URL` exported. | No bootstrap secret beyond the database itself and the path is testable in staging; but database access becomes an operator-granting capability, so who holds it is a security decision, and the audit row carries only the `--actor` string the operator typed. |
| **B — a seeded operator defined by deployment configuration** | The deployment names the initial operator and the application provisions the grant at start. | Reproducible and scriptable and removes the manual step, at the cost of a configuration value that can grant operator rights (so it becomes a secret) and a rule for what happens when it changes after first start. |
| **C — an invitation issued by an existing operator** | A current operator grants the next one from within the console. | Removes database access from routine onboarding and keeps the audit actor real; but it cannot bootstrap the first operator, and it requires an HTTP grant path that **does not exist today** and that the V5 record deliberately forbids — choosing it reopens that non-goal explicitly. |

#### 6. Recovery and revocation

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — CLI recovery, timestamp revocation (today)** | A lost operator is replaced with the CLI; a suspected compromise is revoked by timestamp; a stolen JWT is handled by rotating the signing secret. | Nothing new to build and it never depends on the console being reachable; but recovery requires database access, revocation does not end the account's tenant session, and rotating the secret signs every tenant out — a blunt instrument. |
| **B — recovery through the identity provider** | The organisation's provider handles account recovery and deactivation, and the grant is re-pointed by the CLI or by a trusted operator. | Recovery follows the organisation's existing process and is effective for new logins; it presumes option 1B and leaves the already-issued-token question in place. |
| **C — a second, sealed recovery credential** | A pre-provisioned break-glass credential (or a documented dual-control procedure) is held for the case where both the provider and the console are unavailable. | Bounds the worst case and can be rehearsed, at the cost of a credential that must be stored, rotated and monitored precisely because it bypasses the normal path. |

### Cross-checks an approval must satisfy

- **D2 fixes what the network option can even mean.** Edge enforcement needs an ingress that can refuse a path; an identity-aware proxy is an ingress component; the private path is a network boundary, not an application setting.
- **D4 owns the trust that option 2B depends on.** A forwarded identity is only as trustworthy as the trusted-proxy rule, and a policy that accepts such a header from a public peer would undo the control.
- **D8 must cover the console's own access trail.** Today only mutations are audited; whatever control is chosen should make sign-ins, refusals and grant changes visible to whoever investigates an incident, without logging tokens.
- **D13 owns the session questions this row leans on** — lifetime, revocation and origin-bound widget authentication — because the operator session is an ordinary tenant session today.
- **D11 and the roster decide whether option 4C is possible at all**, since dual control needs a second trained operator rather than a feature flag.
- **D1 decides whether the console is in scope**, because Track A leaves it off entirely and no control in this row is then needed for launch.

### Exact evidence an approver must sign

1. The control chosen (§1) and, if more than one, which is authoritative and which is defence in depth.
2. The enforcement point (§2) and the proof of it: for an edge or proxy, the configuration; for the application, the route inventory showing every platform route depends on the check; plus the statement that a direct path to the application does not bypass it.
3. The identity model (§3): whether operators are tenant accounts with grants or a separate identity class, and how each of the two is suspended — noting that grant revocation ends operator access without ending the tenant login, while suspending the tenant account also removes the operator's login and leaves any issued token valid until expiry or secret rotation.
4. The session lifetime and re-authentication rule (§4) for ordinary and high-impact actions, with the period supplied by the approver — not derived here.
5. The bootstrap path (§5), who may execute it, what credential it needs, and the statement that no HTTP route mints operator access (or an explicit decision to change that non-goal).
6. The recovery procedure (§6) for a lost operator, for total operator lockout and for a stolen session token, including the credential that makes each possible and who holds it.
7. The revocation procedure and its measured effect: what stops at the next request, what does not (an issued JWT), and what the operator must do about the difference.
8. The exposure decision: console enabled or disabled for the launch cohort, and if enabled, from where — public ingress, private path or operator proxy — consistent with D2.
9. The audit expectations for operator access: which events are recorded, who may read them, and how that is verified rather than assumed.
10. Confirmation that the chosen control was exercised end to end in a non-production environment — sign-in, refusal for a tenant account, a grant, a mutation, a revocation and a recovery — with the evidence path recorded.
11. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R2 (operator security) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D5 row moves from **UNAPPROVED** to **APPROVED**, which is the condition for exposing the platform console at all (V6-11) and supplies the operator half of V6-02's ownership model. Gate V6-0G still needs D1, D2, D3, D4, D7, D11 and the remaining decisions, so Wave 1 stays closed; until then `PLATFORM_CONSOLE_ENABLED=false` remains the only operating control.

## Appendix — D6 decision brief

**Status: D6 remains UNAPPROVED.** This brief lays out the upload choices; it names no scanner, vendor, format list, size limit, quarantine period or owner, and it recommends none of the options. The limits quoted below are what the code does today, recorded as evidence, not as a proposal.

### The question

What happens to a file a customer supplies before it becomes knowledge the assistant answers from — whether the upload surface is opened at all for the launch cohort, whether untrusted bytes are scanned and by what kind of control, which formats and sizes are accepted, what happens to a file that fails a check, and what the service does while the check is unavailable. The answer is what V6-13 implements; today the answer is "the surface is open to every signed-in account, nothing is scanned and no format is refused".

### What the code does today (evidence, not a decision)

- **Five entry points, all behind the same login.** `api/upload.py` exposes `POST /api/uploads/` (multipart), `/url`, `/youtube`, `/notion` and `/google-drive`, and every one depends on `get_current_user` — **any** authenticated account of any role in any company, not only an admin or manager. Nothing in `/api/v1` exposes uploads.
- **No format check on the file itself.** The multipart route derives the extension from the supplied filename (`os.path.splitext`) and stores `file.content_type` as sent; there is no allowlist of extensions or MIME types anywhere on the upload path, so a file named `.pdf` is accepted as a PDF and anything else named `.txt` is accepted as text.
- **One size limit, enforced while streaming.** `MAX_UPLOAD_MB` (default `20`) becomes `MAX_UPLOAD_BYTES` (`core/config.py:258`) and the multipart route aborts mid-stream, deleting the partial file; the four import routes enforce the same ceiling on the declared or streamed length (`services/sources.py`). There is no per-company quota on stored uploads.
- **Nothing scans anything.** There is no antivirus, malware or content-scanning code in the tree; the only match for “scan” on this path is a comment about a remote provider's own warning page. `docs/security.md` states plainly that uploads are **not** virus-scanned, and risk R9 records it as accept-with-owner.
- **Parsing happens later, in the worker.** The upload routes store bytes under `uploads/` and create an `Attachment` row; text extraction (`services/parse.py::extract_text_from_file`) runs in `worker.py:316` during ingestion, using `pypdf`, `python-docx`, `python-pptx` or BeautifulSoup depending on the extension. A hostile file is therefore stored first and parsed out of process, and the extracted text becomes an `extra_documents` row the assistant can quote.
- **Nothing serves the stored bytes.** No route returns an uploaded file (D2 records the same fact), so the browser-delivery risk is absent; what a bad file can reach is the parser and, through extracted text, an answer.
- **Deletion is the retention path.** `services/retention.py` unlinks expired attachments and deletes their documents; erasing a conversation or contact is a separate path that does not remove a document an admin uploaded.

### Options and consequences

#### 1. Who may upload, and whether the surface is open at all

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — open to every signed-in account (today)** | Any member of any company can upload a file or import a URL. | Nothing to build and the smallest support burden for a team, but the population that can hand bytes to a parser is every tenant user, which makes the scanning decision below a decision about an untrusted population rather than a few vetted admins. |
| **B — restricted to admins or managers** | The route requires a privileged role before the bytes are accepted. | Shrinks the supply of files to people the customer already trusts and needs one dependency per route plus a frontend state; it is a compromise rather than a control, because a compromised admin account or a customer admin acting in bad faith still reaches the parser. |
| **C — disabled for the launch cohort** | The upload and import routes answer 403 (or are not exposed) and knowledge comes only from crawled pages and text entered by the operator. | Removes the entire threat surface and every scanning question with it, at the cost of a real product capability (documents, YouTube, Notion, Drive) for the first cohort — and the approver must say so in the launch scope (D1) rather than leave a button that fails. |

#### 2. Whether and where untrusted bytes are checked

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — no check, risk accepted and documented** | Uploads are stored and parsed as they are; the accepted risk, its owner and its expiry are recorded. | No dependency, no latency and no new failure mode, and it is the only option that keeps the surface fully usable on a single host; but a malicious file reaches a third-party parser in the worker and its text can be quoted in answers, so the acceptance has to name that consequence instead of saying “no scanning”. |
| **B — scan before the bytes are stored** | The upload is held in memory or a staging location, checked, and only then written and recorded. | Nothing unscanned ever reaches the parser or the retention path, and a rejection is a clean 4xx to the user; but it puts a scanner on the request path (latency and availability), needs a size ceiling the scanner can accept, and must cover all five entry points — an import route that skips the check undoes it. |
| **C — store into quarantine, scan asynchronously** | Bytes land in a quarantined state, a check runs out of band, and only a cleared file becomes an attachment the worker may parse. | Keeps uploads responsive and survives scanner latency, at the cost of a new state on `attachments`, a job or poll to move it, a visible pending state in the UI, and a hard rule that the worker must never parse a quarantined row — which is a code change, not a configuration. |
| **D — check at parse time in the worker** | The worker validates each file immediately before extraction. | Fits the existing pipeline without touching the routes, but the bytes are already stored and the user was already told the upload succeeded; a rejection then surfaces as a failed ingest rather than a refused upload, and the quarantine state still has to exist to hold the file until it is cleared. |

#### 3. What a failing file does

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — reject the upload** | The request fails and the bytes never persist. | Simple to explain and to test, and it leaves nothing to clean up; but the user learns only that the file was refused, and a false positive blocks a legitimate document with no path to a human. |
| **B — accept into quarantine and report the state** | The file is stored, marked as not usable, and the UI shows it. | Keeps the bytes for investigation and for a later decision, at the cost of storing something known-bad and of a state the UI and retention path both have to understand. |
| **C — delete immediately and record the event** | The bytes are discarded and an audit or log entry records the refusal. | Smallest retention of hostile input and a trail for the customer, but a false positive silently destroys the user's file and the event must not contain the filename or contents if those are personal data. |

#### 4. Supported formats and size limits

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — whatever the parser can read, one global size cap (today's shape)** | Every extension with a handler is accepted and one limit applies to all of them. | Nothing to maintain and no surprises for the user; but it treats an OOXML container, a PDF with embedded JavaScript and a plain text file as equally safe, and a single cap ignores that a compressed container can expand far beyond the bytes stored. |
| **B — an explicit allowlist with per-type expectations** | The accepted extensions and MIME types are enumerated, and the check is on the actual content rather than the name. | Prevents a renamed file from reaching the wrong parser and makes the promise auditable; it needs a maintained list, a content-sniffing step and a rejection message, and it will reject files the current behaviour accepts. |
| **C — restrict to text-like formats for the cohort** | Only the extensions the standard library reads; no PDF, DOCX or PPTX. | Removes the third-party parsers — the largest single class of file-processing risk — and needs no scanner for the format itself; but it removes PDF and Office documents, which is much of what customers actually upload, and the limit must be stated in the launch scope. |

Whichever is chosen, the size limit has to be stated per entry point, because the local upload and the four imports enforce the same ceiling through different code paths, and the decompression question (a container that expands past the stored size) has to be answered explicitly — the current cap bounds bytes on disk, not bytes extracted.

#### 5. Behaviour while the check is unavailable

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — fail closed: refuse uploads, keep the product working** | With the scanner unreachable, the upload routes answer 503 and everything already ingested keeps working. | Cannot admit something unchecked, and the blast radius is one feature; but a scanner outage becomes a visible product outage, the error message has to be honest, and the queue-and-retry case is not covered. |
| **B — fail open: accept unscanned and flag it** | Uploads continue and are marked as unchecked until a later pass. | No user-visible outage, at the cost of admitting exactly what the control exists to stop, and it requires the flag to be visible to the operator and to forced re-scan later. |
| **C — queue and retry** | Uploads are accepted into quarantine and held until the check can run. | The user is not blocked and nothing unchecked is parsed, but it needs the quarantine state from option 2C, a retry policy, a bound on how long a file may wait, and a decision about what the user sees. |

### Cross-checks an approval must satisfy

- **D2 fixes where the bytes and the parser live.** Option 2B puts the scanner on the request path; 2C/4C need storage that can hold a quarantined object, and a multi-instance deployment must not let one instance write while another never sees the file.
- **D7 owns the retention of whatever is stored**, including a quarantine that must not outlive its decision and the deletion path for a refused or quarantined file.
- **D8 owns the event a refusal writes** — who can read it and what it may not contain.
- **D1 names the cohort and the included features**, so option 1C or 4C is a scope statement there, not a silent removal here.
- **D3 constrains the latency budget** if the scanner sits synchronously in the request, and the scanner's own availability becomes part of the availability promise.
- **R9 in `docs/risk-register-v6.md` is this decision's risk row**; an accept option must carry the owner and expiry that row leaves blank today.

### Exact evidence an approver must sign

1. The population allowed to upload (§1) and whether the surface is open, admin-only or off for the cohort — recorded in D1's scope as well.
2. The check chosen (§2), the kind of control it is (a scanner service, an engine inside the worker, or an explicit accepted risk), and the point in the path where it runs.
3. Proof that the check covers **all five** entry points — multipart, URL, YouTube, Notion, Google Drive — rather than the form upload alone.
4. The behaviour for a failing file (§3), including what the user is told and what the operator can see.
5. The accepted formats and the exact size limit per entry point, with the decompression rule stated separately from the stored-bytes rule.
6. The behaviour while the check is unavailable (§5), the user-visible message, and the maximum time a file may wait in quarantine if option 5C is chosen.
7. The quarantine state's lifetime, who may release or delete it, and how it is excluded from parsing and from answers until cleared.
8. The latency and availability budget the check adds, consistent with D3 if it sits on the request path.
9. The audit or log event a refusal produces, its retention and its redaction (D8/D7).
10. The residual risk statement if option 2A is chosen: what a malicious file can reach (the parser process and the extracted text an answer may quote), who accepts it, and when it is reviewed.
11. Confirmation that a test upload of a known-bad fixture was exercised end to end against the chosen path in a non-production environment — accepted, quarantined or refused as decided.
12. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R9 of `docs/risk-register-v6.md`.

### What an approval changes

Only the D6 row moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-13 and turns R9 from an unowned P1 into either a mitigated control or a signed acceptance. Gate V6-0G still needs D1, D2, D3, D4, D5, D7, D11 and the remaining decisions, so Wave 1 stays closed; until then uploads keep their current behaviour and R9 keeps its blank owner.

## Appendix — D8 decision brief

**Status: D8 remains UNAPPROVED.** This brief lists the telemetry choices; it names no vendor, no log destination, no retention period, no threshold, no alert route and no owner, and it recommends none of the options. Where it quotes what the code does, that is evidence, not a proposal.

### The question

What the service emits about its own operation — application logs, worker output, error reports, metrics and alerting — where those streams go, which fields they may and may not contain, how long each is kept, who can read it, what is worth waking someone for, and what happens when the telemetry path itself fails. R6 in `docs/risk-register-v6.md` is this decision's risk row: today there is no observability vendor configuration, no deployment workflow that tracks health, and the worker reports with `print`.

### What the code does today (evidence, not a decision)

- **Two reporting styles, no configuration.** Fifteen modules use `logging.getLogger(__name__)` and about thirty log calls; the worker uses `print` in 55 places and the rest of the tree in 78. There is **no** `logging.basicConfig`, `dictConfig`, `LOG_LEVEL` variable or logging config file anywhere in `src/` or `tests/`, so the level, format and destination are whatever the process environment and the ASGI server's defaults produce — no structured format, no JSON, no timestamp contract of our own.
- **No correlation id.** `main.py` installs CORS and the two error handlers and nothing else; there is no request-id middleware, and a log line carries whatever ids the call site happens to pass (company, website, integration, handoff request) rather than one identifier that ties a request's lines together.
- **No error tracking and no metrics.** There is no error-reporting SDK, no tracing, no metrics library and no `/metrics` route in the tree. The only operational endpoint is `GET /health` (`api/routes.py:822`), which pings the database, pings Redis on the app's own loop, reports the limiter's backend and `degraded` flag, and downgrades `status` to `degraded` — a readiness probe with no history, no counters and no thresholds.
- **What log lines currently contain.** Ids, counts, provider types, event types and HTTP status codes (`integration … delivered … (200)`, `clustered N of M questions for company …`, `retention purge … for company …: N rows`). Exception logs carry the traceback (`rag.py` on a failed stream, `mail.py`, `digest.py`, `integrations.py`); a provider failure is stored and logged through the redacting `safe_error`, which strips the provider's secret fields before the text reaches `last_error` or a line.
- **The documented rule.** `docs/security.md` states that no raw API key, integration token or password is written to a log line and that webhook bodies are not logged, and it tells the operator to keep `SQL_ECHO=false` because verbose SQL can put row values in the logs. Both are rules the code follows by construction, not by a filter that would catch a mistake.
- **Durable records that already behave like telemetry.** The platform audit trail (`platform_audit_logs`, append-only, secret-shaped detail redacted, never purged by the app), billing events (`billing_events` — event id and type, deliberately no payload), integration deliveries (`integration_deliveries` — every attempt, its status code and `last_error`, payload cleared when a row dies and settled rows deleted after `DELIVERY_RETENTION_DAYS`), and the run records (`digest_log`, `topic_cluster_runs`, `conversation_insights` status). All of them are in the product database, per tenant, and none is exported anywhere.
- **No retention or access control on the log streams themselves.** Nothing in the app deletes, rotates or redacts a log file; that is the host's job, and `docs/release-v5.md` row 9 ("alert on webhook failures, 5xx, mirror drift, audit writes, console access") is still *pending operations sign-off*. There is no deploy manifest, container file or unit file in the repository that would fix a destination.

### Options and consequences

#### 1. Which streams exist at all

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — the current streams only: application logs, as the host writes them** | Structured logging stays out of scope; the operator collects stdout/stderr however the platform does. | Nothing to build, and `/health` plus the audit tables cover the minimum; but the worker's `print` lines have no level and no destination of their own, a line cannot be correlated with a request or a job, and any alerting has to parse prose. |
| **B — one structured application log** | Every entry point emits one record shape (time, level, event, tenant, correlation id, no payload), with the config and level set from the environment and the `print` calls replaced. | Makes the stream queryable and alertable and is a precondition for any vendor that indexes fields; it touches many call sites, is a code change before anything can be monitored, and needs a rule about what a record may never contain. |
| **C — structured logs plus error reports and metrics** | Adds an error-reporting path (a traceback reaches a place someone watches) and a metrics surface (counters and latency the operator can chart) beside the logs. | The full picture, at the cost of the most code, the most data leaving the host and the most vendor surface to review; it also inherits every question in §2–§5 rather than answering them once. |

#### 2. Where the data goes

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — stays on the operator's own infrastructure** | Logs and metrics go to the host's own collection, and viewing them means access to that infrastructure. | No third party receives anything, no data-processing question arises and there is no vendor cost; but alerts then depend on whatever the host offers, retention is bounded by local disk, and "who can read the logs" becomes the server's access list. |
| **B — a third-party observability service** | Logs, error reports or metrics are shipped to a processor outside the deployment. | Better querying, retention and alerting than a single host runs itself, at the cost of a processor that receives tenant identifiers and operational metadata, a data-processing and retention question, a network path that must not carry payloads, a possible cross-border transfer, and a second outage surface. |
| **C — self-hosted observability stack** | A separate collection stack the operator runs, whether on the same host or another. | Keeps the data inside the operator's boundary and can still index and alert, but it is infrastructure to run, patch, back up and size, and it becomes something else that can be down during an incident. |

Whichever is chosen, the approver has to name it: "no vendor configuration" is not a destination, and a decision to send nothing anywhere is an option that must be recorded, not a default.

#### 3. What may leave the process: identity and redaction

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — internal ids only, with the existing rules as prose** | Lines carry company/website/conversation ids and no personal data, enforced by review and the `docs/security.md` rule. | Nothing to build and the current shape already complies; but a single careless format string in new code puts an email address or a prompt into the stream, and redaction is a habit rather than a control. |
| **B — a redaction filter in the logging path** | One filter scrubs secret-shaped values, tokens and addresses before a record is emitted, and a test proves it. | Catches the mistake the rule only forbids, and a filter is small; but it can only scrub what it recognises, it is easy to bypass with a pre-formatted string, and it does not decide whether a tenant identifier is itself personal data in the processor's hands. |
| **C — a defined field allowlist per record** | Only the listed fields are ever emitted; anything else is dropped rather than scrubbed. | The strongest form, because an unknown field cannot leak; but it needs the record shape from §1B first and it makes ad-hoc debugging harder, since a value the developer wanted is simply absent. |

Related and separately decidable: whether the correlation id is tenant-scoped or global, and whether a chat message, prompt or document excerpt may ever appear in a log line — the current answer is no, enforced only by the rule above.

#### 4. Retention and access

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — whatever the destination keeps by default** | No retention statement of our own. | No work, and it is what happens today; but "how long are our logs kept" then has no answer for a customer, an erasure request or an incident review, and the platform audit trail — which is inside the database — follows a different clock than the streams around it. |
| **B — a stated retention per stream** | Each stream (application logs, error reports, metrics, audit rows) has a period, a deletion mechanism and a documented owner. | Answers the question a customer and an auditor will ask, and separates operational logs from the audit record that must outlive them; it needs someone to enforce it where the data actually lives, and the app can only enforce the part it stores. |
| **C — a stated retention plus an access rule** | As B, and only named roles can read each stream, with access itself recorded. | Makes the log store part of the trust boundary rather than a side effect; it is the most work and needs an identity source outside the app's tenant roles, which the operator boundary (D5) does not currently provide. |

Two specific questions belong here rather than in a separate brief: whether logs are in scope for a customer erasure request (the app erases product rows, not log lines), and whether `platform_audit_logs` retention — the one durable record with no deletion path — is confirmed at the same time.

#### 5. What is worth alerting on

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — nothing; watch `/health` by hand** | A probe answers and someone looks when a user complains. | Honest about the current state and needs no owner; but silent failures are the documented behaviour today (workers `print` and continue), and the release doc's monitoring row stays permanently pending. |
| **B — a small set of signals with a stated responder** | The few conditions that mean the product is broken (health degraded, error rate, job backlog, webhook or delivery failures, audit-write failure) reach a channel someone is assigned to watch. | The minimum a production launch needs and the list maps onto what already exists (`/health`, `integration_deliveries`, `platform_audit_logs`); but it needs thresholds chosen by the approver and a named responder — with nobody named, an alert is a message in a channel no one owns. |
| **C — signals plus escalation and runbooks** | As B, with severity, an escalation path and a runbook link per signal, and an on-call expectation. | Turns an alert into an incident process, which V6-02's SLO/RPO/RTO work needs anyway; it is the largest commitment and cannot be staffed by a document — the approver has to commit people, not just thresholds. |

The thresholds themselves are deliberately absent here: they follow from D3's SLOs, so an approval that fixes a number before the SLO is agreed would be inventing a target.

#### 6. When the telemetry path itself fails

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — lose the data, keep serving** | Shipping is best-effort; a full queue or an unreachable destination drops records. | The product never degrades because of its monitoring, which is the right default for request traffic; but the window where the system was breaking may be exactly the window whose evidence is missing, and nobody knows it was dropped. |
| **B — buffer locally and ship later** | Records are held on the host and forwarded when the destination returns, within a bound. | Keeps the record across a short outage, at the cost of disk that can fill, a bound on how much is held, a decision about what happens when it is exceeded, and the same redaction rules applying to a file on disk. |
| **C — fail closed** | A request or job that cannot emit its record fails. | Guarantees a complete trail, which suits an audit record and is wrong for an operational log: it couples product availability to the observability vendor, and an outage becomes a product outage. |

### Cross-checks an approval must satisfy

- **D1 fixes the cohort and the launch scope**, so the alerting minimum in §5 is sized for that cohort rather than for the eventual product.
- **D3 owns the SLOs** the thresholds in §5 derive from, and the availability promise the telemetry path is allowed to affect.
- **D2 owns where the processes run**, which determines whether §2A is even possible and whether logs on one host survive a replacement.
- **D7 owns retention** of anything the app stores; the audit-trail and log-retention questions in §4 must not contradict it.
- **D5 owns the operator identity** any access rule in §4C would reuse; there is no independent operator login today.
- **D6 owns the refusal events** whose alerting this brief assumes, and D13 the session/audit surface that writes them.
- **R6 is this decision's risk row**; an approval either removes its "no vendor configuration" half or records the residual with an owner.

### Exact evidence an approver must sign

1. Which streams exist (§1) and the record shape if any is standardised, including the level source.
2. The destination for each stream (§2) — named infrastructure, named service, or an explicit decision to send nothing anywhere.
3. If a third party is involved: what categories of data it receives, where they are processed, and the retention and deletion terms that follow.
4. The identity rule (§3): which ids appear, whether tenant ids count as personal data, whether the correlation id is tenant-scoped, and confirmation that prompts, documents, message text, tokens, passwords and webhook bodies never appear.
5. The enforcement chosen (§3A/3B/3C) and the test that proves it.
6. Retention per stream (§4), the deletion mechanism, and whether log lines fall inside a customer erasure request — plus the confirmed retention of `platform_audit_logs`.
7. Who may read each stream and on what authority (§4C), consistent with D5.
8. The alert list and its responder (§5), derived from D3's SLOs, with the thresholds stated as part of the approval rather than before it.
9. The behaviour while telemetry is unavailable (§6), including any local buffer bound.
10. The worker's `print` calls: whether they are converted, left, or removed, and what happens to a job failure that is currently only printed.
11. A dry run of the chosen path in a non-production environment — one request, one failed job and one alert reaching the destination — observed, not asserted.
12. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R6 of `docs/risk-register-v6.md`.

### What an approval changes

Only the D8 row moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-21 and V6-22 and turns R6's "no observability vendor config" into either a named destination or a signed decision to keep telemetry in-house. Gate V6-0G still needs D1, D2, D3, D4, D5, D6, D7, D11 and the remaining decisions, so Wave 1 stays closed; until then the worker keeps printing, the logs keep going wherever the host sends them, and `docs/release-v5.md` row 9 stays pending.

## Appendix — D13 decision brief (sessions and security response)

**Status: D13 remains UNAPPROVED.** This brief covers four separate tenant-side security questions — MFA/SSO, admin audit, session revocation and origin-bound widget auth — and for each one the approver records either **require** (with the scope) or **defer** (with the residual risk and its expiry, per the risk register's vocabulary). It names no identity provider, no second factor, no retention period, no session lifetime, no revocation mechanism vendor and no owner, and it recommends none of the options.

### The question

Which tenant-side security controls the launch carries: whether a company's own users must present a second factor or federate their identity, how much of a tenant admin's activity is recorded, whether a customer can see and end a session other than by deactivating the account, and whether the widget's public reads are bound to an origin by something stronger than a header a non-browser client can write. R10, R11 and R12 in `docs/risk-register-v6.md` are the rows these four answers move.

### What the code does today (evidence, not a decision)

- **One login method, one factor.** `POST /api/token` takes an email and password, verifies it with argon2 and returns a bearer JWT (`create_access_token`, which defaults to a fixed expiry of `timedelta(hours=24)`). Password reset is an emailed link. There is **no** second factor of any kind, no federated **login** and no passwordless path anywhere in the tree; the only OAuth text in the code is the Google Drive Picker access token, which is not an authentication path.
- **A bearer token in `localStorage`.** `frontend/src/utils/api.ts` stores the JWT in `localStorage` and attaches it as `Authorization`; logout is a client-side removal (`AuthContext.logout`) with **no logout route**, no refresh token and no token blacklist. `docs/security.md` records the trade-off: CSRF does not apply to a bearer API, but an XSS can read the token, so the frontend must stay free of untrusted HTML.
- **One server-side check already exists.** `core/auth.py::get_current_user` re-reads the user row on every request and requires `status == "active"`, so deactivating or deleting a user ends that account's access immediately even with a valid token. What does not exist is any way to end **one** session, or all sessions of a user, while the account stays usable: `DELETE /api/company/users/{id}` hard-deletes the user, and nothing lists or revokes a session (R11).
- **Tenant admin activity is not audited.** `docs/security.md` states it plainly: "No admin audit log. API keys keep a `revoked_at` and a last-used timestamp; other admin actions are not recorded." Settings writes, website and document deletion, user create/delete/role change, API-key mint and revoke, integration create and token rotation, and the privacy purge are all unaudited — the purge writes a log line (`api/privacy.py`) and nothing else. Only the **operator** boundary is audited (`platform_audit_logs`, append-only, secret-shaped detail redacted), and the inbox transcript read is explicitly not audited either (the company is the boundary).
- **The widget's origin check is soft by design.** `services/embed_guard.py` compares `Origin`/`Referer` against the website's origin, allows loopback, and accepts the API's own origin as first-party for the hosted page (exact scheme+host+port). A non-browser client sets that header freely, which the module's own docstring says; the optional `X-Embed-Token` is a public, replayable value (`EMBED_TOKEN_MODE` `compat` accepts a missing token, `enforce` requires a valid one), and the K4 session token guards history rather than the origin (`SESSION_TOKEN_MODE` `compat` still accepts a missing token for an unclaimed session). K18 is recorded as accepted, with the residual restated in `docs/security.md` §7.
- **Revocation exists in pieces, never as a UI.** `/api/v1` keys and embed tokens are revoked by stamping `revoked_at` (API keys from Settings → API keys; embed tokens through the website routes), and a K4 `session_tokens` row can be revoked by setting that column — but `docs/security.md` says outright that deleting or stamping the row is the only immediate way and that "there is still no server-side revocation UI".
- **Nothing here is scoped by role yet.** Whatever is decided applies to `admin`/`manager`/`user` differently, and the app has three tenant roles (`get_admin_user`, `get_manager_user`) but no per-role session policy.

### Options and consequences

Each question below is decided **require** or **defer**. Deferring is a recorded decision with the residual in the risk register, not an omission.

#### 1. Tenant MFA and SSO

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — defer: one factor for every tenant user** | Email plus password stays the only login; the residual is recorded against R11. | No integration, no support burden, no recovery process to write; but a stolen or reused password is a full account takeover of a tenant, including its conversations and API keys, and the deferral has to name that and its expiry. |
| **B — require a second factor for tenant admins and managers** | A second factor on the privileged tenant accounts only. | Covers the accounts that can read transcripts, mint keys and delete data while leaving ordinary members unchanged; but it needs enrolment, a recovery path (lost device) that is itself an attack surface, a UI, and a decision about what happens to an existing account that has not enrolled. |
| **C — require a second factor for every tenant user** | A second factor on all logins. | The strongest posture for a product holding customer conversations, at the cost of the highest friction and the largest support surface (every locked-out member is a ticket), and it is a product decision as much as a security one — it belongs in D1's scope statement. |
| **D — federation instead of a factor (SSO)** | A company authenticates its users through its own identity provider. | Removes password handling for those customers and can carry their own policies (including their own second factor); but it is a per-customer integration, it introduces an external dependency on the login path, it needs a model for mapping an assertion to a company and a role, and the password path must stay for everyone else — so it does not replace option B or C, it sits beside them. |

#### 2. Broader admin audit

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — defer: operator-only audit (today)** | Only platform-owner actions are recorded; tenant admin actions are not. | Nothing to build and it is what `docs/security.md` already states; but a customer cannot answer "who deleted this document" or "who rotated this integration token", an incident investigation has only prose logs, and the deferral must be recorded against R10. |
| **B — audit a named set of tenant-admin mutations** | An append-only row for each action in a defined list, written in the same transaction as the change. | Answers the question customers actually ask and reuses the pattern the operator audit already proves; it needs the list agreed (that is D11's mutation set, not a new decision), a table and migration, a reader in the UI, and the same redaction discipline as `platform_audit_logs`. |
| **C — B plus read access logging** | Also records who read a transcript, an export or a secret-bearing page. | Closes the gap `docs/security.md` notes for inbox reads; but it multiplies row volume, turns reads into writes on hot paths, and creates a second store of personal data that retention (D7) and erasure must then answer for. |

Whichever is chosen, the audit rows' own retention is part of the answer, and `platform_audit_logs` already has no deletion path — a second audited surface makes that question unavoidable rather than theoretical.

#### 3. Session revocation for tenant users

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — defer: no revocation UI** | Deactivation or deletion of the account is the only lever; a stolen token is valid until it expires. | Zero work and one real control already exists (the per-request `status == "active"` check); but a customer cannot end a single compromised session, a password change does not end existing sessions, and the residual has to be recorded against R11 with its expiry. |
| **B — a session list with revoke** | The user (and an admin, for the company's users) can see active sessions and end one. | The direct answer to "I think I'm logged in somewhere else"; it requires server-side session state (a session id in the token and a row to check, or a denylist with a revocation check on every request), a UI, and a decision about whether the check costs a database read per request. |
| **C — revoke all sessions for a user or a company** | One action ends every outstanding token for that account or tenant. | Much cheaper than per-session management and enough for the common incident ("revoke everything now"); but there is no per-session granularity, so ending one shared device logs out every device, and it still needs the revocation check from B. |
| **D — shorter-lived tokens with refresh** | Access tokens are short-lived and a refresh path exists; revocation happens by refusing to refresh. | Bounds the exposure window even without a denylist and is the usual shape of a bearer deployment; but it adds a refresh flow, a storage decision for the refresh credential, and a new failure mode every client must handle — and it does not revoke already-issued tokens by itself. |

This question and the widget's K4/embed tokens are separate: the tenant session is a JWT in a browser, the widget's is a hashed row that can already be stamped.

#### 4. Origin-bound widget auth

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — defer: soft origin plus an optional public token (today)** | `Origin`/`Referer` matching, loopback allowed, own origin allowed, `EMBED_TOKEN_MODE=compat`, K4 token in `compat`. | No change and the current snippets keep working everywhere; but the check is advisory against any non-browser client, the embed token is public and replayable, and the residual (R12, K18) stays accepted with its expiry recorded. |
| **B — turn the existing switches on** | `EMBED_TOKEN_MODE=enforce` and `SESSION_TOKEN_MODE=enforce`, with the snippet rollout that implies. | No new code and it does stop a caller without the page's token; but it does not make the origin trustworthy, because the token still ships in the page — it is a revocation and compatibility control, not origin authentication, and the rollout breaks any customer page that has not reloaded the snippet. |
| **C — per-website allowed origins as data** | Each website's permitted origins are stored and enforced, so a page on another domain is refused even though the header is spoofable by hand. | Makes the customer's own configuration the boundary and gives support a fix for a copied snippet; but it is only as strong as the header for non-browser clients, it needs a UI and a migration, and a wrong entry silently breaks a customer's site. |
| **D — a server-minted, short-lived, origin-bound assertion** | The page obtains a credential bound to its origin and lifetime from the server, and the read path verifies it. | The only option here that actually raises the bar against a scripted client; it needs a minting route that can tell a legitimate embed from a curl call (which is the hard part, since the server cannot verify an origin either), a lifetime model, and a rollout that keeps the published snippet working — so it is a design task, not a flag. |

None of these removes the K18 caveat that a public value in a customer's page is replayable; the approver must say which residual remains and against which row.

### Cross-checks an approval must satisfy

- **D1 states what the cohort gets**, so "require MFA for everyone" or "defer" is a scope line there and not only a security note.
- **D5 is the operator half of the same identity story** and already requires strong auth or a private network for the console; a tenant MFA decision must not silently borrow the operator answer or leave the two inconsistent.
- **D2 owns where session state would live** if revocation option B/C is chosen, since a revocation check on every request is a per-process or shared-store decision.
- **D7 owns the retention and erasure of any new audit rows**, and D8 the alerting any of these controls would feed.
- **D11 owns the mutation set** the audit option B assumes; D13 does not re-list it.
- **D6 and D13 meet at the upload/admin boundary** — an audited admin action is what makes "a compromised admin imported that file" answerable.
- **R10, R11 and R12 are this decision's risk rows**; every "defer" must fill their owner and expiry, which are blank today.

### Exact evidence an approver must sign

1. For §1: **require** or **defer**, and if require, whether the factor applies to admins/managers or to every user, whether SSO is offered instead or beside it, and the recovery path for a lost factor.
2. For §1 deferral: the residual statement (a stolen password is a full tenant takeover) and its expiry, recorded against R11.
3. For §2: **require** or **defer**, and if require, the exact mutation list (by D11's identifier), where the row is written, and confirmation that it is in the same transaction as the change.
4. For §2: whether reads are audited at all, and if so what an audited read records without storing the transcript again.
5. The retention of every new audit row and its relationship to erasure requests (D7), plus confirmation that `platform_audit_logs` retention is settled at the same time.
6. For §3: **require** or **defer**, and if require, which of the options (per session / all sessions / short-lived plus refresh), who may revoke (self, company admin, both), and what the revocation check costs per request.
7. Confirmation of what already ends access today — the per-request `status == "active"` check and hard-deletion of a user — so the deferral is described accurately rather than as "no revocation exists".
8. For §4: **require** or **defer**, and if require, whether it is the existing switches, per-website origin data, or a new assertion design, with the snippet rollout and the customer impact stated.
9. The residual that remains after the chosen option — the K18 public-value caveat cannot be removed by any of these — and the row it is recorded against.
10. The role and permission model each answer implies (`admin`, `manager`, `user`), so a control cannot be bypassed by a role that was not considered.
11. A non-production demonstration of each **require** answer (an unenrolled login refused, an audited action producing one row, a revoked session refused on its next request, an off-origin read refused), observed rather than asserted.
12. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into R10, R11 and R12 of `docs/risk-register-v6.md`.

### What an approval changes

Only the D13 row moves from **UNAPPROVED** to **APPROVED** — as four recorded require-or-defer answers, not as one blanket "yes" — which unblocks V6-12 and V6-14, settles the embed/session posture V6-15 must follow, and turns R10, R11 and R12 from unnamed residuals into either controls or signed acceptances with an expiry. With D13 recorded, every decision row that V6-01…V6-03 wait on has a brief; gate V6-0G still needs the approvals themselves, so Wave 1 stays closed and no control in this brief is implemented until an approver signs it. Until then sessions stay bearer-only, tenant admin actions stay unaudited, the widget keeps its soft origin check, and `EMBED_TOKEN_MODE`/`SESSION_TOKEN_MODE` stay at `compat`.
