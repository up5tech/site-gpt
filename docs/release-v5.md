# V5 launch and deployment checklist

V5 adds a public marketing funnel, Stripe-backed subscriptions, plan
entitlements and a separate platform-owner console. **Nothing in V5 is released
yet and paid billing is not approved.** This document is the release checklist
and the go/no-go record; it deliberately does not invent prices, policies,
legal copy or named owners.

Current state (2026-11-22):

- Waves 1–5 engineering are merged to `master` (`028fdee`, fast-forward,
  2026-11-22) but unreleased; the latest released tag remains `v4` and no `v5`
  tag exists.
- Alembic head is `0b22b30bf930` (M12: owners, audit, catalog, prices,
  settings).
- `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false` are the only
  approved production values.
- The provider-free gate `bash scripts/gate_v5_5g/run_all.sh` passes **72/72**
  checks with **2 blocked** (live Stripe test mode, browser journey). See
  `scripts/gate_v5_5g/README.md`.

## 1. Prerequisites and owners

Every row needs a named owner, a date and evidence before go-live. “Blocked”
means the input does not exist in the repository; engineering must not fill it
in.

| # | Prerequisite | Required evidence | State |
|---|---|---|---|
| 1 | Approved commercial catalog (D2/D4/D5/D7) | Tier codes, names, exact limits, prices in minor units, currency, cadence, free/trial choice, upgrade/downgrade/proration, cancellation, refund, grace/past-due and existing-customer policy, signed by product/legal | **BLOCKED — no approval recorded** |
| 2 | Legal and public content (D8/D9) | Terms, privacy notice, cancellation/refund/tax wording, support contact, company identity, approved claims, branding/screenshots | **BLOCKED — no copy supplied** |
| 3 | Stripe merchant readiness (D3) | Account owner, merchant country, test and live keys, webhook endpoint registered, supported currencies/payment methods, test-mode run | **BLOCKED — no test account/keys** |
| 4 | Platform-owner access (D10) | Approved MFA/SSO **or** private operator network, bootstrap operator, recovery/break-glass owner | **BLOCKED — neither approved** |
| 5 | Platform mutation set and settings allowlist (D11/D12) | Approved list of operator actions and typed global settings | **BLOCKED — engineering defaults in use** |
| 6 | Support ownership | Named billing/support owner, escalation path, response promise | **BLOCKED — no owner named** |
| 7 | Deployment topology | TLS, exact `FRONTEND_URL`, `CORS_ORIGINS`, webhook reachability, proxy timeouts | Pending deployment verification |
| 8 | Backups and retention | Database backup/restore test, audit export/retention decision, Stripe identifier retention | Pending operations sign-off |
| 9 | Monitoring | Alert on webhook failures, 5xx, mirror drift, audit writes, console access | Pending operations sign-off |

## 2. Pre-deployment checks

```bash
source .venv/bin/activate
uv run alembic current                       # must equal head 0b22b30bf930
uv run python -m unittest discover -s tests  # report your own counts
node --test tests/*.mjs
cd frontend && npm run build && npm run lint
cd .. && trail build
bash scripts/gate_v5_5g/run_all.sh           # creates/drops v5_gate_5g
```

The gate must not target a shared database: it refuses any name that does not
start with `v5_gate_5g` and drops/recreates it. Live Stripe and browser steps
are printed as **BLOCKED**, never as passes.

## 3. Configuration

Backend-only (never in the frontend bundle):

| Variable | Value |
|---|---|
| `BILLING_ENABLED` | `false` until every prerequisite above is signed; `true` only for the controlled test-mode/live window |
| `STRIPE_SECRET_KEY` | restricted Stripe key; absent while billing is off |
| `STRIPE_WEBHOOK_SECRET` | the endpoint signing secret; rotate per `docs/billing.md` |
| `STRIPE_PRICE_IDS` | optional legacy fallback; the durable catalog's active `PlanPrice.stripe_price_id` wins |
| `STRIPE_API_VERSION` | pinned; changing it is a reviewed change |
| `FRONTEND_URL` | exact public console origin (Checkout/Portal return URLs are built from it) |
| `PLATFORM_CONSOLE_ENABLED` | `false` unless D10 is approved; turning it off makes `/api/platform/*` a 404 |
| `PLATFORM_CONSOLE` | no other switch exists; grants are CLI-only |

Frontend: `VITE_BACKEND_URL` at build time. No Stripe value is ever in
`frontend/.env*`.

## 4. Test-mode rehearsal (blocked on D3)

When a Stripe test account exists:

1. Register a throwaway company, publish one test plan through `/platform` with
   a test-mode `price_…`, and start Checkout as its admin.
2. Pay with a Stripe test card on the hosted page, then confirm:
   - the browser return grants nothing;
   - the signed `checkout.session.completed` activates the company once;
   - replaying the event changes nothing;
   - an invalid signature and a foreign customer change nothing.
3. Open the Billing Portal, cancel at period end, and confirm the mirror changes
   only after the signed subscription event.
4. Check the website/seat/chat boundaries against the plan limits.
5. Disable billing and repeat login, registration, website creation, chat and
   settings — no Stripe call and V4 behaviour.
6. Provision an owner, publish/archive a plan, change a price, request
   reconciliation, update a display setting and read the audit; revoke the
   owner and see the next request refused.

Record the Stripe event ids and the resulting rows (redacted). Do not use live
keys or real cards.

## 5. Launch sequence

1. Complete prerequisites 1–9; record approver and date in this table.
2. Merge the verified commit to `master` only after review; do not rewrite
   history.
3. Apply migrations with a backup in place: `uv run alembic upgrade head`.
4. Deploy the API and worker; deploy the built frontend with the production
   `VITE_BACKEND_URL`.
5. Keep `BILLING_ENABLED=false` and `PLATFORM_CONSOLE_ENABLED=false` for the
   first deployment; verify anonymous `/`, `/pricing`, `/register`, `/login`,
   `/app` login, the existing widget/API paths and a V4 chat.
6. Enable the platform console only behind the approved MFA/network control;
   provision the first owner with `scripts/platform_owner.py grant`.
7. Enable billing in a controlled window, publish exactly the approved catalog,
   run one real low-risk purchase (or an approved test-mode rehearsal), and
   monitor the webhook log.
8. If anything is wrong, set `BILLING_ENABLED=false` first (Checkout stops, the
   mirror stays readable, no Stripe call) and follow `docs/billing.md` §5.

## 6. Go/no-go record

| Gate | Owner | Evidence | Decision |
|---|---|---|---|
| Catalog/legal/commercial | unassigned | — | **NO-GO** |
| Stripe merchant/test | unassigned | — | **NO-GO** |
| Platform owner strong auth/network | unassigned | — | **NO-GO** |
| Security/deployment review | unassigned | `docs/security.md` | Pending |
| Provider-free gate | engineering | 72/72, 2 blocked | PASS (with external blocks) |
| Browser journey | unassigned | manual Wave 4 pass only | Pending deployment repeat |

Do not create the `v5` tag, publish prices or enable live billing while any
row reads **NO-GO**. A release tag is cut once, on the exact commit the release
gate verified, and is never moved (`PLAN_V3.md` §8).

## 7. Rollback

- **Marketing/pricing regression:** revert the isolated frontend deploy; the
  API and `/app` are unaffected.
- **Stripe incident:** `BILLING_ENABLED=false` and restart. Keep the webhook
  endpoint registered if cancellations/refunds still need processing; never mark
  a customer paid by hand.
- **Wrong plan or entitlement:** correct the catalog/price record or disable
  billing enforcement; do not delete subscription or audit rows.
- **Operator console exposure:** set `PLATFORM_CONSOLE_ENABLED=false` and
  restart; revoke grants with the CLI as needed.
- **Migrations:** M11/M12 are forward-only once deployed; take a backup, review
  the diff, and never edit an applied revision. M12's downgrade drops grants,
  audit rows, catalog and settings — export first.
