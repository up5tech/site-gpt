"""V4-5G release gate — the PLAN_V4.md §9 runbook on a throwaway database.

Run against an empty Postgres database already migrated to `f33497bc1ecd`:

    DATABASE_URL=... uv run python scripts/gate_v4_5g/gate.py \
        --v3-src /tmp/gate_v4_5g_v3 [--port 8095]

The caller creates and migrates the throwaway database and drops it afterwards;
this script never touches the dev database. It starts a real `uvicorn` process
against that database (so Redis counters and the async clients run on one
event loop, exactly as deployed) and drives it over HTTP with `httpx`, while
direct database writes and the worker handlers run in this process. The
configured LLM, embedding, YouTube and Notion endpoints are called when they are
reachable; a provider-bound step that cannot run is recorded **BLOCKED** with
its reason and is never counted as a pass (the plan's blocked-item rule).

Covered, in §9 order:

1. schema: single head, M10 table, `attachments.file_type` widened;
2. register → login → website + sitemap page → ingest (real crawl + real
   embeddings) → chat, sync and SSE;
3. analytics trend/funnel/top questions, the CSV (formula neutralisation, no PII
   column) and the hosted page;
4. the per-session cap, its Redis-down fail-open and the `0`/garbage fallbacks;
5. the sitemap scan: success diff, failed/empty fetch no-op, no double queue,
   vanished page takes every document row;
6. one import per new source: `.pptx`, YouTube, Notion (wrong token negative);
7. an insights run with live labels, then erasure (zero orphan rows) and
   retention;
8. all V4 flags off → the V3 smoke again, plus the digest byte comparison
   against the `v3` checkout (code-to-code, not a copy);
9. the negatives: session-cap ordering, hosted-page lookalikes, disabled page,
   foreign id, embed-token hook on the page, widget-config key count.
"""

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import redis as sync_redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models, worker
from site_gpt.app.core.config import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)
from site_gpt.app.db.session import SessionLocal
from site_gpt.app.services import analytics as analytics_service
from site_gpt.app.services import digest, insights, quota
from site_gpt.app.services.embed_guard import (
    EMBED_TOKEN_REQUIRED,
    EmbedTokenRefused,
    ensure_embed_allowed,
)
from site_gpt.app.services.redis import QUEUE_KEY
from site_gpt.app.services.insights import MAX_SUMMARY_LENGTH

HEAD = "f33497bc1ecd"
WINDOW_START = datetime(2026, 11, 2, tzinfo=UTC)
WINDOW_END = datetime(2026, 11, 9, tzinfo=UTC)
NOW = datetime.now(UTC)
YOUTUBE_DEFAULT = "https://www.youtube.com/watch?v=aircAruvnKk"

RESULTS: list[tuple[str, bool]] = []
BLOCKED: list[tuple[str, str]] = []
UPLOADED: list[str] = []


def check(name: str, ok: bool, detail="") -> bool:
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + str(detail)) if detail else ''}")
    return bool(ok)


def blocked(name: str, reason: str) -> None:
    BLOCKED.append((name, reason))
    print(f"BLOCKED  {name} — {str(reason)[:300]}")


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def db_query(sql: str, **params):
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar()


RUNNER = r"""
import json, os
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import site_gpt
from site_gpt.app.services import digest

engine = create_engine(os.environ["DATABASE_URL"])
db = sessionmaker(bind=engine)()
data = digest.build_digest(
    db,
    os.environ["COMPANY_ID"],
    datetime.fromisoformat(os.environ["WINDOW_START"]),
    datetime.fromisoformat(os.environ["WINDOW_END"]),
)
print(json.dumps({
    "module": site_gpt.__file__,
    "keys": sorted(data),
    "json": json.dumps(data, sort_keys=True),
    "html": digest.render_digest_html(data, os.environ["COMPANY_NAME"]),
}))
"""


def v3_digest(src: Path, database: str, company_id, name: str) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(src / "src"),
        "DATABASE_URL": database,
        "COMPANY_ID": str(company_id),
        "COMPANY_NAME": name,
        "WINDOW_START": WINDOW_START.isoformat(),
        "WINDOW_END": WINDOW_END.isoformat(),
    }
    finished = subprocess.run(
        [sys.executable, "-c", RUNNER],
        cwd=str(src),
        env=env,
        capture_output=True,
        text=True,
    )
    if finished.returncode != 0:
        raise RuntimeError(f"v3 checkout failed:\n{finished.stderr[-3000:]}")
    return json.loads(finished.stdout.strip().splitlines()[-1])


def wait_for_health(base: str, process: subprocess.Popen, seconds: int = 40) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return True
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(0.3)
    return False


def main() -> int:  # noqa: C901 - a runbook is one long function on purpose
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3-src", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument(
        "--youtube-url", default=os.getenv("GATE_YOUTUBE_URL", YOUTUBE_DEFAULT)
    )
    args = parser.parse_args()

    database = os.environ["DATABASE_URL"]
    engine = create_engine(database)
    db = sessionmaker(bind=engine)()
    base = f"http://127.0.0.1:{args.port}"
    redis_sync = sync_redis.Redis(
        host=REDIS_HOST,
        port=int(REDIS_PORT),
        password=REDIS_PASSWORD or None,
        db=int(REDIS_DB),
        decode_responses=True,
    )

    stamp = uuid4().hex[:8]
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "site_gpt.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--log-level",
            "warning",
        ],
        env={**os.environ, "DATABASE_URL": database},
        cwd=os.getcwd(),
    )
    if not wait_for_health(base, server):
        server.terminate()
        print("FAIL: the gate API did not become healthy")
        return 1
    client = httpx.Client(base_url=base, timeout=120.0)

    try:
        # -- 1. Schema ------------------------------------------------------
        version = db_query("select version_num from alembic_version")
        check("single alembic head is M10", version == HEAD, str(version))
        check(
            "conversation_insights table exists",
            db_query(
                "select count(*) from information_schema.tables "
                "where table_name = 'conversation_insights'"
            )
            == 1,
        )
        width = db_query(
            "select character_maximum_length from information_schema.columns "
            "where table_name = 'attachments' and column_name = 'file_type'"
        )
        check("attachments.file_type is widened to 120", width == 120, f"length={width}")

        health = client.get("/health")
        check("/health answers", health.status_code == 200, health.text[:120])
        check(
            "/health keeps its shape (status/db/redis/rate_limiter)",
            health.status_code == 200
            and {"status", "db", "redis", "rate_limiter"} <= set(health.json()),
            str(sorted(health.json())) if health.status_code == 200 else "",
        )

        # -- 2. Register, login, website, ingest, chat ----------------------
        admin_email = f"gate5g-{stamp}@example.com"
        password = "Gate!passw0rd"
        reg = client.post(
            "/api/register",
            json={
                "company_name": f"Gate 5G {stamp}",
                "first_name": "Gate",
                "last_name": "Admin",
                "email": admin_email,
                "password": password,
            },
        )
        check("register", reg.status_code in (200, 201), reg.text[:200])
        tok = client.post("/api/token", json={"email": admin_email, "password": password})
        check("login", tok.status_code == 200, tok.text[:80])
        headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}
        me = client.get("/api/users/me", headers=headers)
        check("admin role", me.status_code == 200 and me.json()["role"] == "admin")

        site = client.post(
            "/api/websites/",
            json={
                "url": "https://example.com",
                "site_map_url": "",
                "name": "Gate 5G site",
            },
            headers=headers,
        )
        check("website created", site.status_code in (200, 201), site.text[:160])
        website_id = site.json()["id"]
        origin = "https://example.com"

        config = client.get("/api/widget-config", params={"website_id": website_id})
        check(
            "/api/widget-config publishes exactly the 14 public keys",
            config.status_code == 200 and len(config.json()) == 14,
            str(len(config.json()) if config.status_code == 200 else config.status_code),
        )
        hidden = {
            "live_inbox_enabled",
            "daily_message_limit",
            "conversation_insights_enabled",
        }
        check(
            "no internal key reaches the widget",
            config.status_code == 200 and not (hidden & set(config.json())),
        )

        # A sitemap page gives the real crawler something to fetch.
        with SessionLocal() as patch_db:
            patch_db.add(
                models.WebsitePage(
                    website_id=website_id,
                    url="https://example.com",
                    status="active",
                )
            )
            patch_db.commit()

        knowledge = (
            "Gate 5G knowledge base.\n\n"
            "Enterprise SSO: the Gate 5G product supports SAML single sign-on on the "
            "Team plan. Administrators enable it under Settings, Security, then SSO.\n"
        )
        extra = client.post(
            "/api/extra_documents/",
            json={
                "name": "gate5g-sso.md",
                "content": knowledge,
                "website_id": website_id,
            },
            headers=headers,
        )
        check("extra document created", extra.status_code in (200, 201), extra.text[:160])

        ingest_api = client.post(
            "/api/ingest", params={"website_id": website_id}, headers=headers
        )
        check(
            "POST /api/ingest accepts the job",
            ingest_api.status_code == 200,
            ingest_api.text[:160],
        )
        # Drop exactly the job this call queued, so the shared queue is left as
        # it was found.
        for item in redis_sync.lrange(QUEUE_KEY, 0, -1):
            if website_id in item:
                redis_sync.lrem(QUEUE_KEY, 1, item)

        try:
            asyncio.run(
                worker.handle_ingest({"type": "ingest", "website_id": website_id})
            )
            ingest_ok, ingest_reason = True, ""
        except Exception as exc:  # noqa: BLE001 - crawl is network-bound
            ingest_ok, ingest_reason = False, f"{type(exc).__name__}: {exc}"
        embedded = db_query(
            "select count(*) from embeddings e join extra_documents d "
            "on d.id = e.extra_document_id where d.website_id = :w",
            w=website_id,
        )
        documents = db_query(
            "select count(*) from documents where website_id = :w", w=website_id
        )
        status = db_query(
            "select ingest_status from websites where id = :w", w=website_id
        )
        if ingest_ok:
            check(
                "ingest completed and embedded the knowledge base",
                status == "completed" and embedded >= 1,
                f"status={status} chunks={embedded}",
            )
            if documents >= 1:
                check("the live crawl ingested a page", True, f"documents={documents}")
            else:
                blocked(
                    "live crawl of the website",
                    "crawl of https://example.com returned 0 documents",
                )
        else:
            blocked("ingest (crawl + embeddings)", ingest_reason)

        # The K4 token is minted before the first message, as the widget does.
        session = f"chat-{stamp}"
        token_res = client.post(
            "/api/session-token",
            json={"website_id": website_id, "session_id": session},
            headers={"Origin": origin},
        )
        session_token = (
            token_res.json().get("token", "") if token_res.status_code == 200 else ""
        )
        check("session token minted before the first message", bool(session_token),
              str(token_res.status_code))

        answer_text = ""
        try:
            chat = client.post(
                "/api/chat",
                json={
                    "website_id": website_id,
                    "session_id": session,
                    "question": "Does the product support SAML single sign-on?",
                },
                headers={"Origin": origin},
            )
            answer_text = chat.json().get("answer", "") if chat.status_code == 200 else ""
            live_chat = chat.status_code == 200 and bool(answer_text.strip())
            reason = "" if live_chat else f"{chat.status_code}: {chat.text[:200]}"
        except Exception as exc:  # noqa: BLE001 - provider/network bound
            live_chat, reason = False, f"{type(exc).__name__}: {exc}"
        if live_chat:
            check("chat answered with the live provider", True, answer_text[:80])
            check(
                "the answer used the ingested knowledge",
                "sso" in answer_text.lower() or "sign" in answer_text.lower(),
                answer_text[:160],
            )
        else:
            blocked("chat (live provider)", reason)

        try:
            with client.stream(
                "POST",
                "/api/chat/stream",
                json={
                    "website_id": website_id,
                    "session_id": f"{session}-sse",
                    "question": "What is SSO?",
                },
                headers={"Origin": origin},
            ) as stream:
                body = b"".join(stream.iter_bytes()).decode("utf-8", "replace")
            sse_ok = stream.status_code == 200 and "data:" in body
            reason = "" if sse_ok else f"{stream.status_code}: {body[:200]}"
        except Exception as exc:  # noqa: BLE001
            sse_ok, reason = False, f"{type(exc).__name__}: {exc}"
        if sse_ok:
            check("SSE chat streamed", True, body[:120].replace("\n", " "))
        else:
            blocked("chat SSE (live provider)", reason)

        # -- 3. Analytics, CSV, hosted page --------------------------------
        formula_session = f"formula-{stamp}"
        for role, text_value, flag in (
            ("user", '=HYPERLINK("http://x.test","click") how do I export?', None),
            ("assistant", "Open Settings, then Export.", True),
        ):
            db.add(
                models.ChatMessage(
                    website_id=website_id,
                    session_id=formula_session,
                    role=role,
                    message=text_value,
                    answered=flag,
                    created_at=NOW - timedelta(minutes=5),
                    updated_at=NOW - timedelta(minutes=5),
                )
            )
        db.commit()

        summary = client.get("/api/analytics/summary", params={"days": 7}, headers=headers)
        payload = summary.json() if summary.status_code == 200 else {}
        check(
            "analytics summary carries trend, funnel and top questions",
            summary.status_code == 200
            and {"trend", "funnel", "top_questions"} <= set(payload),
            summary.text[:160],
        )
        check(
            "funnel has the five D4 stages",
            [row["stage"] for row in payload.get("funnel", [])]
            == ["started", "answered", "lead", "handoff", "human"],
            str([row["stage"] for row in payload.get("funnel", [])]),
        )
        questions = [row["question"] for row in payload.get("top_questions", [])]
        check(
            "top questions include the formula-looking question, normalized",
            any(q.startswith("=hyperlink(") for q in questions),
            str(questions[:3]),
        )

        csv_res = client.get(
            "/api/analytics/export.csv", params={"days": 7}, headers=headers
        )
        csv_text = csv_res.text
        check(
            "CSV downloads as an attachment",
            csv_res.status_code == 200
            and "text/csv" in csv_res.headers.get("content-type", "")
            and "attachment" in csv_res.headers.get("content-disposition", ""),
            csv_res.headers.get("content-disposition", ""),
        )
        check(
            "CSV neutralises a formula-leading cell",
            "'=hyperlink(" in csv_text.lower(),
            [line for line in csv_text.splitlines() if "hyperlink" in line.lower()][:1],
        )
        header_line = csv_text.splitlines()[0] if csv_text else ""
        check(
            "CSV header is aggregate-only (no session id / contact column)",
            header_line
            == "date,conversations,messages,visitor_messages,new_contacts,"
            "feedback_up,feedback_down,unanswered",
            header_line,
        )
        check(
            "CSV contains no session id or contact details",
            session not in csv_text and "gate5g-" not in csv_text,
        )

        page = client.get(f"/chat/{website_id}")
        check(
            "hosted page serves the widget in page mode",
            page.status_code == 200
            and "window.ChatWidgetConfig" in page.text
            and "displayMode: 'page'" in page.text
            and "noindex" in page.text,
            page.text[page.text.find("<title>"): page.text.find("</title>") + 8],
        )
        check(
            "hosted page title comes from assistant_name",
            "<title>Site GPT</title>" in page.text,
        )

        # First-party rule: the page's origin is the Host it was served from.
        api_host = f"api.gate.test:{args.port}"
        page_origin = f"http://{api_host}"
        first_party = client.post(
            "/api/chat",
            json={
                "website_id": website_id,
                "session_id": f"{session}-page",
                "question": "hi",
            },
            headers={"Host": api_host, "Origin": page_origin},
        )
        check(
            "the served page's own origin is first-party",
            first_party.status_code != 403,
            f"{first_party.status_code}: {first_party.text[:160]}",
        )
        for lookalike in (
            f"http://api.gate.test.evil:{args.port}",
            f"http://api.gate.test:{args.port + 1}",
            f"https://{api_host}",
        ):
            refused = client.post(
                "/api/chat",
                json={
                    "website_id": website_id,
                    "session_id": f"{session}-look",
                    "question": "hi",
                },
                headers={"Host": api_host, "Origin": lookalike},
            )
            check(
                f"lookalike origin {lookalike} is still refused",
                refused.status_code == 403,
                str(refused.status_code),
            )
        third_party = client.post(
            "/api/chat",
            json={
                "website_id": website_id,
                "session_id": f"{session}-x",
                "question": "hi",
            },
            headers={"Origin": "https://attacker.example.net"},
        )
        check("a third-party origin is still refused", third_party.status_code == 403)

        # Enforce mode: the page still needs the embed token (D8). Patching the
        # mode is in-process and is the only way to flip it without restarting
        # the gate server; the origin part is the real guard.
        site_row = db.query(models.Website).filter(models.Website.id == website_id).one()
        request = MagicMock()
        request.headers = {"origin": page_origin}
        request.base_url = f"{page_origin}/"
        with patch("site_gpt.app.services.embed_guard.EMBED_TOKEN_MODE", "enforce"):
            try:
                ensure_embed_allowed(request, db, site_row)
                enforce_reason = ""
            except EmbedTokenRefused as exc:
                enforce_reason = exc.reason
            except Exception as exc:  # noqa: BLE001 - an origin refusal would fail here
                enforce_reason = f"{type(exc).__name__}"
        check(
            "enforce mode still requires the embed token on the hosted page",
            enforce_reason == EMBED_TOKEN_REQUIRED,
            enforce_reason,
        )

        # Disabled website: the page shows the notice, no widget.
        disabled_site = client.post(
            "/api/websites/",
            json={"url": "https://disabled.example", "site_map_url": "", "name": "Disabled"},
            headers=headers,
        )
        disabled_id = disabled_site.json()["id"]
        with SessionLocal() as patch_db:
            row = (
                patch_db.query(models.Website)
                .filter(models.Website.id == disabled_id)
                .one()
            )
            row.status = "inactive"
            patch_db.commit()
        disabled_page = client.get(f"/chat/{disabled_id}")
        check(
            "a disabled website renders the unavailable notice, not the chat",
            disabled_page.status_code == 200
            and "temporarily unavailable" in disabled_page.text
            and "window.ChatWidgetConfig" not in disabled_page.text,
            str(disabled_page.status_code),
        )
        check(
            "an unknown or malformed website id on the page is a 404",
            client.get(f"/chat/{uuid4()}").status_code == 404
            and client.get("/chat/not-a-uuid").status_code == 404,
        )

        # -- 4. Session cap ---------------------------------------------------
        put = client.put(
            "/api/settings/",
            json=[{"key": "session_message_limit", "value": "3"}],
            headers=headers,
        )
        check("session_message_limit=3 written", put.status_code == 200, put.text[:120])
        cap_session = f"cap-{stamp}"
        cap_key = quota.session_cap_key(website_id, cap_session)
        redis_sync.delete(cap_key)
        daily_key = quota.quota_key(website_id, NOW)

        def daily_used() -> int:
            return int(redis_sync.get(daily_key) or 0)

        before_daily = daily_used()
        answers = []
        for index in range(4):
            try:
                res = client.post(
                    "/api/chat",
                    json={
                        "website_id": website_id,
                        "session_id": cap_session,
                        "question": f"cap probe {index}",
                    },
                    headers={"Origin": origin},
                )
                answers.append(
                    res.json().get("answer", "") if res.status_code == 200 else ""
                )
            except Exception as exc:  # noqa: BLE001
                answers.append(f"<error {type(exc).__name__}>")
        after_daily = daily_used()
        accepted = [a for a in answers[:3] if a and a != quota.SESSION_CAP_MESSAGE]
        if len(accepted) == 3:
            check(
                "the fourth message in one session is refused with the friendly cap notice",
                answers[3] == quota.SESSION_CAP_MESSAGE,
                answers[3][:80],
            )
            check(
                "a capped refusal spends no daily budget",
                after_daily - before_daily == 3,
                f"daily delta={after_daily - before_daily}",
            )
        else:
            blocked(
                "session cap refusal (live provider)",
                "the first three messages did not all answer with the model",
            )
        check(
            "the capped refusal did not reset the K4 session",
            bool(session_token)
            and client.get(
                "/api/chat/messages",
                params={"website_id": website_id, "session_id": session},
                headers={"Origin": origin, "X-Session-Token": session_token},
            ).status_code
            == 200,
        )

        from site_gpt.app.api.setting import company_session_message_limit

        for raw, expected in (("0", 0), ("abc", 0), ("-5", 0), ("", 0), ("7", 7)):
            with SessionLocal() as patch_db:
                row = (
                    patch_db.query(models.Setting)
                    .filter(
                        models.Setting.company_id == site_row.company_id,
                        models.Setting.key == "session_message_limit",
                    )
                    .one_or_none()
                )
                if row is None:
                    patch_db.add(
                        models.Setting(
                            company_id=site_row.company_id,
                            key="session_message_limit",
                            value=raw,
                        )
                    )
                else:
                    row.value = raw
                patch_db.commit()
            with SessionLocal() as read_db:
                resolved = company_session_message_limit(read_db, site_row.company_id)
            check(
                f"session_message_limit {raw!r} resolves to {expected}",
                resolved == expected,
                str(resolved),
            )

        async def redis_down():
            fake = MagicMock()
            fake.incr = AsyncMock(side_effect=RuntimeError("redis down"))
            with patch("site_gpt.app.services.quota.redis_client", fake):
                return await quota.consume_session_message(
                    website_id, "redis-down", limit=1
                )

        check("a Redis outage fails the session cap open", asyncio.run(redis_down()) is True)

        client.put(
            "/api/settings/",
            json=[{"key": "session_message_limit", "value": "0"}],
            headers=headers,
        )

        # -- 5. Sitemap scan --------------------------------------------------
        scan_site = client.post(
            "/api/websites/",
            json={
                "url": "https://scan.example",
                "site_map_url": "https://scan.example/sitemap.xml",
                "name": "Scan site",
            },
            headers=headers,
        )
        scan_id = scan_site.json()["id"]

        # Failed fetch (real DNS failure) changes nothing.
        with SessionLocal() as patch_db:
            row = patch_db.query(models.Website).filter(models.Website.id == scan_id).one()
            row.site_map_url = "https://gate-5g.invalid/sitemap.xml"
            patch_db.commit()
        asyncio.run(
            worker.handle_sitemap_scan({"type": "sitemap_scan", "website_id": scan_id})
        )
        check(
            "a failed sitemap fetch changes zero rows",
            db_query("select count(*) from website_pages where website_id = :w", w=scan_id)
            == 0,
        )

        # Empty fetch (fetch succeeds, returns nothing) also changes nothing.
        with patch.object(worker, "extract_urls_from_sitemap", return_value=[]):
            asyncio.run(
                worker.handle_sitemap_scan({"type": "sitemap_scan", "website_id": scan_id})
            )
        check(
            "an empty sitemap fetch changes zero rows",
            db_query("select count(*) from website_pages where website_id = :w", w=scan_id)
            == 0,
        )

        urls = ["https://scan.example/a", "https://scan.example/b"]
        with patch.object(
            worker, "extract_urls_from_sitemap", return_value=urls
        ), patch.object(worker, "enqueue_job", new=AsyncMock()) as scan_queue:
            asyncio.run(
                worker.handle_sitemap_scan({"type": "sitemap_scan", "website_id": scan_id})
            )
        check(
            "a successful diff adds the pages and queues one ingest",
            db_query("select count(*) from website_pages where website_id = :w", w=scan_id)
            == 2
            and scan_queue.await_count == 1
            and db_query("select ingest_status from websites where id = :w", w=scan_id)
            == "processing",
            f"queued={scan_queue.await_count}",
        )

        with patch.object(
            worker, "extract_urls_from_sitemap", return_value=urls + ["https://scan.example/c"]
        ), patch.object(worker, "enqueue_job", new=AsyncMock()) as second_queue:
            asyncio.run(
                worker.handle_sitemap_scan({"type": "sitemap_scan", "website_id": scan_id})
            )
        check(
            "a processing website is not double-queued by the scan",
            second_queue.await_count == 0,
            f"queued={second_queue.await_count}",
        )

        with SessionLocal() as patch_db:
            patch_db.add(
                models.Document(
                    website_id=scan_id,
                    url="https://scan.example/b",
                    title="b",
                    content="removed page",
                )
            )
            patch_db.add(
                models.Document(
                    website_id=scan_id,
                    url="https://scan.example/b",
                    title="b again",
                    content="second row for the same url",
                )
            )
            row = patch_db.query(models.Website).filter(models.Website.id == scan_id).one()
            row.ingest_status = "none"
            patch_db.commit()
        with patch.object(
            worker, "extract_urls_from_sitemap", return_value=["https://scan.example/a"]
        ), patch.object(worker, "enqueue_job", new=AsyncMock()):
            asyncio.run(
                worker.handle_sitemap_scan({"type": "sitemap_scan", "website_id": scan_id})
            )
        check(
            "a vanished page is retired and both of its documents deleted",
            db_query(
                "select count(*) from documents where website_id = :w and url = :u",
                w=scan_id,
                u="https://scan.example/b",
            )
            == 0
            and db_query(
                "select status from website_pages where website_id = :w and url = :u",
                w=scan_id,
                u="https://scan.example/b",
            )
            == "inactive",
        )

        # -- 6. One import per new source -------------------------------------
        try:
            from pptx import Presentation

            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = "Gate 5G deck"
            slide.placeholders[1].text = "The Gate 5G widget supports SAML SSO."
            buffer = io.BytesIO()
            deck.save(buffer)
            pptx_bytes = buffer.getvalue()
            pptx_ok, pptx_reason = True, ""
        except Exception as exc:  # noqa: BLE001
            pptx_bytes, pptx_ok, pptx_reason = b"", False, f"{type(exc).__name__}: {exc}"

        if pptx_ok:
            res = client.post(
                "/api/uploads/",
                files={
                    "file": (
                        "gate5g.pptx",
                        pptx_bytes,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    )
                },
                headers=headers,
            )
            check(
                ".pptx upload accepted (long MIME type fits file_type)",
                res.status_code == 200,
                res.text[:160],
            )
            if res.status_code == 200:
                UPLOADED.append(res.json()["file_url"])
                doc = client.post(
                    "/api/extra_documents/",
                    json={
                        "name": "gate5g-deck.pptx",
                        "content": "",
                        "website_id": website_id,
                        "file_ids": [res.json()["file_id"]],
                    },
                    headers=headers,
                )
                check(
                    "the .pptx became an extra document",
                    doc.status_code in (200, 201),
                    doc.text[:160],
                )
                if doc.status_code in (200, 201):
                    try:
                        asyncio.run(
                            worker.handle_ingest(
                                {"type": "ingest", "website_id": website_id}
                            )
                        )
                        chunks = db_query(
                            "select count(*) from embeddings e join extra_documents d "
                            "on d.id = e.extra_document_id "
                            "where d.name = 'gate5g-deck.pptx'"
                        )
                        check(
                            ".pptx text was extracted and embedded",
                            chunks >= 1,
                            f"chunks={chunks}",
                        )
                    except Exception as exc:  # noqa: BLE001
                        blocked(".pptx ingest", f"{type(exc).__name__}: {exc}")
        else:
            blocked(".pptx import", pptx_reason)

        try:
            yt = client.post(
                "/api/uploads/youtube", json={"url": args.youtube_url}, headers=headers
            )
            if yt.status_code == 200 and yt.json().get("files"):
                UPLOADED.extend(f["file_url"] for f in yt.json()["files"])
                check(
                    "YouTube import returned caption files",
                    yt.json()["files"][0]["file_type"].startswith("text/markdown"),
                    f"added={yt.json()['added']} total={yt.json()['total']}",
                )
            else:
                blocked(
                    "YouTube import (live captions)", f"{yt.status_code}: {yt.text[:200]}"
                )
        except Exception as exc:  # noqa: BLE001
            blocked("YouTube import (live captions)", f"{type(exc).__name__}: {exc}")

        # A video the captions endpoint returns nothing for must be a 400 and
        # leave no attachment row. If the probe video does have captions there is
        # no caption-less sample to point at, and the check is recorded blocked.
        yt_attachments_before = db_query("select count(*) from attachments")
        try:
            no_caps = client.post(
                "/api/uploads/youtube",
                json={"url": "https://www.youtube.com/watch?v=BaW_jenozKc"},
                headers=headers,
            )
            if no_caps.status_code == 400:
                check(
                    "a YouTube video without usable captions is a 400 with no attachment row",
                    db_query("select count(*) from attachments") == yt_attachments_before,
                    no_caps.text[:160],
                )
            else:
                blocked(
                    "YouTube caption-less negative",
                    f"the probe video did not fail with 400 (status={no_caps.status_code}); "
                    "no caption-less sample available",
                )
                UPLOADED.extend(
                    f["file_url"] for f in (no_caps.json().get("files") or [])
                )
        except Exception as exc:  # noqa: BLE001
            blocked("YouTube caption-less negative", f"{type(exc).__name__}: {exc}")

        # Notion: a wrong token must be refused, stored nowhere, never logged.
        uploads_before = set(os.listdir("uploads")) if os.path.isdir("uploads") else set()
        records: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        attachments_before = db_query("select count(*) from attachments")
        wrong_token = "secret_gate5g_wrong_token"
        try:
            notion = client.post(
                "/api/uploads/notion",
                json={
                    "url": "https://www.notion.so/Gate5g-0123456789abcdef0123456789abcdef",
                    "token": wrong_token,
                },
                headers=headers,
            )
            notion_status = notion.status_code
        except Exception as exc:  # noqa: BLE001
            notion_status = 0
            records.append(f"{type(exc).__name__}: {exc}")
        finally:
            root_logger.removeHandler(handler)
        check(
            "a wrong Notion token is refused with 401/400",
            notion_status in (400, 401),
            f"status={notion_status}",
        )
        check(
            "the refused Notion import stored nothing",
            db_query("select count(*) from attachments") == attachments_before,
        )
        check(
            "the Notion token never reaches a log line",
            not any(wrong_token in line for line in records),
        )
        uploads_after = set(os.listdir("uploads")) if os.path.isdir("uploads") else set()
        check(
            "the refused Notion import wrote no file under uploads/",
            uploads_after == uploads_before,
            f"{len(uploads_before)} -> {len(uploads_after)}",
        )

        attachments_before = db_query("select count(*) from attachments")
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        too_big = client.post(
            "/api/uploads/",
            files={"file": ("huge.txt", big, "text/plain")},
            headers=headers,
        )
        check(
            f"an oversize upload is refused with 413 (limit {MAX_UPLOAD_MB} MB)",
            too_big.status_code == 413,
            str(too_big.status_code),
        )
        check(
            "the refused upload stored no attachment row",
            db_query("select count(*) from attachments") == attachments_before,
        )

        # -- 7. Insights, erasure, retention ----------------------------------
        client.put(
            "/api/settings/",
            json=[{"key": "conversation_insights_enabled", "value": "true"}],
            headers=headers,
        )
        insight_session = f"insight-{stamp}"
        settled = NOW - timedelta(hours=2)
        with SessionLocal() as patch_db:
            patch_db.add(
                models.Conversation(
                    website_id=website_id,
                    session_id=insight_session,
                    state="bot",
                    last_message_at=settled,
                    created_at=settled,
                    updated_at=settled,
                )
            )
            for role, text_value in (
                ("user", "Is SAML SSO included, and how do I turn it on?"),
                ("assistant", "Yes: Settings, Security, SSO."),
            ):
                patch_db.add(
                    models.ChatMessage(
                        website_id=website_id,
                        session_id=insight_session,
                        role=role,
                        message=text_value,
                        answered=True if role == "assistant" else None,
                        created_at=settled,
                        updated_at=settled,
                    )
                )
            patch_db.commit()
        insight_id = None
        try:
            asyncio.run(
                worker.handle_insights(
                    {"type": "insights", "company_id": str(site_row.company_id)}
                )
            )
            row = (
                db.query(models.ConversationInsight)
                .join(
                    models.Conversation,
                    models.Conversation.id == models.ConversationInsight.conversation_id,
                )
                .filter(
                    models.Conversation.website_id == website_id,
                    models.Conversation.session_id == insight_session,
                )
                .one_or_none()
            )
            if row is not None and row.status == "completed":
                check(
                    "insights classified a settled conversation with the live provider",
                    row.sentiment is not None
                    and row.resolution is not None
                    and 0 < len(row.summary or "") <= MAX_SUMMARY_LENGTH,
                    f"sentiment={row.sentiment} resolution={row.resolution} "
                    f"model={row.model}",
                )
                outcomes = client.get(
                    "/api/analytics/summary", params={"days": 7}, headers=headers
                ).json()
                check(
                    "analytics adds outcomes only for an opted-in company",
                    outcomes.get("outcomes", {}).get("classified", 0) >= 1
                    and len(outcomes["outcomes"]["sentiment"]) > 0,
                    json.dumps(outcomes.get("outcomes")),
                )
                insight_id = str(row.conversation_id)
            else:
                blocked(
                    "insight classification (live provider)",
                    f"status={row.status if row else None}",
                )
        except Exception as exc:  # noqa: BLE001
            blocked("insight classification (live provider)", f"{type(exc).__name__}: {exc}")

        export = client.get(
            "/api/privacy/export", params={"website_id": website_id}, headers=headers
        )
        check("privacy export answers", export.status_code == 200, str(export.status_code))
        if insight_id is not None:
            erased = client.delete(
                f"/api/privacy/conversations/{insight_session}",
                params={"website_id": website_id},
                headers=headers,
            )
            orphan_count = db_query(
                "select count(*) from conversation_insights ci "
                "left join conversations c on c.id = ci.conversation_id "
                "where c.id is null"
            )
            remaining = db_query(
                "select count(*) from conversation_insights where conversation_id = :c",
                c=insight_id,
            )
            check(
                "erasure removes the conversation's insight and leaves zero orphans",
                erased.status_code == 200 and remaining == 0 and orphan_count == 0,
                f"status={erased.status_code} rows={remaining} orphans={orphan_count}",
            )

        # Insight negatives: a claim race has one winner, and a failed batch
        # never clears labels a previous batch completed.
        race_session = f"race-{stamp}"
        with SessionLocal() as patch_db:
            patch_db.add(
                models.Conversation(
                    website_id=website_id,
                    session_id=race_session,
                    state="bot",
                    last_message_at=settled,
                    created_at=settled,
                    updated_at=settled,
                )
            )
            for role, text_value in (
                ("user", "Can I export a report as PDF?"),
                ("assistant", "Yes, from the Reports page."),
            ):
                patch_db.add(
                    models.ChatMessage(
                        website_id=website_id,
                        session_id=race_session,
                        role=role,
                        message=text_value,
                        answered=True if role == "assistant" else None,
                        created_at=settled,
                        updated_at=settled,
                    )
                )
            patch_db.commit()

        import json as _json
        import threading
        import time as _time
        from types import SimpleNamespace

        race_calls: list[str] = []
        race_results: list[dict] = []
        release = threading.Event()

        class SlowLLM:
            def invoke(self, messages):
                race_calls.append(messages[1].content)
                release.wait(20)
                count = messages[1].content.count("Conversation ")
                return SimpleNamespace(
                    content=_json.dumps(
                        [
                            {
                                "sentiment": "neutral",
                                "resolution": "resolved",
                                "summary": "Export question answered.",
                            }
                            for _ in range(count)
                        ]
                    )
                )

        def first_job():
            with SessionLocal() as thread_db:
                with patch.object(insights, "get_llm", lambda **_: SlowLLM()):
                    race_results.append(
                        insights.run_for_company(thread_db, off_website_company_id)
                    )

        off_website_company_id = site_row.company_id
        thread = threading.Thread(target=first_job)
        thread.start()
        claimed = False
        for _ in range(100):
            if db_query(
                "select count(*) from conversation_insights ci "
                "join conversations c on c.id = ci.conversation_id "
                "where c.session_id = :s and ci.status = 'processing'",
                s=race_session,
            ):
                claimed = True
                break
            _time.sleep(0.05)
        with patch.object(insights, "get_llm", lambda **_: SlowLLM()):
            duplicate = insights.run_for_company(db, off_website_company_id)
        check(
            "an insight claim race has one winner",
            claimed and duplicate["claimed"] == 0 and duplicate["calls"] == 0,
            _json.dumps(duplicate),
        )
        release.set()
        thread.join(20)
        check(
            "the winning job completes the conversation exactly once",
            race_results and race_results[0]["completed"] == 1,
            _json.dumps(race_results[0] if race_results else {}),
        )

        # A failed batch marks its own row failed and leaves completed labels.
        fail_session = f"fail-{stamp}"
        with SessionLocal() as patch_db:
            patch_db.add(
                models.Conversation(
                    website_id=website_id,
                    session_id=fail_session,
                    state="bot",
                    last_message_at=settled,
                    created_at=settled,
                    updated_at=settled,
                )
            )
            for role, text_value in (
                ("user", "Does the API have a sandbox?"),
                ("assistant", "Yes, keys start in test mode."),
            ):
                patch_db.add(
                    models.ChatMessage(
                        website_id=website_id,
                        session_id=fail_session,
                        role=role,
                        message=text_value,
                        answered=True if role == "assistant" else None,
                        created_at=settled,
                        updated_at=settled,
                    )
                )
            patch_db.commit()

        class BrokenLLM:
            def invoke(self, messages):
                raise RuntimeError("provider down")

        with patch.object(insights, "get_llm", lambda **_: BrokenLLM()):
            asyncio.run(
                worker.handle_insights(
                    {"type": "insights", "company_id": str(site_row.company_id)}
                )
            )
        db.expire_all()
        failed_status = db_query(
            "select ci.status from conversation_insights ci "
            "join conversations c on c.id = ci.conversation_id "
            "where c.session_id = :s",
            s=fail_session,
        )
        kept = db_query(
            "select count(*) from conversation_insights ci "
            "join conversations c on c.id = ci.conversation_id "
            "where ci.status = 'completed' and ci.sentiment is not null"
        )
        check(
            "a failed insight batch is marked failed and keeps completed labels",
            failed_status == "failed" and kept >= 1,
            f"status={failed_status} completed_rows={kept}",
        )

        old_session = f"old-{stamp}"
        with SessionLocal() as patch_db:
            old = models.Conversation(
                website_id=website_id,
                session_id=old_session,
                state="bot",
                last_message_at=NOW - timedelta(days=10),
                created_at=NOW - timedelta(days=10),
                updated_at=NOW - timedelta(days=10),
            )
            patch_db.add(old)
            patch_db.commit()
            old_id = str(old.id)
        preview = client.post(
            "/api/privacy/retention",
            json={"retention_days": 1, "dry_run": True},
            headers=headers,
        )
        applied = client.post(
            "/api/privacy/retention",
            json={"retention_days": 1, "dry_run": False},
            headers=headers,
        )
        check(
            "retention previews then applies",
            preview.status_code == 200 and applied.status_code == 200,
            f"{preview.status_code}/{applied.status_code}",
        )
        check(
            "retention removed the expired conversation",
            db_query("select count(*) from conversations where id = :c", c=old_id) == 0,
        )

        # -- 8. All flags off: V3 smoke + digest byte comparison ---------------
        # A second, properly registered company that never opts into any V4
        # feature — the flags-off comparison needs its default settings rows.
        off_email = f"gate5g-off-{stamp}@example.com"
        off_reg = client.post(
            "/api/register",
            json={
                "company_name": f"Gate 5G Digest {stamp}",
                "first_name": "Gate",
                "last_name": "Off",
                "email": off_email,
                "password": password,
            },
        )
        off_tok = client.post(
            "/api/token", json={"email": off_email, "password": password}
        )
        check(
            "the flags-off company registers with default settings",
            off_reg.status_code in (200, 201) and off_tok.status_code == 200,
            off_reg.text[:120],
        )
        off_site_res = client.post(
            "/api/websites/",
            json={"url": "https://digest.example", "site_map_url": "", "name": "digest"},
            headers={"Authorization": f"Bearer {off_tok.json()['access_token']}"},
        )
        off_site = (
            db.query(models.Website)
            .filter(models.Website.id == off_site_res.json()["id"])
            .one()
        )
        off_company = db.query(models.Company).filter(models.Company.id == off_site.company_id).one()
        for session_id, day, hour, question, answer, answered in (
            ("d1", 1, 10, "How do I export my invoices?", "Open Settings, then Invoices.", True),
            ("d2", 2, 9, "Can I get a refund after 30 days?", "Refunds are available for 30 days.", False),
        ):
            for role, text_value, flag in (
                ("user", question, None),
                ("assistant", answer, answered),
            ):
                db.add(
                    models.ChatMessage(
                        website_id=off_site.id,
                        session_id=session_id,
                        role=role,
                        message=text_value,
                        answered=flag,
                        created_at=WINDOW_START + timedelta(days=day, hours=hour),
                        updated_at=WINDOW_START + timedelta(days=day, hours=hour),
                    )
                )
        db.add(
            models.Contact(
                website_id=off_site.id,
                session_id="d2",
                first_name="Gate",
                last_name="Visitor",
                email="gate5g@example.test",
                created_at=WINDOW_START + timedelta(days=2, hours=9),
            )
        )
        db.add(
            models.HandoffRequest(
                website_id=off_site.id,
                session_id="d1",
                status="accepted",
                created_at=WINDOW_START + timedelta(days=1, hours=11),
            )
        )
        db.commit()

        from site_gpt.app.api.setting import company_setting

        check(
            "an untouched company has every V4 flag off",
            insights.enabled(db, off_company.id) is False
            and (company_setting(db, off_company.id, "sitemap_scan_enabled") or "false")
            == "false"
            and (company_setting(db, off_company.id, "session_message_limit") or "0") == "0",
        )

        def refuse(**kwargs):
            raise AssertionError("the insight run called the provider with the flag off")

        with patch.object(insights, "get_llm", refuse):
            off_run = insights.run_for_company(db, off_company.id)
        check(
            "flags-off insights selects nothing, writes nothing, calls nothing",
            off_run.get("status") == "disabled"
            and off_run.get("claimed") == 0
            and off_run.get("calls") == 0,
            json.dumps(off_run),
        )
        check(
            "flags-off company has zero insight rows",
            db_query(
                "select count(*) from conversation_insights ci "
                "join conversations c on c.id = ci.conversation_id "
                "join websites w on w.id = c.website_id "
                "where w.company_id = :c",
                c=str(off_company.id),
            )
            == 0,
        )

        head_digest = digest.build_digest(db, off_company.id, WINDOW_START, WINDOW_END)
        head_json = json.dumps(head_digest, sort_keys=True)
        head_html = digest.render_digest_html(head_digest, off_company.name)
        try:
            v3 = v3_digest(args.v3_src, database, off_company.id, off_company.name)
            check(
                "digest JSON is byte-identical to tag v3 (all flags off)",
                v3["json"] == head_json,
                f"sha256 {sha(head_json)} vs {sha(v3['json'])}",
            )
            check(
                "digest HTML is byte-identical to tag v3 (all flags off)",
                v3["html"] == head_html,
                f"sha256 {sha(head_html)} vs {sha(v3['html'])}",
            )
            check(
                "digest keys are the V3 set",
                sorted(v3["keys"]) == sorted(head_digest),
                str(sorted(head_digest)),
            )
        except Exception as exc:  # noqa: BLE001
            blocked("digest byte comparison against v3", f"{type(exc).__name__}: {exc}")

        smoke_session = f"smoke-{stamp}"
        smoke = client.post(
            "/api/chat",
            json={
                "website_id": str(off_site.id),
                "session_id": smoke_session,
                "question": "hello",
            },
            headers={"Origin": "https://digest.example"},
        )
        if smoke.status_code == 200 and smoke.json().get("answer"):
            check("flags-off chat still answers", True, smoke.json()["answer"][:60])
        else:
            blocked(
                "flags-off chat (live provider)",
                f"{smoke.status_code}: {smoke.text[:160]}",
            )
        smoke_config = client.get(
            "/api/widget-config", params={"website_id": str(off_site.id)}
        )
        check(
            "flags-off widget-config is still exactly 14 keys",
            smoke_config.status_code == 200 and len(smoke_config.json()) == 14,
        )

        off_summary = {
            **digest.build_digest(db, off_company.id, WINDOW_START, WINDOW_END),
            "days": 7,
            "trend": analytics_service.daily_trend(
                db, off_company.id, WINDOW_START, WINDOW_END
            ),
            "funnel": analytics_service.engagement_funnel(
                db, off_company.id, WINDOW_START, WINDOW_END
            ),
            "top_questions": analytics_service.top_questions(
                db, off_company.id, WINDOW_START, WINDOW_END
            ),
        }
        check(
            "flags-off analytics is the V4-1G shape (no outcomes)",
            "outcomes" not in off_summary
            and {"trend", "funnel", "top_questions"} <= set(off_summary),
            str(sorted(off_summary)),
        )
    finally:
        client.close()
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        for name in UPLOADED:
            path = os.path.join("uploads", name)
            if os.path.exists(path):
                os.remove(path)
        db.close()
        engine.dispose()

    failed = [name for name, ok in RESULTS if not ok]
    print()
    print(
        json.dumps(
            {
                "checks": len(RESULTS),
                "passed": len(RESULTS) - len(failed),
                "failed": failed,
                "blocked": [{"name": n, "reason": r[:300]} for n, r in BLOCKED],
            },
            indent=2,
        )
    )
    print(
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed, "
        f"{len(BLOCKED)} blocked"
    )
    if failed:
        print("FAILED:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
