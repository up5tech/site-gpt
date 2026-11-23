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
| **D2** | What hosting/runtime topology: API, worker, Postgres/pgvector, Redis, upload storage, frontend/CDN, TLS termination, network boundaries, deploy and rollback mechanism? | Infrastructure/deployment owner with the engineering lead — **not yet named** | A topology description or diagram covering each component and whether it is self-managed or a managed service, the network boundaries, and the deploy/rollback mechanism, accepted by the owner who will operate it. | **UNAPPROVED** — no approver recorded. Blocks V6-10/V6-40. |
| **D3** | What availability/support promise applies, with which measurable SLOs, database/upload RPO and RTO, capacity assumptions and maintenance window? | Business owner for the promise, operations for the recovery targets — **not yet named** | An approved service statement and recovery objectives expressed as measurable targets, with the assumptions they rest on. Engineering supplies measurements; it does not set these numbers. | **UNAPPROVED** — no approver recorded. Blocks V6-02/V6-21/V6-42. |
| **D4** | What is the production security profile: secret/config policy, trusted proxy addresses, exact CORS origins, rate-limit backend, docs exposure, environment separation? | Security owner with engineering — **not yet named** | An inventory of the required settings for the chosen environment, each with its source (secret store, environment, config), approved by the security owner against the actual ingress, not a template. | **UNAPPROVED** — no approver recorded. Blocks V6-10. |
| **D5** | Which enforceable control protects platform-owner access: MFA/SSO, or a private operator-only network? Who owns bootstrap, recovery and revocation? | Security owner with the operator — **not yet named** | The selected control, proof it is enforced at the ingress (not only in the application), the named bootstrap/recovery/revocation owner, and a recorded exercise of emergency disable. | **UNAPPROVED** — no approver recorded. Blocks any platform-console exposure (V6-11). |
| **D6** | What is the upload policy for untrusted files: approved scanner/vendor, supported formats and size limits, quarantine behaviour, scanner-outage behaviour — or is the upload surface restricted/disabled? | Security owner with product owner — **not yet named** | The approved policy for each case (malicious file, unsupported type, scanner unavailable, oversize), or a signed decision to restrict or disable uploads for the launch cohort. | **UNAPPROVED** — no approver recorded. Blocks V6-13. |
| **D7** | What data handling applies: retention defaults, audit retention, backup expiry, and deletion/restore semantics for users, companies and backups? | Privacy/legal owner — **not yet named** | The approved retention and deletion rules including how backups are handled, the audit-retention period, and the owner who answers data-subject requests. | **UNAPPROVED** — no approver recorded. Blocks V6-41/V6-42 (and V6-14/V6-15 where they touch retention). |
| **D8** | Which logs, error tracking, metrics and alerting are used; what data goes to which vendor; what is redacted; who has access and for how long? | Security/privacy owner with engineering — **not yet named** | The chosen tools (or an explicit decision to defer), the exact data each receives, the redaction rules, and access/retention terms approved by the privacy owner. | **UNAPPROVED** — no approver recorded. Blocks V6-20/V6-21/V6-22. |
| **D11** | Who owns customer support, through which channel, with what coverage window, escalation target and response expectation? | Support owner (business) — **not yet named** | A named owner, contact channel, coverage window, escalation path and response expectation that the owner accepts — no engineering default promoted into a promise. | **UNAPPROVED** — no approver recorded. Blocks V6-02/V6-41. |
| **D13** | Are tenant MFA/SSO, broader admin audit, a session-revocation UI and origin-bound widget authentication required for this cohort, or explicitly deferred? | Security owner with product owner — **not yet named** | An explicit require/defer decision per item with rationale, affected tasks and — for deferrals — the accepted residual risk and an expiry or review date. | **UNAPPROVED** — no approver recorded. Blocks V6-11/V6-12/V6-13/V6-15. |

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
9. The approver's role, the date, and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4.

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
10. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R4 of `docs/risk-register-v6.md`.

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
9. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into `plans/PLAN_V6.md` §4 and into risk R8 of `docs/risk-register-v6.md`.

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
9. The approver's role, date and evidence path — recorded in the D11 row, copied into `plans/PLAN_V6.md` §4 and into risk R4 (and R3 if Track B is chosen) of `docs/risk-register-v6.md`.

### What an approval changes

Only the D11 row moves from **UNAPPROVED** to **APPROVED**, which supplies the support details V6-41 publishes and the support-ownership half of V6-02. Gate V6-0G still needs D1, D3, D7 and the architecture decisions, so Wave 1 stays closed.
