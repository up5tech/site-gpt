"""V6-20 failure-injection rehearsal: what a crash, a duplicate and an unknown do.

This script answers one question with observations instead of code reading: for
each of the six job types, what actually happens when the worker process dies
mid-job, when the same payload is pushed twice, and when the payload names a type
nothing handles? It records the recovery path each type falls back to and how
long that path waits, because D9 §2 asks for that classification and §3 needs the
numbers.

It decides nothing. Every scenario runs against a throwaway PostgreSQL database
and a disposable Redis, with the worker's own structured log as the evidence —
no handler is patched, no fault is injected inside the code, and no row is
written by hand that a real run would not write.

    bash scripts/v6_20_rehearsal/run.sh             # whole rehearsal
    bash scripts/v6_20_rehearsal/run.sh --keep-db   # leave the database

Infrastructure it owns
----------------------

* **PostgreSQL** — a database named `v6_gate_2g_rehearsal` (override
  `REHEARSAL_DB`; the name must keep the `v6_gate_2g` prefix, because a script
  that drops databases must never be pointed at a shared one). The server itself
  is `REHEARSAL_PG` and is never stopped. This is the same definition of
  "disposable PostgreSQL" the V6-2G gate uses.
* **Redis** — `REHEARSAL_REDIS` (default `redis://127.0.0.1:6379/14`), flushed at
  the start and end. Database 0 is refused, and `run.sh` starts a container on a
  random loopback port so the shared 6379 is not touched at all.

Shortcuts, printed where they are used
--------------------------------------

* **Mid-job is a held table lock**, the trick the V6-2G gate already uses for
  item 13: the harness locks a table the handler must read first, pushes the job,
  waits for `worker.job.received`, then `kill -9`s the worker. The handler is
  inside the job and blocked, which is what "mid-job" means; without network or
  providers there is no other way to hold one open.
* **A day-long wait is not sat through.** Where a recovery path only runs on a
  loop tick (24 h) or after a stale window (6 h, 1 h, 30 min), the harness
  backdates the row and then calls the very scheduler function that tick would
  call, in a child process with the real application environment. The row it
  changed, and the column it changed, are printed with the observation.
* **The tick is called, not waited for.** `--tick` runs
  `enqueue_due_retention`, `enqueue_due_digests`, `enqueue_due_topics`,
  `enqueue_due_sitemap_scans`, `enqueue_due_insights` or `requeue_stuck_ingests`
  directly, so the observation is what the next tick would do, not a guess.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg2
import redis

REPO_ROOT = Path(__file__).resolve().parents[2]

DB = os.getenv("REHEARSAL_DB", "v6_gate_2g_rehearsal")
PG = os.getenv("REHEARSAL_PG", "postgresql://postgres:postgres@127.0.0.1:5432").rstrip("/")
REDIS_SPEC = os.getenv("REHEARSAL_REDIS", "redis://127.0.0.1:6379/14")
QUEUE_KEY = "queue:jobs"
FAILURE_COUNTER = "ops:worker:job_failures"

#: Types in the order they are rehearsed, with the table each handler reads
#: first. Holding that table is what keeps the job in flight long enough to kill.
TYPES = [
    ("ingest", "embeddings"),
    ("digest", "chat_messages"),
    ("retention", "chat_messages"),
    ("topic_clusters", "topic_clusters"),
    ("sitemap_scan", "websites"),
    ("insights", "conversation_insights"),
]

#: The terminal (non-failure) event each type logs when a run finishes. Used to
#: tell "killed mid-job" from "finished before the kill", never to grade it.
DONE_EVENTS = {
    "ingest": ["ingest.completed"],
    "digest": ["digest.period_completed"],
    "retention": ["retention.purged"],
    "topic_clusters": ["topics.window_built"],
    # A scan with nothing to change finishes here, not in `diff_applied`.
    "sitemap_scan": ["sitemap.diff_applied", "sitemap.nothing_changed"],
    "insights": ["insights.run_completed"],
}


def say(text: str = "") -> None:
    print(text, flush=True)


# -- results ----------------------------------------------------------------


@dataclass
class Block:
    """One job type's three observations, kept in the order they were made."""

    name: str
    lines: list[str] = field(default_factory=list)

    def observe(self, text: str) -> None:
        self.lines.append(str(text))
        say(f"  [{self.name}] {text}")


BLOCKS: dict[str, Block] = {}


def block(name: str) -> Block:
    if name not in BLOCKS:
        BLOCKS[name] = Block(name=name)
    return BLOCKS[name]


# -- plumbing ---------------------------------------------------------------


def parse_redis(spec: str) -> dict:
    from urllib.parse import urlparse

    parsed = urlparse(spec)
    if parsed.scheme != "redis":
        raise SystemExit(f"Refusing REHEARSAL_REDIS={spec!r}: expected redis://host:port/db")
    database = int((parsed.path or "/0").lstrip("/") or 0)
    if database == 0:
        raise SystemExit("Refusing Redis database 0: it is the development keyspace.")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": int(parsed.port or 6379),
        "db": database,
        "password": parsed.password,
    }


TARGET = parse_redis(REDIS_SPEC)
CLIENT = redis.Redis(
    host=TARGET["host"],
    port=TARGET["port"],
    db=TARGET["db"],
    password=TARGET["password"],
    decode_responses=True,
)

MANAGED_ENV = {
    "APP_ENV",
    "DATABASE_URL",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_PASSWORD",
    "LOG_LEVEL",
    "PYTHONUNBUFFERED",
    "OPS_EXPECTED_WORKERS",
}


def child_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in MANAGED_ENV}
    env.update(
        {
            "DATABASE_URL": f"{PG}/{DB}",
            "REDIS_HOST": TARGET["host"],
            "REDIS_PORT": str(TARGET["port"]),
            "REDIS_DB": str(TARGET["db"]),
            "PYTHONUNBUFFERED": "1",
            "LOG_LEVEL": "INFO",
            "OPS_EXPECTED_WORKERS": "1",
        }
    )
    if TARGET["password"]:
        env["REDIS_PASSWORD"] = TARGET["password"]
    return env


def admin_connect():
    return psycopg2.connect(PG, connect_timeout=10)


def db_connect():
    return psycopg2.connect(f"{PG}/{DB}", connect_timeout=10)


def query(sql: str, args: tuple = ()) -> list[tuple]:
    connection = db_connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, args)
            rows = cursor.fetchall() if cursor.description else []
        connection.commit()
        return rows
    finally:
        connection.close()


def create_database() -> None:
    connection = admin_connect()
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            # Refuse an existing database instead of dropping it: two rehearsals
            # sharing one name would each drop the other's tables mid-run, and a
            # name that already exists is not this run's to delete.
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
            if cursor.fetchone():
                raise SystemExit(
                    f"Refusing: database {DB} already exists. Drop it with "
                    f'DROP DATABASE "{DB}", or set REHEARSAL_DB to another '\
                    "name starting with 'v6_gate_2g'."
                )
            cursor.execute(f'CREATE DATABASE "{DB}"')
    finally:
        connection.close()


def drop_database() -> None:
    connection = admin_connect()
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (DB,),
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{DB}"')
    finally:
        connection.close()


def migrate() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": f"{PG}/{DB}"},
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise SystemExit("alembic upgrade head failed:\n" + (result.stdout + result.stderr)[-2000:])
    rows = query("SELECT version_num FROM alembic_version")
    return str(rows[0][0])


@dataclass
class Seeded:
    company_id: str
    website_id: str


def seed() -> Seeded:
    company_id, website_id = str(uuid4()), str(uuid4())
    now = datetime.now(UTC)
    period_start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    settings = {
        # On, so the crash/duplicate runs reach the claim instead of the flag.
        "digest_enabled": "true",
        "digest_hour": str(now.hour),
        "digest_day": "monday",
        "topic_clustering_enabled": "true",
        "sitemap_scan_enabled": "true",
        "conversation_insights_enabled": "true",
        "retention_days": "1",
    }
    connection = db_connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO companies (id, name, description, created_at, updated_at) "
                "VALUES (%s, 'Rehearsal tenant', '', now(), now())",
                (company_id,),
            )
            cursor.execute(
                "INSERT INTO websites (id, url, name, description, company_id, "
                "site_map_url, status, ingest_status, created_at, updated_at) "
                "VALUES (%s, 'http://127.0.0.1:1/', 'Rehearsal site', '', %s, "
                "'http://127.0.0.1:1/sitemap.xml', 'active', 'none', now(), now())",
                (website_id, company_id),
            )
            for key, value in settings.items():
                cursor.execute(
                    "INSERT INTO settings (id, key, value, company_id, created_at, "
                    "updated_at) VALUES (%s, %s, %s, %s, now(), now())",
                    (str(uuid4()), key, value, company_id),
                )
            old = now - timedelta(days=10)
            for index in range(200):
                cursor.execute(
                    "INSERT INTO chat_messages (id, session_id, message, role, "
                    "website_id, answered, created_at, updated_at) "
                    "VALUES (%s, 'rehearsal-session', %s, 'user', %s, NULL, %s, %s)",
                    (str(uuid4()), f"row {index}", website_id, old, old),
                )
            # Recent activity, so the digest has a period to build (and a claim to
            # leave behind when it is killed) instead of returning `empty`.
            recent = now - timedelta(days=2)
            for index in range(3):
                cursor.execute(
                    "INSERT INTO chat_messages (id, session_id, message, role, "
                    "website_id, answered, created_at, updated_at) "
                    "VALUES (%s, 'rehearsal-recent', %s, 'user', %s, NULL, %s, %s)",
                    (str(uuid4()), f"recent {index}", website_id, recent, recent),
                )
            # Two settled sessions, so topic clustering and insights have work; some
            # of that work writes rows, which is what a kill can leave behind.
            for index in range(2):
                cursor.execute(
                    "INSERT INTO conversations (id, website_id, session_id, state, "
                    "assigned_user_id, claimed_at, closed_at, last_message_at, "
                    "created_at, updated_at) VALUES (%s, %s, %s, 'bot', NULL, NULL, "
                    "NULL, %s, %s, %s)",
                    (
                        str(uuid4()),
                        website_id,
                        f"rehearsal-conversation-{index}",
                        recent,
                        recent,
                        recent,
                    ),
                )
            # One company-wide extra document: ingest embeds it as text, so the job
            # also has work that writes a row after the website is marked
            # `processing` — the window a kill leaves a stale claim in.
            cursor.execute(
                "INSERT INTO extra_documents (id, name, content, company_id, "
                "website_id, created_at, updated_at) "
                "VALUES (%s, 'rehearsal.txt', 'rehearsal content', %s, NULL, now(), now())",
                (str(uuid4()), company_id),
            )
        connection.commit()
    finally:
        connection.close()
    return Seeded(company_id=company_id, website_id=website_id)


class Worker:
    """One real `python -m site_gpt.app.worker`, writing JSON lines to a file."""

    def __init__(self, name: str, log_dir: Path) -> None:
        self.name = name
        self.log_path = log_dir / f"{name}.log"
        self._handle = self.log_path.open("w", encoding="utf-8")
        self.popen = subprocess.Popen(
            [sys.executable, "-m", "site_gpt.app.worker"],
            cwd=REPO_ROOT,
            env=child_env(),
            stdout=self._handle,
            stderr=subprocess.STDOUT,
        )

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

    def events(self) -> list[dict]:
        found = []
        for line in self.text().splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict) and "event" in payload:
                found.append(payload)
        return found

    def kill9(self) -> None:
        self.popen.kill()
        self.popen.wait(timeout=10)

    def stop(self, timeout: float = 20.0) -> None:
        if not self.alive():
            return
        self.popen.send_signal(15)
        try:
            self.popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.popen.kill()
            self.popen.wait(timeout=10)

    def close(self) -> None:
        self.stop()
        self._handle.close()


def wait_until(predicate, *, timeout: float, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def push(payload: dict) -> None:
    CLIENT.lpush(QUEUE_KEY, json.dumps(payload))


def depth() -> int:
    return int(CLIENT.llen(QUEUE_KEY))


def failure_count() -> int:
    return int(CLIENT.get(FAILURE_COUNTER) or 0)


def queue_types() -> list[str]:
    found = []
    for raw in CLIENT.lrange(QUEUE_KEY, 0, -1):
        try:
            found.append(str(json.loads(raw).get("type")))
        except ValueError:
            found.append("?")
    return found


class TableLock:
    """An ACCESS EXCLUSIVE lock the handler must wait on: the mid-job window."""

    def __init__(self, table: str) -> None:
        self.table = table
        self.connection = None

    def __enter__(self) -> TableLock:
        self.connection = db_connect()
        self.connection.autocommit = False
        with self.connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {self.table} IN ACCESS EXCLUSIVE MODE")
        return self

    def __exit__(self, *exc) -> None:
        if self.connection is not None:
            self.connection.rollback()
            self.connection.close()
            self.connection = None


# -- payloads ---------------------------------------------------------------


def digest_window() -> tuple[str, str]:
    now = datetime.now(UTC)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def payload_for(kind: str, seeded: Seeded, job_id: str) -> dict:
    start, end = digest_window()
    base = {"job_id": job_id, "attempt": 0}
    if kind == "ingest":
        return {**base, "type": kind, "website_id": seeded.website_id}
    if kind == "sitemap_scan":
        return {**base, "type": kind, "website_id": seeded.website_id}
    if kind == "retention":
        return {**base, "type": kind, "company_id": seeded.company_id}
    if kind == "insights":
        return {**base, "type": kind, "company_id": seeded.company_id}
    return {
        **base,
        "type": kind,
        "company_id": seeded.company_id,
        "period_start": start,
        "period_end": end,
    }


# -- per-type state ---------------------------------------------------------


def leftover(kind: str, seeded: Seeded) -> str:
    """The durable state a killed job leaves behind, as one short line."""
    if kind == "ingest":
        rows = query(
            "SELECT ingest_status, updated_at FROM websites WHERE id = %s",
            (seeded.website_id,),
        )
        return f"websites.ingest_status={rows[0][0]}" if rows else "no website row"
    if kind == "digest":
        rows = query(
            "SELECT sent_at, created_at FROM digest_log WHERE company_id = %s",
            (seeded.company_id,),
        )
        if not rows:
            return "no digest_log row (the claim was never made)"
        return f"digest_log.sent_at={'set' if rows[0][0] else 'NULL'} (claim row present)"
    if kind == "retention":
        rows = query("SELECT count(*) FROM chat_messages")
        return f"chat_messages rows={int(rows[0][0])}"
    if kind == "topic_clusters":
        rows = query(
            "SELECT status FROM topic_cluster_runs WHERE company_id = %s",
            (seeded.company_id,),
        )
        return (
            f"topic_cluster_runs.status={[r[0] for r in rows]}"
            if rows
            else "no topic_cluster_runs row"
        )
    if kind == "sitemap_scan":
        key = f"sitemap:scan:{seeded.website_id}"
        return f"{key} present={bool(CLIENT.exists(key))} (nothing durable is written)"
    if kind == "insights":
        rows = query("SELECT count(*) FROM conversation_insights")
        return f"conversation_insights rows={int(rows[0][0])}"
    return "?"


def reset(kind: str, seeded: Seeded) -> None:
    if kind == "ingest":
        query(
            "UPDATE websites SET ingest_status = 'none', updated_at = now() WHERE id = %s",
            (seeded.website_id,),
        )
    elif kind == "digest":
        query("DELETE FROM digest_log WHERE company_id = %s", (seeded.company_id,))
    elif kind == "topic_clusters":
        query("DELETE FROM topic_cluster_runs WHERE company_id = %s", (seeded.company_id,))
        query("DELETE FROM topic_clusters WHERE company_id = %s", (seeded.company_id,))
    elif kind == "sitemap_scan":
        CLIENT.delete(f"sitemap:scan:{seeded.website_id}")
    elif kind == "insights":
        query("DELETE FROM conversation_insights")
    CLIENT.delete(QUEUE_KEY)


def received_count(worker: Worker, kind: str) -> int:
    return len(
        [
            e
            for e in worker.events()
            if e["event"] == "worker.job.received" and e.get("job_type") == kind
        ]
    )


def jobs_of(events: list[dict], job_id: str) -> list[dict]:
    return [event for event in events if event.get("job_id") == job_id]


def trace(events: list[dict], job_id: str) -> list[dict]:
    """Every event about this job, in order.

    Only the consumer's own lines carry `job_id`; a handler's events carry the
    request id the consumer bound for the job. Following one job therefore needs
    both, which is the same chain an operator reads out of the file. A payload
    delivered twice carries one `job_id` and two request ids, so every request id
    seen on that job's lines is followed, not just the first.
    """
    mine = jobs_of(events, job_id)
    request_ids = {event.get("request_id") for event in mine if event.get("request_id")}
    if not request_ids:
        return mine
    return [
        event
        for event in events
        if event.get("job_id") == job_id or event.get("request_id") in request_ids
    ]


# -- the tick ---------------------------------------------------------------


def run_tick(kind: str, seeded: Seeded) -> dict:
    """Call the scheduler function this type's loop tick would call, once."""
    import asyncio

    note = ""
    if kind == "ingest":
        rows = query(
            "UPDATE websites SET updated_at = now() - interval '7 hours' "
            "WHERE id = %s AND ingest_status = 'processing' RETURNING ingest_status",
            (seeded.website_id,),
        )
        note = (
            "backdated websites.updated_at by -7 h (STUCK_INGEST_AFTER is 6 h); "
            "the real wait is up to 6 h"
            if rows
            else "nothing was left in `processing`, so there was nothing to recover"
        )
        asyncio.run(_requeue_stuck())
    elif kind == "digest":
        rows = query(
            "UPDATE digest_log SET created_at = now() - interval '2 hours' "
            "WHERE company_id = %s AND sent_at IS NULL RETURNING created_at",
            (seeded.company_id,),
        )
        note = (
            "backdated digest_log.created_at by -2 h (DIGEST_CHECK_SECONDS is 3600 s); "
            "the real wait is up to 1 h"
            if rows
            else "no unsent claim row to age"
        )
        asyncio.run(_enqueue(_worker().enqueue_due_digests, datetime.now(UTC)))
    elif kind == "retention":
        note = "no time gate: RETENTION_CHECK_SECONDS is the only wait (24 h)"
        asyncio.run(_enqueue(_worker().enqueue_due_retention))
    elif kind == "topic_clusters":
        rows = query(
            "UPDATE topic_cluster_runs SET updated_at = now() - interval '31 minutes' "
            "WHERE company_id = %s AND status = 'running' RETURNING status",
            (seeded.company_id,),
        )
        note = (
            "backdated topic_cluster_runs.updated_at by -31 min (STALE_RUN_AFTER is 30 min); "
            "the real wait is up to 30 min"
            if rows
            else "no `running` run row to age"
        )
        asyncio.run(_enqueue(_worker().enqueue_due_topics, datetime.now(UTC)))
    elif kind == "sitemap_scan":
        note = "no time gate: SITEMAP_SCAN_INTERVAL_SECONDS is the only wait (24 h)"
        asyncio.run(_enqueue(_worker().enqueue_due_sitemap_scans))
    elif kind == "insights":
        note = "no time gate: INSIGHT_INTERVAL_SECONDS is the only wait (24 h)"
        asyncio.run(_enqueue(_worker().enqueue_due_insights))
    return {"tick": kind, "queued": queue_types(), "note": note}


def _worker():
    from site_gpt.app import worker

    return worker


async def _enqueue(function, *args) -> None:
    result = function(*args)
    if hasattr(result, "__await__"):
        await result


async def _requeue_stuck() -> None:
    await _worker().requeue_stuck_ingests()


# -- scenarios --------------------------------------------------------------


def unhandled(log_dir: Path) -> None:
    """A payload whose type nothing handles: consumed, logged, dropped."""
    name = "unhandled"
    block_ = block(name)
    before = failure_count()
    worker = Worker("worker-unhandled", log_dir)
    try:
        wait_until(lambda: '"worker.started"' in worker.text(), timeout=20)
        push({"type": "rehearsal.unhandled", "note": "nothing handles this"})
        wait_until(lambda: depth() == 0, timeout=15)
        time.sleep(1.0)
        events = worker.events()
        received = [e for e in events if e["event"] == "worker.job.received"]
        unknown = [e for e in events if e["event"] == "worker.job.unknown"]
        failed = [e for e in events if e["event"] == "worker.job.failed"]
        same = bool(received and unknown) and received[-1].get("job_id") == unknown[-1].get("job_id")
        block_.observe(
            "$ redis-cli LPUSH queue:jobs '{\"type\":\"rehearsal.unhandled\"}' "
            f"-> queue depth {depth()}; worker.job.received={len(received)}, "
            f"worker.job.unknown={len(unknown)}, worker.job.failed={len(failed)}; "
            f"received and unknown share job_id: {same}"
        )
        block_.observe(
            f"ops:worker:job_failures {before} -> {failure_count()} "
            "(an unknown type is not a failed job)"
        )
    finally:
        worker.close()


def duplicate(kind: str, seeded: Seeded, log_dir: Path) -> None:
    block_ = block(kind)
    worker = Worker(f"worker-dup-{kind}", log_dir)
    try:
        wait_until(lambda: '"worker.started"' in worker.text(), timeout=20)
        job_id = str(uuid4())
        payload = payload_for(kind, seeded, job_id)
        before_left = leftover(kind, seeded)
        push(payload)
        push(payload)  # byte-identical, same job_id: a producer replay
        wait_until(lambda: depth() == 0, timeout=20)
        time.sleep(2.0)
        events = worker.events()
        mine = trace(events, job_id)
        received = [e for e in mine if e["event"] == "worker.job.received"]
        failed = [e for e in mine if e["event"] == "worker.job.failed"]
        done = [e for e in mine if e["event"] in DONE_EVENTS[kind]]
        detail = ""
        if kind == "retention":
            detail = " rows_deleted=" + str([e.get("rows_deleted") for e in done])
        elif kind == "digest":
            detail = " reason=" + str([e.get("reason") or e.get("sent") for e in done])
        elif kind == "topic_clusters":
            detail = " status=" + str([e.get("status") for e in done])
        elif kind == "insights":
            detail = " status/eligible=" + str([(e.get("status"), e.get("eligible")) for e in done])
        elif kind == "ingest":
            detail = " websites.ingest_status=" + str(
                [r[0] for r in query("SELECT ingest_status FROM websites WHERE id = %s", (seeded.website_id,))]
            )
        elif kind == "sitemap_scan":
            detail = " events=" + str([e["event"] for e in done])
        block_.observe(
            f"same payload pushed twice (job_id {job_id[:8]}…) -> "
            f"received={len(received)}, terminal({'/'.join(DONE_EVENTS[kind])})={len(done)}, "
            f"failed={len(failed)}{detail}"
        )
        block_.observe(f"before: {before_left}; after: {leftover(kind, seeded)}")
    finally:
        worker.close()


def crash(kind: str, table: str, seeded: Seeded, log_dir: Path) -> None:
    block_ = block(kind)
    worker = Worker(f"worker-crash-{kind}", log_dir)
    job_id = str(uuid4())
    before_left = leftover(kind, seeded)
    try:
        wait_until(lambda: '"worker.started"' in worker.text(), timeout=20)
        with TableLock(table):
            push(payload_for(kind, seeded, job_id))
            seen = wait_until(
                lambda: any(
                    e["event"] == "worker.job.received" and e.get("job_id") == job_id
                    for e in worker.events()
                ),
                timeout=20,
            )
            time.sleep(0.5)
            finished_early = any(
                e["event"] in DONE_EVENTS[kind] for e in trace(worker.events(), job_id)
            )
            worker.kill9()
        events = worker.events()
        mine = trace(events, job_id)
        names = [e["event"] for e in mine]
        block_.observe(
            f"$ kill -9 {worker.pid} with `{table}` held -> the job was in flight: {seen}, "
            f"had already finished: {finished_early}; events for this job_id: {names}"
        )
        block_.observe(f"after the kill: {leftover(kind, seeded)}")
    finally:
        worker.close()

    # Does anything redo it? A fresh worker starts, and if it does nothing in the
    # probe window, the only path left is this type's own loop tick.
    probe = Worker(f"worker-probe-{kind}", log_dir)
    try:
        wait_until(lambda: '"worker.started"' in probe.text(), timeout=20)
        time.sleep(8.0)
        events = probe.events()
        same = [e for e in events if e.get("job_id") == job_id]
        new_of_type = [
            e
            for e in events
            if e["event"] == "worker.job.received" and e.get("job_type") == kind and e.get("job_id") != job_id
        ]
        block_.observe(
            "a fresh worker starts -> the killed job's own id seen again: "
            f"{[e['event'] for e in same] or 'never'}; a new {kind} job within 8 s: "
            f"{len(new_of_type)}"
        )

        # The tick, with the stale column backdated, and the worker running so a
        # re-queued job is visibly consumed.
        before_tick = received_count(probe, kind)
        tick = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--tick",
                kind,
                "--company",
                seeded.company_id,
                "--website",
                seeded.website_id,
            ],
            cwd=REPO_ROOT,
            env=child_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        try:
            result = json.loads(tick.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            result = {"tick": kind, "queued": [], "note": f"tick failed: {tick.stdout[-400:]}{tick.stderr[-400:]}"}
        consumed = wait_until(
            lambda: received_count(probe, kind) > before_tick, timeout=10
        )
        time.sleep(1.5)
        by_type = [e for e in probe.events() if e.get("job_type") == kind]
        block_.observe(f"next tick: {result['note']} -> queue at tick {result['queued'] or 'empty'}")
        block_.observe(
            f"the fresh worker takes a new {kind} job after the tick: {consumed}; "
            f"its events: {[e['event'] for e in by_type][-4:]}"
        )
        block_.observe(f"after the tick: {leftover(kind, seeded)}")
    finally:
        probe.close()


# -- main -------------------------------------------------------------------


def rehearse(keep_db: bool) -> int:
    if not DB.startswith("v6_gate_2g"):
        say(f"Refusing REHEARSAL_DB={DB!r}: the name must start with 'v6_gate_2g'.")
        return 2

    log_dir = Path(tempfile.mkdtemp(prefix="v6-20-rehearsal-"))
    say(f"PostgreSQL {PG} database {DB}")
    say(f"Redis {TARGET['host']}:{TARGET['port']}/{TARGET['db']}")
    say(f"worker logs {log_dir}")

    create_database()
    CLIENT.flushdb()
    revision = migrate()
    say(f"alembic head {revision}")
    seeded = seed()
    say(f"seeded company {seeded.company_id} website {seeded.website_id}\n")

    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()
    say(f"commit {commit}\n")

    try:
        unhandled(log_dir)
        for kind, table in TYPES:
            reset(kind, seeded)
            duplicate(kind, seeded, log_dir)
            reset(kind, seeded)
            crash(kind, table, seeded, log_dir)
            reset(kind, seeded)
            say("")
    finally:
        CLIENT.flushdb()
        if keep_db:
            say(f"kept database {DB}; drop it with DROP DATABASE \"{DB}\"")
        else:
            drop_database()

    rows = [f"# V6-20 failure-injection rehearsal\n", f"- commit `{commit}`", f"- alembic `{revision}`\n"]
    for block_ in BLOCKS.values():
        rows.append(f"## {block_.name}\n")
        rows.extend(f"- {line}" for line in block_.lines)
        rows.append("")
    (log_dir / "rows.md").write_text("\n".join(rows), encoding="utf-8")
    say(f"\nrows: {log_dir / 'rows.md'}")
    say(f"logs: {log_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--tick", choices=[kind for kind, _ in TYPES])
    parser.add_argument("--company")
    parser.add_argument("--website")
    args = parser.parse_args()

    if args.tick:
        seeded = Seeded(company_id=args.company or "", website_id=args.website or "")
        print(json.dumps(run_tick(args.tick, seeded)))
        return 0

    return rehearse(args.keep_db)


if __name__ == "__main__":
    sys.exit(main())
