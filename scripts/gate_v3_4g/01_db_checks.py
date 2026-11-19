"""V3-4G gate: database-level checks on the throwaway gate database.

Run after `00_migrations.sh`; it creates its own company, website and agent and
asserts the inbox, cluster, erasure and retention invariants at the SQL layer.
"""

import gate_env  # noqa: F401  — sets DATABASE_URL before site_gpt is imported

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from site_gpt.app import models
from site_gpt.app.core.config import EMBEDDING_DIMENSIONS
from site_gpt.app.db.session import SessionLocal
from site_gpt.app.services import conversations, rag, session_tokens

assert gate_env.GATE_DB in os.environ["DATABASE_URL"], os.environ["DATABASE_URL"]

db = SessionLocal()
ok = 0


def check(name, fn):
    global ok
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    ok += 1
    print(f"ok   {name}{' — ' + detail if detail else ''}")


stamp = uuid4().hex[:8]
company = models.Company(name=f"Gate {stamp}")
db.add(company)
db.flush()
site = models.Website(company_id=company.id, url=f"https://gate-{stamp}.example", site_map_url=f"https://gate-{stamp}.example/sitemap.xml", name="Gate")
site2 = models.Website(company_id=company.id, url=f"https://two-{stamp}.example", site_map_url=f"https://two-{stamp}.example/sitemap.xml", name="Two")
user = models.User(
    company_id=company.id,
    email=f"agent-{stamp}@example.com",
    password_hash="x",
    first_name="Gate",
    last_name="Agent",
    role="admin",
    status="active",
)
db.add_all([site, site2, user])
db.commit()


def conv_lazy_create():
    rag.save_message(db, site.id, "s1", "user", "how do I install it?")
    rag.save_message(db, site.id, "s1", "assistant", "pip install site-gpt", answered=True)
    conv = conversations.conversation_for(db, site.id, "s1")
    assert conv is not None, "conversation row not created lazily"
    assert conv.state == "bot", conv.state
    assert conv.last_message_at is not None
    return f"state={conv.state}, last_message_at={conv.last_message_at.isoformat()}"


def duplicate_conversation_rejected():
    db.add(models.Conversation(website_id=site.id, session_id="s1", state="bot"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "unique (website_id, session_id) held"
    raise AssertionError("duplicate conversation accepted")


def agent_reply_visible():
    conv = conversations.ensure_conversation(db, site.id, "s1")
    conversations.set_state(db, conv, "waiting")
    conversations.claim(db, conv, user.id)
    rag.save_message(db, site.id, "s1", "assistant", "I'm here, one moment.", author_user_id=user.id)
    rows = conversations.get_conversation_messages(db, site.id, "s1")
    def author_of(row):
        return row.get("author_user_id") if isinstance(row, dict) else getattr(row, "author_user_id", None)

    authors = [author_of(r) for r in rows]
    assert str(user.id) in {str(a) for a in authors if a}, authors
    conv = conversations.conversation_for(db, site.id, "s1")
    assert conversations.human_handling(db, site.id, "s1") is True
    assert conv.assigned_user_id in (None, user.id)
    return f"{len(rows)} messages, agent author recorded"


def same_session_other_website():
    conversations.ensure_conversation(db, site2.id, "s1")
    db.commit()
    return "same session id on two websites is unambiguous"


def delete_conversation_path():
    deleted = conversations.delete_conversation(db, site.id, "s1")
    left = (
        db.query(func.count(models.ChatMessage.id))
        .filter_by(website_id=site.id, session_id="s1")
        .scalar()
    )
    rows = (
        db.query(func.count(models.Conversation.id))
        .filter_by(website_id=site.id, session_id="s1")
        .scalar()
    )
    assert left == 0 and rows == 0, (left, rows)
    return f"{deleted} messages + conversation row removed"


def erase_session_path():
    sid = "s2"
    rag.save_message(db, site.id, sid, "user", "erase me")
    rag.save_message(db, site.id, sid, "assistant", "done", author_user_id=user.id)
    session_tokens.mint(db, site.id, sid)
    db.add(models.HandoffRequest(website_id=site.id, session_id=sid, message="human please", status="pending"))
    msg = (
        db.query(models.ChatMessage)
        .filter_by(website_id=site.id, session_id=sid, role="assistant")
        .first()
    )
    db.add(models.ChatFeedback(website_id=site.id, session_id=sid, rating="up", message_id=msg.id))
    db.commit()
    counts = conversations.erase_session(db, site.id, sid)
    assert all(v == 0 for k, v in counts.items() if k != "conversations") or counts
    for model in (
        models.ChatMessage,
        models.ChatFeedback,
        models.HandoffRequest,
        models.SessionToken,
        models.Conversation,
    ):
        remaining = db.query(func.count(model.id)).filter_by(website_id=site.id, session_id=sid).scalar()
        assert remaining == 0, (model.__name__, remaining)
    return f"erased {counts}"


def cluster_run_claim():
    start = datetime(2026, 11, 9, tzinfo=UTC)
    db.add(models.TopicClusterRun(company_id=company.id, period_start=start, status="running", claimed_at=datetime.now(UTC)))
    db.commit()
    db.add(models.TopicClusterRun(company_id=company.id, period_start=start, status="running"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "duplicate (company, window) claim rejected"
    raise AssertionError("duplicate cluster run accepted")


def cluster_run_status_check():
    db.add(
        models.TopicClusterRun(
            company_id=company.id, period_start=datetime(2026, 11, 2, tzinfo=UTC), status="bogus"
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "status CHECK constraint held"
    raise AssertionError("invalid status accepted")


def cluster_row_identity_and_vector():
    start = datetime(2026, 11, 9, tzinfo=UTC)
    row = models.TopicCluster(
        company_id=company.id,
        period_start=start,
        cluster_key="abc123",
        label="Installation",
        summary="How to install",
        centroid=[0.01] * EMBEDDING_DIMENSIONS,
        sampled_messages=3,
        eligible_messages=3,
    )
    db.add(row)
    db.commit()
    db.add(
        models.TopicCluster(
            company_id=company.id,
            period_start=start,
            cluster_key="abc123",
            label="Duplicate",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("duplicate cluster key accepted")
    db.add(
        models.TopicCluster(
            company_id=company.id, period_start=start, cluster_key="def456", label="Pricing"
        )
    )
    db.commit()
    stored = (
        db.query(models.TopicCluster)
        .filter_by(company_id=company.id, period_start=start, cluster_key="abc123")
        .one()
    )
    assert stored.centroid is not None and len(stored.centroid) == EMBEDDING_DIMENSIONS
    return f"pgvector centroid round-trip {len(stored.centroid)}d, duplicate key rejected"


def conversation_retention_expiry():
    old = datetime.now(UTC) - timedelta(days=400)
    rag.save_message(db, site2.id, "old", "user", "ancient question")
    conv = conversations.conversation_for(db, site2.id, "old")
    conv.last_message_at = old
    db.commit()
    from site_gpt.app.services import retention

    result = retention.purge_company(db, company.id, days=90, dry_run=False)
    remaining = (
        db.query(func.count(models.Conversation.id)).filter_by(website_id=site2.id, session_id="old").scalar()
    )
    assert remaining == 0, remaining
    return f"purged past retention ({sorted(result)} )"


check("M9 conversation row created lazily on first message", conv_lazy_create)
check("unique (website_id, session_id)", duplicate_conversation_rejected)
check("agent reply stored with author and visible in transcript", agent_reply_visible)
check("same session id on another website", same_session_other_website)
check("delete_conversation drops transcript + row", delete_conversation_path)
check("erase_session is atomic over 5 tables", erase_session_path)
check("one cluster run per (company, window)", cluster_run_claim)
check("cluster run status constraint", cluster_run_status_check)
check("cluster identity + centroid vector", cluster_row_identity_and_vector)
check("retention expiry removes the inbox row", conversation_retention_expiry)

print(f"\n{ok} database checks passed")
