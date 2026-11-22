# V5-5G — release gate

`PLAN_V5.md` §7 as a runnable check. It creates and drops its own throwaway
PostgreSQL database, migrates it to head, starts a real `uvicorn` process and
drives the paid-account and platform-owner journeys over HTTP.

```bash
# defaults to v5_gate_5g on postgresql://postgres:postgres@127.0.0.1:5432
bash scripts/gate_v5_5g/run_all.sh

# another throwaway name, or keep the database for inspection
GATE_DB=v5_gate_5g_demo bash scripts/gate_v5_5g/run_all.sh --keep-db
```

`GATE_PG` overrides the PostgreSQL server base URL. The database name must start
with `v5_gate_5g`; the script drops and recreates it, so never point it at a
database you care about. Redis is **not** required: registration, login,
billing, catalog, website limits and platform operations take the memory
rate-limit path; chat/ingest (provider-bound) is out of scope.

## Stripe fixture

No merchant account is used and the real Stripe SDK is not called. A tiny
`stripe` module is written to a temporary directory and injected through
`PYTHONPATH` for the API process. It:

- returns hosted-like URLs for Checkout and Billing Portal;
- records every call (Price ID, mode, URLs, customer, metadata) to JSONL;
- verifies `Stripe-Signature` with the configured `STRIPE_WEBHOOK_SECRET` using
  Stripe's `t=…,v1=…` HMAC scheme, so valid, duplicate, stale and invalid
  signature deliveries are exercised exactly as the endpoint sees them.

The checks cover: schema/M12, public funnel APIs, owner grant/refusal/revocation,
draft → publish → immutable price change, tampered Checkout input, unknown /
contact-sales / unmapped plans failing closed, webhook activation once,
duplicate, stale, foreign customer, entitlements at the website ceiling, usage,
Portal scoping, reconciliation, cancel-at-period-end vs the mirror, settings
preview/update and public display, audit redaction/read-only, invoice failure,
cancellation and no revival, and billing-off parity (404 surface, no provider
call, plan ceiling stops applying).

## Blocked, not skipped

- **Live Stripe test-mode Checkout/Portal/webhook delivery** — no D3 merchant
  test account or keys. The fixture and signed payloads are what run here.
- **Browser journey** across `/`, `/pricing`, `/app` and `/platform` — the gate
  is headless. The manual Wave 4 browser pass is recorded in `PLAN_V5.md` and
  must be repeated on the deployment.

A blocked item is printed and counted separately; it never counts as a pass.
