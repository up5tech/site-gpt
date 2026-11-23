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
