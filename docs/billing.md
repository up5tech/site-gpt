# Billing and plan entitlements — operator guide (V5)

SiteGPT owns subscription *state*; Stripe owns *payment*. This document covers
what the code does, what an operator must do when Stripe and the mirror
disagree, and which decisions are still unapproved.

> **Status.** `BILLING_ENABLED=false` is the default and the only approved state
> so far. No plan is published (`services/plan_catalog.PLANS` is empty) and no
> Stripe live or test-mode account is configured. Nothing here is a commercial
> promise: tier names, prices, trials, grace periods and refunds stay blocked on
> decisions D2/D4/D5/D7/D8 in `plans/PLAN_V5.md` §3.

## 1. What the server stores

| Table | Holds | Deliberately does not hold |
|---|---|---|
| `subscriptions` | one row per company: Stripe customer/subscription ids, plan code, cadence, lifecycle status, period dates, `cancel_at_period_end`, `last_event_at` | card data, prices, raw Stripe objects |
| `billing_events` | one row per processed Stripe event id, its type, Stripe creation time and processing time | the webhook payload, customer details |

Both are deleted with their company (`ON DELETE CASCADE`). Downgrading M11
discards billing state: it is a disposable-database operation, not a production
rollback.

## 2. Billing off (the default)

With `BILLING_ENABLED=false`:

- no Stripe credential is read and no Stripe call is made;
- `GET /api/billing/status` answers `{"enabled": false}` and every other
  `/api/billing/*` route answers 404;
- `services/entitlements.resolve` returns an empty snapshot **without a
  database read**, so quotas, websites and seats behave exactly as in V4
  (`daily_message_limit` / `session_message_limit` settings and their env
  defaults);
- the console shows no Billing link.

An empty `STRIPE_PRICE_IDS` is not an error while billing is off; with billing
on, a published plan without a mapping fails closed at Checkout (409) and is
never sent to Stripe as a guessed price.

## 3. Plan entitlements (V5 F3)

`services/entitlements.py` is the only place a plan becomes a limit.

| Subscription status | Plan limits granted? |
|---|---|
| `active`, `trialing` | yes, from the **currently published** catalog entry |
| `incomplete`, `past_due`, `unpaid`, `paused`, `canceled`, none | no |
| active, but the plan code is unpublished/unknown | no |

"No limits granted" means the company keeps its V4 ceilings — it is **not** a
lockout and **not** a guessed free tier. Unapproved plan data can therefore
never raise access, and a quiet Stripe webhook can never remove it.

Enforced keys (`ENFORCEABLE_LIMITS`): `websites`, `seats`, `daily_messages`,
`session_messages`. A catalog `limits` entry with any other key is display copy
and has no effect. A limit of `0` is treated as "not stated" and not enforced,
because `0` already means "no cap" in `services/quota.py` and the two meanings
cannot be told apart.

`seats` counts only users whose status is `active` (`entitlements.seat_count`,
the same count the usage report shows). Deactivating a user frees the seat and
keeps every row that user owns; the seat boundary and `GET /api/billing/usage`
never disagree. Each chat handler resolves **one** snapshot per request and
derives both caps from it, so a message reads the subscription and catalog once.

The effective value is the **stricter** of the company's own setting and the
plan ceiling, so `PUT /api/settings` can lower usage but never raise a plan
limit, and an uncapped company setting (`0`) becomes the plan ceiling rather
than infinity. Ordering is unchanged: per-IP limiter → session cap → daily
quota; Redis failures still fail open.

Boundaries:

| Ceiling | Enforced in | Refusal |
|---|---|---|
| `websites` | `POST /api/websites` | 403, names the ceiling |
| `seats` | `POST /api/companies/users` | 403, names the ceiling |
| `daily_messages` | `/api/chat`, `/api/chat/stream`, `/api/v1/chat` | friendly answer (429 on `/api/v1`), as in V4 |
| `session_messages` | same three chat handlers | friendly answer / SSE frame, as in V4 |

## 4. Routine operations

### A delivery failed (Stripe shows 5xx)

1. Stripe retries automatically. The receipt row is rolled back on a failed
   apply, so the retry is processed rather than answered as a duplicate.
2. Find the event in the Stripe Dashboard → Webhooks → the endpoint → the
   failed delivery. The server log has a line
   `stripe webhook <type> (<event_id>) failed to apply`.
3. Fix the cause (database reachable, migration applied, company row present),
   then **Resend** the event from the Stripe Dashboard.
4. Do not mark a company paid by hand. A browser's `?checkout=success` is not
   evidence of payment.

### A subscription looks wrong in the console

1. Compare `GET /api/billing/subscription` (or the console Billing page) with
   the Stripe Dashboard's subscription for that customer.
2. If Stripe is ahead, resend the newest `customer.subscription.updated` event
   for that subscription. Events older than `subscriptions.last_event_at` are
   ignored by design (an out-of-order retry cannot restore stale access), so
   resending an *older* event will not change anything.
3. If the mirror references a customer/company pair you cannot match, stop: the
   webhook refuses metadata that disagrees with the stored row, and that
   refusal is the safe outcome. Investigate the Stripe object instead of
   editing the row.

### An invoice failed

`invoice.payment_failed` moves the row to `past_due`, which grants no plan
limits. Stripe's dunning settings decide retries. The grace period, the
notification wording and what a past-due tenant may still do are **blocked on
D5**; until approved, no automatic downgrade or lockout happens — the company
keeps its V4 ceilings.

### Cancellation

Cancellation is at period end by default and is driven by Stripe's Billing
Portal. `customer.subscription.deleted` sets `status='canceled'` and
`cancel_at_period_end=true`; a later `invoice.paid` never revives it (only a
new subscription event does). Refunds and reactivation wording are blocked on
D5.

## 5. Rollback

| Situation | Action |
|---|---|
| Stripe unreachable or misconfigured | `BILLING_ENABLED=false` and restart. No Stripe call is made afterwards; console billing disappears (404) and entitlements stop being enforced. |
| Wrong entitlement rollout | Disable billing enforcement the same way, then correct the catalog/plan mapping. Do not delete subscription or event rows. |
| Bad webhook state | Fix the cause and resend from Stripe. Never edit `subscriptions` by hand to grant access. |
| M11 needs reverting before deploy | Regenerate the unapplied revision after review. |
| M11 already deployed | A forward migration, never an edit of an applied revision. Billing state is disposable; back up and review first. |

## 6. Still blocked (external prerequisites)

- **Stripe test/live account and keys** (D3): no live Checkout, Portal or
  webhook delivery has ever run. Only mocked SDK and signature fixtures are
  verified.
- **Approved catalog and terms** (V5-01 / D2/D4/D5/D7): no price, tier, trial,
  grace period or refund policy exists yet, so no limit is enforced by default.
- **Legal and support copy** (D8): no cancellation/refund wording, support
  contact or approved claim is in the product.
- **Platform-owner console** (Wave 4): reconciliation tooling is the Stripe
  Dashboard and this runbook.

## 7. Rendering check with throwaway data (2026-11-22)

The console page had never been rendered, so it was driven once locally with
dummy configuration and a temporary plan. This is a **rendering** check only:
no Stripe key, Checkout redirect, Portal session or webhook delivery was
involved, and no limit became enforceable.

**Setup (temporary, reverted afterwards).** A throwaway Postgres database
(`site_gpt_billing_demo`, created and dropped with the compose `postgres16`
container), migrated to `a7c41d9e6b52`; the API started with
`BILLING_ENABLED=true`, a dummy `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` and
`STRIPE_PRICE_IDS=starter:month=price_dummy_starter_month`; the frontend on a
second port pointed at it with `VITE_BACKEND_URL`. A wrapper module patched
`plan_catalog.PLANS` in memory with one published `starter` plan (websites 1,
seats 2, daily 500, session 40) so the catalog file itself never changed, a
company/admin was registered through `POST /api/register`, and the mirrored
`subscriptions` row was seeded directly per state. All of it was removed
afterwards: temp scripts deleted, both servers stopped, the database dropped,
and `plan_catalog.PLANS` is still empty.

**Observed (viewport 1280 × 900, header 64 px, no overlap or horizontal
overflow, no console errors):**

| State | What the page showed |
|---|---|
| No subscription | "No subscription yet" info alert ("This company has no billing account…"), **Manage in Stripe** disabled, a "Choose a plan" card listing Starter with an enabled **Select**, and usage reading `0 used` / `1 used` with no progress bars and "No plan ceiling is being enforced right now, so your existing limits apply." |
| `past_due` | Plan `starter (monthly)`, an orange **Payment past due** tag, "Renews / ends" date, **Manage in Stripe** enabled, and "Change plan" with Starter marked **Current** and its Select disabled (the current plan cannot be re-bought). Usage still renders counts-only: a past-due row grants no ceiling, exactly as the resolver policy says. |
| Active + `?checkout=success` | The info alert "Confirming your payment with Stripe" appears above the cards, but the state below it still comes from the mirrored row — the page never treats the query string as proof of payment. Status tag is green **Active**, usage reads `0 of 1` / `1 of 2` with 0 % and 50 % progress bars, and the note "Ceilings are the stricter of your plan and your own settings." |

**Not observed (still unverified):** a real Checkout redirect or Billing Portal
session (needs D3 merchant credentials), any webhook-driven state change, the
non-admin view (a member sees the read-only wording), the narrow/mobile layout,
and the billing-off alert — that last one needs `BILLING_ENABLED=false`, where
the page renders its "Billing is not enabled for this deployment" state instead
of the cards.

**Worth deciding later.** A `past_due` subscription is signalled only by the
orange tag: there is no dunning banner or payment-failure guidance, because that
copy is part of the blocked D8 legal/support text. The same applies to
`checkout=success`: the notice is deliberately inert, and while it says the plan
"becomes active" it also renders when the mirror already reads `Active`.
