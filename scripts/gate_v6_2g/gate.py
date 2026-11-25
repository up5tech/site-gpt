"""V6-2G items 1-14 — the V6-21/V6-23 staging checklist as a runnable check.

`PLAN_V6.md` records the reliability gate as 14 observations: health probes, the
ops route, a stopped worker, a queue backlog, repeated job failures, dependency
alerts, fleet 5xx, an ingress-only 5xx, replica coverage, the per-worker roster,
Redis durability, a Redis interruption, graceful shutdown and pool sizing. The
table there wants pasted command output, not a summary, so this script runs the
items and prints one paste-ready row per item.

    bash scripts/gate_v6_2g/run_all.sh            # throwaway database + keyspace
    bash scripts/gate_v6_2g/run_all.sh --keep-db  # leave it for inspection

Infrastructure it owns
----------------------

* **PostgreSQL** — a database named `v6_gate_2g` (override `GATE_DB`, which must
  keep that prefix). It drops and recreates it, migrates to head and drops it at
  the end. The server is `GATE_PG` (default `postgresql://postgres:postgres@127.0.0.1:5432`).
* **Redis** — one database index on `GATE_REDIS` (default
  `redis://127.0.0.1:6379/15`), flushed before and after. Database 0 is refused:
  the development stack uses it, and `FLUSHDB` here must not reach it.
* **Processes** — two API replicas with a good database and Redis (A, D), one
  with a closed database port (B), one with a closed Redis port (C), a production
  profile replica with no ops token (N), and workers. Every process is a real
  `uvicorn`/`site_gpt.app.worker` started on 127.0.0.1 with its own log file.

Faults it cannot own
--------------------

A dependency outage is reproduced the way item 1 already allows — "B booted with
a closed port" — because this gate will not stop the host's shared PostgreSQL or
Redis. So items that need the dependency *stopped and restarted* (6, 12) and the
item that needs the server's `CONFIG` changed (11) run their observations here
and are recorded **BLOCKED**, with what was seen, for the staging pass. Item 8
needs an ingress, so it is always blocked until one is named with its query and
lag. A blocked row never counts as a pass.

Shortcuts, stated where they are used
-------------------------------------

* Item 4 backdates `ops:queue:last_pop` instead of waiting the 900 s threshold.
* Item 5 needs PostgreSQL: on SQLite `"not-a-uuid"` is not a bind error.
* Item 13 needs a *slow* job and there is no network or provider here, so a
  retention purge is held on a PostgreSQL table lock. The property under test is
  the same: a popped job finishes before the process exits.

Every shortcut is printed in the row it affects.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg2
import redis
from psycopg2.extras import execute_values

# A bracketed IPv6 entry in NO_PROXY makes older httpx builds raise at import.
os.environ.pop("NO_PROXY", None)
os.environ.pop("no_proxy", None)

REPO_ROOT = Path(__file__).resolve().parents[2]

HEAD = "0b22b30bf930"
GATE_DB = os.getenv("GATE_DB", "v6_gate_2g")
PG = os.getenv("GATE_PG", "postgresql://postgres:postgres@127.0.0.1:5432").rstrip("/")
REDIS_SPEC = os.getenv("GATE_REDIS", "redis://127.0.0.1:6379/15")
OPS_TOKEN = "gate-v6-2g-ops-token"
#: A port nothing listens on. PostgreSQL and Redis clients fail on it at once
#: (ECONNREFUSED on loopback), which is the closed-port replica item 1 allows.
DEAD_PORT = 1
#: Ceiling `pg_stat_activity` is compared with: two API replicas and one worker.
POOL_INSTANCES = 3

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"


def say(text: str = "") -> None:
    print(text, flush=True)


# -- results ----------------------------------------------------------------


@dataclass
class Row:
    number: int
    item: str
    verdict: str = ""
    reason: str = ""
    lines: list[str] = field(default_factory=list)

    def observe(self, text: str) -> None:
        self.lines.append(str(text))
        say(f"    {text}")


ROWS: dict[int, Row] = {}


def row(number: int, item: str) -> Row:
    if number not in ROWS:
        ROWS[number] = Row(number=number, item=item)
        say(f"\n[{number}] {item}")
    return ROWS[number]


def conclude(number: int, verdict: str, reason: str = "", **extra) -> bool:
    current = ROWS[number]
    current.verdict = verdict
    current.reason = reason
    for key, value in extra.items():
        current.observe(f"{key}: {value}")
    if verdict == PASS:
        say(f"  -> PASS {current.item}")
        return True
    if verdict == BLOCKED:
        say(f"  -> BLOCKED {current.item} — {reason}")
        return False
    say(f"  -> FAIL {current.item} — {reason}")
    return False


# -- HTTP / Redis / SQL helpers --------------------------------------------


#: A replica whose Redis port is closed answers slowly rather than refusing:
#: redis-py retries a failed command, so one read costs 4-10 s and
#: `/api/ops/status` (heartbeat, durability, fleet buckets) costs ~25 s. A short
#: client timeout would report the replica as unreachable and hide the very
#: degradation the item is looking for, so every call here is patient.
HTTP_TIMEOUT_SECONDS = 90.0


def get(url: str, *, headers: dict | None = None, timeout: float = HTTP_TIMEOUT_SECONDS):
    """One GET, or None when it could not be made."""
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            return client.get(url, headers=headers or {})
    except Exception:  # noqa: BLE001 - the check reports, it does not raise
        return None


def storm(url: str, count: int, *, concurrency: int = 1) -> list[int]:
    """`count` GETs to one URL; 0 records a request that never answered.

    One connection per request (`Connection: close`) on purpose: a 500 makes
    uvicorn close the socket, and a pooled keep-alive connection then fails the
    *next* request with a transport error that is not a 5xx — which read as 14
    of 25 counted errors until this loop stopped reusing connections.
    """

    def one() -> int:
        try:
            with httpx.Client(trust_env=False, timeout=HTTP_TIMEOUT_SECONDS) as client:
                return client.get(url, headers={"Connection": "close"}).status_code
        except Exception:  # noqa: BLE001 - the count is the evidence
            return 0

    if concurrency <= 1:
        return [one() for _ in range(count)]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda _: one(), range(count)))


def body(response) -> dict:
    if response is None:
        return {}
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - an unreadable body is an empty one
        return {}
    return payload if isinstance(payload, dict) else {}


def snapshot(origin: str) -> dict:
    """`GET /api/ops/status` as a dict; {} when it did not answer 200."""
    response = get(f"{origin}/api/ops/status", headers={"X-Ops-Token": OPS_TOKEN})
    if response is None or response.status_code != 200:
        return {}
    return body(response)


def codes(payload: dict) -> list[str]:
    return [
        str(alert.get("code"))
        for alert in payload.get("alerts") or []
        if isinstance(alert, dict)
    ]


def alert(payload: dict, code: str) -> dict:
    for entry in payload.get("alerts") or []:
        if isinstance(entry, dict) and entry.get("code") == code:
            return entry
    return {}


def wait_until(predicate, *, timeout: float, interval: float = 0.5):
    """The first truthy result, or None once `timeout` elapsed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
        except Exception:  # noqa: BLE001 - a probe that raises is not ready
            value = None
        if value:
            return value
        time.sleep(interval)
    return None


@dataclass(frozen=True)
class RedisTarget:
    host: str
    port: int
    db: int
    password: str | None


def parse_redis(spec: str) -> RedisTarget:
    raw = spec.strip()
    if raw.startswith("redis://"):
        raw = raw[len("redis://") :]
    password = None
    if "@" in raw:
        credentials, raw = raw.split("@", 1)
        if ":" in credentials:
            _, password = credentials.split(":", 1)
        else:
            password = credentials
    host_port, _, db_part = raw.partition("/")
    host, _, port = host_port.partition(":")
    return RedisTarget(
        host=host or "127.0.0.1",
        port=int(port or 6379),
        db=int(db_part or 0),
        password=password,
    )


def redis_client(target: RedisTarget) -> redis.Redis:
    return redis.Redis(
        host=target.host,
        port=target.port,
        db=target.db,
        password=target.password,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def with_app(url: str, name: str) -> str:
    """Label a process's connections, so `pg_stat_activity` can attribute them.

    Item 14 asks for a per-process pool ceiling, which a bare total cannot show.
    `application_name` is a libpq connection parameter, so it rides in the URL
    the app already reads and needs no code change.
    """
    if "application_name=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}application_name=gate-{name}"


def admin_connect() -> psycopg2.extensions.connection:
    """A connection to the server's `postgres` database (create/drop only)."""
    connection = psycopg2.connect(f"{PG}/postgres", connect_timeout=10)
    connection.autocommit = True
    return connection


def gate_connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(f"{PG}/{GATE_DB}", connect_timeout=10)


# -- processes --------------------------------------------------------------


@dataclass
class Proc:
    name: str
    popen: subprocess.Popen
    log_path: Path
    port: int | None = None

    @property
    def pid(self) -> int:
        return int(self.popen.pid)

    def alive(self) -> bool:
        return self.popen.poll() is None

    def text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def tail(self, limit: int = 6) -> str:
        lines = [line for line in self.text().splitlines() if line.strip()]
        return "\n".join(lines[-limit:])

    def stop(self, timeout: float = 15.0, *, sig: int = 15) -> int | None:
        """Signal once and wait; returns the exit code (None if it had to die)."""
        if not self.alive():
            return self.popen.returncode
        try:
            if sig == 9:
                self.popen.kill()
            else:
                self.popen.send_signal(sig)
        except ProcessLookupError:
            return self.popen.returncode
        try:
            return self.popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.popen.kill()
            self.popen.wait(timeout=10)
            return None


MANAGED_ENV = {
    "APP_ENV",
    "DATABASE_URL",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_PASSWORD",
    "OPS_STATUS_TOKEN",
    "OPS_EXPECTED_WORKERS",
    "DOCS_ENABLED",
    "JWT_SECRET_KEY",
    "CORS_ORIGINS",
    "SQL_ECHO",
    "RATE_LIMIT_BACKEND",
    "API_KEY_PEPPER",
    "INTEGRATION_WEBHOOK_SECRET",
    "TRUSTED_PROXY_IPS",
}


class Gate:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.procs: dict[str, Proc] = {}
        self.database_url = f"{PG}/{GATE_DB}"
        self.redis = parse_redis(REDIS_SPEC)
        self.client = redis_client(self.redis)
        self.expected_workers = 2
        self.commit = "unknown"
        self.by = os.getenv("GATE_BY", "gate (local rehearsal)")
        self.counter = 0

    # -- process plumbing ---------------------------------------------------

    def env(
        self,
        *,
        database_url: str | None = None,
        redis: RedisTarget | None = None,
        token: str | None = OPS_TOKEN,
        expected_workers: int | None = None,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        inherited = {k: v for k, v in os.environ.items() if k not in MANAGED_ENV}
        target = redis or self.redis
        env = {
            **inherited,
            "DATABASE_URL": database_url or self.database_url,
            "REDIS_HOST": target.host,
            "REDIS_PORT": str(target.port),
            "REDIS_DB": str(target.db),
            # Logs are read as files; keep them unbuffered and one JSON per line.
            "PYTHONUNBUFFERED": "1",
            "LOG_LEVEL": "INFO",
            "OPS_EXPECTED_WORKERS": str(
                self.expected_workers if expected_workers is None else expected_workers
            ),
        }
        if target.password:
            env["REDIS_PASSWORD"] = target.password
        if token is not None:
            env["OPS_STATUS_TOKEN"] = token
        if extra:
            env.update({k: str(v) for k, v in extra.items()})
        return env

    def _log_path(self, name: str) -> Path:
        self.counter += 1
        return self.log_dir / f"{self.counter:02d}-{name}.log"

    def start_api(self, name: str, *, env: dict[str, str], port: int | None = None) -> Proc:
        port = port or free_port()
        env = {**env, "DATABASE_URL": with_app(env["DATABASE_URL"], name)}
        log_path = self._log_path(name)
        handle = log_path.open("w", encoding="utf-8")
        popen = subprocess.Popen(
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
            cwd=REPO_ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        handle.close()
        proc = Proc(name=name, popen=popen, log_path=log_path, port=port)
        self.procs[name] = proc
        return proc

    def start_worker(self, name: str, *, env: dict[str, str]) -> Proc:
        env = {**env, "DATABASE_URL": with_app(env["DATABASE_URL"], name)}
        log_path = self._log_path(name)
        handle = log_path.open("w", encoding="utf-8")
        popen = subprocess.Popen(
            [sys.executable, "-m", "site_gpt.app.worker"],
            cwd=REPO_ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        handle.close()
        proc = Proc(name=name, popen=popen, log_path=log_path)
        self.procs[name] = proc
        return proc

    def await_api(self, proc: Proc, timeout: float = 40.0) -> bool:
        origin = f"http://127.0.0.1:{proc.port}"
        return bool(
            wait_until(
                lambda: (get(f"{origin}/health/live", timeout=2) or httpx.Response(500))
                .status_code
                == 200,
                timeout=timeout,
            )
        )

    def stop(self, name: str, *, sig: int = 15, timeout: float = 20.0) -> Proc | None:
        proc = self.procs.get(name)
        if proc is None:
            return None
        proc.stop(timeout=timeout, sig=sig)
        return proc

    def origin(self, name: str) -> str:
        return f"http://127.0.0.1:{self.procs[name].port}"

    # -- database -----------------------------------------------------------

    def create_database(self) -> None:
        connection = admin_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s",
                    (GATE_DB,),
                )
                cursor.execute(f'DROP DATABASE IF EXISTS "{GATE_DB}"')
                cursor.execute(f'CREATE DATABASE "{GATE_DB}"')
        finally:
            connection.close()

    def drop_database(self) -> None:
        connection = admin_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (GATE_DB,),
                )
                cursor.execute(f'DROP DATABASE IF EXISTS "{GATE_DB}"')
        finally:
            connection.close()

    def migrate(self) -> str:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env={**os.environ, "DATABASE_URL": self.database_url},
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "alembic upgrade head failed:\n" + (result.stdout + result.stderr)[-2000:]
            )
        connection = gate_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                revision = str(cursor.fetchone()[0])
        finally:
            connection.close()
        return revision

    def seed(self) -> tuple[str, str]:
        """One company with a retention policy and 3000 old chat messages.

        Item 13 needs a job that takes long enough to signal a worker mid-run;
        a purge held on a table lock is that job without any provider or network.
        """
        company_id, website_id = str(uuid4()), str(uuid4())
        connection = gate_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO companies (id, name, description, created_at, "
                    "updated_at) VALUES (%s, 'Gate tenant', '', now(), now())",
                    (company_id,),
                )
                cursor.execute(
                    "INSERT INTO websites (id, url, name, description, company_id, "
                    "site_map_url, status, ingest_status, created_at, updated_at) "
                    "VALUES (%s, 'https://gate.example.test', 'Gate site', '', %s, "
                    "'', 'active', 'none', now(), now())",
                    (website_id, company_id),
                )
                cursor.execute(
                    "INSERT INTO settings (id, key, value, company_id, created_at, "
                    "updated_at) VALUES (%s, 'retention_days', '1', %s, now(), now())",
                    (str(uuid4()), company_id),
                )
                old = datetime.now(UTC) - timedelta(days=10)
                execute_values(
                    cursor,
                    "INSERT INTO chat_messages (id, session_id, message, role, "
                    "website_id, answered, created_at, updated_at) VALUES %s",
                    [
                        (
                            str(uuid4()),
                            "gate-session",
                            f"row {index}",
                            "user",
                            website_id,
                            None,
                            old,
                            old,
                        )
                        for index in range(3000)
                    ],
                    page_size=500,
                )
            connection.commit()
        finally:
            connection.close()
        return company_id, website_id

    # -- process inventory --------------------------------------------------

    def start_workers(self, count: int = 2, prefix: str = "worker") -> list[Proc]:
        env = self.env()
        return [
            self.start_worker(f"{prefix}-{index}", env=env)
            for index in range(1, count + 1)
        ]

    def worker_keys(self) -> list[str]:
        return sorted(self.client.scan_iter(match="ops:worker:heartbeat:*"))

    def stop_all_workers(self) -> list[str]:
        """Stop every worker this run started, whatever its label."""
        stopped: list[str] = []
        for name in list(self.procs):
            if name.startswith("worker"):
                self.stop(name)
                stopped.append(name)
        return stopped


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def dead_database_url() -> str:
    return f"postgresql://gate:gate@127.0.0.1:{DEAD_PORT}/{GATE_DB}"


DEAD_REDIS = RedisTarget(host="127.0.0.1", port=DEAD_PORT, db=0, password=None)


# =========================================================================
# Items
# =========================================================================


def item_1(gate: Gate) -> None:
    current = row(1, "Health probes (V6-21)")
    a, b, c = gate.origin("api-a"), gate.origin("api-b"), gate.origin("api-c")

    for name, origin in (("A", a), ("B", b), ("C", c)):
        response = get(f"{origin}/health")
        status = None if response is None else response.status_code
        payload = body(response)
        current.observe(f"$ curl -sS {origin}/health -> {status} {json.dumps(payload)}")

    a_health = body(get(f"{a}/health"))
    b_health = body(get(f"{b}/health"))
    ready_b = get(f"{b}/health/ready")
    live_b = get(f"{b}/health/live")
    ready_c = get(f"{c}/health/ready")
    ready_c_body = body(ready_c)

    checks = {
        "A /health 200 ok/db/redis": (
            a_health.get("status") == "ok"
            and a_health.get("db") is True
            and a_health.get("redis") is True
        ),
        "A /health keeps its contract": {"status", "db", "redis", "rate_limiter"}
        <= set(a_health),
        "B /health 200 degraded (never an HTTP error)": b_health.get("status")
        == "degraded",
        "B /health/ready 503 not_ready db:false": ready_b is not None
        and ready_b.status_code == 503
        and body(ready_b).get("status") == "not_ready"
        and body(ready_b).get("db") is False,
        "B /health/live 200 alive": live_b is not None
        and live_b.status_code == 200
        and body(live_b).get("status") == "alive",
        "C /health/ready 200 degraded db:true redis:false": ready_c is not None
        and ready_c.status_code == 200
        and ready_c_body.get("status") == "degraded"
        and ready_c_body.get("db") is True
        and ready_c_body.get("redis") is False,
    }
    current.observe(
        f"$ curl -sS -o /dev/null -w '%{{http_code}}' {b}/health/ready -> "
        f"{None if ready_b is None else ready_b.status_code} {json.dumps(body(ready_b))}"
    )
    current.observe(
        f"$ curl -sS {b}/health/live -> "
        f"{None if live_b is None else live_b.status_code} {json.dumps(body(live_b))}"
    )
    current.observe(
        f"$ curl -sS {c}/health/ready -> "
        f"{None if ready_c is None else ready_c.status_code} {json.dumps(ready_c_body)}"
    )
    failed = [name for name, ok in checks.items() if not ok]
    current.observe(
        "fault: B = closed database port, C = closed Redis port (item 1's own "
        "'booted with a closed port'); no shared service was stopped"
    )
    if failed:
        conclude(1, FAIL, "; ".join(failed))
    else:
        conclude(1, PASS)


def item_2(gate: Gate) -> None:
    current = row(2, "Ops route contract (V6-21)")
    a = gate.origin("api-a")

    unset = get(f"{gate.origin('api-prod')}/api/ops/status", timeout=2)
    wrong = get(f"{a}/api/ops/status", headers={"X-Ops-Token": "not-the-token"})
    right = get(f"{a}/api/ops/status", headers={"X-Ops-Token": OPS_TOKEN})
    payload = body(right)
    raw = "" if right is None else right.text

    current.observe(
        "$ curl -sS -o /dev/null -w '%{http_code}' <production, token unset>"
        f"/api/ops/status -> {None if unset is None else unset.status_code}"
    )
    current.observe(
        f"$ curl -sS -H 'X-Ops-Token: not-the-token' {a}/api/ops/status -> "
        f"{None if wrong is None else wrong.status_code}"
    )
    current.observe(
        f"$ curl -sS -H 'X-Ops-Token: $T' {a}/api/ops/status -> "
        f"{None if right is None else right.status_code}, "
        f"Cache-Control: {None if right is None else right.headers.get('cache-control')}"
    )
    current.observe(
        "  jq -c '{db, codes:[.alerts[].code], thresholds}' -> "
        + json.dumps(
            {
                "db": payload.get("db"),
                "codes": codes(payload),
                "thresholds": payload.get("thresholds"),
            },
            sort_keys=True,
        )
    )

    prod_log = gate.procs["api-prod"].text() if "api-prod" in gate.procs else ""
    boot_lines = [
        line for line in prod_log.splitlines() if "config.ops_status_disabled" in line
    ]
    current.observe(
        f"production boot log: config.ops_status_disabled x{len(boot_lines)}"
    )
    prod_up = "api-prod" in gate.procs and gate.procs["api-prod"].alive()

    checks = {
        "unset token 404": unset is not None and unset.status_code == 404,
        "wrong token 401": wrong is not None and wrong.status_code == 401,
        "right token 200": right is not None and right.status_code == 200,
        "Cache-Control no-store": right is not None
        and (right.headers.get("cache-control") or "") == "no-store",
        "token never in the body": OPS_TOKEN not in raw,
        "exactly one boot warning": len(boot_lines) == 1,
        "snapshot has db/alerts/thresholds": {"db", "alerts", "thresholds"}
        <= set(payload),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if not prod_up:
        conclude(
            2,
            BLOCKED,
            "the production-profile replica did not start, so the unset-token 404 "
            "and its boot warning could not be observed; its log tail is below",
            **{"api-prod tail": gate.procs["api-prod"].tail() if "api-prod" in gate.procs else "n/a"},
        )
        return
    if failed:
        conclude(2, FAIL, "; ".join(failed))
    else:
        conclude(2, PASS)


def item_3(gate: Gate) -> None:
    current = row(3, "Worker stopped (V6-21)")
    thresholds = snapshot(gate.origin("api-a")).get("thresholds") or {}
    interval = int(thresholds.get("worker_heartbeat_interval_seconds") or 15)
    ttl_budget = 3 * interval

    started = time.monotonic()
    gate.stop_all_workers()
    gone = wait_until(
        lambda: gate.client.exists("ops:worker:heartbeat") == 0,
        timeout=ttl_budget + 30,
        interval=1,
    )
    key_gone = time.monotonic() - started

    missing = wait_until(
        lambda: "worker.heartbeat_missing"
        in codes(snapshot(gate.origin("api-a"))),
        timeout=30,
        interval=1,
    )
    alert_at = time.monotonic() - started
    payload = snapshot(gate.origin("api-a"))
    alert_codes = codes(payload)

    gate.start_workers()
    cleared = wait_until(
        lambda: not [
            code for code in codes(snapshot(gate.origin("api-a"))) if code.startswith("worker.")
        ],
        timeout=60,
        interval=1,
    )

    current.observe(
        f"$ redis-cli GET ops:worker:heartbeat -> (nil) after {key_gone:.1f} s "
        f"(TTL budget 3 x {interval} s = {ttl_budget} s; the key outlives the last "
        f"beat by up to one interval, so the pass window is {ttl_budget} + {interval} s)"
    )
    current.observe(
        f"alerts {alert_codes} at {alert_at:.1f} s after the stop; "
        f"worker.heartbeat_stale present: {'worker.heartbeat_stale' in alert_codes}"
    )
    current.observe(
        "restarted both workers -> "
        + json.dumps({"worker_alerts": [c for c in codes(snapshot(gate.origin('api-a'))) if c.startswith('worker.')]})
    )

    checks = {
        "legacy heartbeat key expires": bool(gone) and key_gone <= ttl_budget + 15,
        "worker.heartbeat_missing fires": bool(missing),
        "missing, not stale": "worker.heartbeat_missing" in alert_codes
        and "worker.heartbeat_stale" not in alert_codes,
        "restart clears every worker alert": bool(cleared),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(3, FAIL, "; ".join(failed))
    else:
        conclude(3, PASS)


def item_4(gate: Gate) -> None:
    current = row(4, "Queue backlog (V6-21)")
    thresholds = snapshot(gate.origin("api-a")).get("thresholds") or {}
    depth_alert = int(thresholds.get("queue_depth") or 100)
    age_alert = int(thresholds.get("queue_age_seconds") or 900)

    gate.client.delete("ops:queue:last_pop")
    gate.client.lpush("queue:jobs", '{"type":"noop"}')
    popped = wait_until(
        lambda: gate.client.exists("ops:queue:last_pop") == 1, timeout=30, interval=0.5
    )
    current.observe(
        "$ redis-cli LPUSH queue:jobs '{\"type\":\"noop\"}' -> consumed; "
        f"ops:queue:last_pop written: {bool(popped)} (value {gate.client.get('ops:queue:last_pop')})"
    )

    gate.stop_all_workers()
    for index in range(depth_alert + 1):
        gate.client.lpush("queue:jobs", json.dumps({"type": "noop", "i": index}))
    depth = int(gate.client.llen("queue:jobs"))
    payload = snapshot(gate.origin("api-a"))
    depth_fired = "queue.depth_high" in codes(payload)
    current.observe(
        f"$ redis-cli LLEN queue:jobs -> {depth} (threshold {depth_alert}); "
        f"alerts {codes(payload)}"
    )

    backdated = datetime.now(UTC) - timedelta(seconds=age_alert + 120)
    gate.client.set("ops:queue:last_pop", backdated.isoformat())
    payload = snapshot(gate.origin("api-a"))
    age_fired = "queue.age_high" in codes(payload)
    current.observe(
        "$ redis-cli SET ops:queue:last_pop "
        f"{backdated.isoformat()}  # backdated instead of waiting {age_alert} s -> "
        f"queue_age_seconds={payload.get('redis', {}).get('queue_age_seconds')}, "
        f"alerts {codes(payload)}"
    )

    gate.client.delete("queue:jobs")
    payload = snapshot(gate.origin("api-a"))
    cleared = [code for code in codes(payload) if code.startswith("queue.")]
    current.observe(
        f"$ redis-cli DEL queue:jobs -> depth 0; queue alerts {cleared}"
    )
    gate.start_workers()

    checks = {
        "a pop writes last_pop": bool(popped),
        "depth 101 raises queue.depth_high": depth == depth_alert + 1 and depth_fired,
        "a 17-minute-old pop raises queue.age_high": age_fired,
        "clearing the queue clears both": not cleared,
    }
    failed = [name for name, ok in checks.items() if not ok]
    current.observe(
        "shortcut: last_pop is backdated; the threshold itself is unchanged "
        f"({age_alert} s)"
    )
    if failed:
        conclude(4, FAIL, "; ".join(failed))
    else:
        conclude(4, PASS)


def item_5(gate: Gate) -> None:
    current = row(5, "Repeated job failure (V6-21)")
    thresholds = snapshot(gate.origin("api-a")).get("thresholds") or {}
    expected = int(thresholds.get("job_failures") or 3)

    offsets = {name: len(gate.procs[name].text()) for name in ("worker-1", "worker-2")}
    gate.client.delete("ops:worker:job_failures")
    for _ in range(expected):
        gate.client.lpush(
            "queue:jobs",
            json.dumps({"type": "ingest", "website_id": "not-a-uuid"}),
        )
    count = wait_until(
        lambda: int(gate.client.get("ops:worker:job_failures") or 0) >= expected,
        timeout=40,
        interval=0.5,
    )
    payload = snapshot(gate.origin("api-a"))
    failures_alert = alert(payload, "worker.job_failures")

    combined = "".join(
        gate.procs[name].text()[offset:] for name, offset in offsets.items()
    )
    failure_lines = [
        line for line in combined.splitlines() if '"worker.job.failed"' in line
    ]
    visible = wait_until(
        lambda: len(
            [
                line
                for name, offset in offsets.items()
                for line in gate.procs[name].text()[offset:].splitlines()
                if '"worker.job.failed"' in line
            ]
        )
        >= expected,
        timeout=10,
        interval=0.5,
    )
    current.observe(
        "$ for i in 1 2 3; do redis-cli LPUSH queue:jobs "
        "'{\"type\":\"ingest\",\"website_id\":\"not-a-uuid\"}'; done"
    )
    current.observe(
        f"$ redis-cli GET ops:worker:job_failures -> {gate.client.get('ops:worker:job_failures')}"
    )
    current.observe(
        f"jq -c '[.alerts[]|select(.code==\"worker.job_failures\")]' -> "
        f"{json.dumps([failures_alert])}"
    )
    current.observe(
        f"worker logs: {len(failure_lines)} x worker.job.failed "
        f"(job_type: {sorted({json.loads(line).get('job_type') for line in failure_lines if line.startswith('{')})})"
    )

    consuming = False
    gate.client.delete("ops:queue:last_pop")
    gate.client.lpush("queue:jobs", '{"type":"noop"}')
    consuming = bool(
        wait_until(
            lambda: gate.client.exists("ops:queue:last_pop") == 1,
            timeout=20,
            interval=0.5,
        )
    )
    current.observe(f"loop still consuming after the failures: {consuming}")

    checks = {
        "counter reaches 3": bool(count),
        "one alert with failures=3": failures_alert.get("evidence", {}).get("failures")
        == expected,
        "one worker.job.failed line per job": len(failure_lines) == expected,
        "each line names job_type=ingest": all(
            json.loads(line).get("job_type") == "ingest"
            for line in failure_lines
            if line.startswith("{")
        )
        and bool(failure_lines),
        "the loop keeps consuming": consuming,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(5, FAIL, "; ".join(failed))
    else:
        conclude(5, PASS)


def item_6(gate: Gate) -> None:
    current = row(6, "Dependency alerts (V6-21)")
    b = snapshot(gate.origin("api-b"))
    c = snapshot(gate.origin("api-c"))
    a = snapshot(gate.origin("api-a"))

    current.observe(
        "B (closed database port) /api/ops/status -> "
        + json.dumps({"db": b.get("db"), "codes": codes(b)}, sort_keys=True)
    )
    current.observe(
        "C (closed Redis port) /api/ops/status -> "
        + json.dumps(
            {"redis": (c.get("redis") or {}).get("ok"), "codes": codes(c)},
            sort_keys=True,
        )
    )
    current.observe(
        "A (both reachable) -> "
        + json.dumps(
            {"db": a.get("db"), "codes": codes(a)}, sort_keys=True
        )
        + " — the alert half is observable, the clear half is A"
    )

    checks = {
        "DB fault raises api.database_unreachable": "api.database_unreachable"
        in codes(b),
        "Redis fault raises api.redis_unreachable": "api.redis_unreachable"
        in codes(c),
        "a healthy replica raises neither": not {
            "api.database_unreachable",
            "api.redis_unreachable",
        }
        & set(codes(a)),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(6, FAIL, "; ".join(failed))
    else:
        conclude(
            6,
            BLOCKED,
            "the alerts are observed on closed-port replicas, but this gate does "
            "not stop the host's shared PostgreSQL/Redis, so the stop -> restart "
            "-> clears-in-one-snapshot half needs the staging pass",
        )


def item_7(gate: Gate) -> None:
    current = row(7, "Fleet 5xx from Redis buckets (V6-23)")
    a, b = gate.origin("api-a"), gate.origin("api-b")
    statuses = storm(f"{b}/api/plans", 25)
    counts = Counter(statuses)
    # The buckets are summed per window, so a request that lands a moment later
    # is not an error: read until the fleet has counted all of them.
    wait_until(
        lambda: int(
            ((snapshot(a).get("api") or {}).get("fleet") or {}).get("errors_5xx") or 0
        )
        >= 25,
        timeout=90,
        interval=1,
    )
    payload = snapshot(a)
    api = payload.get("api") or {}
    fleet = api.get("fleet") or {}
    rate_alert = alert(payload, "api.error_rate")
    current.observe(
        f"$ for i in $(seq 1 25); do curl -sS -o /dev/null -w '%{{http_code}}\\n' "
        f"{b}/api/plans; done -> {dict(counts)}"
    )
    current.observe(
        f"A: jq -c '{{instance:.api.errors_5xx, fleet:.api.fleet}}' -> "
        + json.dumps(
            {"instance": api.get("errors_5xx"), "fleet": fleet}, sort_keys=True
        )
    )
    current.observe(
        f"B: instance errors_5xx = "
        f"{(snapshot(b).get('api') or {}).get('errors_5xx')}"
    )
    current.observe(
        "A: jq -c '[.alerts[]|select(.code==\"api.error_rate\")]' -> "
        + json.dumps([rate_alert])
    )

    checks = {
        "all 25 requests are 500": set(statuses) == {500},
        "A's own instance window is 0": api.get("errors_5xx") == 0,
        "the fleet window is readable": fleet.get("ok") is True,
        "the fleet counts them": (fleet.get("errors_5xx") or 0) >= 25,
        "the alert reads the fleet": rate_alert.get("evidence", {}).get("source")
        == "fleet",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(7, FAIL, "; ".join(failed))
    else:
        conclude(7, PASS)


def item_8(gate: Gate) -> None:
    current = row(8, "Ingress-only 5xx (V6-23)")
    current.observe(
        "no ingress in this checkout: with both replicas out of rotation the edge "
        "answers 502/503 and no process serves /api/ops/status, so there is no "
        "app alert to read — the row stays the open C half"
    )
    conclude(
        8,
        BLOCKED,
        "an ingress or CDN product must be named with the query that counts 5xx "
        "over the alert window and its observed lag/sampling (e.g. "
        "'# product: …; query: …; lag: … s; sampled: yes/no'), then run on staging",
    )


def run_ops_status(gate: Gate, origins: list[str]) -> tuple[int, dict, str]:
    env = {
        **os.environ,
        "OPS_STATUS_URLS": ",".join(origins),
        "OPS_STATUS_TOKEN": OPS_TOKEN,
    }
    result = subprocess.run(
        [sys.executable, "scripts/ops_status.py"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except Exception:  # noqa: BLE001 - an unreadable report is an empty one
        payload = {}
    return result.returncode, payload, result.stderr.strip()


def item_9(gate: Gate) -> None:
    current = row(9, "Replica coverage of the external check (V6-23)")
    a, b, d = gate.origin("api-a"), gate.origin("api-b"), gate.origin("api-d")

    healthy_exit, healthy, _ = run_ops_status(gate, [a, d])
    current.observe(
        f"$ OPS_STATUS_URLS={a},{d} python scripts/ops_status.py; echo exit:$? -> "
        f"exit:{healthy_exit} checked={healthy.get('checked')} "
        f"ok={[r.get('ok') for r in healthy.get('results') or []]}"
    )

    alert_exit, alerting, _ = run_ops_status(gate, [a, b])
    current.observe(
        f"$ OPS_STATUS_URLS={a},{b} … (B's database is closed) -> exit:{alert_exit} "
        f"ok={[r.get('ok') for r in alerting.get('results') or []]}"
    )

    gate.stop("api-b")
    down_exit, down, stderr = run_ops_status(gate, [a, b])
    current.observe(
        f"$ kill -TERM <B>; OPS_STATUS_URLS={a},{b} … -> exit:{down_exit} "
        f"ok={[r.get('ok') for r in down.get('results') or []]} stderr={stderr!r}"
    )

    partial_exit, partial, _ = run_ops_status(gate, [a])
    current.observe(
        f"$ OPS_STATUS_URLS={a} (B still down) -> exit:{partial_exit} "
        f"checked={partial.get('checked')} — a partial run is only distinguishable "
        "by the printed checked list"
    )

    gate.start_api("api-b", env=gate.env(database_url=dead_database_url()))
    restarted = gate.await_api(gate.procs["api-b"])
    current.observe(f"B restarted: {restarted}")

    checks = {
        "two healthy replicas exit 0": healthy_exit == 0
        and len(healthy.get("checked") or []) == 2
        and all(r.get("ok") for r in healthy.get("results") or []),
        "a critical alert behind a 200 exits 1": alert_exit == 1,
        "an unreachable replica exits 2": down_exit == 2
        and (down.get("results") or [{}])[0].get("ok") is True,
        "one listed origin exits 0 while another is down": partial_exit == 0
        and len(partial.get("checked") or []) == 1,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(9, FAIL, "; ".join(failed))
    else:
        conclude(9, PASS)


def item_10(gate: Gate) -> None:
    current = row(10, "Per-worker heartbeat and the roster (V6-23)")
    thresholds = snapshot(gate.origin("api-a")).get("thresholds") or {}
    interval = int(thresholds.get("worker_heartbeat_interval_seconds") or 15)
    expected = int(thresholds.get("expected_workers") or gate.expected_workers)

    # A worker this run stopped earlier leaves its key for three intervals; that
    # corpse would count as a live worker, so this item starts from the roster
    # the two running workers own.
    running = {
        f"ops:worker:heartbeat:{socket.gethostname()}:{proc.pid}"
        for name, proc in gate.procs.items()
        if name.startswith("worker") and proc.alive()
    }
    for key in gate.worker_keys():
        if key not in running:
            gate.client.delete(key)
    wait_until(
        lambda: set(gate.worker_keys()) == running and len(running) == expected,
        timeout=45,
        interval=1,
    )
    keys = gate.worker_keys()
    legacy = gate.client.get("ops:worker:heartbeat")
    current.observe(f"$ redis-cli --scan --pattern 'ops:worker:heartbeat:*' -> {keys}")
    current.observe(f"$ redis-cli GET ops:worker:heartbeat -> {bool(legacy)}")

    worker_names = [
        name
        for name, proc in gate.procs.items()
        if name.startswith("worker") and proc.alive()
    ]
    victim_name = worker_names[-1] if worker_names else "worker-2"
    victim = gate.procs[victim_name]
    victim_key = f"ops:worker:heartbeat:{socket.gethostname()}:{victim.pid}"
    kill_at = time.monotonic()
    gate.stop(victim_name, sig=9)
    gone = wait_until(
        lambda: gate.client.exists(victim_key) == 0, timeout=3 * interval + 30, interval=1
    )
    gone_after = time.monotonic() - kill_at
    payload = snapshot(gate.origin("api-a"))
    redis_state = payload.get("redis") or {}
    current.observe(
        f"$ kill -9 {victim.pid} -> {victim_key} gone after {gone_after:.1f} s; "
        f"legacy key still present: {gate.client.exists('ops:worker:heartbeat') == 1}"
    )
    current.observe(
        "jq -c '{workers:.redis.workers, live:.redis.workers_live, "
        "worker_alerts:[…]}' -> "
        + json.dumps(
            {
                "live": redis_state.get("workers_live"),
                "worker_alerts": [c for c in codes(payload) if c.startswith("worker.")],
                "count_low": alert(payload, "worker.count_low"),
            },
            sort_keys=True,
        )
    )

    gate.start_worker(f"{victim_name}-again", env=gate.env())
    recovered = wait_until(
        lambda: len(gate.worker_keys()) >= expected
        and not [c for c in codes(snapshot(gate.origin("api-a"))) if c == "worker.count_low"],
        timeout=60,
        interval=1,
    )
    current.observe(f"restarted the worker -> live={len(gate.worker_keys())}, count_low cleared={bool(recovered)}")

    disabled = gate.start_api(
        "api-roster-off",
        env=gate.env(expected_workers=0),
    )
    disabled_up = gate.await_api(disabled)
    off_payload = snapshot(gate.origin("api-roster-off"))
    gates_still = [
        code for code in codes(off_payload) if code in {"worker.count_low"}
    ]
    current.observe(
        f"replica with OPS_EXPECTED_WORKERS=0 (restarted process) -> "
        f"count_low={gates_still} (thresholds.expected_workers="
        f"{(off_payload.get('thresholds') or {}).get('expected_workers')})"
    )

    aggregate = [c for c in codes(payload) if c in {"worker.heartbeat_missing", "worker.heartbeat_stale"}]
    checks = {
        "two per-worker keys and one legacy document": len(keys) >= 2
        and bool(legacy),
        "the killed worker's key disappears": bool(gone),
        "live drops to 1 with count_low": redis_state.get("workers_live") == 1
        and alert(payload, "worker.count_low").get("evidence", {}).get("live") == 1,
        "no aggregate heartbeat alert while a peer lives": not aggregate,
        "the roster clears when the worker returns": bool(recovered),
        "expected=0 disables count_low": disabled_up and not gates_still,
    }
    failed = [name for name, ok in checks.items() if not ok]
    current.observe(
        "note: a per-worker heartbeat_stale cannot be produced with these "
        f"defaults ({3 * interval} s TTL vs the stale threshold), so count_low is "
        "what a SIGKILL raises here"
    )
    if failed:
        conclude(10, FAIL, "; ".join(failed))
    else:
        conclude(10, PASS)


def read_setting(client, name: str) -> str | None:
    """One Redis CONFIG value, or None when this server refuses the read.

    Asked one name at a time: a managed or proxied Redis may refuse the
    multi-pattern form the app uses, and then `durability.ok` is false with no
    alert — which is exactly what item 11 has to record.
    """
    try:
        value = client.config_get(name)
    except Exception:  # noqa: BLE001 - an unreadable setting is reported as one
        return None
    if isinstance(value, dict):
        value = value.get(name)
    return None if value is None else str(value)


def item_11(gate: Gate) -> None:
    current = row(11, "Redis durability (V6-23)")
    settings = {
        name: read_setting(gate.client, name)
        for name in ("maxmemory-policy", "appendonly", "save")
    }
    payload = snapshot(gate.origin("api-a"))
    durability = (payload.get("redis") or {}).get("durability") or {}
    current.observe(
        "$ redis-cli CONFIG GET maxmemory-policy appendonly save -> "
        + json.dumps(settings, sort_keys=True)
    )
    current.observe(f"snap .redis.durability -> {json.dumps(durability, sort_keys=True)}")

    problems = durability.get("problems") or []
    alert_present = "redis.durability_unsafe" in codes(payload)

    if any(value is None for value in settings.values()):
        current.observe(
            "this server refuses CONFIG GET (a managed Redis often does), so the "
            "snapshot must report unreadable settings and raise no alert"
        )
        checks = {
            "unreadable settings are reported, not guessed": durability.get("ok")
            is False
            and not problems,
            "no alert from an unreadable setting": not alert_present,
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            conclude(11, FAIL, "; ".join(failed))
        else:
            conclude(
                11,
                BLOCKED,
                "the durability read is checked and this server refuses CONFIG, so "
                "the unsafe-policy mutation and its clear cannot be observed here; "
                "run them on a Redis this deployment owns",
            )
        return

    if durability.get("ok") is not True:
        # The app asks for all three names in one CONFIG GET; this server refuses
        # that form while the per-name reads above work, so the snapshot reports
        # "unreadable" and raises nothing — the documented unreadable path, and
        # the reason no unsafe-policy alert can exist here.
        current.observe(
            "the app reports durability unreadable while per-key reads work: its "
            "combined CONFIG GET is refused by this server, so the classifier "
            "never sees a value and no alert is raised"
        )
    policy_bad = str(settings.get("maxmemory-policy", "")).lower() != "noeviction"
    persistence_bad = str(settings.get("appendonly", "")).lower() != "yes" and not str(
        settings.get("save") or ""
    ).strip()
    expected_problems = (["maxmemory-policy"] if policy_bad else []) + (
        ["appendonly"] if persistence_bad else []
    )
    current.observe(
        f"expected problems {expected_problems}; snapshot problems {problems}; "
        f"redis.durability_unsafe={alert_present}"
    )

    if durability.get("ok") is True:
        consistent = sorted(problems) == sorted(expected_problems) and (
            alert_present == bool(expected_problems)
        )
    else:
        # Unreadable settings must not be guessed: no problems, no alert.
        consistent = not problems and not alert_present

    if not os.getenv("GATE_REDIS_ALLOW_CONFIG"):
        conclude(
            11,
            BLOCKED,
            "the read side is checked above; flipping maxmemory-policy needs "
            "CONFIG SET on the server, which this gate will not do to a shared "
            "Redis. Point GATE_REDIS at a disposable instance and set "
            "GATE_REDIS_ALLOW_CONFIG=1, or run the mutation on staging",
        )
        return

    original = settings.get("maxmemory-policy")
    try:
        gate.client.config_set("maxmemory-policy", "allkeys-lru")
        flipped = snapshot(gate.origin("api-a"))
        flipped_alert = alert(flipped, "redis.durability_unsafe")
        current.observe(
            "$ redis-cli CONFIG SET maxmemory-policy allkeys-lru -> "
            + json.dumps(flipped_alert, sort_keys=True)
        )
    finally:
        gate.client.config_set("maxmemory-policy", original)
    restored = snapshot(gate.origin("api-a"))
    current.observe(
        f"$ redis-cli CONFIG SET maxmemory-policy {original} -> "
        f"redis.durability_unsafe present: {'redis.durability_unsafe' in codes(restored)}"
    )

    checks = {
        "the snapshot agrees with CONFIG GET": consistent,
        "an unsafe policy raises the critical alert": flipped_alert.get(
            "evidence", {}
        ).get("problems")
        == ["maxmemory-policy"],
        "restoring noeviction clears it": "redis.durability_unsafe"
        not in codes(restored),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(11, FAIL, "; ".join(failed))
    else:
        conclude(11, PASS)


def item_12(gate: Gate) -> None:
    current = row(12, "Redis interruption while serving (V6-23)")
    c = gate.origin("api-c")
    ready = get(f"{c}/health/ready")
    payload = snapshot(c)
    redis_state = payload.get("redis") or {}
    fleet = (payload.get("api") or {}).get("fleet") or {}
    current.observe(
        f"C (closed Redis port): /health/ready -> {None if ready is None else ready.status_code} "
        f"{json.dumps(body(ready))}"
    )
    current.observe(
        "C: jq -c '{redis:.redis.ok, fleet:.api.fleet}' -> "
        + json.dumps({"redis": redis_state.get("ok"), "fleet": fleet}, sort_keys=True)
    )
    current.observe(f"C alerts -> {codes(payload)}")

    # Under-reporting: a replica that cannot read the buckets must label its own
    # window "instance" even while another replica is erroring too.
    both_dead = gate.start_api(
        "api-e",
        env=gate.env(database_url=dead_database_url(), redis=DEAD_REDIS),
    )
    gate.await_api(both_dead)
    e = gate.origin("api-e")
    # Concurrent, because each request in this replica waits out a dead-Redis
    # write in the middleware (4-10 s); sequential would take minutes.
    e_statuses = storm(f"{e}/api/plans", 25, concurrency=10)
    e_payload = snapshot(e)
    e_rate = alert(e_payload, "api.error_rate")
    e_fleet = (e_payload.get("api") or {}).get("fleet") or {}
    current.observe(
        "E (database and Redis both closed), 25 x GET /api/plans -> "
        f"{dict(Counter(e_statuses))}; "
        + json.dumps({"fleet": e_fleet, "api.error_rate": e_rate}, sort_keys=True)
    )

    # The restore half: a replica that can read the buckets again labels "fleet".
    restored = gate.start_api("api-e2", env=gate.env(database_url=dead_database_url()))
    gate.await_api(restored)
    e2 = gate.origin("api-e2")
    e2_statuses = storm(f"{e2}/api/plans", 25, concurrency=10)
    e2_payload = snapshot(e2)
    e2_rate = alert(e2_payload, "api.error_rate")
    current.observe(
        "E2 (same fault, Redis reachable), 25 x GET /api/plans -> "
        f"{dict(Counter(e2_statuses))}; api.error_rate "
        + json.dumps(e2_rate, sort_keys=True)
    )

    checks = {
        "ready stays 200 degraded": ready is not None
        and ready.status_code == 200
        and body(ready).get("status") == "degraded",
        "the fleet view is unreadable, not zero": redis_state.get("ok") is False
        and fleet.get("ok") is False
        and fleet.get("requests") is None,
        "the rate falls back to the instance window": e_rate.get(
            "evidence", {}
        ).get("source")
        == "instance",
        "it returns to the fleet when the buckets are readable": e2_rate.get(
            "evidence", {}
        ).get("source")
        == "fleet",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(12, FAIL, "; ".join(failed))
    else:
        conclude(
            12,
            BLOCKED,
            "the outage state and both labels are observed, but the gate cannot "
            "stop and restart the host's Redis to record the under-reporting "
            "window on a real restart — that half belongs to staging",
        )


def item_13(gate: Gate, company_id: str) -> None:
    current = row(13, "Graceful shutdown (V6-23)")
    gate.stop_all_workers()
    worker = gate.start_worker("worker-shutdown", env=gate.env())
    wait_until(lambda: worker.alive(), timeout=5)

    lock = gate_connect()
    lock.autocommit = False
    with lock.cursor() as cursor:
        cursor.execute("LOCK TABLE chat_messages IN ACCESS EXCLUSIVE MODE")
    gate.client.lpush(
        "queue:jobs", json.dumps({"type": "retention", "company_id": company_id})
    )
    started = time.monotonic()
    in_flight = wait_until(
        lambda: '"retention"' in worker.text() or time.monotonic() - started > 30,
        timeout=30,
        interval=0.2,
    )
    time.sleep(1.5)
    current.observe(
        f"$ redis-cli LPUSH queue:jobs '{{\"type\":\"retention\",\"company_id\":\"{company_id}\"}}'"
        f" -> received: {bool(in_flight)}; chat_messages held by a table lock "
        "(the slow job this checkout can produce without network/providers)"
    )

    worker.popen.send_signal(15)
    time.sleep(3)
    still_running = worker.alive()
    before_release = worker.text()
    current.observe(
        f"$ kill -TERM {worker.pid} while the job runs -> process still alive: "
        f"{still_running}, worker.stopped logged yet: "
        f"{'worker.stopped' in before_release}"
    )

    lock.rollback()
    lock.close()
    exit_code = worker.stop(timeout=60)
    finished = time.monotonic() - started
    log = worker.text()
    events = [
        json.loads(line).get("event")
        for line in log.splitlines()
        if line.startswith("{") and '"event"' in line
    ]
    stopped_lines = [line for line in log.splitlines() if '"worker.stopped"' in line]
    graceful = bool(stopped_lines) and json.loads(stopped_lines[-1]).get("graceful") is True
    failed_lines = [line for line in log.splitlines() if '"worker.job.failed"' in line]
    order_ok = (
        events.index("retention.purged") < events.index("worker.stopped")
        if "retention.purged" in events and "worker.stopped" in events
        else False
    )
    deleted = _message_count(gate)

    stop_grace = os.getenv("GATE_STOP_GRACE_SECONDS")
    current.observe(
        f"released the lock -> exit {exit_code} after {finished:.1f} s; last events "
        f"{events[-3:]}; worker.stopped graceful={graceful}; "
        f"worker.job.failed={len(failed_lines)}; chat_messages left={deleted}"
    )
    if stop_grace:
        current.observe(
            f"job duration {finished:.1f} s vs stop_grace_period {stop_grace} s "
            f"(within: {finished < float(stop_grace)})"
        )
    else:
        current.observe(
            f"job duration {finished:.1f} s; platform stop_grace_period not set "
            "here — record it beside this number on the deployment"
        )

    api = gate.procs["api-b"]
    api.popen.send_signal(15)
    try:
        api_exit = api.popen.wait(timeout=30)
    except subprocess.TimeoutExpired:
        api.popen.kill()
        api_exit = None
    api_log = api.text()
    leaked = [
        marker
        for marker in ("db.dispose_failed", "redis.close_failed")
        if marker in api_log
    ]
    current.observe(
        f"$ kill -TERM {api.pid} (uvicorn) -> exit {api_exit}; "
        f"db.dispose_failed/redis.close_failed present: {leaked}"
    )

    gate.start_worker("worker-1", env=gate.env())
    gate.start_worker("worker-2", env=gate.env())

    checks = {
        "the job finishes before the process leaves": still_running
        and order_ok
        and deleted == 0,
        "worker.stopped graceful:true": graceful,
        "no worker.job.failed for that job": not failed_lines,
        "the API stops without a dispose/close failure": api_exit is not None
        and not leaked,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        conclude(13, FAIL, "; ".join(failed))
    else:
        conclude(13, PASS)


def _message_count(gate: Gate) -> int:
    connection = gate_connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM chat_messages")
            return int(cursor.fetchone()[0])
    finally:
        connection.close()


def item_14(gate: Gate) -> None:
    current = row(14, "Pool sizing under load (V6-23)")
    a = gate.origin("api-a")
    per_process = 5 + 5  # DB_POOL_SIZE + DB_MAX_OVERFLOW
    ceiling = POOL_INSTANCES * per_process

    def sample() -> dict[str, int]:
        """Backends per labelled process, plus the unlabelled sampler itself."""
        connection = gate_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT coalesce(nullif(application_name, ''), '(unlabelled)'), "
                    "count(*) FROM pg_stat_activity WHERE datname = %s GROUP BY 1",
                    (GATE_DB,),
                )
                return {str(name): int(count) for name, count in cursor.fetchall()}
        finally:
            connection.close()

    # Every counted entry is a process: each one is started with its own
    # application_name, and the gate's own sampler is dropped by name.
    peak: dict[str, int] = {}

    # An idle worker holds no pooled connection, so replacing one would prove
    # nothing. Queue a database-backed job until every worker has opened its
    # pool, then take the reading.
    connection = gate_connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM companies LIMIT 1")
            found = cursor.fetchone()
    finally:
        connection.close()
    live_workers = {
        f"gate-{name}"
        for name, proc in gate.procs.items()
        if name.startswith("worker") and proc.alive()
    }
    if found:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and not live_workers <= set(sample()):
            gate.client.lpush(
                "queue:jobs",
                json.dumps(
                    {"type": "retention", "company_id": str(found[0]), "dry_run": True}
                ),
            )
            time.sleep(2)

    def load() -> None:
        storm(f"{a}/api/plans", 6)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(load) for _ in range(8)]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not all(f.done() for f in futures):
            try:
                for name, count in sample().items():
                    if name != "(unlabelled)":
                        peak[name] = max(peak.get(name, 0), count)
            except Exception:  # noqa: BLE001 - a failed sample is not a failure
                pass
            time.sleep(0.05)
        for future in futures:
            future.result()

    connection = gate_connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW max_connections")
            max_connections = int(cursor.fetchone()[0])
    finally:
        connection.close()

    restarted = [
        name
        for name, proc in gate.procs.items()
        if name.startswith("worker") and proc.alive()
    ][-1]
    before = sample()
    gate.stop(restarted)
    time.sleep(3)
    after = sample()
    gate.start_worker(f"{restarted}-again", env=gate.env())
    replacement = wait_until(
        lambda: sample().get(f"gate-{restarted}-again", 0) > 0, timeout=30, interval=1
    )

    current.observe(
        "while A + two workers serve 48 concurrent /api/plans: peak backends per "
        f"application_name = {json.dumps(peak, sort_keys=True)} "
        f"(per-process ceiling {per_process}, deployment ceiling "
        f"{POOL_INSTANCES} x {per_process} = {ceiling}); "
        f"max_connections = {max_connections}"
    )
    current.observe(
        f"$ pg_stat_activity before/after replacing {restarted}: "
        f"{json.dumps(before, sort_keys=True)} -> {json.dumps(after, sort_keys=True)}; "
        f"gate-{restarted}-again present after restart: {bool(replacement)}"
    )

    retired_gone = f"gate-{restarted}" not in after
    within_process = all(count <= per_process for count in peak.values())
    replacement_ok = bool(replacement) and (
        sample().get(f"gate-{restarted}-again", 0) <= per_process
    )
    checks = {
        "every process stays under pool_size + max_overflow": within_process,
        "the deployment stays under its pool ceiling": sum(peak.values()) <= ceiling,
        "the database allows the ceiling plus headroom": max_connections > ceiling,
        "every worker held a pool before the restart": live_workers
        <= set(before),
        "the replaced process leaves no backend behind": retired_gone,
        "the substitute process connects within its own ceiling": replacement_ok,
    }
    failed = [name for name, ok in checks.items() if not ok]
    current.observe(
        "attribution: each process is started with its own application_name "
        "(`gate-<process>`), so this row is per process; a deployment that sets "
        "none can only show the total"
    )
    if failed:
        conclude(14, FAIL, "; ".join(failed))
    else:
        conclude(14, PASS)


# =========================================================================
# Reporting
# =========================================================================


def table(commit: str, by: str) -> str:
    out = [
        "| # | Item | Observed (command + output, timestamp) | Commit / image | By |",
        "|---|---|---|---|---|",
    ]
    for number in sorted(ROWS):
        current = ROWS[number]
        observed = " <br> ".join(line.replace("|", "\\|") for line in current.lines)
        if len(observed) > 2400:
            observed = observed[:2400] + " … (truncated)"
        verdict = current.verdict or BLOCKED
        cell = f"**{verdict}**"
        if current.reason:
            cell += f" — {current.reason.replace('|', '\\|')}"
        cell += f" <br> {observed}"
        out.append(f"| {number} | {current.item} | {cell} | {commit} | {by} |")
    return "\n".join(out)


def summary() -> tuple[int, int, int]:
    passed = sum(1 for r in ROWS.values() if r.verdict == PASS)
    blocked = sum(1 for r in ROWS.values() if r.verdict == BLOCKED)
    failed = sum(1 for r in ROWS.values() if r.verdict == FAIL)
    return passed, blocked, failed


# =========================================================================
# Orchestration
# =========================================================================


def spawn_topology(gate: Gate) -> str:
    """Start the replicas and workers every item reads from."""
    a = gate.start_api("api-a", env=gate.env())
    b = gate.start_api("api-b", env=gate.env(database_url=dead_database_url()))
    c = gate.start_api("api-c", env=gate.env(redis=DEAD_REDIS))
    d = gate.start_api("api-d", env=gate.env())
    for proc in (a, b, c, d):
        if not gate.await_api(proc):
            raise RuntimeError(f"{proc.name} did not answer /health/live:\n{proc.tail()}")
    say(
        f"replicas up: A {a.port} (healthy), B {b.port} (closed database), "
        f"C {c.port} (closed Redis), D {d.port} (healthy)"
    )

    production_env = gate.env(
        token=None,
        extra={
            "APP_ENV": "production",
            "DOCS_ENABLED": "false",
            "PLATFORM_CONSOLE_ENABLED": "false",
            "JWT_SECRET_KEY": "gate-v6-2g-not-a-real-secret",
            "CORS_ORIGINS": "https://gate.example.test",
            "SQL_ECHO": "false",
            "RATE_LIMIT_BACKEND": "redis",
            "API_KEY_PEPPER": "gate-v6-2g-pepper",
            "INTEGRATION_WEBHOOK_SECRET": "gate-v6-2g-webhook-secret",
            "TRUSTED_PROXY_IPS": "127.0.0.1",
        },
    )
    production = gate.start_api("api-prod", env=production_env)
    if not gate.await_api(production):
        say("WARNING: the production-profile replica did not start; item 2's")
        say("unset-token half will fail. Its log tail is printed at the end.")

    workers = gate.start_workers()
    ready = wait_until(lambda: len(gate.worker_keys()) >= 2, timeout=60, interval=1)
    if not ready:
        raise RuntimeError(
            "workers did not publish two heartbeats: "
            + " / ".join(proc.tail() for proc in workers)
        )
    say(f"workers up: {[proc.pid for proc in workers]}")
    return production.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-db", action="store_true", help="keep the database")
    parser.add_argument("--log-dir", default="", help="where the process logs go")
    args = parser.parse_args()

    if not GATE_DB.startswith("v6_gate_2g"):
        say(f"Refusing GATE_DB={GATE_DB!r}: the name must start with 'v6_gate_2g'.")
        return 2
    redis_target = parse_redis(REDIS_SPEC)
    if redis_target.db == 0 and not os.getenv("GATE_REDIS_ALLOW_DB0"):
        say(
            "Refusing to FLUSHDB Redis database 0: it is the development keyspace. "
            "Set GATE_REDIS=redis://127.0.0.1:6379/15 (or another index)."
        )
        return 2
    if not shutil.which(sys.executable):
        say("The interpreter that runs this script must run the app too.")
        return 2

    log_dir = Path(args.log_dir) if args.log_dir else Path(tempfile.mkdtemp(prefix="v6-2g-"))
    log_dir.mkdir(parents=True, exist_ok=True)
    gate = Gate(log_dir)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        gate.commit = result.stdout.strip() or "unknown"
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()
        if dirty:
            gate.commit += "+dirty"
    except Exception:  # noqa: BLE001 - the commit is metadata, not a check
        pass

    say(f"V6-2G gate — commit {gate.commit}")
    say(f"PostgreSQL {PG} database {GATE_DB}")
    say(f"Redis {redis_target.host}:{redis_target.port}/{redis_target.db}")
    say(f"Logs {log_dir}")

    try:
        gate.create_database()
        revision = gate.migrate()
        gate.client.flushdb()
        say(f"migrated; alembic_version = {revision}")
        if revision != HEAD:
            say(f"WARNING: expected head {HEAD}")
        company_id, _website_id = gate.seed()
        say("seeded one tenant with a retention policy and 3000 old messages")

        spawn_topology(gate)

        item_1(gate)
        item_2(gate)
        item_3(gate)
        item_4(gate)
        item_5(gate)
        item_6(gate)
        # Item 9 must run before item 7: the 25 forced 5xx of item 7 stay in the
        # fleet window and would make "two healthy replicas exit 0" impossible.
        item_9(gate)
        item_7(gate)
        item_8(gate)
        item_10(gate)
        item_11(gate)
        item_12(gate)
        item_13(gate, company_id)
        item_14(gate)
    except Exception as exc:  # noqa: BLE001 - report, clean up, then fail
        say(f"\nABORTED: {type(exc).__name__}: {exc}")
        for number in range(1, 15):
            if number not in ROWS or not ROWS[number].verdict:
                row(number, f"item {number}")
                conclude(number, BLOCKED, "the run aborted before this item")
    finally:
        for name in list(gate.procs):
            gate.stop(name)
        try:
            gate.client.flushdb()
            gate.client.close()
        except Exception:  # noqa: BLE001 - cleanup is best effort
            pass
        if args.keep_db:
            say(f"\nkept database {GATE_DB}; drop it with DROP DATABASE \"{GATE_DB}\"")
        else:
            try:
                gate.drop_database()
            except Exception as exc:  # noqa: BLE001 - say so, do not hide it
                say(f"could not drop {GATE_DB}: {type(exc).__name__}: {exc}")

    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    rendered = f"Recorded {stamp}\n\n" + table(gate.commit, gate.by) + "\n"
    rows_path = log_dir / "rows.md"
    rows_path.write_text(rendered, encoding="utf-8")

    passed, blocked, failed = summary()
    say("\n" + "-" * 78)
    say(rendered)
    say("-" * 78)
    say(f"{passed} passed, {blocked} blocked, {failed} failed — commit {gate.commit}")
    say(f"Paste-ready rows: {rows_path}")
    say(f"Process logs: {log_dir}")
    if failed:
        for name, proc in gate.procs.items():
            if proc.text():
                say(f"\n--- {name} (last lines)\n{proc.tail()}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
