"""V4-4G gate checks for conversation insights (V4 F2), on a real database.

Run against a throwaway Postgres database already migrated to
`f33497bc1ecd`:

    DATABASE_URL=... uv run python scripts/gate_v4_4g/gate.py \
        --v3-src /tmp/gate_v4_4g_v3 --one-g-src /tmp/gate_v4_4g_1g

What it proves, in the plan's gate order (all reads/writes go through the real
services, the real models and Postgres — only the chat model is stubbed):

1. **Flag off**: no insight row, no provider call (a stub that raises proves it),
   the scheduler queues nothing, the digest JSON + HTML are byte-identical to the
   code at tag `v3`, and the analytics summary is byte-identical to the code at
   the V4-1G commit and carries no `outcomes` key.
2. **Flag on, stubbed provider**: one run classifies a settled conversation; a
   second job running while the first holds its claim claims nothing and spends
   nothing; a duplicate job after completion is a no-op; a failed batch is
   retried on the next job and reuses its row.
3. **Live provider**: one real classification attempt, recorded as evidence when
   it works and as **blocked** (with the logged reason) when the provider is not
   reachable — the blocked-item rule, not a gate pass.
4. **Cascades**: `erase_session`, `delete_conversation` and `retention.
   purge_company` each remove exactly their conversation's insight and leave
   **zero** orphan rows.

The script never touches the dev database: the caller creates the throwaway one
and drops it afterwards. Exit status is non-zero when a stubbed check fails; a
provider-blocked live check does not fail the run.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from site_gpt.app import models, worker
from site_gpt.app.services import (
    analytics,
    conversations,
    digest,
    insights,
    retention,
)

# The digest window of the V4-1G gate fixture, so the payloads can be compared
# to the code that produced that record. Pinned, never "now".
WINDOW_START = datetime(2026, 11, 2, tzinfo=UTC)
WINDOW_END = datetime(2026, 11, 9, tzinfo=UTC)

# Insight eligibility is measured from the wall clock (settle delay), so the
# insight fixture is relative — and old enough to be settled.
NOW = datetime.now(UTC)
SETTLED = NOW - timedelta(hours=2)

# Computed in a subprocess from an older checkout so the comparison is
# code-to-code, not a copy (the V3-3G / V4-1G technique).
RUNNER = r"""
import json, os, sys, uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import site_gpt
from site_gpt.app.services import digest

engine = create_engine(os.environ["DATABASE_URL"])
db = sessionmaker(bind=engine)()
start = datetime.fromisoformat(os.environ["WINDOW_START"])
end = datetime.fromisoformat(os.environ["WINDOW_END"])
company = uuid.UUID(os.environ["COMPANY_ID"])
name = os.environ["COMPANY_NAME"]
mode = os.environ["MODE"]

if mode == "digest":
    data = digest.build_digest(db, company, start, end)
    payload = {
        "keys": sorted(data),
        "json": json.dumps(data, sort_keys=True),
        "html": digest.render_digest_html(data, name),
    }
else:
    from site_gpt.app.services import analytics

    data = {
        **digest.build_digest(db, company, start, end),
        "days": 7,
        "trend": analytics.daily_trend(db, company, start, end),
        "funnel": analytics.engagement_funnel(db, company, start, end),
        "top_questions": analytics.top_questions(db, company, start, end),
    }
    payload = {"keys": sorted(data), "json": json.dumps(data, sort_keys=True, default=str)}

payload["module"] = site_gpt.__file__
print(json.dumps(payload))
"""

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    return bool(ok)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def external(src_root: Path, mode: str, database: str, company_id, name: str) -> dict:
    """Run one older checkout's code against the same rows and return its output."""
    env = {
        **os.environ,
        "PYTHONPATH": str(src_root / "src"),
        "MODE": mode,
        "DATABASE_URL": database,
        "COMPANY_ID": str(company_id),
        "COMPANY_NAME": name,
        "WINDOW_START": WINDOW_START.isoformat(),
        "WINDOW_END": WINDOW_END.isoformat(),
    }
    finished = subprocess.run(
        [sys.executable, "-c", RUNNER],
        cwd=str(src_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if finished.returncode != 0:
        raise RuntimeError(
            f"{src_root} ({mode}) failed:\n{finished.stderr[-3000:]}"
        )
    return json.loads(finished.stdout.strip().splitlines()[-1])


def seed_company(db, name: str, site: str):
    company = models.Company(name=name)
    db.add(company)
    db.commit()
    website = models.Website(
        company_id=company.id,
        name=site,
        url=f"https://{site}.test",
        site_map_url="",
    )
    db.add(website)
    db.commit()
    return company, website


def message(db, website, session_id, role, body, when, answered=None):
    db.add(
        models.ChatMessage(
            website_id=website.id,
            session_id=session_id,
            role=role,
            message=body,
            answered=answered,
            created_at=when,
            updated_at=when,
        )
    )
    db.commit()


def conversation(db, website, session_id, last, state="bot", created=None):
    row = models.Conversation(
        website_id=website.id,
        session_id=session_id,
        state=state,
        last_message_at=last,
        created_at=created or last,
        updated_at=created or last,
    )
    db.add(row)
    db.commit()
    return row


def insight_row(db, conversation_row, summary="Visitor asked about the product."):
    row = models.ConversationInsight(
        conversation_id=conversation_row.id,
        status="completed",
        sentiment="frustrated",
        resolution="escalated",
        summary=summary,
    )
    db.add(row)
    db.commit()
    return row


def reply_for(human: str, sentiment="positive", resolution="resolved") -> str:
    """One classification object per `Conversation N:` block in the prompt."""
    count = human.count("Conversation ")
    return json.dumps(
        [
            {
                "sentiment": sentiment,
                "resolution": resolution,
                "summary": "Visitor asked about pricing and the answer satisfied them.",
            }
            for _ in range(count)
        ]
    )


class FakeLLM:
    def __init__(self, calls, *, reply=None, error=None, gate=None):
        self.calls = calls
        self.reply = reply or reply_for
        self.error = error
        self.gate = gate

    def invoke(self, messages):
        self.calls.append(messages[1].content)
        if self.gate is not None:
            self.gate.wait(20)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.reply(messages[1].content))


def finding(db, conversation_id):
    return (
        db.query(models.ConversationInsight)
        .filter(models.ConversationInsight.conversation_id == conversation_id)
        .one_or_none()
    )


def orphans(db) -> int:
    return db.execute(
        text(
            "SELECT count(*) FROM conversation_insights ci "
            "LEFT JOIN conversations c ON c.id = ci.conversation_id "
            "WHERE c.id IS NULL"
        )
    ).scalar_one()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3-src", required=True, type=Path)
    parser.add_argument("--one-g-src", required=True, type=Path)
    args = parser.parse_args()

    database = os.environ["DATABASE_URL"]
    engine = create_engine(database)
    Session = sessionmaker(bind=engine)
    db = Session()

    # -- Fixture for the digest/analytics comparison (V4-1G's shape) ----------
    fixture, site_a = seed_company(db, "Gate 4G Co", "gate-4g")
    message(db, site_a, "s1", "user", "How do I export my invoices?",
            WINDOW_START + timedelta(days=1, hours=10))
    message(db, site_a, "s1", "assistant",
            "Open Settings, then Invoices, and press Export.",
            WINDOW_START + timedelta(days=1, hours=10, seconds=4), answered=True)
    message(db, site_a, "s1", "user", "Thanks!",
            WINDOW_START + timedelta(days=1, hours=10, minutes=1))
    message(db, site_a, "s1", "assistant", "You're welcome.",
            WINDOW_START + timedelta(days=1, hours=10, minutes=1, seconds=3),
            answered=True)
    message(db, site_a, "s2", "user", "Can I get a refund after 30 days?",
            WINDOW_START + timedelta(days=2, hours=9))
    message(db, site_a, "s2", "assistant", "Refunds are available for 30 days.",
            WINDOW_START + timedelta(days=2, hours=9, seconds=6), answered=False)
    conversation(db, site_a, "s1",
                 WINDOW_START + timedelta(days=1, hours=10, minutes=1, seconds=3),
                 state="human")
    conversation(db, site_a, "s2",
                 WINDOW_START + timedelta(days=2, hours=9, seconds=6), state="bot")
    db.add(
        models.Contact(
            website_id=site_a.id,
            session_id="s2",
            first_name="Gate",
            last_name="Visitor",
            email="gate4g@example.test",
            created_at=WINDOW_START + timedelta(days=2, hours=9),
        )
    )
    db.add(
        models.ChatFeedback(
            website_id=site_a.id,
            session_id="s1",
            rating="up",
            created_at=WINDOW_START + timedelta(days=3, hours=12),
        )
    )
    db.add(
        models.HandoffRequest(
            website_id=site_a.id,
            session_id="s1",
            status="accepted",
            created_at=WINDOW_START + timedelta(days=1, hours=10, seconds=20),
        )
    )
    db.commit()

    # -- 1. Flag off --------------------------------------------------------
    check("flag off by default", insights.enabled(db, fixture.id) is False)

    def refuse(**kwargs):
        raise AssertionError("the insight run called the provider with the flag off")

    with patch.object(insights, "get_llm", refuse):
        off = insights.run_for_company(db, fixture.id)
    check(
        "flag off: the run selects nothing, writes nothing, calls nothing",
        off["status"] == "disabled" and off["claimed"] == 0 and off["calls"] == 0,
        json.dumps(off),
    )
    check(
        "flag off: zero insight rows for the fixture company",
        db.query(models.ConversationInsight)
        .join(
            models.Conversation,
            models.Conversation.id == models.ConversationInsight.conversation_id,
        )
        .filter(models.Conversation.website_id == site_a.id)
        .count()
        == 0,
    )

    with patch.object(worker, "enqueue_job", new=AsyncMock()) as queued:
        scheduled = asyncio.run(worker.enqueue_due_insights())
    check(
        "flag off: the scheduler queues no insights job for the company",
        str(fixture.id) not in scheduled and queued.await_count == 0,
        f"queued={queued.await_count}",
    )

    # Digest, HEAD (flag off) against tag v3 code.
    head_digest = digest.build_digest(db, fixture.id, WINDOW_START, WINDOW_END)
    head_digest_json = json.dumps(head_digest, sort_keys=True)
    head_digest_html = digest.render_digest_html(head_digest, "Gate 4G Co")
    v3 = external(args.v3_src, "digest", database, fixture.id, "Gate 4G Co")
    check(
        "digest JSON byte-identical to v3",
        v3["json"] == head_digest_json,
        f"sha256 {sha(head_digest_json)} vs {sha(v3['json'])}; "
        f"module {v3['module']}",
    )
    check(
        "digest HTML byte-identical to v3",
        v3["html"] == head_digest_html,
        f"sha256 {sha(head_digest_html)} vs {sha(v3['html'])}",
    )
    check(
        "digest keys are the V3 set (no V4 key leaked)",
        sorted(v3["keys"]) == sorted(head_digest),
        str(sorted(head_digest)),
    )

    # Analytics summary: the admin route's payload, HEAD (flag off) against the
    # V4-1G commit, same pinned window and rows.
    head_summary = {
        **digest.build_digest(db, fixture.id, WINDOW_START, WINDOW_END),
        "days": 7,
        "trend": analytics.daily_trend(db, fixture.id, WINDOW_START, WINDOW_END),
        "funnel": analytics.engagement_funnel(
            db, fixture.id, WINDOW_START, WINDOW_END
        ),
        "top_questions": analytics.top_questions(
            db, fixture.id, WINDOW_START, WINDOW_END
        ),
    }
    head_summary_json = json.dumps(head_summary, sort_keys=True, default=str)
    one_g = external(args.one_g_src, "analytics", database, fixture.id, "Gate 4G Co")
    check(
        "analytics summary byte-identical to V4-1G (flag off)",
        one_g["json"] == head_summary_json,
        f"sha256 {sha(head_summary_json)} vs {sha(one_g['json'])}; "
        f"module {one_g['module']}",
    )
    check(
        "analytics summary carries no outcomes key when the flag is off",
        "outcomes" not in head_summary and one_g["keys"] == sorted(head_summary),
        str(sorted(head_summary)),
    )
    print(
        "      funnel:",
        {row["stage"]: row["sessions"] for row in head_summary["funnel"]},
        "| trend rows:",
        len(head_summary["trend"]),
        "| top questions:",
        len(head_summary["top_questions"]),
    )

    # -- 2. Flag on, stubbed provider ---------------------------------------
    company, site = seed_company(db, "Gate 4G Insights Co", "gate-4g-insights")
    db.add(
        models.Setting(
            company_id=company.id,
            key="conversation_insights_enabled",
            value="true",
        )
    )
    db.commit()
    check("flag on after the opt-in row", insights.enabled(db, company.id) is True)

    # A settled conversation is what a run may classify.
    message(db, site, "s3", "user", "My invoice PDF will not download.",
            SETTLED - timedelta(minutes=4))
    message(db, site, "s3", "assistant",
            "Try the Download button on the invoice row.", SETTLED, answered=True)
    raced = conversation(db, site, "s3", SETTLED)

    release = threading.Event()
    calls: list[str] = []
    race_result: list[dict] = []

    def first_job():
        thread_db = Session()
        try:
            with patch.object(
                insights, "get_llm", lambda **_: FakeLLM(calls, gate=release)
            ):
                race_result.append(insights.run_for_company(thread_db, company.id))
        finally:
            thread_db.close()

    worker_thread = threading.Thread(target=first_job)
    worker_thread.start()
    # The job blocks inside its provider call; wait for its committed claim row.
    claimed = None
    for _ in range(100):
        fresh = finding(db, raced.id)
        if fresh is not None and fresh.status == "processing":
            claimed = fresh
            break
        time.sleep(0.05)
    check(
        "the claim is a single `processing` row on the real database",
        claimed is not None and claimed.status == "processing",
    )

    no_calls: list[str] = []
    with patch.object(insights, "get_llm", lambda **_: FakeLLM(no_calls)):
        duplicate = insights.run_for_company(db, company.id)
    check(
        "a duplicate job while the claim is live claims nothing and calls nothing",
        duplicate["claimed"] == 0 and duplicate["calls"] == 0 and no_calls == [],
        json.dumps(duplicate),
    )

    release.set()
    worker_thread.join(20)
    check(
        "the first job completed exactly one conversation",
        race_result and race_result[0]["completed"] == 1 and len(calls) == 1,
        json.dumps(race_result[0] if race_result else {}),
    )
    db.expire_all()
    row = finding(db, raced.id)
    check(
        "the classified row holds only bounded derived values",
        row is not None
        and row.status == "completed"
        and row.sentiment == "positive"
        and row.resolution == "resolved"
        and 0 < len(row.summary or "") <= insights.MAX_SUMMARY_LENGTH
        and "invoice" not in (row.summary or "").lower(),
        f"status={row.status if row else None} sentiment={row.sentiment if row else None} "
        f"resolution={row.resolution if row else None} model={row.model if row else None}",
    )

    # Duplicate job after completion: the job path, no work, no spend.
    after_calls: list[str] = []
    with patch.object(insights, "get_llm", lambda **_: FakeLLM(after_calls)):
        asyncio.run(worker.handle_insights({"type": "insights", "company_id": str(company.id)}))
    check(
        "a repeated job after completion does no work and spends nothing",
        after_calls == [] and finding(db, raced.id).id == row.id,
    )

    # Failed batch, retried by the next job on the same row.
    message(db, site, "s4", "user", "Where is my order?", SETTLED - timedelta(minutes=3))
    message(db, site, "s4", "assistant", "It ships tomorrow.", SETTLED, answered=True)
    retried = conversation(db, site, "s4", SETTLED)
    failing = FakeLLM([], error=RuntimeError("provider down"))
    with patch.object(insights, "get_llm", lambda **_: failing):
        asyncio.run(worker.handle_insights({"type": "insights", "company_id": str(company.id)}))
    db.expire_all()
    failed_row = finding(db, retried.id)
    check(
        "a provider failure marks the batch failed instead of raising",
        failed_row is not None
        and failed_row.status == "failed"
        and failed_row.sentiment is None,
        f"status={failed_row.status if failed_row else None}",
    )

    retry_calls: list[str] = []
    with patch.object(insights, "get_llm", lambda **_: FakeLLM(retry_calls)):
        asyncio.run(worker.handle_insights({"type": "insights", "company_id": str(company.id)}))
    db.expire_all()
    retried_row = finding(db, retried.id)
    check(
        "the next job retries the failed row in place and completes it",
        retried_row is not None
        and retried_row.id == failed_row.id
        and retried_row.status == "completed"
        and len(retry_calls) == 1,
        f"status={retried_row.status if retried_row else None} calls={len(retry_calls)}",
    )

    # -- 3. Live provider (blocked-item rule) -------------------------------
    message(db, site, "s5", "user", "Do you support SSO on the team plan?",
            SETTLED - timedelta(minutes=2))
    message(db, site, "s5", "assistant", "Yes, SSO is included on the team plan.",
            SETTLED, answered=True)
    live = conversation(db, site, "s5", SETTLED)

    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    logging.getLogger("site_gpt.app.services.insights").addHandler(handler)
    try:
        asyncio.run(
            worker.handle_insights({"type": "insights", "company_id": str(company.id)})
        )
    finally:
        logging.getLogger("site_gpt.app.services.insights").removeHandler(handler)
    db.expire_all()
    live_row = finding(db, live.id)
    if live_row is not None and live_row.status == "completed":
        print(
            f"      live provider: completed — sentiment={live_row.sentiment} "
            f"resolution={live_row.resolution} model={live_row.model}"
        )
    else:
        print(
            "      live provider: BLOCKED — "
            f"status={live_row.status if live_row else None}; "
            f"{(records[-1] if records else 'no logged reason')[:300]}"
        )

    # -- 4. Erasure / retention cascade on the real database ----------------
    cascade = {}
    for session_id, when in (
        ("c1", NOW - timedelta(hours=5)),
        ("c2", NOW - timedelta(hours=6)),
        ("c3", NOW - timedelta(hours=7)),
    ):
        message(db, site, session_id, "user", f"Question from {session_id}?", when)
        cascade[session_id] = conversation(db, site, session_id, when)
        insight_row(
            db, cascade[session_id], summary=f"Cascade check for {session_id}."
        )
    # Hold ids, not ORM instances: `erase_session` deletes the row and a later
    # attribute access on an expired instance would raise.
    cascade_ids = {name: row.id for name, row in cascade.items()}

    expired_conv = conversation(
        db, site, "c4", NOW - timedelta(days=10), created=NOW - timedelta(days=10)
    )
    insight_row(db, expired_conv, summary="Expired conversation.")
    fresh_conv = conversation(db, site, "c5", NOW - timedelta(hours=1))
    insight_row(db, fresh_conv, summary="Fresh conversation.")
    expired_id, fresh_id = expired_conv.id, fresh_conv.id

    total_before = (
        db.query(models.ConversationInsight)
        .join(
            models.Conversation,
            models.Conversation.id == models.ConversationInsight.conversation_id,
        )
        .filter(models.Conversation.website_id == site.id)
        .count()
    )

    conversations.erase_session(db, site.id, "c2")
    db.expire_all()
    check(
        "erase_session removes the erased session's insight and keeps a neighbour's",
        finding(db, cascade_ids["c2"]) is None
        and finding(db, cascade_ids["c1"]) is not None,
        f"kept={finding(db, cascade_ids['c1']) is not None} "
        f"gone={finding(db, cascade_ids['c2']) is None}",
    )

    conversations.delete_conversation(db, site.id, "c3")
    db.expire_all()
    check(
        "delete_conversation leaves no insight for that conversation",
        finding(db, cascade_ids["c3"]) is None,
    )

    purged = retention.purge_company(db, company.id, days=1, dry_run=False, now=NOW)
    db.expire_all()
    check(
        "retention expiry removes the expired conversation's insight and keeps the fresh one",
        purged["deleted"]["conversations"] >= 1
        and finding(db, expired_id) is None
        and finding(db, fresh_id) is not None,
        f"conversations deleted={purged['deleted']['conversations']}",
    )
    check(
        "zero orphan insight rows after every cascade",
        orphans(db) == 0,
        f"orphans={orphans(db)}",
    )

    print(
        json.dumps(
            {
                "cascade": {
                    "insights_before": total_before,
                    "insights_after": db.query(models.ConversationInsight).count(),
                    "conversations_deleted_by_retention": purged["deleted"][
                        "conversations"
                    ],
                    "orphans": orphans(db),
                },
                "checks": [{"name": n, "ok": ok} for n, ok, _ in CHECKS],
            },
            indent=2,
        )
    )

    failed = [name for name, ok, _ in CHECKS if not ok]
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        print("FAILED:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
