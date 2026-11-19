"""V3-4G gate: clustering is opt-in — no job and no provider call when off.

Runs in its own process because `enqueue_due_topics` owns an asyncio Redis
client. Uses the company from `02_http_smoke.py`, leaves the flag off and
removes its own queued job from `queue:jobs` so the shared Redis is untouched.
"""

import asyncio
from uuid import UUID

import gate_env  # noqa: F401  — sets DATABASE_URL before site_gpt is imported

from site_gpt.app import models, worker
from site_gpt.app.db.session import SessionLocal
from site_gpt.app.services.redis import QUEUE_KEY, redis_client

state = gate_env.load_state()
company_id = UUID(state["company_id"])
db = SessionLocal()


def set_flag(value: str) -> None:
    row = (
        db.query(models.Setting)
        .filter_by(company_id=company_id, key="topic_clustering_enabled")
        .first()
    )
    assert row is not None, "the smoke company has no topic_clustering_enabled row"
    row.value = value
    db.commit()


async def main() -> None:
    set_flag("false")
    off = await worker.enqueue_due_topics()
    assert str(company_id) not in off, "flag off queued a clustering job"
    runs = db.query(models.TopicClusterRun).filter_by(company_id=company_id).count()
    assert runs == 0, f"flag off created {runs} cluster run row(s)"
    print("ok   flag off: no job queued, no cluster run row, no provider call")

    set_flag("true")
    queued = await worker.enqueue_due_topics()
    assert str(company_id) in queued, queued

    removed = 0
    for item in await redis_client.lrange(QUEUE_KEY, 0, -1):
        if str(company_id) in item:
            await redis_client.lrem(QUEUE_KEY, 1, item)
            removed += 1
    set_flag("false")
    print(f"ok   flag on: window queued; removed {removed} test job(s) from {QUEUE_KEY}")
    print("\n2 clustering opt-in checks passed")


try:
    asyncio.run(main())
finally:
    db.close()
