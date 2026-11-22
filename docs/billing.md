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

### 1.1 Data flow

```
browser ──POST /api/billing/checkout {plan_code}──► API
                                                     │ plan_code → published catalog plan
                                                     │ plan → active PlanPrice.stripe_price_id
                                                     │ company → Stripe Customer (server metadata)
                                                     ▼
                                              Stripe Checkout (hosted card entry)
                                                     │ browser returns to FRONTEND_URL
                                                     │   ?checkout=success (informational only)
                                                     ▼
Stripe ──signed webhook──► POST /api/billing/webhook
                              │ verify Stripe-Signature over the raw body
                              │ receipt unique event id (billing_events)
                              │ apply to subscriptions (last_event_at ordering)
                              ▼
                      entitlements.resolve → website/seat/chat boundaries
```

No PAN/CVC, price object or raw webhook payload is stored. The browser's return
URL is never read as payment evidence.

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
Portal or the platform console's audited **cancel at period end** action. The
console action calls Stripe and does **not** write the mirror;
`customer.subscription.deleted` sets `status='canceled'` and
`cancel_at_period_end=true`; a later `invoice.paid` never revives it (only a
new subscription event does). Refunds and reactivation wording are blocked on
D5.

### Subscription deletion

Deleting a company row cascades its `subscriptions` and `billing_events` rows;
nothing about the Stripe objects is deleted by SiteGPT. Before deleting a
tenant, cancel the Stripe subscription and confirm the customer/company mapping
— an orphaned Stripe subscription continues to bill. A canceled mirror row is
kept (not deleted) so support can still read what happened.

### Key and webhook-secret rotation

- **Webhook signing secret:** create the new endpoint secret in Stripe, set
  `STRIPE_WEBHOOK_SECRET` and restart. Deliveries signed with the old secret are
  then refused (`400 Invalid Stripe signature`) and Stripe retries them with the
  new one. Rotate during a quiet window; a missing secret answers `503`.
- **Secret key:** issue a new restricted key with only the permissions the
  integration uses (Customers, Checkout Sessions, Billing Portal Sessions,
  Subscriptions), swap `STRIPE_SECRET_KEY`, restart, then revoke the old key. No
  stored row changes.
- **Price IDs:** never edit a Stripe Price. Create a new one, map it through the
  platform catalog's immutable price record, and publish the new active price;
  existing subscribers stay on the Price they bought.
- **API version:** `STRIPE_API_VERSION` is pinned; review it and the SDK before
  changing either.

### Reconciling from the platform console

An owner can request reconciliation for a company, which writes one audit row
and changes nothing, then compares the console subscription view with the Stripe
Dashboard. Fix Stripe if Stripe is wrong and resend the newest event; never edit
`subscriptions` to grant access. The console has no “mark paid” or amount entry.

### Global settings are not billing controls

The platform settings allowlist (`public_status_message`, `support_contact_email`)
is display-only. Plan limits, enforcement, billing on/off and Stripe credentials
stay in the catalog or deployment configuration; no browser form can change
them.

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
- **Platform-owner console** (Wave 4): it can request reconciliation and cancel
  at period end with an audit trail, but the Stripe Dashboard remains the
  canonical investigation tool.
- **Live test-mode run** (Wave 5): `scripts/gate_v5_5g/gate.py` exercises the
  whole chain with a local Stripe fixture (72/72 checks, 2 blocked); a real
  Stripe test-mode Checkout/Portal/webhook delivery still needs D3 credentials.
  See `docs/release-v5.md`.

## 7. Rendering check with throwaway data (2026-11-22)

The console page had never been rendered, so it was driven locally — three
times, on the same throwaway setup — with dummy configuration and a temporary
plan. This is a **rendering** check only: no Stripe key, Checkout redirect,
Portal session or webhook delivery was involved, and no limit became
enforceable.

**Setup (temporary, reverted afterwards).** A throwaway Postgres database
(`site_gpt_billing_demo`, created and dropped with the compose `postgres16`
container), migrated to `a7c41d9e6b52`; the API started with
`BILLING_ENABLED=true`, a dummy `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` and
`STRIPE_PRICE_IDS=starter:month=price_dummy_starter_month`; the frontend on a
second port pointed at it with `VITE_BACKEND_URL`. A wrapper module patched
`plan_catalog.PLANS` in memory with one published `starter` plan (websites 1,
seats 2, daily 500, session 40) so the catalog file itself never changed, a
company/admin was registered through `POST /api/register`, and the mirrored
`subscriptions` row was seeded directly per state. A second pass reused the same
database and ports with `BILLING_ENABLED=false`, no Stripe variables at all and
no seeded plan, only a registered admin. A third registered a second user with
`role: "user"` through `POST /api/companies/users` and signed in as that member
against the seeded active plan. All of it was removed afterwards: temp scripts
deleted, both servers stopped, the database dropped, and `plan_catalog.PLANS` is
still empty.

**Observed (viewport 1280 × 900, header 64 px, no overlap or horizontal
overflow, and no page errors — the member session's only console errors were two
`403`s from `/api/inbox/status`, a manager-only surface unrelated to this page):**

| State | What the page showed |
|---|---|
| No subscription | "No subscription yet" info alert ("This company has no billing account…"), **Manage in Stripe** disabled, a "Choose a plan" card listing Starter with an enabled **Select**, and usage reading `0 used` / `1 used` with no progress bars and "No plan ceiling is being enforced right now, so your existing limits apply." |
| `past_due` | Plan `starter (monthly)`, an orange **Payment past due** tag, "Renews / ends" date, **Manage in Stripe** enabled, and "Change plan" with Starter marked **Current** and its Select disabled (the current plan cannot be re-bought). Usage still renders counts-only: a past-due row grants no ceiling, exactly as the resolver policy says. |
| Active + `?checkout=success` | The info alert "Confirming your payment with Stripe" appears above the cards, but the state below it still comes from the mirrored row — the page never treats the query string as proof of payment. Status tag is green **Active**, usage reads `0 of 1` / `1 of 2` with 0 % and 50 % progress bars, and the note "Ceilings are the stricter of your plan and your own settings." |
| Non-admin member (active plan) | The Plan card shows the mirrored `starter (monthly)`, a green **Active** tag and the period end, but instead of a **Manage in Stripe** button it ends with the plain sentence "A company admin manages the subscription." There is **no** button anywhere on the page (no portal, no Select) and no Change-plan/Choose-a-plan card, while Usage still renders `0 of 1` / `2 of 2` with the ceiling note — so a member sees what the plan includes without any way to change it. The Billing nav link is visible to them too, because the navigation gates on `GET /api/billing/status`, not on role; the server refuses the mutations regardless (`POST /api/billing/checkout` and `/portal` answer 403 "Not enough permissions" for that session, and it made no such request). |
| Billing off (`BILLING_ENABLED=false`) | Heading "Billing" and one info alert, "Billing is not enabled for this deployment" / "This instance does not use paid subscriptions. Plans, checkout and the billing portal are unavailable, and your current limits are unchanged." — no Plan, Change-plan or Usage card at all. The console navigation has ten links and **no** Billing entry (`GET /api/billing/status` answers `{"enabled":false}`), and reaching `/app/billing` directly renders only that alert rather than a 404 or an empty page. The page made no `/api/billing/usage` or `/subscription` request, and both answer 404 by design. |

**Not observed (still unverified):** a real Checkout redirect or Billing Portal
session (needs D3 merchant credentials), any webhook-driven state change, the
narrow/mobile layout.

**Worth deciding later.** A `past_due` subscription is signalled only by the
orange tag: there is no dunning banner or payment-failure guidance, because that
copy is part of the blocked D8 legal/support text. The same applies to
`checkout=success`: the notice is deliberately inert, and while it says the plan
"becomes active" it also renders when the mirror already reads `Active`.
