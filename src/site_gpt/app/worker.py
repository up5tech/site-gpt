import asyncio
import json
import os
import time
import traceback
from datetime import datetime, timedelta, UTC
from uuid import UUID

from site_gpt.app.services.crawler import crawl_website
from site_gpt.app.services.ingest import ingest_document, ingest_extra_document
from site_gpt.app.services.ingest_claim import STUCK_INGEST_AFTER
from site_gpt.app.services.parse import extract_text_from_file
from site_gpt.app.services.redis import redis_client, enqueue_job
from site_gpt.app.core.config import (
    CRAWL_REFRESH_HOURS,
    DELIVERY_CHECK_SECONDS,
    DELIVERY_RETENTION_CHECK_SECONDS,
    DIGEST_CHECK_SECONDS,
    RETENTION_CHECK_SECONDS,
    TOPIC_CLUSTER_INTERVAL_SECONDS,
    DIGEST_ENABLED,
    DIGEST_HOUR,
)
from site_gpt.app.services import company_settings, digest, retention, topics
from site_gpt.app.services.integrations import (
    process_due_deliveries,
    purge_deliveries,
)
from site_gpt.app.db.session import SessionLocal
from site_gpt.app import models

# The stale-row window is defined in services/ingest_claim.py so the API's
# atomic claim and this recovery loop can never disagree about when an ingest is
# dead; it is re-exported here for callers that already import it from `worker`.


def _is_stuck(
    website,
    *,
    now: datetime | None = None,
    threshold: timedelta = STUCK_INGEST_AFTER,
) -> bool:
    """Whether a website row is an orphaned `processing` ingest.

    `websites.updated_at` is bumped when `handle_ingest` flips the row to
    `processing` and is not touched again until it completes or fails, so it
    marks when the ingest started.
    """
    if website.ingest_status != "processing":
        return False

    started_at = website.updated_at
    if started_at is None:
        return True

    now = now or datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - started_at > threshold


def recover_stuck_ingests(
    db,
    *,
    now: datetime | None = None,
    threshold: timedelta = STUCK_INGEST_AFTER,
) -> list[str]:
    """Mark orphaned `processing` ingests as `failed`; return their ids.

    The caller re-enqueues them, so the knowledge base catches up instead of
    silently serving stale content forever.
    """
    now = now or datetime.now(UTC)
    candidates = (
        db.query(models.Website)
        .filter(models.Website.ingest_status == "processing")
        .all()
    )

    recovered: list[str] = []
    for website in candidates:
        if _is_stuck(website, now=now, threshold=threshold):
            website.ingest_status = "failed"
            recovered.append(str(website.id))

    if recovered:
        db.commit()
    return recovered


async def requeue_stuck_ingests(
    *, now: datetime | None = None, threshold: timedelta = STUCK_INGEST_AFTER
) -> list[str]:
    """Recover stuck ingests and re-enqueue them. Returns the website ids."""
    db = SessionLocal()
    try:
        website_ids = recover_stuck_ingests(db, now=now, threshold=threshold)
        for website_id in website_ids:
            try:
                await enqueue_job({"type": "ingest", "website_id": website_id})
            except Exception as e:
                # One Redis hiccup must not skip the remaining recoveries.
                print(
                    f"[worker] could not re-queue website {website_id}: {e}"
                )
                continue
            print(f"[worker] recovered stuck ingest for website {website_id}")
        return website_ids
    finally:
        db.close()


async def worker():
    print("Worker started, waiting for jobs...")
    # Pick up ingests orphaned by a previous process before consuming jobs.
    try:
        await requeue_stuck_ingests()
    except Exception as e:
        print(f"[worker] stuck-ingest recovery failed: {e}")
    # Periodic re-crawl scheduler (keeps knowledge fresh).
    asyncio.create_task(scheduler_loop())
    # Weekly digest scheduler. Off unless DIGEST_ENABLED is set, so a deployment
    # that never opted in runs exactly the V1 loops.
    if DIGEST_ENABLED:
        asyncio.create_task(digest_loop())
    # Retries for outbound integration deliveries that failed or were queued
    # while the endpoint was down. Always on: an event must not be lost because
    # the receiver had a bad minute.
    asyncio.create_task(delivery_loop())
    # Daily retention purge for companies that set a policy. Queued rather than
    # run inline so a large delete does not stall the job loop.
    asyncio.create_task(retention_loop())
    # Topic clustering for companies that opted in (`topic_clustering_enabled`).
    # The loop only reads settings, so with nobody opted in it makes no provider
    # call and no job is ever queued.
    asyncio.create_task(topic_loop())
    while True:
        try:
            _, job = await redis_client.brpop("queue:jobs")  # type: ignore
        except Exception as e:
            print(f"[worker] redis error: {e}")
            await asyncio.sleep(2)
            continue

        data = json.loads(job)
        print("Processing:", data)

        if data.get("type") == "ingest":
            try:
                await handle_ingest(data)
            except Exception as e:
                print(f"[worker] ingest failed: {e}")
                traceback.print_exc()
        elif data.get("type") == "digest":
            try:
                await handle_digest(data)
            except Exception as e:
                print(f"[worker] digest failed: {e}")
                traceback.print_exc()
        elif data.get("type") == "retention":
            try:
                await handle_retention(data)
            except Exception as e:
                print(f"[worker] retention purge failed: {e}")
                traceback.print_exc()
        elif data.get("type") == "topic_clusters":
            try:
                await handle_topic_clusters(data)
            except Exception as e:
                print(f"[worker] topic clustering failed: {e}")
                traceback.print_exc()


async def handle_ingest(data):
    if not data.get("website_id"):
        print("Missing website_id")
        return

    db = SessionLocal()
    try:
        website = (
            db.query(models.Website)
            .filter(models.Website.id == data["website_id"])
            .first()
        )
        if not website:
            print("Website not found")
            return

        # A disabled website must not be crawled or embedded: it is queued
        # before the owner disables it, or by the refresh scheduler.
        if (website.status or "").strip().lower() != "active":
            print(f"[worker] skipping ingest for disabled website {website.id}")
            return

        website.ingest_status = "processing"
        db.commit()

        # ---- 1. Crawl site pages and upsert documents (avoid duplicates) ----
        docs = crawl_website(db, website.id)
        crawled_urls: set[str] = set()
        for doc in docs:
            url = doc.metadata["source"]
            title = doc.metadata.get("title", url)
            text = doc.page_content

            crawled_urls.add(url)
            existing = (
                db.query(models.Document)
                .filter(
                    models.Document.website_id == website.id,
                    models.Document.url == url,
                )
                .first()
            )
            if existing:
                existing.title = title
                existing.content = text
                document = existing
            else:
                document = models.Document(
                    title=title,
                    content=text,
                    url=url,
                    website_id=website.id,
                )
                db.add(document)
            db.commit()
            db.refresh(document)
            ingest_document(db, document.id, document.content)

        # ---- 1b. Remove chunks for pages no longer present / not crawled ----
        # Guard: only prune when we actually crawled something, so a full
        # network outage can't wipe a website's entire knowledge base.
        if crawled_urls:
            stale = (
                db.query(models.Document)
                .filter(
                    models.Document.website_id == website.id,
                    ~models.Document.url.in_(crawled_urls),
                )
                .all()
            )
            for d in stale:
                print(f"[worker] removing stale document {d.url}")
                db.delete(d)
            db.commit()

        # ---- 2. Ingest extra documents (text + uploaded file contents) ----
        # Include both website-linked docs and company-wide docs (website_id IS NULL),
        # matching the scope used by rag.search().
        extra_documents = (
            db.query(models.ExtraDocument)
            .filter(
                (models.ExtraDocument.website_id == website.id)
                | (
                    (models.ExtraDocument.website_id == None)
                    & (models.ExtraDocument.company_id == website.company_id)
                )
            )
            .all()
        )
        for extra_document in extra_documents:
            text_parts: list[str] = []
            if extra_document.content and extra_document.content.strip():
                text_parts.append(extra_document.content)

            attachments = (
                db.query(models.Attachment)
                .filter(models.Attachment.extra_document_id == extra_document.id)
                .all()
            )
            for att in attachments:
                file_path = os.path.join("uploads", att.file_url)
                try:
                    file_text = extract_text_from_file(file_path, att.filename)
                    if file_text and file_text.strip():
                        text_parts.append(file_text)
                except Exception as e:
                    print(f"[worker] failed to parse attachment {att.filename}: {e}")

            combined = "\n\n".join(p for p in text_parts if p and p.strip())
            if combined:
                ingest_extra_document(db, extra_document.id, combined)
            else:
                # No usable content: drop any previously embedded chunks so
                # stale knowledge from this extra document doesn't surface.
                db.query(models.Embedding).filter(
                    models.Embedding.extra_document_id == extra_document.id
                ).delete()
                db.commit()

        website.ingest_status = "completed"
        db.commit()
        print(f"Ingest completed for website {website.id}")
    except Exception as e:
        db.rollback()
        try:
            website = (
                db.query(models.Website)
                .filter(models.Website.id == data["website_id"])
                .first()
            )
            if website:
                website.ingest_status = "failed"
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


async def handle_retention(data):
    """Purge one company's expired rows.

    `dry_run` exists for the same reason the API has it: a policy change should be
    previewable, and this is the code path an operator would want to run by hand
    before trusting it.
    """
    company_id = data.get("company_id")
    if not company_id:
        print(f"[retention] incomplete job: {data}")
        return

    db = SessionLocal()
    try:
        result = retention.purge_company(
            db, UUID(str(company_id)), dry_run=bool(data.get("dry_run"))
        )
        print(
            f"[retention] company {company_id} days={result['retention_days']} "
            f"dry_run={result['dry_run']} rows={result['deleted']}"
        )
    except Exception as e:
        db.rollback()
        print(f"[retention] company {company_id} failed: {e}")
        raise
    finally:
        db.close()


async def enqueue_due_retention() -> list[str]:
    """Queue a purge for every company with a retention policy."""
    db = SessionLocal()
    queued: list[str] = []
    try:
        for company_id in retention.companies_with_policy(db):
            enqueue_job({"type": "retention", "company_id": str(company_id)})
            queued.append(str(company_id))
    finally:
        db.close()
    return queued


async def retention_loop():
    """Wake every RETENTION_CHECK_SECONDS and queue the daily purges."""
    while True:
        await asyncio.sleep(RETENTION_CHECK_SECONDS)
        try:
            queued = await enqueue_due_retention()
            if queued:
                print(f"[worker] retention purge queued for {len(queued)} companies")
        except Exception as e:
            print(f"[worker] retention enqueue failed: {e}")


async def handle_digest(data):
    """Send one digest period. The claim inside `send_period` makes repeats safe.

    Claiming happens before the email goes out, so a duplicate job, a retry, a
    worker restart or two workers on the same period all end with at most one
    email; only the winner stamps `sent_at`.
    """
    company_id = data.get("company_id")
    period_start_raw = data.get("period_start")
    period_end_raw = data.get("period_end")
    if not company_id or not period_start_raw or not period_end_raw:
        print(f"[digest] incomplete job: {data}")
        return

    db = SessionLocal()
    try:
        period_start = datetime.fromisoformat(str(period_start_raw))
        period_end = datetime.fromisoformat(str(period_end_raw))
        stale_before = datetime.now(UTC) - timedelta(seconds=DIGEST_CHECK_SECONDS)
        result = await digest.send_period(
            db, UUID(str(company_id)), period_start, period_end, stale_before
        )
        print(f"[digest] company {company_id}: {result}")
    finally:
        db.close()


async def enqueue_due_digests(now: datetime | None = None) -> list[str]:
    """Enqueue a digest job for every company whose send hour has come.

    Only enqueues: the job itself claims the period, so two workers finding the
    same company still send one email. A period that was already sent, or is
    claimed by a live worker, is skipped; a claim from a dead worker is retried.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    stale_before = now - timedelta(seconds=DIGEST_CHECK_SECONDS)

    db = SessionLocal()
    queued: list[str] = []
    try:
        for company in db.query(models.Company).all():
            settings = company_settings.values(
                db, company.id, ("digest_enabled", "digest_hour", "digest_day")
            )
            enabled = (
                (settings.get("digest_enabled") or "").strip().lower()
                in company_settings.TRUE_VALUES
            )
            if not enabled:
                continue

            try:
                hour = int(str(settings.get("digest_hour") or DIGEST_HOUR).strip())
            except (TypeError, ValueError):
                hour = DIGEST_HOUR
            if now.hour != hour:
                continue

            # The last complete week, not the one in progress: it is the window
            # the topic worker clusters, and a digest of a half-finished week
            # would mark that period sent and never cover the rest of it.
            period_start, period_end = digest.previous_period(
                now, settings.get("digest_day") or "monday"
            )
            if digest.period_settled(
                db, company.id, period_start, stale_before
            ):
                continue

            # Queue the week's clusters *before* the digest that reports them. The
            # queue is FIFO (`lpush` + `brpop`), so one worker finishes the run and
            # then sends a digest that carries the groups instead of falling back
            # to term counts. An already settled window queues nothing.
            if company_settings.flag(
                db, company.id, "topic_clustering_enabled"
            ) and not topics.window_settled(
                db,
                company.id,
                period_start,
                stale_before=now - topics.STALE_RUN_AFTER,
            ):
                await enqueue_job(
                    {
                        "type": "topic_clusters",
                        "company_id": str(company.id),
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    }
                )

            await enqueue_job(
                {
                    "type": "digest",
                    "company_id": str(company.id),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                }
            )
            queued.append(str(company.id))
            print(f"[digest] queued company {company.id} for {period_start}")
    finally:
        db.close()
    return queued


async def enqueue_due_topics(now: datetime | None = None) -> list[str]:
    """Enqueue the last complete week for every company that opted in.

    The switch is per company (`topic_clustering_enabled`, off by default), so a
    deployment where nobody opted in makes no provider call. This loop only
    enqueues: the job claims the window, so two workers finding the same company
    still build it once, a completed window is skipped, and a claim left by a dead
    worker is recovered here and retried by the job's own claim.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    stale_before = now - topics.STALE_RUN_AFTER

    db = SessionLocal()
    queued: list[str] = []
    try:
        recovered = topics.recover_stale_runs(db, stale_before=stale_before)
        for company_id, period_start in recovered:
            print(
                f"[topics] recovered stale run for company {company_id} "
                f"window {period_start}"
            )

        for company in db.query(models.Company).all():
            settings = company_settings.values(
                db,
                company.id,
                # `topic_cluster_count` is read by the run itself, when it builds
                # the naming prompt; the scheduler only decides whether to queue.
                ("topic_clustering_enabled", "digest_day"),
            )
            enabled = (
                (settings.get("topic_clustering_enabled") or "").strip().lower()
                in company_settings.TRUE_VALUES
            )
            if not enabled:
                continue

            period_start, period_end = topics.previous_window(
                now, settings.get("digest_day") or "monday"
            )
            if topics.window_settled(
                db, company.id, period_start, stale_before=stale_before
            ):
                continue

            await enqueue_job(
                {
                    "type": "topic_clusters",
                    "company_id": str(company.id),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                }
            )
            queued.append(str(company.id))
            print(f"[topics] queued company {company.id} for {period_start}")
    finally:
        db.close()
    return queued


async def handle_topic_clusters(data):
    """Cluster one claimed week. The run row makes duplicates and retries safe."""
    company_id = data.get("company_id")
    period_start_raw = data.get("period_start")
    period_end_raw = data.get("period_end")
    if not company_id or not period_start_raw or not period_end_raw:
        print(f"[topics] incomplete job: {data}")
        return

    db = SessionLocal()
    try:
        result = topics.run_window(
            db,
            UUID(str(company_id)),
            datetime.fromisoformat(str(period_start_raw)),
            datetime.fromisoformat(str(period_end_raw)),
            stale_before=datetime.now(UTC) - topics.STALE_RUN_AFTER,
        )
        print(f"[topics] company {company_id}: {result}")
    finally:
        db.close()


async def topic_loop():
    """Wake every TOPIC_CLUSTER_INTERVAL_SECONDS and queue the opted-in companies.

    The interval is only how often this check runs; the window boundaries come from
    `normalize_period`/`digest_day`, so windows never overlap or leave a gap.
    """
    while True:
        await asyncio.sleep(TOPIC_CLUSTER_INTERVAL_SECONDS)
        try:
            await enqueue_due_topics()
        except Exception as e:
            print(f"[topics] loop error: {e}")
            traceback.print_exc()


async def delivery_loop():
    """Retry integration deliveries whose backoff has elapsed.

    The row is the queue: if this worker dies before the next tick, the delivery
    is still `pending` in the database and the next process picks it up.

    Retention runs on its own, much slower clock (`DELIVERY_RETENTION_CHECK_SECONDS`,
    default hourly): a row becomes deletable days after it settled, so scanning
    for it on every retry tick is work with nothing to find.
    """
    next_purge = 0.0
    while True:
        db = SessionLocal()
        try:
            result = await process_due_deliveries(db)
            if result["attempted"]:
                print(f"[worker] integration deliveries: {result}")
            if time.monotonic() >= next_purge:
                # Delivery rows carry the visitor's contact details; clear a dead
                # row's payload and drop settled rows past the window.
                purged = purge_deliveries(db)
                next_purge = time.monotonic() + DELIVERY_RETENTION_CHECK_SECONDS
                if purged["cleared_payloads"] or purged["deleted"]:
                    print(f"[worker] delivery retention: {purged}")
        except Exception as e:
            print(f"[worker] integration delivery retry failed: {e}")
        finally:
            db.close()
        await asyncio.sleep(DELIVERY_CHECK_SECONDS)


async def digest_loop():
    """Wake every DIGEST_CHECK_SECONDS and enqueue the companies that are due."""
    while True:
        await asyncio.sleep(DIGEST_CHECK_SECONDS)
        try:
            await enqueue_due_digests()
        except Exception as e:
            print(f"[digest] loop error: {e}")
            traceback.print_exc()


async def scheduler_loop():
    """Periodically re-enqueue ingest for websites due for a refresh.

    Runs in the same process as the job consumer and reuses the Redis queue,
    so no extra infrastructure is needed.
    """
    while True:
        # Check roughly once per refresh interval (but cap the sleep so config
        # changes / restarts take effect without a huge idle wait).
        sleep_seconds = max(60, CRAWL_REFRESH_HOURS * 3600 // 12)
        await asyncio.sleep(sleep_seconds)
        try:
            # Another worker may have died mid-ingest while this one kept
            # running, so check for orphans on every scheduler tick too.
            await requeue_stuck_ingests()

            db = SessionLocal()
            threshold = datetime.now(UTC) - timedelta(hours=CRAWL_REFRESH_HOURS)
            due = (
                db.query(models.Website)
                .filter(models.Website.status == "active")
                .filter(models.Website.ingest_status == "completed")
                .filter(
                    (models.Website.updated_at == None)
                    | (models.Website.updated_at < threshold)
                )
                .all()
            )
            for site in due:
                # Mark as processing so the next cycle won't re-enqueue it
                # until this run finishes.
                site.ingest_status = "processing"
                db.commit()
                try:
                    await enqueue_job(
                        {"type": "ingest", "website_id": str(site.id)}
                    )
                except Exception as e:
                    # Never leave a row in `processing` when no job exists.
                    site.ingest_status = "failed"
                    db.commit()
                    print(f"[scheduler] failed to queue website {site.id}: {e}")
                    continue
                print(f"[scheduler] queued refresh for website {site.id}")
            db.close()
        except Exception as e:
            print(f"[scheduler] error: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(worker())
