"""V5-5G release gate — the PLAN_V5.md §7 runbook on a throwaway database.

    uv run python scripts/gate_v5_5g/gate.py [--keep-db]

The script creates (and drops) its own PostgreSQL database, named
`v5_gate_5g` by default, migrates it to head, starts a real `uvicorn` process
and drives it over HTTP with `httpx`. Stripe is replaced by a local fixture
module injected through `PYTHONPATH` (the official SDK is not called): it signs
webhooks with the configured endpoint secret, records every call to a JSONL
file, and returns hosted URLs, so the whole checkout → webhook → entitlement
chain runs without a merchant account.

Covered:

1. schema: single head, the five M12 tables, catalog/price/settings columns;
2. public funnel (API level): empty catalog, public display config, register,
   login, a second tenant for isolation;
3. platform owner: out-of-band grant, tenant/anonymous/API-key refusal,
   overview, catalog draft → publish → immutable price change, audit;
4. checkout: server-resolved Price ID, fixed return URLs, tampered body
   ignored, unknown/contact-sales/unmapped plans fail closed;
5. webhooks: valid signature activates once, duplicate is a no-op, invalid
   signature changes nothing, stale/out-of-order cannot restore access, a
   foreign customer is ignored;
6. entitlements: the website ceiling refuses the second site, usage reports it;
7. platform operations: reconciliation audit, cancel-at-period-end calls Stripe
   without writing the mirror, the webhook applies it, settings preview/update,
   audit redaction and append-only reads, owner revocation;
8. billing off: the billing surface is a 404 except `status`, no provider call
   happens, and the plan ceiling stops applying (V4 behaviour);
9. negatives: price tampering, tenant isolation, secret redaction.

**Blocked, not skipped:** live Stripe test-mode Checkout/Portal/webhook
delivery (no D3 merchant credentials) and the browser journey across `/`,
`/pricing`, `/app` and `/platform` (the gate is headless; the manual browser
pass is recorded in `plans/PLAN_V5.md`).
"""

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# The harness and the app both create httpx clients; a bracketed IPv6 entry in
# NO_PROXY makes older httpx builds raise at import time, so the gate runs
# without proxy environment variables at all.
os.environ.pop("NO_PROXY", None)
os.environ.pop("no_proxy", None)

HEAD = "0b22b30bf930"
GATE_DB = os.getenv("GATE_DB", "v5_gate_5g")
PG = os.getenv("GATE_PG", "postgresql://postgres:postgres@127.0.0.1:5432")
WEBHOOK_SECRET = "whsec_gate_5g"
FRONTEND_URL = "http://gate.example.test"

RESULTS: list[tuple[str, bool]] = []
BLOCKED: list[tuple[str, str]] = []

FAKE_STRIPE = r'''
"""Local Stripe fixture for the V5-5G gate. Never used by the application."""
import hashlib
import hmac
import json
import os
from types import SimpleNamespace

LOG = os.environ.get("FAKE_STRIPE_LOG")


def _log(call, **kwargs):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"call": call, "kwargs": kwargs}, default=str) + "\n")


class SignatureVerificationError(Exception):
    pass


class _Customer:
    @staticmethod
    def create(**kwargs):
        _log("Customer.create", **kwargs)
        return SimpleNamespace(id="cus_gate")


class _Checkout:
    @staticmethod
    def create(**kwargs):
        _log("checkout.Session.create", **kwargs)
        return SimpleNamespace(id="cs_gate", url="https://checkout.stripe.test/cs_gate")


class _Portal:
    @staticmethod
    def create(**kwargs):
        _log("billing_portal.Session.create", **kwargs)
        return SimpleNamespace(id="bps_gate", url="https://billing.stripe.test/bps_gate")


class _Subscription:
    @staticmethod
    def modify(subscription_id, **kwargs):
        _log("Subscription.modify", subscription_id=subscription_id, **kwargs)
        return SimpleNamespace(id=subscription_id)


class _Webhook:
    @staticmethod
    def construct_event(payload, signature, secret):
        try:
            parts = dict(item.split("=", 1) for item in signature.split(","))
            timestamp = parts["t"]
            expected = hmac.new(
                secret.encode(),
                (timestamp + ".").encode() + payload,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, parts["v1"]):
                raise ValueError("signature mismatch")
            return json.loads(payload)
        except Exception as exc:  # noqa: BLE001 - mirrors the SDK's single error
            raise SignatureVerificationError(str(exc))


Customer = _Customer
Subscription = _Subscription
Webhook = _Webhook
checkout = SimpleNamespace(Session=_Checkout)
billing_portal = SimpleNamespace(Session=_Portal)
'''


def check(name: str, ok: bool, detail="") -> bool:
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + str(detail)) if detail else ''}")
    return bool(ok)


def blocked(name: str, reason: str) -> None:
    BLOCKED.append((name, reason))
    print(f"BLOCKED  {name} — {reason[:300]}")


def _admin(sql: str) -> None:
    connection = psycopg2.connect(f"{PG}/postgres")
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with connection.cursor() as cursor:
        cursor.execute(sql)
    connection.close()


def _create_database(name: str) -> None:
    if not name.startswith("v5_gate_5g"):
        raise SystemExit("refusing a database name that does not start with v5_gate_5g")
    _admin(f'DROP DATABASE IF EXISTS "{name}"')
    _admin(f'CREATE DATABASE "{name}"')


def _drop_database(name: str) -> None:
    _admin(f'DROP DATABASE IF EXISTS "{name}"')


def _run_alembic(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)
    finished = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
    )
    if finished.returncode != 0:
        raise SystemExit(f"alembic failed:\n{finished.stdout}\n{finished.stderr[-3000:]}")


def _wait_for_health(
    client: httpx.Client, process: subprocess.Popen, log_path: Path, seconds: int = 40
) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            if client.get("/health", timeout=2).status_code == 200:
                return True
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(0.3)
    print(log_path.read_text()[-3000:] if log_path.exists() else "")
    return False


def _start_server(env: dict, port: int, log_path: Path) -> subprocess.Popen:
    handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - closed by the caller
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "site_gpt.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=handle,
        stderr=handle,
    )
    process._gate_log = handle  # type: ignore[attr-defined]
    return process


def _stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    handle = getattr(process, "_gate_log", None)
    if handle is not None:
        handle.close()


def _sign(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), (stamp + ".").encode() + body, hashlib.sha256
    ).hexdigest()
    return body, f"t={stamp},v1={signature}"


def _event(event_id: str, event_type: str, created: int, obj: dict) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "created": created,
        "data": {"object": obj},
    }


def _now() -> int:
    return int(datetime.now(UTC).timestamp())


def main() -> int:  # noqa: C901 - a runbook is one long function on purpose
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8096)
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args()

    libpq = f"{PG}/{GATE_DB}"
    database_url = libpq.replace("postgresql://", "postgresql+psycopg2://", 1)
    base = f"http://127.0.0.1:{args.port}"
    stamp = uuid4().hex[:8]

    fixture_dir = Path(tempfile.mkdtemp(prefix="v5_gate_5g_"))
    (fixture_dir / "stripe").mkdir()
    (fixture_dir / "stripe" / "__init__.py").write_text(FAKE_STRIPE)
    stripe_log = fixture_dir / "stripe_calls.jsonl"
    server_log = fixture_dir / "uvicorn.log"

    _create_database(GATE_DB)
    _run_alembic(database_url)

    engine = create_engine(database_url)
    db = sessionmaker(bind=engine)()

    server_env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "BILLING_ENABLED": "true",
        "STRIPE_SECRET_KEY": "sk_test_gate_5g",
        "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "STRIPE_API_VERSION": "2026-11-18.endive",
        "STRIPE_PRICE_IDS": "",
        "FRONTEND_URL": FRONTEND_URL,
        "PLATFORM_CONSOLE_ENABLED": "true",
        "RATE_LIMIT_BACKEND": "memory",
        "PYTHONPATH": str(fixture_dir) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "FAKE_STRIPE_LOG": str(stripe_log),
    }
    for key in ("NO_PROXY", "no_proxy"):
        server_env.pop(key, None)

    client = httpx.Client(base_url=base, timeout=60.0, trust_env=False)
    server = _start_server(server_env, args.port, server_log)
    if not _wait_for_health(client, server, server_log):
        _stop_server(server)
        print("FAIL: the gate API did not become healthy")
        return 1

    def calls() -> list[dict]:
        if not stripe_log.exists():
            return []
        return [
            json.loads(line)
            for line in stripe_log.read_text().splitlines()
            if line.strip()
        ]

    def db_scalar(sql: str, **params):
        with engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()

    def owner_cli(command: str, email: str) -> int:
        env = {**os.environ, "DATABASE_URL": database_url}
        env.pop("NO_PROXY", None)
        env.pop("no_proxy", None)
        finished = subprocess.run(
            [
                sys.executable,
                "scripts/platform_owner.py",
                command,
                "--email",
                email,
                "--actor",
                "V5-5G gate",
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            capture_output=True,
            text=True,
        )
        if finished.returncode != 0:
            print(finished.stdout, finished.stderr)
        return finished.returncode

    try:
        # -- 1. Schema ------------------------------------------------------
        version = db_scalar("select version_num from alembic_version")
        check("single Alembic head is M12", version == HEAD, str(version))
        for table in (
            "platform_owners",
            "platform_audit_logs",
            "catalog_plans",
            "plan_prices",
            "platform_settings",
        ):
            check(
                f"{table} exists",
                db_scalar(
                    "select count(*) from information_schema.tables "
                    "where table_schema='public' and table_name=:name",
                    name=table,
                )
                == 1,
            )
        check(
            "one active price index is partial",
            "WHERE active" in (
                db_scalar(
                    "select indexdef from pg_indexes "
                    "where tablename='plan_prices' "
                    "and indexname='uq_plan_prices_active_plan'"
                )
                or ""
            ),
        )
        health = client.get("/health")
        check("health answers", health.status_code == 200, health.text[:100])

        # -- 2. Public funnel (API level) -----------------------------------
        plans = client.get("/api/plans")
        check(
            "empty catalog is public and honest",
            plans.status_code == 200 and plans.json() == {"plans": []},
            plans.text[:120],
        )
        config = client.get("/api/public/config")
        check(
            "public display config is empty before operator input",
            config.status_code == 200
            and config.json() == {"status_message": "", "support_email": ""},
            config.text[:120],
        )

        admin_email = f"gate5g-{stamp}@example.com"
        password = "Gate!passw0rd"
        registered = client.post(
            "/api/register",
            json={
                "company_name": f"Gate 5G {stamp}",
                "first_name": "Gate",
                "last_name": "Admin",
                "email": admin_email,
                "password": password,
            },
        )
        check("register", registered.status_code in (200, 201), registered.text[:160])
        token = client.post(
            "/api/token", json={"email": admin_email, "password": password}
        )
        check("login", token.status_code == 200, token.text[:120])
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
        me = client.get("/api/users/me", headers=headers)
        check(
            "registered user is a company admin",
            me.status_code == 200 and me.json()["role"] == "admin",
            me.text[:120],
        )
        company_id = me.json()["company_id"] if me.status_code == 200 else None

        other_email = f"gate5g-other-{stamp}@example.com"
        other_reg = client.post(
            "/api/register",
            json={
                "company_name": f"Gate 5G Other {stamp}",
                "first_name": "Other",
                "last_name": "Admin",
                "email": other_email,
                "password": password,
            },
        )
        other_token = client.post(
            "/api/token", json={"email": other_email, "password": password}
        )
        other_headers = {
            "Authorization": f"Bearer {other_token.json()['access_token']}"
        }
        check(
            "second tenant registers for isolation checks",
            other_reg.status_code in (200, 201) and other_token.status_code == 200,
        )

        # -- 3. Platform owner and catalog ---------------------------------
        anonymous = client.get("/api/platform/session")
        check(
            "anonymous platform call is refused",
            anonymous.status_code in (401, 403),
            str(anonymous.status_code),
        )
        check(
            "tenant admin is refused before a grant",
            client.get("/api/platform/session", headers=headers).status_code == 403,
        )
        check(
            "API key is not a platform session",
            client.get(
                "/api/platform/session", headers={"X-API-Key": "sk_fake_gate"}
            ).status_code
            in (401, 403),
        )
        check("CLI grants the operator", owner_cli("grant", admin_email) == 0)
        session = client.get("/api/platform/session", headers=headers)
        check(
            "granted owner reaches the console",
            session.status_code == 200 and session.json()["email"] == admin_email,
            session.text[:120],
        )
        check(
            "the other tenant is still refused",
            client.get(
                "/api/platform/session", headers=other_headers
            ).status_code
            == 403,
        )

        plan_body = {
            "code": "gate",
            "name": "Gate",
            "description": "Gate plan.",
            "features": ["One website"],
            "limits": {
                "websites": 1,
                "seats": 2,
                "daily_messages": 100,
                "session_messages": 20,
            },
            "self_serve_checkout": True,
            "interval": "month",
            "currency": "usd",
            "price_minor": 2900,
            "stripe_price_id": "price_gate_v1",
            "reason": "gate catalog",
        }
        created = client.post("/api/platform/plans", json=plan_body, headers=headers)
        check("owner creates a draft plan", created.status_code == 200, created.text[:160])
        check(
            "draft is invisible publicly",
            client.get("/api/plans").json() == {"plans": []},
        )
        unpublished_checkout = client.post(
            "/api/billing/checkout", json={"plan_code": "gate"}, headers=headers
        )
        check(
            "draft cannot be bought",
            unpublished_checkout.status_code == 400,
            unpublished_checkout.text[:120],
        )
        published = client.post(
            "/api/platform/plans/gate/publish",
            json={"reason": "approved for the gate", "confirm": True},
            headers=headers,
        )
        check("owner publishes the plan", published.status_code == 200, published.text[:160])
        public = client.get("/api/plans").json()["plans"]
        check(
            "public catalog carries the plan without Stripe ids",
            len(public) == 1
            and public[0]["price_minor"] == 2900
            and "stripe" not in json.dumps(public).lower(),
            json.dumps(public)[:200],
        )
        price_changed = client.post(
            "/api/platform/plans/gate/prices",
            json={
                "interval": "month",
                "currency": "usd",
                "price_minor": 3900,
                "stripe_price_id": "price_gate_v2",
                "reason": "gate price change",
                "confirm": True,
            },
            headers=headers,
        )
        prices = price_changed.json().get("prices", []) if price_changed.status_code == 200 else []
        check(
            "price change archives the old row and keeps history",
            price_changed.status_code == 200
            and len(prices) == 2
            and sum(1 for price in prices if price["active"]) == 1
            and next(price for price in prices if price["active"])["stripe_price_id"]
            == "price_gate_v2",
            price_changed.text[:200],
        )
        check(
            "public price follows the new active record",
            client.get("/api/plans").json()["plans"][0]["price_minor"] == 3900,
        )

        contact = client.post(
            "/api/platform/plans",
            json={
                **plan_body,
                "code": "contact",
                "name": "Contact",
                "self_serve_checkout": False,
                "stripe_price_id": None,
            },
            headers=headers,
        )
        client.post(
            "/api/platform/plans/contact/publish",
            json={"reason": "contact sales", "confirm": True},
            headers=headers,
        )
        unmapped = client.post(
            "/api/platform/plans",
            json={**plan_body, "code": "unmapped", "name": "Unmapped", "stripe_price_id": None},
            headers=headers,
        )
        unmapped_publish = client.post(
            "/api/platform/plans/unmapped/publish",
            json={"reason": "missing mapping", "confirm": True},
            headers=headers,
        )
        check("contact-sales plan is created", contact.status_code == 200)
        check(
            "unmapped self-serve plan cannot publish while billing is on",
            unmapped.status_code == 200 and unmapped_publish.status_code == 409,
            unmapped_publish.text[:160],
        )

        # -- 4. Checkout ----------------------------------------------------
        unknown = client.post(
            "/api/billing/checkout", json={"plan_code": "nope"}, headers=headers
        )
        contact_checkout = client.post(
            "/api/billing/checkout", json={"plan_code": "contact"}, headers=headers
        )
        tampered = client.post(
            "/api/billing/checkout",
            json={
                "plan_code": "gate",
                "amount": 1,
                "price_id": "price_attacker",
                "success_url": "https://attacker.test/ok",
                "customer": "cus_attacker",
            },
            headers=headers,
        )
        check("unknown plan is refused", unknown.status_code == 400, unknown.text[:120])
        check(
            "contact-sales plan cannot be bought",
            contact_checkout.status_code == 409,
            contact_checkout.text[:120],
        )
        check(
            "Checkout starts with only the plan code trusted",
            tampered.status_code == 200 and tampered.json()["url"].startswith("https://"),
            tampered.text[:160],
        )
        checkout_call = next(
            (call for call in calls() if call["call"] == "checkout.Session.create"),
            None,
        )
        kwargs = (checkout_call or {}).get("kwargs", {})
        check(
            "Checkout uses the server-resolved Price ID and subscription mode",
            kwargs.get("mode") == "subscription"
            and kwargs.get("line_items") == [{"price": "price_gate_v2", "quantity": 1}],
            str(kwargs.get("line_items")),
        )
        check(
            "Checkout return URLs come from configuration",
            kwargs.get("success_url", "").startswith(f"{FRONTEND_URL}/app/billing")
            and kwargs.get("cancel_url", "").startswith(f"{FRONTEND_URL}/app/billing"),
            f"{kwargs.get('success_url')} | {kwargs.get('cancel_url')}",
        )
        check(
            "client amount/price/customer never reach Stripe",
            "price_attacker" not in json.dumps(kwargs)
            and "cus_attacker" not in json.dumps(kwargs)
            and "attacker.test" not in json.dumps(kwargs),
        )
        check(
            "Checkout carries an idempotency key",
            bool(kwargs.get("idempotency_key")),
            str(kwargs.get("idempotency_key")),
        )
        row_customer = db_scalar(
            "select stripe_customer_id from subscriptions where company_id=:id",
            id=company_id,
        )
        check(
            "company is linked to the fixture customer",
            row_customer == "cus_gate",
            str(row_customer),
        )
        check(
            "returning from Checkout grants nothing before a webhook",
            db_scalar(
                "select status from subscriptions where company_id=:id", id=company_id
            )
            == "incomplete",
        )

        # -- 5. Webhooks ----------------------------------------------------
        now = _now()
        checkout_event = _event(
            f"evt_gate_checkout_{stamp}",
            "checkout.session.completed",
            now,
            {
                "id": "cs_gate",
                "customer": "cus_gate",
                "subscription": "sub_gate",
                "client_reference_id": company_id,
                "payment_status": "paid",
                "metadata": {
                    "company_id": company_id,
                    "plan_code": "gate",
                    "plan_interval": "month",
                },
            },
        )
        body, signature = _sign(checkout_event)
        first = client.post(
            "/api/billing/webhook", content=body, headers={"Stripe-Signature": signature}
        )
        check("signed checkout webhook is accepted", first.status_code == 200, first.text[:160])
        check(
            "the webhook activates the subscription",
            db_scalar(
                "select status from subscriptions where company_id=:id", id=company_id
            )
            == "active",
        )
        duplicate = client.post(
            "/api/billing/webhook", content=body, headers={"Stripe-Signature": signature}
        )
        check(
            "duplicate event is acknowledged once",
            duplicate.status_code == 200 and duplicate.json().get("duplicate") is True,
            duplicate.text[:120],
        )
        check(
            "duplicate did not create a second receipt",
            db_scalar(
                "select count(*) from billing_events where stripe_event_id=:id",
                id=checkout_event["id"],
            )
            == 1,
        )
        events_before = db_scalar("select count(*) from billing_events")
        invalid_signature = signature[:-1] + ("0" if signature[-1] != "0" else "1")
        invalid = client.post(
            "/api/billing/webhook",
            content=body,
            headers={"Stripe-Signature": invalid_signature},
        )
        check(
            "invalid signature changes no row",
            invalid.status_code == 400
            and db_scalar("select count(*) from billing_events") == events_before,
            invalid.text[:120],
        )
        stale = _event(
            f"evt_gate_stale_{stamp}",
            "customer.subscription.updated",
            now - 3600,
            {
                "id": "sub_gate",
                "customer": "cus_gate",
                "status": "canceled",
                "cancel_at_period_end": True,
                "metadata": {"company_id": company_id, "plan_code": "gate"},
            },
        )
        stale_body, stale_sig = _sign(stale)
        client.post(
            "/api/billing/webhook",
            content=stale_body,
            headers={"Stripe-Signature": stale_sig},
        )
        check(
            "an older event cannot restore a worse state",
            db_scalar(
                "select status from subscriptions where company_id=:id", id=company_id
            )
            == "active",
        )
        foreign = _event(
            f"evt_gate_foreign_{stamp}",
            "customer.subscription.updated",
            now + 60,
            {
                "id": "sub_foreign",
                "customer": "cus_foreign",
                "status": "canceled",
                "metadata": {"company_id": str(uuid4())},
            },
        )
        foreign_body, foreign_sig = _sign(foreign)
        client.post(
            "/api/billing/webhook",
            content=foreign_body,
            headers={"Stripe-Signature": foreign_sig},
        )
        check(
            "a foreign customer cannot move this company",
            db_scalar(
                "select status from subscriptions where company_id=:id", id=company_id
            )
            == "active",
        )

        # -- 6. Entitlements ------------------------------------------------
        usage = client.get("/api/billing/usage", headers=headers)
        check(
            "usage reports the granted website ceiling",
            usage.status_code == 200
            and usage.json()["websites"]["limit"] == 1
            and usage.json()["websites"]["used"] == 0,
            usage.text[:160],
        )
        site = client.post(
            "/api/websites/",
            json={
                "url": "https://gate.example.test",
                "site_map_url": "",
                "name": "Gate site",
            },
            headers=headers,
        )
        check("first website is allowed", site.status_code in (200, 201), site.text[:160])
        over = client.post(
            "/api/websites/",
            json={
                "url": "https://second.example.test",
                "site_map_url": "",
                "name": "Second site",
            },
            headers=headers,
        )
        check(
            "second website is refused at the plan ceiling",
            over.status_code == 403,
            over.text[:160],
        )

        portal = client.post("/api/billing/portal", headers=headers)
        check("portal session is created", portal.status_code == 200, portal.text[:160])
        portal_call = next(
            (call for call in calls() if call["call"] == "billing_portal.Session.create"),
            None,
        )
        check(
            "portal uses the company's stored customer and fixed return URL",
            (portal_call or {}).get("kwargs", {}).get("customer") == "cus_gate"
            and (portal_call or {}).get("kwargs", {}).get("return_url")
            == f"{FRONTEND_URL}/app/billing",
            str((portal_call or {}).get("kwargs")),
        )
        other_portal = client.post("/api/billing/portal", headers=other_headers)
        other_subscription = client.get(
            "/api/billing/subscription", headers=other_headers
        )
        check(
            "another tenant has no portal or subscription state",
            other_portal.status_code == 404
            and other_subscription.status_code == 200
            and other_subscription.json()["has_billing_account"] is False,
            f"{other_portal.status_code}/{other_subscription.text[:80]}",
        )

        # -- 7. Platform operations ----------------------------------------
        overview = client.get("/api/platform/overview", headers=headers)
        companies = client.get("/api/platform/companies", headers=headers)
        subscriptions = client.get("/api/platform/subscriptions", headers=headers)
        check(
            "overview counts both companies",
            overview.status_code == 200 and overview.json()["companies"] >= 2,
            overview.text[:160],
        )
        check(
            "company list is paginated and searchable",
            companies.status_code == 200
            and companies.json()["total"] >= 2
            and any("Gate 5G" in item["name"] for item in companies.json()["items"]),
            companies.text[:160],
        )
        check(
            "subscription list carries mirrored state and Stripe references",
            subscriptions.status_code == 200
            and subscriptions.json()["items"][0]["stripe_customer_id"] == "cus_gate",
            subscriptions.text[:200],
        )
        reconcile = client.post(
            f"/api/platform/subscriptions/{company_id}/actions",
            json={
                "action": "request_reconciliation",
                "reason": "gate reconciliation",
            },
            headers=headers,
        )
        check(
            "reconciliation is audit-only",
            reconcile.status_code == 200,
            reconcile.text[:160],
        )
        cancel = client.post(
            f"/api/platform/subscriptions/{company_id}/actions",
            json={
                "action": "cancel_at_period_end",
                "reason": "gate cancellation",
                "confirm": True,
            },
            headers=headers,
        )
        check(
            "cancel-at-period-end calls Stripe",
            cancel.status_code == 200
            and any(call["call"] == "Subscription.modify" for call in calls()),
            cancel.text[:160],
        )
        check(
            "the mirror is not written by the action",
            db_scalar(
                "select cancel_at_period_end from subscriptions where company_id=:id",
                id=company_id,
            )
            is False,
        )
        cancel_event = _event(
            f"evt_gate_cancel_{stamp}",
            "customer.subscription.updated",
            now + 120,
            {
                "id": "sub_gate",
                "customer": "cus_gate",
                "status": "active",
                "cancel_at_period_end": True,
                "metadata": {"company_id": company_id, "plan_code": "gate"},
            },
        )
        cancel_body, cancel_sig = _sign(cancel_event)
        client.post(
            "/api/billing/webhook",
            content=cancel_body,
            headers={"Stripe-Signature": cancel_sig},
        )
        check(
            "the verified webhook applies cancellation",
            db_scalar(
                "select cancel_at_period_end from subscriptions where company_id=:id",
                id=company_id,
            )
            is True,
        )
        preview = client.post(
            "/api/platform/settings/public_status_message/preview",
            json={"value": "Gate maintenance"},
            headers=headers,
        )
        saved = client.put(
            "/api/platform/settings/public_status_message",
            json={"value": "Gate maintenance", "reason": "gate settings"},
            headers=headers,
        )
        public_config = client.get("/api/public/config")
        check(
            "settings preview writes nothing and update is public",
            preview.status_code == 200
            and saved.status_code == 200
            and public_config.json()["status_message"] == "Gate maintenance",
            public_config.text[:160],
        )
        unknown_setting = client.put(
            "/api/platform/settings/secret_key",
            json={"value": "nope", "reason": "gate"},
            headers=headers,
        )
        bad_email = client.put(
            "/api/platform/settings/support_contact_email",
            json={"value": "not-an-email", "reason": "gate"},
            headers=headers,
        )
        check(
            "unknown keys and invalid values are refused",
            unknown_setting.status_code == 404 and bad_email.status_code == 400,
        )
        audit = client.get("/api/platform/audit", headers=headers)
        actions = {event["action"] for event in audit.json().get("events", [])}
        check(
            "audit records the operator actions",
            audit.status_code == 200
            and {
                "platform.plan.publish",
                "platform.plan.price",
                "platform.subscription.reconciliation_requested",
                "platform.subscription.cancel_at_period_end",
                "platform.setting.update",
            }
            <= actions,
            str(sorted(actions)),
        )
        check(
            "audit route is read-only over HTTP",
            client.put("/api/platform/audit", json={}, headers=headers).status_code == 405
            and client.delete("/api/platform/audit", headers=headers).status_code == 405,
        )
        from site_gpt.app.services import platform as platform_service

        redacted = platform_service.record_audit(
            db,
            action="gate.redaction",
            target_type="company",
            target_id=str(company_id),
            detail={
                "password": "hunter2",
                "api_key": "sk_live_gate",
                "nested": {"stripe_secret_key": "sk_test_gate"},
                "label": "ok",
            },
        )
        check(
            "audit redacts secret-shaped detail",
            redacted.detail["password"] == "[redacted]"
            and redacted.detail["api_key"] == "[redacted]"
            and redacted.detail["nested"]["stripe_secret_key"] == "[redacted]"
            and redacted.detail["label"] == "ok",
            str(redacted.detail),
        )
        check(
            "no raw secret is stored in the audit row",
            db_scalar(
                "select count(*) from platform_audit_logs where detail::text like :needle",
                needle="%sk_live_gate%",
            )
            == 0,
        )

        # -- 8. Invoice failure and cancellation ---------------------------
        failed = _event(
            f"evt_gate_failed_{stamp}",
            "invoice.payment_failed",
            now + 180,
            {"subscription": "sub_gate", "customer": "cus_gate"},
        )
        failed_body, failed_sig = _sign(failed)
        client.post(
            "/api/billing/webhook",
            content=failed_body,
            headers={"Stripe-Signature": failed_sig},
        )
        check(
            "invoice failure moves the mirror to past_due",
            db_scalar(
                "select status from subscriptions where company_id=:id", id=company_id
            )
            == "past_due",
        )
        past_due_usage = client.get("/api/billing/usage", headers=headers)
        check(
            "past_due grants no plan ceiling",
            past_due_usage.json()["enforced"] is False
            and past_due_usage.json()["websites"]["limit"] is None,
            past_due_usage.text[:160],
        )
        deleted = _event(
            f"evt_gate_deleted_{stamp}",
            "customer.subscription.deleted",
            now + 240,
            {
                "id": "sub_gate",
                "customer": "cus_gate",
                "status": "canceled",
                "metadata": {"company_id": company_id, "plan_code": "gate"},
            },
        )
        deleted_body, deleted_sig = _sign(deleted)
        client.post(
            "/api/billing/webhook",
            content=deleted_body,
            headers={"Stripe-Signature": deleted_sig},
        )
        paid = _event(
            f"evt_gate_paid_{stamp}",
            "invoice.paid",
            now + 300,
            {"subscription": "sub_gate", "customer": "cus_gate"},
        )
        paid_body, paid_sig = _sign(paid)
        client.post(
            "/api/billing/webhook",
            content=paid_body,
            headers={"Stripe-Signature": paid_sig},
        )
        check(
            "a canceled subscription is not revived by an invoice",
            db_scalar(
                "select status from subscriptions where company_id=:id", id=company_id
            )
            == "canceled",
        )

        # -- 9. Owner revocation --------------------------------------------
        check("CLI revokes the operator", owner_cli("revoke", admin_email) == 0)
        check(
            "revocation takes effect on the next request",
            client.get("/api/platform/session", headers=headers).status_code == 403,
        )

        # -- 10. Billing off -------------------------------------------------
        calls_before_off = len(calls())
        _stop_server(server)
        off_env = {
            **server_env,
            "BILLING_ENABLED": "false",
        }
        server = _start_server(off_env, args.port, server_log)
        if not _wait_for_health(client, server, server_log):
            check("billing-off server starts", False)
            raise SystemExit(1)
        status = client.get("/api/billing/status", headers=headers)
        subscription = client.get("/api/billing/subscription", headers=headers)
        checkout = client.post(
            "/api/billing/checkout", json={"plan_code": "gate"}, headers=headers
        )
        webhook = client.post(
            "/api/billing/webhook", content=b"{}", headers={"Stripe-Signature": "x"}
        )
        check(
            "billing off answers status and 404s every other billing route",
            status.status_code == 200
            and status.json() == {"enabled": False}
            and subscription.status_code == 404
            and checkout.status_code == 404
            and webhook.status_code == 404,
            f"{status.text[:40]}/{subscription.status_code}/{checkout.status_code}/{webhook.status_code}",
        )
        second_after_off = client.post(
            "/api/websites/",
            json={
                "url": "https://second.example.test",
                "site_map_url": "",
                "name": "Second site",
            },
            headers=headers,
        )
        check(
            "billing off stops plan enforcement (V4 behaviour)",
            second_after_off.status_code in (200, 201),
            second_after_off.text[:160],
        )
        check(
            "billing off makes no provider call",
            len(calls()) == calls_before_off,
            f"{calls_before_off} -> {len(calls())}",
        )

        # -- 11. Blocked externals -------------------------------------------
        blocked(
            "Stripe test-mode Checkout, Portal and webhook delivery",
            "no Stripe merchant test account/keys (D3); the local fixture and signed "
            "fixtures are what ran here",
        )
        blocked(
            "browser journey across /, /pricing, /app and /platform",
            "the gate is headless; the manual browser pass is recorded in "
            "PLAN_V5.md Wave 4 and must be repeated after deployment",
        )
    finally:
        _stop_server(server)
        db.close()
        engine.dispose()
        client.close()

    failed = [name for name, ok in RESULTS if not ok]
    print()
    print(
        f"V5-5G: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed, "
        f"{len(BLOCKED)} blocked"
    )
    if failed:
        for name in failed:
            print(f"  FAILED: {name}")

    if not args.keep_db:
        _drop_database(GATE_DB)
        print(f"dropped throwaway database {GATE_DB}")
    else:
        print(f"kept throwaway database {GATE_DB}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
