# Platform owner console (V5 Wave 4)

The operator control plane is **not** a tenant feature. It is a separate grant
bound to an existing authenticated user, provisioned out of band, and it is
closed by default. This document covers the boundary, the provisioning
procedure, the operations the console offers and the recovery runbook.

Wave 4 implements V5-40 … V5-44 on the engineering defaults in decisions
D10–D12. Those decisions (strong authentication, the exact mutation set and the
runtime-settings allowlist) and gate V5-3G are still unapproved, so
`PLATFORM_CONSOLE_ENABLED` must stay false in production until they are.

## Authorization matrix

| Caller | `/api/platform/*` |
|---|---|
| Anonymous | 401/403; while the switch is off, 404 |
| Company member / manager / admin (JWT) | 403 |
| Company API key (`X-API-Key`) | 401/403 — never a platform session |
| User with an **active** `platform_owners` grant | allowed |
| User whose grant was revoked | 403 on the very next request |
| Any request that tries to grant/revoke ownership through HTTP | no such route |

Two independent gates apply to every route:

1. `PLATFORM_CONSOLE_ENABLED` — false by default; the whole surface answers
   **404** (it is not merely forbidden, so an unopened deployment does not even
   advertise it).
2. `require_platform_owner` — a JWT for an `active` user with a live grant row.
   A tenant `admin` is not an operator; `users.role` is never consulted.

The platform surface and `/app` share only the user table. There is no tenant
impersonation, no super-tenant login and no way to act *as* a company.

## What exists

| Piece | What it does |
|---|---|
| `models.PlatformOwner` (M12) | One grant row per operator. `revoked_at` ends it; a partial unique index allows **one active grant per user**, so revoked rows stay as history and a re-grant inserts a new row. `ON DELETE CASCADE` on the user removes the grant with them. |
| `models.PlatformAuditLog` (M12) | Append-only trail: actor (`actor_user_id` for API actions, `actor_label` for the CLI), action, target type/id, time, and a JSON `detail` redacted by the writer. No payload, card, token or credential column. |
| `models.CatalogPlan` / `models.PlanPrice` (M12) | Durable plans and immutable price records. Plan status is `draft` → `published` → `archived`; one active price per plan. |
| `models.PlatformSetting` (M12) | One row per allowlisted display override. |
| `services/platform.py` | `is_owner` / `active_grant`, idempotent `grant_owner`, timestamp `revoke_owner`, `record_audit`, `recent_audit`. |
| `services/platform_ops.py` | Cross-company overview, paginated companies/subscriptions and the two approved subscription actions. |
| `services/plan_catalog.py` | Public catalog reads (durable first, static fallback) and the validated create/edit/price/publish/archive operations. |
| `services/platform_settings.py` | The typed non-secret allowlist, validation, preview and upsert. |
| `api/platform.py` | The owner-only API: session, overview, companies, subscriptions + actions, plans + lifecycle/prices, settings + preview, audit. |
| `api/public_config.py` | Anonymous read of the two display values only. |
| `scripts/platform_owner.py` | The only way to grant or revoke: `grant`, `revoke`, `list [--history]`. |
| `frontend/src/pages/platform/*` | The isolated `/platform` shell with Overview, Companies, Plans & pricing, Subscriptions, Settings and Audit sections. |

There is deliberately **no API** that mints a grant, no `mark_paid` action and
no route that edits or deletes an audit row.

## The switch

`PLATFORM_CONSOLE_ENABLED` (env, default `false`) gates the whole surface. Keep
it false until D10's requirement — approved strong authentication (MFA/SSO)
**or** a private operator-only network restriction — is approved and in place.
Neither is approved, which is why the default is off. The `/platform` UI shows
"not enabled" when the API answers 404 and "operator access required" for a
tenant account.

## Granting, revoking and recovery

Run these from a host with the deployment's `DATABASE_URL` exported. `--actor`
is required and is what the audit row records.

```bash
# grant (idempotent: an active grant is reported, not duplicated)
uv run python scripts/platform_owner.py grant --email ops@example.com \
    --actor "on-call SRE (OPS-12)" --note "primary operator"

# see who is active / what history exists
uv run python scripts/platform_owner.py list
uv run python scripts/platform_owner.py list --history

# revoke: stamps revoked_at; the next request is refused, the row stays
uv run python scripts/platform_owner.py revoke --email ops@example.com \
    --actor "on-call SRE (OPS-12)"
```

Failure modes and recovery:

| Situation | Recovery |
|---|---|
| Operator locked out (lost device, unknown account) | Grant the replacement user with the CLI. Grants are per user; nothing is shared. |
| All operators locked out | Run the CLI against the deployment database — it is the break-glass path and needs no web session. Restrict DB access to the on-call operator. |
| Operator account deleted | The grant cascades away; grant another existing user. Audit rows that named the user keep `actor_user_id=NULL` (SET NULL) and any CLI `actor_label`. |
| Suspected compromise | Revoke immediately; revocation is read on the next request. Review `/api/platform/audit` and the Stripe dashboard. Rotate the JWT secret if tokens may be stolen (deployment config, not this console). |
| Console accidentally enabled | Set `PLATFORM_CONSOLE_ENABLED=false` and restart; every platform route becomes a 404 again. Grants and audit rows are unaffected. |

Strong authentication, session timeout tuning and re-authentication for
high-impact actions are **not implemented**; the UI's confirmation checkbox and
the API's `confirm` flag are procedural safeguards, not MFA. Do not expose the
console publicly until D10 is approved.

### Browser verification (2026-11-22)

With `PLATFORM_CONSOLE_ENABLED=true` on a dev API and Vite, an anonymous
`/platform` visit redirected to `/login`; the signed-in tenant admin saw the 403
"operator access required" state; a CLI grant plus reload rendered the console;
a draft plan was created through the Plans UI; a settings preview followed by
Save showed the audited override and the public landing page rendered the
status banner. The test company, plan, grant and setting were removed and the
servers stopped. This pass does **not** replace D10's strong-auth requirement.

## Subscription operations (V5-41)

The console lists every company and its mirrored subscription state. It shows
opaque Stripe customer/subscription identifiers for support and reconciliation;
it never shows card data or a raw Stripe object.

Two actions exist, both requiring a reason of at least three characters:

* **Request reconciliation** — writes one audit row and changes nothing. Use it
  when a customer reports a mismatch; then inspect the Stripe dashboard and the
  `/api/billing/subscription` view for that company.
* **Cancel at period end** — requires `confirm=true` in the API and the
  explicit checkbox in the UI. It calls Stripe
  (`Subscription.modify(cancel_at_period_end=True)`) and **does not** write the
  local row. The mirror changes only when the signed
  `customer.subscription.updated` webhook arrives. With billing disabled the
  action answers 409 and records `refused_billing_disabled`. A provider failure
  answers 502 and records `provider_error` with the exception type only.

There is no action that grants a plan, extends a period or marks a subscription
paid. If Stripe is wrong, fix it in Stripe and let the webhook reconcile.

## Catalog and pricing (V5-42)

Plan codes are immutable, lowercase and unique. A new plan starts as a **draft**
and is invisible to `GET /api/plans` and Checkout. Publishing requires:

* a usable active price (positive-integer minor units, three-letter currency,
  `month`/`year` interval);
* a Stripe Price mapping (`price_…`) when `BILLING_ENABLED=true` and the plan is
  self-serve — a plan that could not be bought is refused rather than shown;
* an explicit confirmation and a reason, both audited.

Price records are immutable. A change requires explicit confirmation, archives the
active row and inserts a new one; existing Stripe subscribers keep the Price they bought, and only new
Checkout sessions see the new active row. Archiving a plan removes it from the
public list and Checkout without deleting its records or touching existing
subscribers. Draft/published plans may be edited (name, copy, limits,
self-serve), with every edit confirmed and audited. Archived plans are frozen.

The public response contract is unchanged: `code`, `name`, `description`,
`price_minor`, `currency`, `interval`, `features`, `limits`,
`self_serve_checkout`. Stripe IDs stay private to the operator surface and the
checkout path. Checkout resolves the durable active price first and falls back
to the `STRIPE_PRICE_IDS` env mapping for deployments that have not moved yet.

Creating Stripe Products/Prices from the console is **not implemented** (it
needs merchant credentials and D3). Map a validated pre-created `price_…` ID
instead.

## Global settings (V5-43, D12)

Only these keys are writable, and only as text:

| Key | Meaning | Default |
|---|---|---|
| `public_status_message` | Optional announcement on the marketing pages (≤ 280 chars) | empty |
| `support_contact_email` | Address shown in the public footer | empty |

An absent row means the default. `POST …/preview` validates without writing;
`PUT …/{key}` validates again, requires a reason, and writes the row and its
audit entry in one transaction. Unknown keys are rejected. There is no generic
environment editor: auth, networking, secrets, database URLs, CORS, billing
enforcement and destructive retention stay in deployment configuration. The two
values are display-only, so a mistaken change cannot lock anyone out or delete
data.

## Audit and retention (V5-44)

Every grant, revoke, subscription action (including failures), plan change and
setting change writes one row. The writer redacts keys matching
`secret|token|password|passwd|api_key|private_key|authorization|bearer|credential|dsn|database_url|session`
and refuses non-scalar values, so a caller cannot persist a credential by
mistake. The API exposes reads only; there is no update/delete route.

The trail is append-only at the application boundary, not enforced by a
database role. The deployment should grant the application role no `UPDATE` or
`DELETE` on `platform_audit_logs`; until that is configured, treat DB access as
operator access. Define retention before production: export rows you must keep,
then delete in a controlled maintenance window. Downgrading M12 drops the trail
irrecoverably — export first.

CSRF hardening is not applicable to the API: authentication is a bearer JWT in
`localStorage`, not an ambient cookie. The trade-off is that any XSS can read
the token; the existing CSP/asset rules and React escaping remain the relevant
controls.

## Migration M12

`0b22b30bf930` chains from M11 `a7c41d9e6b52` and creates five tables:
`platform_owners`, `platform_audit_logs`, `catalog_plans`, `plan_prices` and
`platform_settings`, with their indexes (new tables, so no `CONCURRENTLY`). The
price partial unique index (`plan_id WHERE active`) mirrors the owner-grant
predicate pattern. V5-42/V5-43 extended this revision before release while Wave 4 was in
flight; it remains the sole head. Downgrading it drops all five
tables, so export grants and audit rows first if a downgrade is ever genuinely
required. The feature dashboard's M12 replay (upgrade → downgrade → upgrade on a
throwaway PostgreSQL database) is recorded in `plans/PLAN_V5.md`.

## Not built yet (blocked)

- Strong authentication (MFA/SSO), re-authentication prompts or an IP allowlist
  for operators (D10). Until approved, keep the switch off or use a private
  network.
- Stripe Product/Price creation and test-mode sync (D3 credentials).
- Approved commercial catalog, prices, trial/grace/refund policy and legal copy
  (D2/D4/D5/D8) — the console can hold drafts, but nothing should be published.
- Database-role enforcement of audit immutability and a formal audit-retention
  schedule (deployment operation, not application code).
- Tenant impersonation: never planned. The boundary is additive, not a
  super-tenant login.
