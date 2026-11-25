# V6 pre-flight decision and owner record

| | |
|---|---|
| Status | **v1 — the ten Wave 0/Wave 1 decisions (D1, D2, D3, D4, D5, D6, D7, D8, D11, D13) are APPROVED for Track A (hosted core, billing off) on 2026-11-24 by the repository owner, who is the single approver for every role. D9 and D10 remain UNAPPROVED and gate Wave 2/Wave 3 work. D12 is NOT APPLICABLE because Track B was not chosen.** |
| Scope | The decisions `plans/PLAN_V6.md` §4 marks as blocking for Wave 0 and Wave 1 — D1/D3/D7/D11 (launch scope, operations, data handling, support) and D2/D4/D5/D6/D8/D13 (topology, security profile, operator authentication, uploads, telemetry, session/embed posture) — plus D9 (background-job delivery) and D10 (CI and browser execution), which block V6-20 in Wave 2 and V6-30/V6-32/V6-33 in Wave 3 and are briefed here because they decide risks R5 and R7, and D12 (Track B commercial and Stripe readiness), briefed because it decides R3 and applies only if Track B is chosen. |
| Snapshot | `master` at `66dd197`, branch `feat/v6` (2026-11-23), Alembic head `0b22b30bf930`. Decisions recorded 2026-11-24. |
| Rule | A proposed default, an engineering preference or this document is **not** an approval. An approval exists only when a named approver, a date and the evidence are recorded in the row. |

The ten decisions below that block Wave 0 and Wave 1 are now recorded with an
approver, a date and the answer they choose; their consequences are in
[Recorded decisions](#recorded-decisions--2026-11-24). D9 and D10 remain open,
and D12 does not apply while Track A is the launch track.

## Decisions

| ID | Question | Approver recorded | Evidence | Status |
|---|---|---|---|---|
| [**D1**](#appendix--d1-decision-brief) | Track A (hosted core, billing off), Track B (paid SaaS + operator console), or both? Which customer cohort, regions, data types, and is public registration open or invite-only? | Jacky — repository owner, 2026-11-24 | Track A, public registration, Vietnam cohort, approved data categories and empty catalog: [Recorded decision D1](#recorded-decision-d1). | **APPROVED** — blocks V6-01/V6-02, now signed. |
| [**D2**](#appendix--d2-decision-brief) | What hosting/runtime topology: API, worker, Postgres/pgvector, Redis, upload storage, frontend/CDN, TLS termination, network boundaries, deploy and rollback mechanism? | Jacky — repository owner, 2026-11-24 | Managed containers, managed Postgres/pgvector and Redis, CDN SPA, object-storage target: [Recorded decision D2](#recorded-decision-d2) and [`docs/architecture-v6.md`](architecture-v6.md). | **APPROVED** — blocks V6-02/V6-10/V6-40, now signed. |
| [**D3**](#appendix--d3-decision-brief) | What availability/support promise applies, with which measurable SLOs, database/upload RPO and RTO, capacity assumptions and maintenance window? | Jacky — repository owner, 2026-11-24 | 99.5% monthly, RPO 24h, RTO 8h, 30-day backups: [Recorded decision D3](#recorded-decision-d3). | **APPROVED** — blocks V6-02/V6-21/V6-42, now signed. |
| [**D4**](#appendix--d4-decision-brief) | What is the production security profile: secret/config policy, trusted proxy addresses, exact CORS origins, rate-limit backend, docs exposure, environment separation? | Jacky — repository owner, 2026-11-24 | Fail-closed production profile: [Recorded decision D4](#recorded-decision-d4). | **APPROVED** — blocks V6-02/V6-10, now signed. |
| [**D5**](#appendix--d5-decision-brief) | Which enforceable control protects platform-owner access: MFA/SSO, or a private operator-only network? Who owns bootstrap, recovery and revocation? | Jacky — repository owner, 2026-11-24 | Console stays off; MFA/SSO and operator network deferred to 2027-02-28: [Recorded decision D5](#recorded-decision-d5). | **APPROVED** — unblocks V6-02; V6-11 partial (console-off scope implemented 2026-11-24, task unticked); console exposure still requires a new answer. |
| [**D6**](#appendix--d6-decision-brief) | What is the upload policy for untrusted files: approved scanner/vendor, supported formats and size limits, quarantine behaviour, scanner-outage behaviour — or is the upload surface restricted/disabled? | Jacky — repository owner, 2026-11-24 | Admin-only, format- and size-limited, no scanner, residual owned to 2027-02-28: [Recorded decision D6](#recorded-decision-d6). | **APPROVED** — blocks V6-13, now signed. |
| [**D7**](#appendix--d7-decision-brief) | What data handling applies: retention defaults, audit retention, backup expiry, and deletion/restore semantics for users, companies and backups? | Jacky — repository owner, 2026-11-24 | Existing retention default, 30-day backups, 1-year audit, owner named: [Recorded decision D7](#recorded-decision-d7). | **APPROVED** — blocks V6-41/V6-42, now signed. |
| [**D8**](#appendix--d8-decision-brief) | Which logs, error tracking, metrics and alerting are used; what data goes to which vendor; what is redacted; who has access and for how long? | Jacky — repository owner, 2026-11-24 | Redacted structured logs, `/health`, minimal alerts, no vendor: [Recorded decision D8](#recorded-decision-d8). | **APPROVED** — blocks V6-21/V6-22, now signed. |
| [**D9**](#appendix--d9-decision-brief) | What delivery guarantee applies to background jobs, which duplicate/loss cases are acceptable by job type, what retry limit and backoff, and who owns a dead-letter queue and replay? | — not yet recorded | A per-job-type guarantee, retry rule, dead-letter owner and replay path. | **UNAPPROVED** — blocks V6-20 (Wave 2). |
| [**D10**](#appendix--d10-decision-brief) | Where do the project's checks run, which of them must pass before a change lands, how is the browser journey executed, how are dependencies reviewed, and what does a passing run authorise? | — not yet recorded | The CI environment, blocking set, browser runner and dependency-review rule. | **UNAPPROVED** — blocks V6-30/V6-32/V6-33 (Wave 3). |
| [**D11**](#appendix--d11-decision-brief) | Who owns customer support, through which channel, with what coverage window, escalation target and response expectation? | Jacky — repository owner, 2026-11-24 | Owner, email, weekday coverage and 1-business-day acknowledgement: [Recorded decision D11](#recorded-decision-d11). | **APPROVED** — blocks V6-02/V6-41, now signed. |
| [**D12**](#appendix--d12-decision-brief) | Track B only: at what granularity V5's commercial answers (D2 catalog and terms, D3 Stripe and merchant readiness, D4 trial/free tier and registration, D5 lifecycle, D6 existing-company rollout, D7 enforcement, D8 legal content, D9 branding) are signed, which merchant account receives payment and who holds its keys, how the approved catalog is published, who may switch live billing on, and who owns refunds, disputes, reconciliation and webhook failures? V5 D10–D12 (operator boundary) are not carried here. | — not applicable | Track B was not chosen; no merchant, catalog or legal answer is required for this launch. | **NOT APPLICABLE** — D1 chose Track A; V6-51 and gate V6-6G stay closed. |
| [**D13**](#appendix--d13-decision-brief-sessions-and-security-response) | Are tenant MFA/SSO, broader admin audit, a session-revocation UI and origin-bound widget authentication required for this cohort, or explicitly deferred? | Jacky — repository owner, 2026-11-24 | All four deferred to 2027-02-28 with owned residuals: [Recorded decision D13](#recorded-decision-d13). | **APPROVED** — blocks V6-12/V6-14/V6-15/V6-16 as deferrals. |

## Decision register — one page to sign

An index of the thirteen decisions in this record: each question in a line, the risk rows it moves, and a sign-off slot in the same row. The options, their consequences and the exact evidence an approver must supply are in that row's appendix below; nothing here restates, narrows or recommends them. D9 and D10 are briefed but stay **UNAPPROVED**: they block V6-20 in Wave 2 and V6-30/V6-32/V6-33 in Wave 3 rather than the Wave 0 gate. D12 is **NOT APPLICABLE** because D1 chose Track A, so paid activation (V6-51/gate V6-6G) stays closed.

| ID | Question | Status | Risk rows | Approver | Role | Date | Evidence path |
|---|---|---|---|---|---|---|---|
| [**D1**](#appendix--d1-decision-brief) | Which launch track, cohort, regions, data types and registration mode? | **APPROVED** | [R3](risk-register-v6.md#r3) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D1](#recorded-decision-d1) |
| [**D2**](#appendix--d2-decision-brief) | Which hosting/runtime topology, network boundaries and deploy/rollback mechanism? | **APPROVED** | [R4](risk-register-v6.md#r4), [R6](risk-register-v6.md#r6), [R8](risk-register-v6.md#r8) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D2](#recorded-decision-d2) |
| [**D3**](#appendix--d3-decision-brief) | Which availability/support promise, SLOs, RPO/RTO and capacity assumptions? | **APPROVED** | [R4](risk-register-v6.md#r4), [R6](risk-register-v6.md#r6), [R8](risk-register-v6.md#r8) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D3](#recorded-decision-d3) |
| [**D4**](#appendix--d4-decision-brief) | Which production security profile — secrets/config, proxy trust, CORS, limiter backend, docs exposure? | **APPROVED** | [R1](risk-register-v6.md#r1) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D4](#recorded-decision-d4) |
| [**D5**](#appendix--d5-decision-brief) | Which enforceable control protects platform-owner access, and who owns bootstrap, recovery and revocation? | **APPROVED** | [R2](risk-register-v6.md#r2), [R3](risk-register-v6.md#r3) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D5](#recorded-decision-d5) |
| [**D6**](#appendix--d6-decision-brief) | Which upload policy for untrusted files — scanning, formats, quarantine, outage behaviour — or restriction/disablement? | **APPROVED** | [R9](risk-register-v6.md#r9) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D6](#recorded-decision-d6) |
| [**D7**](#appendix--d7-decision-brief) | Which retention, audit-retention, backup-expiry and deletion semantics, and which privacy/legal owner? | **APPROVED** | [R8](risk-register-v6.md#r8), [R10](risk-register-v6.md#r10) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D7](#recorded-decision-d7) |
| [**D8**](#appendix--d8-decision-brief) | Which logs, error tracking, metrics and alerting; what reaches which vendor; redaction, access and retention? | **APPROVED** | [R6](risk-register-v6.md#r6) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D8](#recorded-decision-d8) |
| [**D9**](#appendix--d9-decision-brief) | Which delivery guarantee, duplicate/loss tolerance by job type, retry limits, dead-letter destination and replay? | **UNAPPROVED** | [R5](risk-register-v6.md#r5) |  |  |  |  |
| [**D10**](#appendix--d10-decision-brief) | Where do the checks run, what blocks a change, how does the browser journey run, how are dependencies reviewed, and what does a passing run authorise? | **UNAPPROVED** | [R7](risk-register-v6.md#r7) |  |  |  |  |
| [**D11**](#appendix--d11-decision-brief) | Who owns customer support, through which channel, with what coverage, escalation and response expectation? | **APPROVED** | [R4](risk-register-v6.md#r4), [R10](risk-register-v6.md#r10) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D11](#recorded-decision-d11) |
| [**D12**](#appendix--d12-decision-brief) | Track B only: are V5's commercial answers D2–D9 signed and how, which merchant account receives payment, how the catalog is published, who activates billing, and who owns refunds, disputes, reconciliation and webhook failures? V5 D10–D12 (operator boundary) are not carried. | **NOT APPLICABLE** | [R3](risk-register-v6.md#r3) | — | — | — | Track A chosen in [Recorded decision D1](#recorded-decision-d1) |
| [**D13**](#appendix--d13-decision-brief-sessions-and-security-response) | Are tenant MFA/SSO, broader admin audit, a session-revocation UI and origin-bound widget auth required or deferred? | **APPROVED** | [R10](risk-register-v6.md#r10), [R11](risk-register-v6.md#r11), [R12](risk-register-v6.md#r12), [R13](risk-register-v6.md#r13) | Jacky | Repository owner, single approver for all roles | 2026-11-24 | [Recorded decision D13](#recorded-decision-d13) |

**Signing a row.** Put the approver's name, role and date in the row, put the evidence path or link in the last cell, and change the status cell from **UNAPPROVED** to **APPROVED**. Then copy the same four facts into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into the risk rows named in the register, as “How an approval gets recorded” below describes. A row that is PROPOSED or BLOCKED stays unsigned, and no task whose decision is unsigned may start.

## Status vocabulary

- **UNAPPROVED** — no approver, date or evidence recorded. D9 and D10 remain in this state for Wave 2 and Wave 3.
- **PROPOSED** — a candidate exists but no approver has accepted it. Still not an approval, and no dependent task may start.
- **BLOCKED** — an external party (merchant, legal, vendor, customer) has not supplied what the decision needs.
- **APPROVED** — approver named, date recorded, evidence linked. Only then may the dependent task start.

## What the approved scope keeps off

- Wave 1 has started with V6-10 (production-config validation), V6-11 (platform-owner control, console-off scope — partial, task unticked) and V6-13 (D6 upload enforcement); no tenant-identity, session or audit work (V6-12, V6-14…V6-16) is implemented by this record. V6-11 added no MFA/SSO or operator network: it made the approved off state fail closed in production, pinned that the switch is not host- or proxy-derived, and recorded the disable/recovery exercise.
- `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false`; `/api/platform` remains a 404. Track B and D12 are out of scope.
- Uploads follow the admin-only, format- and size-limited policy recorded in D6, enforced by V6-13 on all five upload routes; they still land in the local `uploads/` directory, so the public launch cohort also needs a durable storage adapter.
- No production deployment, no release tag, and no SLO, support promise or pricing statement is published; D3's 99.5%/24h/8h target is an internal operating target until V6-41 approves customer-facing copy.
- Wave 0's tasks are V6-01…V6-04, all completed; their evidence is in [`plans/PLAN_V6.md`](../plans/PLAN_V6.md) §6 and gate V6-0G.

## Out of scope of this record

Every decision [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) lists now has an appendix here, D12 included. D12 is out of scope because Track A is the launch track: billing stays off and the paid surfaces stay 404. D9 and D10 are briefed here even though they gate Wave 2 and Wave 3 tasks, because R5 and R7 have no other decision to wait on; both remain unapproved. D12 gates paid activation (V6-51/gate V6-6G), not the Wave 0 gate, and carries only V5's commercial answers D2–D9: V5 D10–D12 are the operator boundary, V6 D5 takes only the console's authentication requirement, and the rest stays open in `plans/PLAN_V5.md` §3.

## How an approval gets recorded

1. The named approver supplies the decision, the date and the evidence (path or link) in the row.
2. The row's status changes from UNAPPROVED to APPROVED, and the same facts are copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks).
3. Only then may the dependent task start; a task whose dependency is PROPOSED or BLOCKED stays unticked.

## Recorded decisions — 2026-11-24

Approver for every row below: **Jacky**, repository owner, recorded as the single
approver for all roles at the owner's direction on 2026-11-24. A single-person
approval is a real approval for this repository but it is not independent review;
V6-03's threat-model classification and the risk register record that limitation.
The launch track is **Track A (hosted core, billing off)**; **D12 is not applicable**;
**D9 and D10 remain UNAPPROVED** and continue to block V6-20 and V6-30/V6-32/V6-33.

### Recorded decision D1

**Track A — hosted core with `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false`; public registration stays open; cohort is Vietnam; data categories are public website content, chat transcripts and contact details (name/email); an empty public plan catalog is accepted, so `/pricing` shows its being-finalised state.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-01 and the scope half of V6-02.
- Consequences: no Stripe merchant account, no plan/price publication, no trial, refund or billing legal copy, and no D12 answer in this launch. V5's operator/commercial answers stay open.
- Launch copy may not state a price, guarantee, certification or feature beyond this scope. V6-41 owns the approved public copy.
- Residual: public registration without tenant MFA or email-verification changes is accepted under D13's deferral until 2027-02-28.

### Recorded decision D2

**Managed containers for the API and the worker (separate deploy units), managed PostgreSQL with pgvector, managed Redis, the built SPA served from a CDN, object storage as the target for uploaded bytes, and TLS terminated at the managed ingress.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-10's validator target and V6-40's runbook.
- Consequences: `RATE_LIMIT_BACKEND=redis` is mandatory (more than one instance); `TRUSTED_PROXY_IPS` must list the ingress addresses; `CORS_ORIGINS` lists the exact API/SPA origins; PostgreSQL and Redis are private-network only; the worker has no inbound path; the proxy must not buffer `/api/chat/stream`, `/api/chat/messages/stream` or `/api/inbox/events`.
- Deploy is a rolling replacement of immutable artifacts with backward-compatible migrations (expand now, contract later); rollback redeploys the previous artifact and fixes the schema forward rather than running `alembic downgrade`, because M11/M12 downgrades discard billing and operator state.
- **Object storage is not implemented today.** `api/upload.py` writes to a local `uploads/` directory and `services/retention.py` unlinks from it. The D6 admin-only policy has been enforced since V6-13, so the remaining requirement is the object-storage adapter (a V6-40 prerequisite): until it exists on the managed containers, uploads stay closed for the launch cohort.
- The architecture and threat-model classification this decision feeds is [`docs/architecture-v6.md`](architecture-v6.md).

### Recorded decision D3

**99.5% monthly availability, RPO 24 hours, RTO 8 hours; encrypted daily database backups kept 30 days; upload-volume backups on the same schedule.**

- Approver/date: Jacky, 2026-11-24. Unblocks the objectives V6-21 alerts on and V6-42's restore is measured against.
- Measurement: availability is measured monthly from an external check on the public API origin and `/health`; it is an internal operating target until V6-41 approves customer-facing wording. No service credits or contractual remedy are created by this decision.
- No planned-maintenance carve-out is claimed: planned work counts against the 99.5% target until a window policy is approved.
- Redis state (queue and counters) is treated as rebuildable, not backed up; a restore must reconcile the database with the upload volume per V6-42.

### Recorded decision D4

**Fail-closed production profile: required non-default secrets, exact CORS origins, `SQL_ECHO=false`, the Redis rate-limit backend, API docs hidden, and an explicit trusted-proxy list.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-10.
- Required and fatal when the production profile is on: a non-default `JWT_SECRET_KEY`; `API_KEY_PEPPER` when `/api/v1` is exposed; `INTEGRATION_WEBHOOK_SECRET` when integrations are enabled; `CORS_ORIGINS` with no `*`; `RATE_LIMIT_BACKEND=redis`; `TRUSTED_PROXY_IPS` matching the ingress; `SQL_ECHO=false`; `/docs`, `/redoc` and `/openapi.json` disabled; model-provider and mail settings required only on the paths that use them.
- The validator reports setting **names** only, never values, and development/test defaults stay usable. The environment flag the code does not yet have (`APP_ENV`/equivalent) is added by V6-10.
- `SESSION_TOKEN_MODE` and `EMBED_TOKEN_MODE` stay `compat` per D13; D4 does not change them.
- **Clarification (2026-11-24): `INTEGRATION_WEBHOOK_SECRET` is required whenever the production profile is on — not only once a tenant has enabled a webhook.** This record's "when integrations are enabled" cannot be read as a per-tenant condition because there is no enablement switch to gate on: `/api/integrations` is mounted unconditionally in every profile and any tenant admin may create and enable a `webhook` integration at any time, so a boot-time check for an enabled row would be satisfied by a row created a minute later (and, on a fresh database, by no row at all). The outbound signature is computed with `config.INTEGRATION_WEBHOOK_SECRET or ""` (`services/integrations.py`), so an unset secret yields a signature that anyone can recompute, and a receiver verifying with the same empty key cannot tell our payload from a forged one. Startup is the only point that covers an always-mounted surface, so the requirement fails closed there; `API_KEY_PEPPER` stays mandatory for the same reason while `/api/v1` is mounted. Covered by `tests/test_production_config.py::test_webhook_secret_is_required_even_without_tenant_integrations`.

### Recorded decision D5

**The platform console stays disabled for this launch: `PLATFORM_CONSOLE_ENABLED=false`, no MFA/SSO or operator-only network is implemented, owner Jacky, review by 2027-02-28.**

- Approver/date: Jacky, 2026-11-24. Supplies the operator half of V6-02; V6-11 is partially implemented on this decision's console-off branch and stays unticked until the control it requires exists.
- Emergency disable is the flag (it makes `/api/platform` a 404) plus `scripts/platform_owner.py revoke` for a compromised grant. Bootstrap/recovery stays database access through that CLI, as `docs/platform.md` records; whoever holds production database credentials is the real root of this boundary.
- Reopening the console requires a new approved D5 answer naming an ingress-enforced MFA/SSO or operator-only network and an exercise of it; the UI confirmation checkbox is not authentication.
- Residual: no operator session re-authentication, no console sign-in audit and no independent review are accepted with the expiry above.
- **Partially implemented by V6-11 (2026-11-24, console-off scope — task unticked):** `production_config_errors` refuses `PLATFORM_CONSOLE_ENABLED=true` under `APP_ENV=production` (setting name only), so the approved state is enforced at boot instead of left to a deployment's configuration. `tests/test_platform_owner.py::ConsoleOffAtTheIngressTests` pins that the switch hides every `/api/platform` route from a granted operator and a tenant admin with the gate's own 404 body, that `Host`/`X-Forwarded-*`/`Origin` neither reveal the surface nor replace the owner check, that every route carries the gate dependency, and that toggling the switch preserves grants and audit rows. `scripts/exercise_platform_disable.py` is the recorded disable/recovery exercise (**14/14** checks): CLI grant, hidden surface, revocation refused on the next request, re-grant recovery, then the switch off again with grants, history and audit intact. **Still blocked:** no MFA/SSO, operator re-authentication or private operator network exists, and no production ingress exists to test one at, so re-opening the console needs a new D5 answer plus an exercise of that control at the real edge.

### Recorded decision D6

**Uploads are restricted to tenant administrators, limited to the formats the parsers support (PDF, DOCX, PPTX, TXT/Markdown, HTML) and the existing `MAX_UPLOAD_MB=20` ceiling; no scanner is integrated, and that residual is accepted with an owner and expiry.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-13; turns R9 into a signed acceptance.
- Consequences: the four remote-import routes (`/api/uploads/url`, `/youtube`, `/notion`, `/google-drive`) follow the same admin-only rule; unsupported extensions and oversize files are refused; there is no quarantine because there is no scanner, and the "scanner unavailable" case stays out of scope until a scanner is approved.
- **Implemented by V6-13 (2026-11-24):** all five upload routes now require a tenant admin, the extension allowlist refuses every format outside the list before a byte is written, and the 20 MB ceiling is unchanged. Residual: no scanner and no MIME-versus-extension cross-check; uploads still write to the local `uploads/` directory until a durable object-storage adapter exists.
- Residual owner Jacky, expiry 2027-02-28, recorded against R9.

### Recorded decision D7

**Keep the application's existing per-company retention policy and its current default; keep encrypted backups 30 days; keep the platform audit trail 1 year; privacy/legal owner is Jacky; erasure and export endpoints remain the data-subject path.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-41 and the retention side of V6-42.
- Deletion semantics: user/company erasure and the retention purge remove product rows immediately through the existing services; copies in backups expire with the 30-day backup retention, so a data-subject deletion is complete in the live system at once and in backups within 30 days. Backup expiry is enforced by the backup schedule, not by the application.
- Audit retention: `platform_audit_logs` is append-only and retained 1 year; no pruning job exists yet, so V6-14/V6-42 must add or document the enforcement.
- No new retention default is introduced by this decision; the company setting remains authoritative and can only be lowered within its existing validation.

### Recorded decision D8

**Structured, redacted application logs plus the existing `/health` endpoint and a minimal alert set; no observability vendor, no APM and no error-tracking SaaS for this launch.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-21/V6-22.
- Alert set: API 5xx rate and API-down; database unreachable; Redis unreachable; worker heartbeat stale and queue age/depth above threshold; repeated job failure. Stripe/webhook alerts apply only on Track B, which is not this launch.
- Redaction rule: no password, bearer token, API key, integration token, card data, raw webhook body or full transcript in any log line; `SQL_ECHO=false` is part of D4; provider errors keep the existing `safe_error` redaction. Log retention follows a 30-day host default approved here; access is limited to the owner.
- `/health` keeps its current contract and status codes; liveness/readiness split, if needed, is additive and must not restart a merely degraded process.
- **Implemented by V6-22 (2026-11-24):** `core/logging.py` writes one JSON event per line through `log_event`/`log_exception`, with a central redactor (sensitive field names at any depth, bearer/Stripe/webhook/Slack/JWT-shaped strings and email addresses in text, bounded fields, no `repr`), exception type + category + scrubbed message (a traceback only at `LOG_LEVEL=DEBUG`), and a request id from `X-Request-ID` echoed on the response plus one id per worker job. Every `print()` under `src/` was converted (last one: `rag.ask_stream`'s traceback message), `main.py` installs the middleware and formatter, `/health` is untouched, and `tests/test_logging.py` pins redaction, JSON shape, correlation ids, the 4xx/5xx access levels and handler idempotency. **Implemented by V6-21 (2026-11-24):** the alert set is code, not a vendor. The worker publishes a self-expiring heartbeat, a queue-pop time and a windowed job-failure counter into Redis; `core/telemetry.py` turns those plus `LLEN queue:jobs` and this process's rolling 5xx window into the approved alerts (`api.database_unreachable`, `api.redis_unreachable`, `api.error_rate`, `worker.heartbeat_missing`/`heartbeat_stale`, `queue.depth_high`, `queue.age_high`, `worker.job_failures`), each with a stable code, a severity and aggregate evidence only; every threshold is environment configuration. `GET /api/ops/status` serves the snapshot behind `OPS_STATUS_TOKEN` (404 while unset, 401 on a wrong token, never echoing it) and `scripts/ops_status.py` is the external check whose exit code is the alert. `/health` keeps its contract; `/health/live` checks nothing (no crash-loop restart for a degraded process) and `/health/ready` requires the database with Redis reported as degraded on a 200. **Per-instance, not aggregate:** the 5xx window is held in the API process and the snapshot is answered by one instance, and the worker heartbeat/pop keys are a single document overwritten by every worker, so behind the ingress the alert rate is that instance's own and the heartbeat view proves only that some worker is alive and the queue is draining — not the fleet's error rate, every replica's health or per-worker progress. What the external check proves is exactly that: the instance it reached serves HTTP, can reach the database, and sees a fresh heartbeat and a consuming queue. Nothing aggregates these counters because D8 chose no vendor; a fleet view is later work (V6-23/V6-40). **Unset `OPS_STATUS_TOKEN`:** the route is absent (404) in every environment, and that is deliberate — it exposes nothing, so it is fail-closed without being a boot failure, and a production boot logs one `config.ops_status_disabled` warning instead of refusing to start. The validator stays out of it because the gap is visibility, not security: an operator who never sets the token has a working API with no alert path, which the warning names and the deploy runbook must treat as a missing step. **Still blocked:** the Done-when's staging fault injection needs the V6-40 environment, so no alert has fired on real infrastructure; alert transport is the host's cron/monitor reading the exit code (no shipper because D8 chose no vendor), and 30-day log rotation remains a host concern with no code.

### Recorded decision D11

**Support owner Jacky, contact `tdhungit@gmail.com`, coverage Monday–Friday 09:00–17:00 ICT, acknowledgement within 1 business day, no resolution-time commitment.**

- Approver/date: Jacky, 2026-11-24. Supplies the support half of V6-02 and the details V6-41 publishes.
- Escalation: the owner is the only responder; there is no deputy and no paging rotation, and that single-person residual is accepted with an expiry of 2027-02-28. A service-down report is handled best-effort inside the same window.
- Channel: email only; no portal and no phone. The published address goes into `platform_settings.support_contact_email` and the same text must appear in the app, footer and privacy notice when V6-41 approves the copy. The address above is a personal mailbox and must be confirmed or replaced before it is published.
- Support-side data access is not audited (only `platform_audit_logs` records operator mutations); that residual is accepted against R10 until 2027-02-28.

### Recorded decision D13

**Defer all four tenant-side controls to 2027-02-28: tenant MFA/SSO, broader admin audit, a session-revocation UI and origin-bound widget authentication.**

- Approver/date: Jacky, 2026-11-24. Unblocks V6-12/V6-14/V6-15/V6-16 as deferrals.
- Tenant MFA/SSO: not built; password login plus the 24-hour JWT stays; no login or launch copy may claim a second factor or federated login. The residual is [R13](risk-register-v6.md#r13).
- Admin audit: only the platform-owner boundary is audited; tenant admin actions (settings, users, API keys, deletions, export/erasure) stay unaudited until V6-14, with the residual accepted.
- Session revocation: account deactivation and user deletion end access immediately, but there is no way to end one session or revoke a live JWT; `DELETE /api/company/users/{id}` and JWT-secret rotation remain the incident tools.
- Embed/origin: `SESSION_TOKEN_MODE=compat` and `EMBED_TOKEN_MODE=compat` stay; K18's soft Origin/Referer boundary remains accepted.
- Residuals R10, R11, R12 and R13 are owned by Jacky with expiry 2027-02-28; a review before that date must either implement a control or record a new deferral.

## Appendix — D1 decision brief

**Status: D1 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D1](#recorded-decision-d1): Track A, public registration, Vietnam cohort, empty plan catalog accepted. This appendix keeps the options and evidence as the reasoning behind it.

### The question

Which launch is being approved — **Track A** (hosted core, billing and platform console off), **Track B** (paid SaaS plus the operator console), or **both** — and, for whichever is chosen: which customers, in which regions, with which data types, and with public registration open or invite-only? The answer decides whether V6-01 has a scope to record, and whether gate V6-6G (paid activation) is in scope at all.

### Options and consequences

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — hosted core, billing off** | `plans/PLAN_V6.md` §3's Track A: the approved core product, launched to a controlled cohort, with `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false`. | Gate **V6-5G** is the only launch gate; V6-6G does not apply. No Stripe merchant account, plan catalog, price, refund/trial policy or billing legal copy is needed. The public pricing surface renders its being-finalised state, so the approver must accept that state for the cohort or approve content before launch. V5's commercial answers (D2–D9) stay open, as do the operator answers (D10–D12); enabling billing later is a separate authorized change with its own gate and a decision about existing companies. Core support, privacy and retention content is still required (V6 D7/D11, V6-41). |
| **B — paid SaaS and platform operations** | Track B: the core launch plus self-serve paid plans and the operator console. | Requires everything in A **and** the V5 prerequisites: an approved catalog/limits/terms set, legal and support copy, a merchant account with test-mode access, a real Stripe test-mode rehearsal, and the V6 D5 control actually enforced at the ingress before the console is exposed. Gate **V6-6G** must pass independently of V6-5G, and live activation is a separate staged change with monitoring, abort thresholds and a rollback owner. This is the longest path to any launch, because core and commercial readiness must both land. |
| **Both — core first, paid later** | Approve Track A now and Track B as a later, separately gated step. | The core launch is not held behind commercial work, but there are two go/no-go records, two sets of customer-facing promises to keep consistent, and a decision about whether the first cohort is grandfathered or price-protected when paid plans go live. The pricing-state question from A must still be answered for the first cohort, and B's prerequisites still apply before any payment. |

### Exact evidence an approver must sign

1. The track chosen, stated explicitly (A, B, or both, with the order).
2. The cohort: who is invited, roughly how many, and whether it is internal, beta or external — supplied by the approver.
3. Registration policy: open or invite-only, and how an invitation is issued.
4. The regions where data is stored and processed, and the data types accepted, listed per category (for example chat transcripts, uploaded files, contact details).
5. The included features, and the features or flags that stay off at launch.
6. For the cohort's pricing surface: accept the empty-catalog being-finalised state at launch, or record that the catalog content will be approved under D12 before any price is published (required for B or both).
7. For B or both: the statement that the V5 commercial answers (D2–D9), the merchant account, the operational owner and the live-activation authority are D12 prerequisites that this row does not approve, and that D12 must be signed before V6-51 and gate V6-6G.
8. Sign-off on launch copy: no price, guarantee, SLO, certification or feature claim beyond the approved scope.
9. The approver's role, the date, and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R3](risk-register-v6.md#r3) (the track a paid launch still waits on) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D1 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-01 and the scope half of V6-02. Gate V6-0G was signed on 2026-11-24 together with the other nine decisions, so Wave 1 is unblocked but not started.

## Appendix — D3 decision brief

**Status: D3 is APPROVED (2026-11-24).** The signed target is [Recorded decision D3](#recorded-decision-d3): 99.5% monthly, RPO 24h, RTO 8h, 30-day backups. This brief keeps the options and evidence as the reasoning behind it.

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
5. Capacity assumptions the promise rests on: expected peak demand, provider rate limits and the headroom assumed in the database, Redis and worker sizing D2 records — as supplied by business/operations, not derived by engineering.
6. The §4 maintenance-window policy, including the notice channel and the freeze end condition if option C is chosen.
7. The §3 support coverage: who answers, through which channel, in which hours, and the escalation target. (D11 names the support owner; this decision records the coverage the promise needs.)
8. The exclusions the promise relies on: which third-party dependencies, customer-side causes and events are outside it.
9. Where status and incidents are communicated, if the promise includes any.
10. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R4](risk-register-v6.md#r4) (operational ownership), [R6](risk-register-v6.md#r6) (the alert thresholds) and [R8](risk-register-v6.md#r8) (the approved RPO/RTO) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D3 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks the objective half of V6-02 and gives V6-21 its alert thresholds and V6-42 its restore targets. Gate V6-0G was signed on 2026-11-24; Wave 1 is unblocked but not started.

## Appendix — D7 decision brief

**Status: D7 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D7](#recorded-decision-d7): existing retention default, 30-day backups, 1-year audit retention, owner named. This brief keeps the options and evidence as the reasoning behind it.

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
4. Backup expiry, backup access control, and the restore-time rule for data deleted after the backup was taken, with the re-deletion step stated as a pass condition of V6-42's restore rehearsal. That rehearsal is V6-42 evidence, checked after this signature.
5. The deletion path and actor for a user and for a company (tenant admin, support, platform owner), whether it is immediate or pending, and the evidence a customer receives.
6. The legal or contractual exceptions that outlive deletion, stated explicitly rather than implied.
7. The privacy-notice wording that matches the behaviour above (V6-41), with no promise the code cannot keep.
8. The owner and channel for data-subject requests and how they are recorded (adjacent to D11).
9. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R8](risk-register-v6.md#r8) (backup expiry and restore) and [R10](risk-register-v6.md#r10) (audit retention) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D7 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-41 and the retention side of V6-42, and settles the retention questions inside V6-14 and V6-15. Gate V6-0G was signed on 2026-11-24; Wave 1 is unblocked but not started.

## Appendix — D11 decision brief

**Status: D11 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D11](#recorded-decision-d11): owner Jacky, email contact, weekday coverage and 1-business-day acknowledgement. This brief keeps the options and evidence as the reasoning behind it.

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
6. The support-side data access: which staff or vendor may read which tenant data, through which tool, and how that access is audited — or the explicit statement that it is not audited and the residual accepted against R10.
7. The exact published text for the marketing footer, the app and the privacy notice, containing no promise the owner has not accepted.
8. The value to set in `platform_settings.support_contact_email`, and the person who maintains it; until it is set the footer correctly shows no address.
9. The approver's role, date and evidence path — recorded in [the D11 row](#decision-register--one-page-to-sign), copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R4](risk-register-v6.md#r4) (named support and incident ownership) and [risk R10](risk-register-v6.md#r10) (the support-side data-access residual) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D11 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which supplies the support details V6-41 publishes, the support-ownership half of V6-02 and the support-side data-access answer R10 waits on — audited, or an explicit statement that it is not and a signed residual with an expiry. Gate V6-0G was signed on 2026-11-24; Wave 1 is unblocked but not started.

## Appendix — D2 decision brief

**Status: D2 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D2](#recorded-decision-d2) and the resulting diagram/runbook is [`docs/architecture-v6.md`](architecture-v6.md). This brief keeps the options and evidence as the reasoning behind it.

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
- **D9 owns queue survivability**, but this row decides whether Redis persists, whether eviction can drop keys and whether a restart loses queued work; those facts belong in [the D9 brief](#appendix--d9-decision-brief).
- **D1 decides whether Track B is in scope**, which adds the payment provider's webhook ingress and the operator console's origin to the boundary description.

### Exact evidence an approver must sign

1. A component inventory — API process, worker process, PostgreSQL with pgvector, Redis, upload volume, admin build, ingress/TLS — each marked self-managed or managed, with the operator who owns it. Any provider name, region and account belongs in this signed evidence; this brief deliberately contains none.
2. The network boundary description: what is reachable from the public internet and on which paths, what is private, and the egress destinations required (model/embedding provider, SMTP, and for Track B the payment provider and its webhook ingress).
3. The TLS termination point, certificate source and renewal owner, and the exact external scheme, host and port the application sees — because `GET /chat/{id}`'s embed allowlist compares `request.base_url` exactly.
4. The `TRUSTED_PROXY_IPS` value and confirmation that `Host`, `X-Forwarded-For` and `X-Forwarded-Proto` are forwarded; without it the limiter keys on the proxy and every visitor shares a bucket.
5. The `CORS_ORIGINS` list and the admin app's public URL (`FRONTEND_URL`), consistent with option 5.
6. Sizing and capacity, supplied by the operator: API instance count, worker count, database size and connection budget, Redis memory and eviction policy, upload volume size and headroom. D3's capacity assumptions are then written against these numbers.
7. The upload volume's identity — local path, shared mount or bucket — whether it survives a host replacement, who backs it up, and, if it stays local, confirmation that only one API instance serves and purges it.
8. The frontend pipeline: where the build is served, the `VITE_BACKEND_URL` baked into it, and how `index.html` and `/widget.js?v=…` are invalidated after a deploy.
9. The deploy procedure this row selects: the artifact and mechanism, the order relative to `alembic upgrade head`, whether requests are served during it, and who executes it — with the rehearsal that proves it stated as a pass condition. The rehearsal record itself is V6-40 evidence, checked after this signature.
10. The rollback procedure this row selects: how many previous artifacts are retained, the migration policy (downgrade, forward-fix or restore), and the mixed-version rule for the API, worker and schema, with the rehearsal's pass conditions stated — the record itself is V6-40 evidence, not a description.
11. The environment list: production and whatever non-production environment exists, how secrets and data differ, and which data may never appear outside production (D7/D8).
12. The health contract the ingress uses — `/health` as it exists today (JSON with `db`, `redis` and limiter state) or a separate readiness path — plus the proxy's buffering and idle-timeout settings for the three SSE endpoints.
13. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R4](risk-register-v6.md#r4) (topology verification), [R6](risk-register-v6.md#r6) (the deployment workflow behind `/health`) and [R8](risk-register-v6.md#r8) (TLS, private networking, backups) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D2 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-10 (the validator needs to know which settings are required in this environment) and V6-40 (a deploy/rollback runbook needs a mechanism to describe), and supplies the topology half of V6-02's operating model. Gate V6-0G was signed on 2026-11-24; Wave 1 is unblocked but not started.

## Appendix — D4 decision brief

**Status: D4 is APPROVED (2026-11-24).** The signed profile is [Recorded decision D4](#recorded-decision-d4): fail-closed production validation with exact CORS, required secrets, Redis limiter, hidden docs and trusted proxies. This brief keeps the options and evidence as the reasoning behind it.

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
9. The requirement that the approved policy leave development, the unit suites and `scripts/gate_v5_5g` runnable without production secrets, and the demonstration V6-10 must produce — a validator that breaks them is not acceptable. The demonstration is V6-10 evidence, after this signature.
10. The names of the settings whose absence the deployment must treat as fatal, agreed with the operator who will run the start-up, so the validator can be written against a signed list rather than an engineering guess.
11. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R1](risk-register-v6.md#r1) (secure boot) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D4 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-10 (the production-mode validator needs a signed required-set and a defined failure mode) and supplies the configuration half of V6-02's operating model. Gate V6-0G was signed on 2026-11-24; Wave 1 is unblocked but not started.

## Appendix — D5 decision brief

**Status: D5 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D5](#recorded-decision-d5): the console stays disabled, with the MFA/operator-network question deferred to 2027-02-28 and an owner named. This brief keeps the options and evidence as the reasoning behind it.

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
10. The acceptance scenarios V6-11 must demonstrate in a non-production environment — sign-in, refusal for a tenant account, a grant, a mutation, a revocation and a recovery — agreed now, with the evidence path recorded. The demonstration is V6-11 evidence, after this signature.
11. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R2](risk-register-v6.md#r2) (operator security) and [R3](risk-register-v6.md#r3) (the operator half of the paid-launch row) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D5 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which is the condition for exposing the platform console at all (V6-11) and supplies the operator half of V6-02's ownership model. Gate V6-0G was signed on 2026-11-24 with the console kept disabled, so `PLATFORM_CONSOLE_ENABLED=false` remains the only operating control until a new D5 answer approves an ingress-enforced alternative.

## Appendix — D6 decision brief

**Status: D6 is APPROVED (2026-11-24).** The signed policy is [Recorded decision D6](#recorded-decision-d6): admin-only uploads, parser-supported formats, the existing 20 MB ceiling, no scanner and an owned residual to 2027-02-28. The limits quoted below are what the code does today, recorded as evidence.

### The question

What happens to a file a customer supplies before it becomes knowledge the assistant answers from — whether the upload surface is opened at all for the launch cohort, whether untrusted bytes are scanned and by what kind of control, which formats and sizes are accepted, what happens to a file that fails a check, and what the service does while the check is unavailable. The answer is what V6-13 implements; today the answer is "the surface is open to every signed-in account, nothing is scanned and no format is refused".

### What the code does today (evidence, not a decision)

- **Five entry points, all behind the same login.** `api/upload.py` exposes `POST /api/uploads/` (multipart), `/url`, `/youtube`, `/notion` and `/google-drive`, and every one depends on `get_current_user` — **any** authenticated account of any role in any company, not only an admin or manager. Nothing in `/api/v1` exposes uploads.
- **No format check on the file itself.** The multipart route derives the extension from the supplied filename (`os.path.splitext`) and stores `file.content_type` as sent; there is no allowlist of extensions or MIME types anywhere on the upload path, so a file named `.pdf` is accepted as a PDF and anything else named `.txt` is accepted as text.
- **One size limit, enforced while streaming.** `MAX_UPLOAD_MB` (default `20`) becomes `MAX_UPLOAD_BYTES` (`core/config.py:258–259`) and the multipart route aborts mid-stream, deleting the partial file; the four import routes enforce the same ceiling on the declared or streamed length (`services/sources.py`). There is no per-company quota on stored uploads.
- **Nothing scans anything.** There is no antivirus, malware or content-scanning code in the tree; the only match for “scan” on this path is a comment about a remote provider's own warning page. `docs/security.md` states plainly that uploads are **not** virus-scanned, and [risk R9](risk-register-v6.md#r9) records it as accept-with-owner.
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
3. If a check is chosen, proof that it covers **all five** entry points — multipart, URL, YouTube, Notion, Google Drive — rather than the form upload alone; under option 2A, the statement that no entry point is checked, with the residual recorded in item 10.
4. The behaviour for a failing file (§3), including what the user is told and what the operator can see.
5. The accepted formats and the exact size limit per entry point, with the decompression rule stated separately from the stored-bytes rule.
6. The behaviour while the check is unavailable (§5), the user-visible message, and the maximum time a file may wait in quarantine if option 5C is chosen.
7. The quarantine state's lifetime, who may release or delete it, and how it is excluded from parsing and from answers until cleared.
8. The latency and availability budget the check adds, consistent with D3 if it sits on the request path.
9. The audit or log event a refusal produces, its retention and its redaction (D8/D7).
10. The residual risk statement if option 2A is chosen: what a malicious file can reach (the parser process and the extracted text an answer may quote), who accepts it, and when it is reviewed.
11. The acceptance test V6-13 must pass: a known-bad fixture uploaded through each chosen entry point, ending accepted, quarantined or refused as decided, in a non-production environment, with the evidence path recorded. The result is V6-13 evidence, after this signature.
12. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R9](risk-register-v6.md#r9) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D6 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-13 and turns R9 from an unowned P1 into either a mitigated control or a signed acceptance. Gate V6-0G was signed on 2026-11-24 and V6-13 enforced the admin-only policy on the same day; R9 is carried as a signed acceptance with an owner and a 2027-02-28 expiry.

## Appendix — D8 decision brief

**Status: D8 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D8](#recorded-decision-d8): redacted structured logs, `/health`, a minimal alert set and no vendor. Where it quotes what the code does, that is evidence.

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
5. The enforcement chosen (§3A/3B/3C) and the test that must prove it — the test is written with V6-21/V6-22, and its result is recorded after this signature.
6. Retention per stream (§4), the deletion mechanism, and whether log lines fall inside a customer erasure request — plus the confirmed retention of `platform_audit_logs`.
7. Who may read each stream and on what authority (§4C), consistent with D5.
8. The alert list and its responder (§5), derived from D3's SLOs, with the thresholds stated as part of the approval rather than before it.
9. The behaviour while telemetry is unavailable (§6), including any local buffer bound.
10. The worker's `print` calls: whether they are converted, left, or removed, and what happens to a job failure that is currently only printed.
11. The dry run V6-21/V6-22 must demonstrate in a non-production environment — one request, one failed job and one alert reaching the destination — agreed now, with the evidence path recorded. The dry run itself is that task's evidence, after this signature.
12. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R6](risk-register-v6.md#r6) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D8 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-21 and V6-22 and turns R6's "no observability vendor config" into either a named destination or a signed decision to keep telemetry in-house. Gate V6-0G was signed on 2026-11-24; until V6-21/V6-22 land the worker keeps printing, the logs keep going wherever the host sends them, and `docs/release-v5.md` row 9 stays pending.

## Appendix — D13 decision brief (sessions and security response)

**Status: D13 is APPROVED (2026-11-24).** The signed answer is [Recorded decision D13](#recorded-decision-d13): all four controls are deferred to 2027-02-28 with owned residuals, and `SESSION_TOKEN_MODE`/`EMBED_TOKEN_MODE` stay `compat`. This brief covers the four questions and keeps their options as the reasoning behind the deferral.

### The question

Which tenant-side security controls the launch carries: whether a company's own users must present a second factor or federate their identity, how much of a tenant admin's activity is recorded, whether a customer can see and end a session other than by deactivating the account, and whether the widget's public reads are bound to an origin by something stronger than a header a non-browser client can write. R10, R11 and R12 in `docs/risk-register-v6.md` are the rows these four answers move.

### What the code does today (evidence, not a decision)

- **One login method, one factor.** `POST /api/token` takes an email and password, verifies it with argon2 and returns a bearer JWT (`create_access_token`, which defaults to a fixed expiry of `timedelta(hours=24)`). Password reset is an emailed link. There is **no** second factor of any kind, no federated **login** and no passwordless path anywhere in the tree; the only OAuth text in the code is the Google Drive Picker access token, which is not an authentication path.
- **A bearer token in `localStorage`.** `frontend/src/utils/api.ts` stores the JWT in `localStorage` and attaches it as `Authorization`; logout is a client-side removal (`AuthContext.logout`) with **no logout route**, no refresh token and no token blacklist. `docs/security.md` records the trade-off: CSRF does not apply to a bearer API, but an XSS can read the token, so the frontend must stay free of untrusted HTML.
- **One server-side check already exists.** `core/auth.py::get_current_user` re-reads the user row on every request and requires `status == "active"`, so deactivating or deleting a user ends that account's access immediately even with a valid token. What does not exist is any way to end **one** session, or all sessions of a user, while the account stays usable: `DELETE /api/company/users/{id}` hard-deletes the user, and nothing lists or revokes a session (R11).
- **Tenant admin activity is not audited.** `docs/security.md` states it plainly: "No admin audit log. API keys keep a `revoked_at` and a last-used timestamp; other admin actions are not recorded." Settings writes, website and document deletion, user create/delete/role change, API-key mint and revoke, integration create and token rotation, and the privacy purge are all unaudited — the purge writes a log line (`api/privacy.py`) and nothing else. Only the **operator** boundary is audited (`platform_audit_logs`, append-only, secret-shaped detail redacted), and the inbox transcript read is explicitly not audited either (the company is the boundary).
- **The widget's origin check is soft by design.** `services/embed_guard.py` compares `Origin`/`Referer` against the website's origin, allows loopback, and accepts the API's own origin as first-party for the hosted page (exact scheme+host+port). A non-browser client sets that header freely, which the module's own docstring says; the optional `X-Embed-Token` is a public, replayable value (`EMBED_TOKEN_MODE` `compat` accepts a missing token, `enforce` requires a valid one), and the K4 session token guards history rather than the origin (`SESSION_TOKEN_MODE` `compat` still accepts a missing token for an unclaimed session). K18 is recorded as accepted, with the residual restated in `docs/security.md` §5.
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
| **B — audit a named set of tenant-admin mutations** | An append-only row for each action in a defined list, written in the same transaction as the change. | Answers the question customers actually ask and reuses the pattern the operator audit already proves; it needs the list agreed — that list is this decision's §2 answer, not another row's — a table and migration, a reader in the UI, and the same redaction discipline as `platform_audit_logs`. |
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
- **D13 owns the tenant-admin mutation list** the audit option B assumes; it is not V5 D11's operator mutation set, which covers different actions and is not re-listed here.
- **D6 and D13 meet at the upload/admin boundary** — an audited admin action is what makes "a compromised admin imported that file" answerable.
- **R10, R11, R12 and R13 are this decision's risk rows**; every "defer" must fill their owner and expiry.

### Exact evidence an approver must sign

1. For §1: **require** or **defer**, and if require, whether the factor applies to admins/managers or to every user, whether SSO is offered instead or beside it, and the recovery path for a lost factor.
2. For §1 deferral: the residual statement (a stolen password is a full tenant takeover) and its expiry, recorded against [R13](risk-register-v6.md#r13).
3. For §2: **require** or **defer**, and if require, the exact tenant-admin mutation list (this decision's §2 answer), where the row is written, and confirmation that it is in the same transaction as the change.
4. For §2: whether reads are audited at all, and if so what an audited read records without storing the transcript again.
5. The retention of every new audit row and its relationship to erasure requests (D7), plus confirmation that `platform_audit_logs` retention is settled at the same time.
6. For §3: **require** or **defer**, and if require, which of the options (per session / all sessions / short-lived plus refresh), who may revoke (self, company admin, both), and what the revocation check costs per request.
7. Confirmation of what already ends access today — the per-request `status == "active"` check and hard-deletion of a user — so the deferral is described accurately rather than as "no revocation exists".
8. For §4: **require** or **defer**, and if require, whether it is the existing switches, per-website origin data, or a new assertion design, with the snippet rollout and the customer impact stated.
9. The residual that remains after the chosen option — the K18 public-value caveat cannot be removed by any of these — and the row it is recorded against.
10. The role and permission model each answer implies (`admin`, `manager`, `user`), so a control cannot be bypassed by a role that was not considered.
11. The demonstration each **require** answer must produce in a non-production environment — an unenrolled login refused, an audited action producing one row, a revoked session refused on its next request, an off-origin read refused — agreed now as acceptance criteria, with the evidence path recorded. The demonstrations are V6-12/V6-14/V6-15/V6-16 evidence, checked after this signature.
12. The approver's role, date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [R10](risk-register-v6.md#r10), [R11](risk-register-v6.md#r11), [R12](risk-register-v6.md#r12) and [R13](risk-register-v6.md#r13) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D13 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED** — as four recorded require-or-defer answers, not as one blanket "yes" — which unblocks V6-12, V6-14 and V6-16, settles the embed/session posture V6-15 must follow, and turns R10, R11, R12 and R13 from unnamed residuals into either controls or signed acceptances with an expiry. Gate V6-0G was signed on 2026-11-24 with this deferral, so Wave 1 is unblocked but not started and no control in this brief is implemented. Sessions stay bearer-only, tenant admin actions stay unaudited, the widget keeps its soft origin check, and `EMBED_TOKEN_MODE`/`SESSION_TOKEN_MODE` stay at `compat` until the 2027-02-28 review.

## Appendix — D9 decision brief

**Status: D9 remains UNAPPROVED.** This brief lays out the choices for background-job delivery; it names no mechanism, no attempt limit or deadline, no backoff interval, no dead-letter owner and no replay authority, and it recommends none of the options. The windows and limits quoted below are what the code does today, recorded in `docs/worker-delivery.md` as evidence, not as a proposal.

### The question

What delivery guarantee applies to the jobs on `queue:jobs` — `ingest`, `digest`, `retention`, `topic_clusters`, `sitemap_scan` and `insights` — and for each of them: may a crash or a provider failure lose the job, run it twice, or leave it repeating forever? The answer decides the queue mechanism V6-20 builds, the retry and terminal-state rules, where a failed job becomes visible and who may replay it. It changes no job's work; it decides what happens to a job's work when the process holding it dies.

### What the code does today (evidence, not a decision)

- **The queue is a bare list.** `enqueue_job` is `LPUSH queue:jobs` (`services/redis.py:58`), and the consumer is `BRPOP queue:jobs` (`worker.py:167`) followed by dispatch. There is no acknowledgement, visibility timeout, attempt counter or dead-letter list: once `BRPOP` returns, the message exists only in the worker's memory, and a handler exception is caught, printed with a traceback, and the message is gone.
- **Each job type is recovered, or not, by its own record.** `ingest` has `claim_ingest` with a 6 h stale takeover (`STUCK_INGEST_AFTER`) plus `recover_stuck_ingests` at startup and on each scheduler tick; `digest` claims a unique `digest_log (company_id, period_start)` before the email and re-queues a claim older than `DIGEST_CHECK_SECONDS`; `topic_clusters` and `insights` take a unique row per window or conversation, skip a fresh claim and take over a stale one after 30 minutes. `retention` and `sitemap_scan` have no claim row at all: retention has a daily loop over an idempotent age cutoff, sitemap a best-effort Redis key with a TTL.
- **One known duplicate-send path, one known duplicate-spend path and one known stale-knowledge path.** A `digest` crash between the mail server accepting and the `sent_at` commit re-sends the period, and a partial send stamps the period so the failed recipients are never retried; `topic_clusters` and `insights` can repeat an embedding/naming or classification call after a crash; a `sitemap_scan` that commits its page diff and then loses the message leaves knowledge stale until the periodic re-crawl.
- **Nothing bounds repeats.** `digest`, `topic_clusters` and `insights` re-queue on a timer with no attempt counter, so a deterministic failure repeats every interval; only the claim windows bound concurrency.
- **A durable, claim-per-row pattern already runs here.** `integration_deliveries` records every event before its first send, claims each row with `SELECT … FOR UPDATE SKIP LOCKED`, and retries it on its own tick.

### Options and consequences

#### 1. Where the delivery guarantee lives

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — no queue-level guarantee (today)** | `LPUSH`/`BRPOP`, with each handler's claim, unique row or scheduler tick as the only recovery. | No new mechanism, no migration and no change to the job payloads; but the guarantee differs per job type, two types have none, a crash always loses the message, and recovery waits for a stale window or the next tick — a day for `retention`, a whole scan interval for a lost `sitemap_scan`. |
| **B — reliable Redis delivery** | A popped message moves to a per-worker processing list and is removed only after the handler returns; a reaper returns entries whose worker stopped. | Reuses the Redis the queue already runs on — no second datastore and no migration — and makes the queue at-least-once, so every handler must tolerate a repeat; but a flush, an eviction or a restart can still lose the main list and the processing lists together, and it needs a reaper interval plus a rule for a job whose worker vanished mid-send. |
| **C — durable job record** | Each job is a database row (written in the producer's transaction where one exists) and the worker claims rows with `FOR UPDATE SKIP LOCKED`, the pattern `integration_deliveries` already uses. | Survives a Redis loss and makes the backlog queryable and countable; requires a migration — which this row must then place in scope for V6-20 — a poll interval instead of a blocking pop, a settle/purge rule for finished rows (adjacent D7) and an index for the claim. |

#### 2. Which duplicate and loss cases are acceptable, by job type

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one rule for all six** | A single duplicate/loss statement applied to `ingest`, `digest`, `retention`, `topic_clusters`, `sitemap_scan` and `insights` alike. | Shortest to state and to test, and no classification work; but the six are not alike — a repeated `digest` is a duplicate email to a customer, a repeated `retention` deletes nothing twice and a lost `ingest` leaves partially refreshed knowledge — so one rule is either too loose for the send or stricter than the purge needs. |
| **B — three classes** | Each job type is placed in must-not-lose, must-not-duplicate or either-acceptable, and §1's mechanism is sized to the strictest class it carries. | Keeps the statement to three lines and lets a cheap job stay cheap; requires the approver to place all six, and a job that later changes class needs a recorded re-decision. |
| **C — one answer per job type** | Each of the six gets its own duplicate/loss answer, with no classes to belong to. | The most precise record and nothing to infer when one job's needs change; the longest to write and keep true, and two jobs that share an answer are still recorded twice, so a later job needs its own entry rather than a class to join. |

#### 3. Retry and terminal state

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — no retry; the next tick is the retry** | What the loops do today for `digest`/`topic_clusters`/`insights`, and what the 6 h stale window does for `ingest`. | Nothing to build; but a deterministic failure repeats on every tick for as long as the timer runs, is indistinguishable from a healthy backlog, and can spend provider credit on each repeat. |
| **B — a bounded number of attempts** | The job carries its attempt count and last failure; after the approved limit it stops in a terminal state that only a replay clears. | Bounds cost and noise and turns “this job is stuck” into a state rather than an inference; needs somewhere to keep the count and the failure (the queue entry, a job row or the handler's own claim row) and a rule for what clears the terminal state. |
| **C — attempts until an elapsed deadline** | Attempts continue with a growing backoff and stop when the approved deadline passes. | Absorbs an outage of unknown length without anyone deciding per job; but a deterministic failure keeps spending calls until the deadline, and the deadline is a target the approver has to choose and keep under review. |

#### 4. Where a failed job is visible

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — the log only (today)** | A caught exception is printed with a traceback and the message is gone. | Nothing to own or retain; but a failed job is not countable, not replayable and not visible to anyone who is not reading the log at that moment. |
| **B — a dead-letter list or table** | Terminal jobs move to a destination carrying the payload, the failure and the time, readable by an operator. | Failures become countable and replayable; needs its own expiry, redaction rule and access control (adjacent D7 and D8), and someone has to read it or it is a log with a query attached. |
| **C — the job's own state row** | The job's claim row carries the terminal state, and the backlog is a query over those rows. | Reuses the claims `ingest`, `digest`, `topic_clusters` and `insights` already have and needs no second destination; but `retention` and `sitemap_scan` have no row to record it in, and a later job type has to be given one deliberately. |

#### 5. Who may replay, and how

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — no replay** | A lost or stopped job is not re-created; the next scheduled run is the only recovery. | Nothing to build, authorize or document; but a lost `sitemap_scan` waits a whole interval, and a `digest` period already stamped as sent cannot be re-sent at all, so a partial send has no lever behind it. |
| **B — replay through the producer** | Each job type documents the command or endpoint that re-creates its work (a re-ingest, a window re-queue) and the idempotency key that makes the repeat safe. | No new interface, and the safety argument is written per type; but the operator must know the producer and have access to it, and work a producer cannot reproduce — a scan whose diff was committed, a stamped `digest` week — has no replay. |
| **C — replay the job record** | An operator action replays the stopped entry itself and writes an audit row (actor, job, time). | The trail an incident review needs, and it covers work a producer cannot reproduce because the payload is the record; adds an interface, an authorization decision and a redaction rule for the payload it shows, and it needs a record to replay from (§1 C or §4 B). |

### Exact evidence an approver must sign

1. The §1 mechanism, and — if a durable record is chosen — the statement in this row that a migration is in scope for V6-20.
2. The §2 statement, at the granularity chosen — one rule, three classes or six individual answers — covering each of the six job types, the rule for a job type added later, whether a crash may lose it or run it twice, and what makes an allowed repeat safe.
3. The §3 retry rule — the attempt limit or the elapsed deadline, the backoff, and where a stopped job rests and what clears it.
4. The §4 destination for a terminal job, who may read it, its retention or expiry, and which parts of its payload are redacted.
5. The §5 replay authority and procedure, the idempotency key each replay relies on, and — where the replay is recorded — where the audit row is written and who may read it.
6. For `digest` specifically: whether a duplicate send is accepted for the launch cohort, and if not, the guard that closes the window between the mail server accepting and `sent_at` committing.
7. The crash-window pass conditions V6-20 will be judged by, agreed now: which cases must pass — crash before the handler, during it, after an external send and before the job is acknowledged or removed, after a commit, and on a provider failure — on disposable infrastructure, never against data that matters, and where each result is recorded. The results are V6-20 and gate V6-2G evidence, checked after this signature because this decision is what unblocks them.
8. The retention rule for settled job records or dead-letter entries, if either is durable (adjacent D7).
9. The approver's role, the date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R5](risk-register-v6.md#r5) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D9 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-20 and turns R5 from an unowned P1 into a stated guarantee with a tested recovery path. V6-20 is a Wave 2 task. Gate V6-0G was signed on 2026-11-24 without D9, so this row still blocks V6-20; until it is signed the queue keeps its at-most-once behaviour and R5 stays open with its owner recorded.

## Appendix — D10 decision brief

**Status: D10 remains UNAPPROVED.** This brief lays out the choices for where the project's checks run; it names no vendor or product, sets no severity threshold, retention period or owner, and recommends none of the options. The commands and counts it quotes are what the checkout does today, recorded in `AGENTS.md` and [`plans/PLAN_V6.md`](../plans/PLAN_V6.md) §8 as evidence, not as a proposal.

### The question

Where do the checks the project already has run, which of them must pass before a change lands, how is the browser journey executed, how are dependencies reviewed, and what does a passing run authorise? The answer decides the workflow V6-30 adds, the browser runner V6-32 needs and the dependency and artifact rules V6-33 records. It adds no check of its own: every command named below exists today and is run by hand.

### What the code does today (evidence, not a decision)

- **No tracked workflow.** The checkout has no workflow directory, no CI configuration file and no `Makefile`: the commands in `AGENTS.md` and [`plans/PLAN_V6.md`](../plans/PLAN_V6.md) §8 are run on a developer's machine and their results transcribed into a document. Nothing runs on a push, and no result is attached to a commit.
- **The checks that exist.** `uv run python -m unittest discover -s tests` (64 modules / 1114 tests at the last recording), `node --test tests/*.mjs` (46), `uv run python -c "import site_gpt.app.main; import site_gpt.app.worker"`, `cd frontend && npm run build && npm run lint` (`tsc && vite build` and `eslint … --max-warnings 0`), `uv run alembic current` = `uv run alembic heads` = `0b22b30bf930`, `trail build`, plus the gate scripts under `scripts/`. `scripts/gate_v5_5g/run_all.sh` creates, migrates to head and drops its own `v5_gate_5g` database, refusing a name that does not start with `v5_gate_5g`, and needs no provider; `scripts/gate_v3_4g`, `scripts/gate_v4_4g` and `scripts/gate_v4_5g` regress earlier versions and need inputs this checkout does not have (a prior version's tree, fixed Redis ports, live providers).
- **Two runtimes, and a test that skips instead of failing.** `tests/test_widget_markdown.py` shells out to `node` and calls `skipTest` when it is absent, so a Python run on a machine without Node reports success with the widget checks skipped. `frontend/package.json` deliberately has no `test` script, so the frontend's only automated checks are build and lint.
- **Lockfiles are committed; runtime versions are prose.** `uv.lock` and `frontend/package-lock.json` exist, while Python 3.13.13 and Node v24.19.0 are recorded in documents and there is no `.python-version` or `.nvmrc` file for a runner to read.
- **Nothing is retained.** A run leaves terminal output in a shell: no test report, build artifact or digest is stored, and nothing ties a deployed build to a run that passed.
- **The browser item is already blocked.** V5-5G records the journey across `/`, `/pricing`, `/app` and `/platform` as **blocked** because that gate is headless, and there is no browser runner in the tree.

### Options and consequences

#### 1. Where the checks execute

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — where it runs today** | No workflow: the documented commands run on a developer's machine and the result is transcribed. | Nothing to configure, pay for or keep available, and no repository credential leaves the team's machines; but a check nobody ran is not evidence, results depend on the machine that ran them, and a release claim cannot be tied to a commit without a transcript. |
| **B — a hosted service triggered by the repository** | Push and pull-request events start the checks on infrastructure the service provides. | Runs without anyone remembering and attaches the result to the commit; needs an account, a credential-scoping rule for any job that needs one, images someone keeps current, and a policy for the workflow's own third-party dependencies. |
| **C — a runner on infrastructure the team operates** | The team installs, patches and keeps the runner available itself. | The runtime can be the target environment itself and no third party holds the repository's credentials; but the runner has to be patched, monitored and kept up (adjacent D2 and D8), and its result is trusted only as far as the runner is. |

#### 2. Which checks block a change

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — none required** | Every check is advisory; a change lands on review alone. | No waiting and no setup; but the suites and gate scripts that exist protect nothing at merge time, and the only record of a regression is someone noticing it later. |
| **B — a fast subset required, the rest scheduled** | The unit suites, node checks, imports and build/lint block; the database gate scripts and whatever §3 chooses for the browser run on a schedule or before a release. | Keeps the wait per change short and still catches the expensive regressions; but the schedule lags the change, so a defect those gates would catch lands first, and someone has to read the scheduled result. |
| **C — everything required** | Both suites, the imports, build/lint, the migration check, the gate scripts and whatever §3 chooses for the browser all block. | Nothing lands unchecked and every change is recorded the same way; but a change waits on a database-dropping gate and a browser run, and the gates that need inputs this checkout lacks have to be made self-contained first or they block every change. |

#### 3. How the browser journey runs

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — no automated browser (today)** | The journey is walked by hand and the pass is recorded as prose. | No runner to install or keep in step; but the journey is only as repeatable as the person and the day, and a regression is found when someone happens to look. |
| **B — a browser on the same runner as the checks** | That runner has a browser installed and drives the journey there; needs §1 B or C, because §1 A has no runner to install it on. | One environment carries both the checks and the browser, and the result attaches to the same run; needs the browser and its driver kept in step with the frontend, and the runner available whenever a change needs it. |
| **C — a hosted browser service** | The journey runs against a service that supplies the browser, per change or per release, wherever §1 puts the other checks. | Independent of the team's machines and able to cover several viewports in one run; adds a third party that receives the staging URL and any test credential, an account to keep, and a per-run cost. |

#### 4. Dependency review

The review V6-33 asks for covers vulnerability advisories and licence terms, and the options differ in when a person looks and whether a finding can stop a change; V6-33's SBOM question is recorded in evidence item 5.

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — review when a dependency changes** | A person reads the advisory feed and the licence terms for a package when it is added or bumped. | No tooling and no false blocking; but nothing reports a new advisory in an unchanged dependency, and nothing records that a review happened. |
| **B — a scheduled report with a named owner** | A report runs on a cadence covering advisories and licences, the owner reads it and records each decision; it never fails a build. | Nothing is blocked on a busy day and the decisions have an owner; but the exposure lasts as long as the cadence, and an unreviewed week looks the same as a clean one. |
| **C — a blocking threshold** | A report runs per change and fails it above a severity the approver sets, with an exception path. | Nothing above the threshold lands; but a new advisory can block unrelated work, the threshold has to be chosen and reviewed, and an exception needs an owner and an expiry or it becomes a permanent waiver. |

#### 5. What a passing run authorises

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — evidence only** | A person reads the run and deploys as a separate manual step from an approved commit; only logs are kept. | No workflow credential can change production and there is nothing to retain; but nothing ties the deployed build to the run that passed, and the logs disappear with the service's own retention. |
| **B — a named operator may deploy from that run** | Test reports and build artifacts are retained for an approved period, and the named operator deploys from the run that produced them. | The deployed thing is the tested thing, and the evidence outlives the run; needs an operator named in the approval, a rule for who may trigger the deploy, and retention that is enforced rather than assumed. |
| **C — the workflow deploys on its own** | A passing run on an approved branch deploys without a human step, retaining artifacts and recording a digest. | No human latency and no forgotten deploy; but a defect in the pipeline is a production change, rollback has to be automatic or rehearsed (V6-44), and the branch that may deploy has to be protected exactly as the deploy credential is. |

### Exact evidence an approver must sign

1. The §1 environment and the role or team that operates it.
2. The §2 blocking set: which of the commands above must pass before a change lands, which run on a schedule, and what a failure blocks.
3. The §3 browser choice and where its results will be recorded; if none is chosen, the recorded statement that the V5 browser item stays blocked, never a pass. The result itself is V6-32 evidence, checked after this signature because this decision is what unblocks the runner.
4. The §4 rule: what is reviewed (vulnerability advisories and licences, application dependencies, frontend dependencies or both), on what cadence, who reads it, and which severity stops a change.
5. The §5 deploy authority: who may deploy from a passing run, which artifacts and reports are retained (including whether an SBOM is emitted), for how long, and whether a digest or signature is required.
6. The credentials a workflow or runner may hold, their scope, and the guarantee that no production or live-provider secret is available to a job triggered by a change.
7. Which gate scripts run where; for `gate_v5_5g`, the name guard that keeps it on its own disposable database; for `gate_v3_4g`, the `GATE_DB` its own script drops and recreates; for `gate_v4_4g`/`gate_v4_5g`, the empty throwaway database the caller creates and drops; and the explicit recording of the gates whose inputs this checkout lacks — blocked, never passed.
8. Where the Python and Node versions are pinned so a runner matches the recorded environment, and the lockfiles it installs from.
9. The approver's role, the date and a link or path to the signed evidence — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R7](risk-register-v6.md#r7) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D10 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, which unblocks V6-30 and supplies the execution, browser, dependency and artifact rules V6-32 and V6-33 apply, and turns R7 from an unowned P1 into a defined workflow with a recorded result per commit. It opens no wave: V6-30 is a Wave 3 task, and gate V6-0G was signed on 2026-11-24 without D10. Until it is signed, the checks stay local, the browser journey stays recorded as blocked and R7 stays open with its owner recorded.

## Appendix — D12 decision brief

**Status: D12 is NOT APPLICABLE (2026-11-24).** D1 chose Track A (see [Recorded decision D1](#recorded-decision-d1)), so no catalog, merchant, legal or activation answer is required for this launch; billing and the platform console stay off. This brief is retained for a future Track B decision. The configuration and document states it quotes are what the checkout does today, recorded in `docs/release-v5.md` and `plans/PLAN_V5.md` §3 as evidence.

### The question

If Track B is chosen, what has to be approved before a customer can be charged: which of V5's commercial answers are signed and at what granularity, which merchant account receives the money and who holds its keys, how the approved catalog reaches the public pricing page, who may switch live billing on, and who runs refunds, disputes and reconciliation afterwards. The answer is what gate V6-6G (paid activation) and V6-51 (paid rehearsal) wait on; it changes no Track A task and no code.

### What the repository does today (evidence, not a decision)

- **Billing is off and fails closed.** `BILLING_ENABLED` defaults to `false`, and the lifespan in `main.py` validates the Stripe settings only when it is true (`core/config.py:167`), so billing-off needs no merchant credentials and makes no provider call. Checkout, Portal and the webhook answer 404 while it is off.
- **The catalog is empty until someone publishes.** `PLANS` is an empty tuple (`services/plan_catalog.py:82`), kept as the empty-table fallback; a plan is public only when its `catalog_plans` row is `published` **and** carries a usable `plan_prices` row, and with billing on a published plan without a `price_…` mapping refuses checkout rather than guessing one.
- **The provider configuration is server-only and pinned.** `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, the legacy `STRIPE_PRICE_IDS` fallback and a pinned `STRIPE_API_VERSION` (`2026-11-18.endive`) live in `core/config.py`; no Stripe value is in the frontend bundle, and with billing on and a key missing, startup refuses and reports setting names only.
- **Entitlements cannot be bought by accident.** Only `active`/`trialing` plus a currently published plan grants a limit; every other status, and an unpublished or unknown plan code, leaves the company on its V4 ceilings. A limit of `0` means “not stated”, never unlimited.
- **No commercial term is recorded anywhere.** `docs/release-v5.md` §1 lists the catalog, legal content, merchant readiness, operator access, mutation set and support ownership as **BLOCKED**, and §6 records catalog/legal/commercial and Stripe merchant/test as **NO-GO**; `docs/billing.md` states that no grace period or refund policy exists yet; the §4 test-mode rehearsal has never run, and V5-5G stands at 72/72 with its live Stripe and browser items blocked.
- **The operator half is not this row.** V5 D10–D12 (who a platform owner is, what they may change, which settings are editable) belong to the operator boundary: V6 D5 takes only the console's authentication requirement, and the grant model, the permitted mutation set and the settings allowlist stay open in `plans/PLAN_V5.md` §3, with the surface that exists today described in `docs/platform.md` and `docs/security.md`. This row carries only what a customer pays and who operates the merchant relationship.

### Options and consequences

#### 1. Which commercial answers are signed, and how

[`plans/PLAN_V6.md`](../plans/PLAN_V6.md)'s D12 row asks for V5's commercial answers, D2–D9: catalog and terms (D2), Stripe and merchant readiness (D3), trial/free tier and registration (D4), lifecycle (D5), existing-company rollout (D6), enforcement (D7), legal content (D8) and branding (D9). V5 D10–D12 are the operator boundary and are not part of this decision: V6 D5 carries only the console's authentication requirement, and the rest stays open in `plans/PLAN_V5.md` §3, so this brief carries none of it.

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — each answer signed in its own row** | Every commercial V5 decision gets a named approver, a date and its own evidence, all signed before the rehearsal, and the gate reads the eight records. | Nothing is inferred and each owner signs only what they own; but it is the slowest path, and the last signature gates the rehearsal, so test-mode work can wait on legal copy that has no engineering dependency. |
| **B — one Track B approval containing every answer** | A single signed record, given at one point, states each commercial answer and the owner who accepted it. | One record and one go/no-go to read; but one signature then covers pricing and legal together, so the record has to name which owner accepted which part or it is one person approving another's domain. |
| **C — two sign-off points, however the answers are recorded** | Catalog, terms and legal copy are signed before any test-mode rehearsal; the rollout, lifecycle and enforcement answers follow before live activation, and each point may use one record or eight. | Rehearsal can start as soon as a catalog and copy exist and the remaining answers can follow; but the two sign-off points have to stay consistent, and activation can arrive with a lifecycle policy signed later than the prices it charges. |

#### 2. Which merchant account receives payment, and who holds its keys

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — the organisation's existing merchant account** | The product charges through the account the organisation already uses, under its current owner. | The account, its payout history and its key holders already exist, so nothing new is opened; but this product's charges share that account's disputes and payout schedule with whatever else uses it, and its owner becomes the merchant for these charges whether or not they operate billing. |
| **B — a merchant account opened for this product** | A separate account holds this product's charges, keys and disputes. | Isolates the charges, the keys and the dispute history, and gives the operational owner an account they hold; but opening one needs the organisation's legal and banking details and its own test-mode key and webhook registration — the longest lead time in this row. |
| **C — no merchant account** | Track B does not launch; the flags stay off. | Nothing to configure and no card data anywhere; but there is no paid track at all, and V5 D3 forbids substituting another processor or building card entry, so this is a deferral rather than a workaround. |

#### 3. How the approved catalog reaches customers

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — publish the approved rows live after sign-off** | The catalog row signed under §1 is published in live mode in one step. | One publication and the public page matches the signed rows immediately; but a wrong price row is visible to customers before any rehearsal has seen it. |
| **B — test mode first, then exactly those rows live** | The catalog is published to test mode, rehearsed, then published live as the same set. | The catalog is exercised end to end before a customer sees it, and the live publication repeats a rehearsed set; but test and live are two records that must stay identical, and a mapping mistake between them fails at the first real checkout. |
| **C — launch with the catalog unpublished** | Pricing keeps its “being finalised” state, checkout stays unavailable, and plans are published in a later authorized change. | No price is published unapproved and the core product can launch; but Track B has no paid surface at all, and customers see the placeholder state until that later change. |

#### 4. How far live activation reaches

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — one switch for every customer** | Billing is enabled for the whole customer base in one window. | One configuration change, one monitoring window and one rollback; but every customer meets the new billing path at once, including those whose cards or currencies the rehearsal did not cover. |
| **B — a named cohort first, then widened** | Billing is enabled for an approved cohort, and widening it is a separate decision with abort thresholds. | A defect reaches a named cohort first and the expansion is its own decision; but it needs a cohort definition, thresholds and someone watching, and two product states to support at once. |
| **C — no live activation in V6** | The paid path is rehearsed in test mode only; live billing waits for a later authorization. | The rehearsal evidence exists and no customer can be charged by accident; but the paid track is not launched in V6, and every approval above buys nothing until that later change. |

#### 5. Who runs billing after activation

| Option | What it means | Consequences to accept |
|---|---|---|
| **A — the support owner also owns billing** | The V6 D11 support owner answers billing questions and handles refunds, disputes and failed webhooks. | One contact for the customer and no handoff; but that owner now carries refund decisions and dispute evidence they may not be trained or authorized for. |
| **B — a separate merchant-operations owner** | Refunds, disputes, reconciliation and failed webhooks sit with whoever holds the merchant relationship, and support escalates to them. | Each job sits with someone equipped for it and the customer still has one entry point; but it adds a role to name and a handoff to document, and a slow escalation is a customer waiting. |
| **C — no named owner** | The merchant-account holder acts when something happens, with no roster or procedure. | Nothing to name and nothing to document; but a refund or a chargeback then has no owner, no procedure and no evidence — the state `docs/release-v5.md` §1 row 6 records today. |

### Exact evidence an approver must sign

1. D1 naming Track B (or “both”) in scope for a named cohort, and the commercial V5 answers carried — D2–D9, each with the approver and evidence §1 requires — at the granularity §1 chooses.
2. The merchant-account facts supplied by its owner: account holder, merchant country, supported currencies and payment methods, where test and live keys are kept, the registered webhook endpoint and who rotates its signing secret — recorded by reference, never as key values.
3. The approved catalog exactly as it will be published — code, name, limits, price in integer minor units, currency, cadence and whether self-serve checkout is offered — with the statement that nothing outside that set is published.
4. The trial and free-tier answer (V5 D4), or an explicit “no trial and no free tier”.
5. The lifecycle and rollout answers (V5 D5–D6): cancellation timing, invoice retry and grace, past-due behaviour, upgrade/downgrade/proration, refund policy, reactivation and the grandfathering rule for companies that existed before billing — plus the enforcement policy (V5 D7): the plan-to-entitlement mappings and how they resolve against existing admin-set limits. Values are the approver's, not derived here.
6. Legal and support content approved (V5 D8/D9, plus V6 D7/D11 where they touch retention and support), the pages each appears on, and the support contact a paying customer is given.
7. The §4 activation scope: who may change the flag, for which cohort, the abort thresholds, the exact configuration change and the rollback owner — plus the statement that a deploy does not enable billing by itself.
8. The pass conditions the rehearsal will be judged by (V6-51), agreed now: which cases must pass — Checkout, signed webhook, duplicate, out-of-order, invalid signature, provider failure, Portal cancel-at-period-end, entitlement boundaries and flag-off parity — how each result is recorded and who attests it, with fixture-only tests recorded as fixtures, never as a live Stripe run. The results are V6-51 and gate V6-6G evidence, checked after this signature because this decision is what unblocks them, not before it.
9. The §5 owner for refunds, disputes, reconciliation and webhook failures with the procedure each follows, and the approver's role, date and signed-evidence link — recorded in this row and copied into [`plans/PLAN_V6.md` §4](../plans/PLAN_V6.md#4-pre-flight-decisions-blocking-for-the-affected-tasks) and into [risk R3](risk-register-v6.md#r3) of `docs/risk-register-v6.md`.

### What an approval changes

Only [the D12 row](#decision-register--one-page-to-sign) moves from **UNAPPROVED** to **APPROVED**, and only for Track B: it is one of the conditions gate V6-6G and V6-51 wait on, and it neither opens Wave 1 nor authorizes a charge by itself — the activation scope it records in §4 is part of this row (and under §4's option C there is none), so what remains between this signature and a customer's card is V6-51's rehearsal and gate V6-6G's own evidence. A deploy does not enable billing on its own. Under Track A nothing changes: billing stays off, the catalog stays unpublished, the paid surfaces answer 404 and R3 stays mitigated by configuration alone.
