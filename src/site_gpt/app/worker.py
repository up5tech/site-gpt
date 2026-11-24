import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, UTC
from uuid import UUID

from site_gpt.app.services.crawler import crawl_website, extract_urls_from_sitemap
from site_gpt.app.services.ingest import ingest_document, ingest_extra_document
from site_gpt.app.services.ingest_claim import STUCK_INGEST_AFTER, claim_ingest
from site_gpt.app.services.sitemap import add_missing_pages
from site_gpt.app.services.parse import extract_text_from_file
from site_gpt.app.services.redis import redis_client, enqueue_job
from site_gpt.app.core.config import (
    CRAWL_REFRESH_HOURS,
    DELIVERY_CHECK_SECONDS,
    DELIVERY_RETENTION_CHECK_SECONDS,
    DIGEST_CHECK_SECONDS,
    INSIGHT_INTERVAL_SECONDS,
    RETENTION_CHECK_SECONDS,
    SITEMAP_SCAN_INTERVAL_SECONDS,
    TOPIC_CLUSTER_INTERVAL_SECONDS,
    WORKER_HEARTBEAT_INTERVAL_SECONDS,
    DIGEST_ENABLED,
    DIGEST_HOUR,
)
from site_gpt.app.services import company_settings, digest, insights, retention, topics
from site_gpt.app.services.integrations import (
    process_due_deliveries,
    purge_deliveries,
)
from site_gpt.app.db.session import SessionLocal
from site_gpt.app.core.logging import (
    bind_request_id,
    configure_logging,
    log_event,
    log_exception,
)
from site_gpt.app.core.telemetry import (
    note_job_failure,
    note_queue_pop,
    write_heartbeat,
)
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
                log_exception(
                    "worker.stuck_ingest.requeue_failed",
                    e,
                    level=logging.WARNING,
                    website_id=website_id,
                )
                continue
            log_event("worker.stuck_ingest.requeued", website_id=website_id)
        return website_ids
    finally:
        db.close()


# Strong references to the scheduler loops. asyncio keeps only weak references
# to tasks, so a loop created without one can be garbage-collected mid-run and
# that scheduler would stop silently. Holding each task here until it finishes
# also lets a completed loop be collected.
_background_tasks: set[asyncio.Task] = set()


def _keep_task(task: asyncio.Task) -> asyncio.Task:
    """Hold a strong reference to `task` until it completes."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def start_background_loops() -> list[asyncio.Task]:
    """Create the scheduler loops and keep every task referenced.

    Called once by `worker()` at startup. The digest loop stays opt-in behind
    `DIGEST_ENABLED`, so a deployment that never enabled digests runs exactly
    the other loops; every loop only reads settings until the interval elapses.
    """
    coros = [heartbeat_loop(), scheduler_loop()]  # heartbeat first: a dead process must be visible
    if DIGEST_ENABLED:
        coros.append(digest_loop())
    coros.extend(
        [
            delivery_loop(),  # outbound integration retries, always on
            retention_loop(),  # daily purge for companies with a policy
            topic_loop(),  # clustering for companies that opted in
            sitemap_loop(),  # daily sitemap diff scan, opt-in
            insight_loop(),  # conversation insights, opt-in
        ]
    )
    return [_keep_task(asyncio.create_task(coro)) for coro in coros]


def _running_loops() -> list[str]:
    """The loops this process actually runs, for the heartbeat's own report."""
    names = [
        "queue",
        "scheduler",
        "delivery",
        "retention",
        "topics",
        "sitemap",
        "insights",
    ]
    if DIGEST_ENABLED:
        names.append("digest")
    return names


async def heartbeat_loop():
    """Publish one heartbeat per interval (V6-21).

    The key expires after three intervals, so a stopped, crashed or hung worker
    stops answering without anyone having to clean up after it; the API reads
    the same key for `worker.heartbeat_missing`/`heartbeat_stale`.
    """
    while True:
        await write_heartbeat(redis_client, loops=_running_loops())
        await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL_SECONDS)


async def worker():
    configure_logging()
    log_event("worker.started")
    # Pick up ingests orphaned by a previous process before consuming jobs.
    try:
        await requeue_stuck_ingests()
    except Exception as e:
        log_exception("worker.stuck_ingest.recovery_failed", e)
    # Scheduler loops. `start_background_loops` keeps a strong reference to every
    # task: the event loop holds only weak references, so an unreferenced loop
    # could be garbage-collected mid-run and stop silently.
    start_background_loops()
    while True:
        try:
            _, job = await redis_client.brpop("queue:jobs")  # type: ignore
        except Exception as e:
            log_exception("worker.queue.read_failed", e)
            await asyncio.sleep(2)
            continue

        # V6-21: a queue that is no longer being drained is the alert; the pop
        # time is what makes "backlog age" readable from a Redis list.
        await note_queue_pop(redis_client)

        data = json.loads(job)
        job_type = data.get("type")
        # One correlation id per job: its handler's events and any failure share
        # it, so a support report resolves to one job without guessing by time.
        with bind_request_id() as job_request_id:
            log_event("worker.job.received", job_type=job_type)
            handler = _JOB_HANDLERS.get(str(job_type))
            if handler is None:
                log_event(
                    "worker.job.unknown",
                    level=logging.WARNING,
                    job_type=job_type,
                )
                continue
            try:
                await handler(data)
            except Exception as e:
                # The handler owns its claims and rows; this loop does not retry,
                # so the failure must be visible as one structured event and in
                # the repeated-failure counter V6-21 alerts on.
                log_exception("worker.job.failed", e, job_type=job_type)
                await note_job_failure(redis_client)


async def handle_ingest(data):
    if not data.get("website_id"):
        log_event("ingest.missing_website_id", level=logging.WARNING)
        return

    db = SessionLocal()
    try:
        website = (
            db.query(models.Website)
            .filter(models.Website.id == data["website_id"])
            .first()
        )
        if not website:
            log_event(
                "ingest.website_not_found",
                level=logging.WARNING,
                website_id=data.get("website_id"),
            )
            return

        # A disabled website must not be crawled or embedded: it is queued
        # before the owner disables it, or by the refresh scheduler.
        if (website.status or "").strip().lower() != "active":
            log_event(
                "ingest.skipped_disabled_website", website_id=str(website.id)
            )
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
                log_event(
                    "ingest.stale_document_removed",
                    website_id=str(website.id),
                    url=d.url,
                )
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
                    # The filename is user text, so only the row ids are logged.
                    log_exception(
                        "ingest.attachment_parse_failed",
                        e,
                        level=logging.WARNING,
                        attachment_id=str(att.id),
                        extra_document_id=str(extra_document.id),
                    )

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
        log_event("ingest.completed", website_id=str(website.id))
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
        log_event("retention.incomplete_job", level=logging.WARNING, job=data)
        return

    db = SessionLocal()
    try:
        result = retention.purge_company(
            db, UUID(str(company_id)), dry_run=bool(data.get("dry_run"))
        )
        log_event(
            "retention.purged",
            company_id=company_id,
            retention_days=result["retention_days"],
            dry_run=result["dry_run"],
            rows_deleted=result["deleted"],
        )
    except Exception as e:
        db.rollback()
        log_exception("retention.failed", e, company_id=company_id)
        raise
    finally:
        db.close()


async def enqueue_due_retention() -> list[str]:
    """Queue a purge for every company with a retention policy."""
    db = SessionLocal()
    queued: list[str] = []
    try:
        for company_id in retention.companies_with_policy(db):
            # Awaited: `enqueue_job` is a coroutine, so a bare call pushed nothing
            # while this function still reported the company as queued.
            await enqueue_job(
                {"type": "retention", "company_id": str(company_id)}
            )
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
                log_event("retention.queued", companies=len(queued))
        except Exception as e:
            log_exception("retention.enqueue_failed", e)


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
        log_event("digest.incomplete_job", level=logging.WARNING, job=data)
        return

    db = SessionLocal()
    try:
        period_start = datetime.fromisoformat(str(period_start_raw))
        period_end = datetime.fromisoformat(str(period_end_raw))
        stale_before = datetime.now(UTC) - timedelta(seconds=DIGEST_CHECK_SECONDS)
        result = await digest.send_period(
            db, UUID(str(company_id)), period_start, period_end, stale_before
        )
        # Only the outcome fields: the digest body and its recipients are not
        # something a log line may carry.
        log_event(
            "digest.period_completed",
            company_id=company_id,
            period_start=str(period_start_raw),
            sent=result.get("sent"),
            reason=result.get("reason"),
        )
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
            log_event(
                "digest.queued",
                company_id=str(company.id),
                period_start=period_start.isoformat(),
            )
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
            log_event(
                "topics.stale_run_recovered",
                company_id=str(company_id),
                period_start=str(period_start),
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
            log_event(
                "topics.queued",
                company_id=str(company.id),
                period_start=period_start.isoformat(),
            )
    finally:
        db.close()
    return queued


async def handle_topic_clusters(data):
    """Cluster one claimed week. The run row makes duplicates and retries safe."""
    company_id = data.get("company_id")
    period_start_raw = data.get("period_start")
    period_end_raw = data.get("period_end")
    if not company_id or not period_start_raw or not period_end_raw:
        log_event("topics.incomplete_job", level=logging.WARNING, job=data)
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
        # Cluster labels are derived from visitor questions, so the result's
        # counts are logged and its text is not.
        log_event(
            "topics.window_built",
            company_id=company_id,
            period_start=str(period_start_raw),
            status=result.get("status") if isinstance(result, dict) else None,
        )
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
            log_exception("topics.loop_failed", e)


# -- Sitemap diff scan (V4 F4, D7) -------------------------------------------
# Best-effort bookkeeping: Redis remembers when a website was last queued so the
# daily loop does not queue it again on the next tick. A lost key (outage, flush,
# a new Redis) costs one extra scan — never a wrong deletion, because the scan
# only ever removes pages after a fully successful, non-empty fetch.


def sitemap_scan_key(website_id) -> str:
    return f"sitemap:scan:{website_id}"


async def sitemap_recently_scanned(website_id) -> bool:
    """True when this website was queued inside the current interval.

    A Redis error answers False on purpose: the cost of a duplicate scan is one
    sitemap fetch, while treating an unknown as "already scanned" would stop the
    scan entirely during an outage.
    """
    try:
        return bool(await redis_client.exists(sitemap_scan_key(website_id)))  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - one extra scan is harmless
        log_exception(
            "sitemap.last_scan_read_failed",
            e,
            level=logging.WARNING,
            website_id=str(website_id),
        )
        return False


async def mark_sitemap_scanned(website_id) -> None:
    """Remember that this website's scan was queued; never raises."""
    try:
        await redis_client.set(  # type: ignore[attr-defined]
            sitemap_scan_key(website_id),
            datetime.now(UTC).isoformat(),
            ex=SITEMAP_SCAN_INTERVAL_SECONDS,
        )
    except Exception as e:  # noqa: BLE001 - best-effort, see the block comment
        log_exception(
            "sitemap.mark_failed",
            e,
            level=logging.WARNING,
            website_id=str(website_id),
        )


async def enqueue_due_sitemap_scans() -> list[str]:
    """Queue one scan per opted-in `active` website that is due.

    The switch is per company (`sitemap_scan_enabled`, off by default), so a
    deployment where nobody opted in queues nothing. Only websites that are
    `active` and have a sitemap URL are considered; the last-scan key is Redis
    and best-effort, so a Redis outage may queue one extra scan.
    """
    db = SessionLocal()
    queued: list[str] = []
    try:
        for company in db.query(models.Company).all():
            if not company_settings.flag(db, company.id, "sitemap_scan_enabled"):
                continue
            sites = (
                db.query(models.Website)
                .filter(
                    models.Website.company_id == company.id,
                    models.Website.status == "active",
                )
                .all()
            )
            for site in sites:
                if not (site.site_map_url or "").strip():
                    continue
                if await sitemap_recently_scanned(site.id):
                    continue
                try:
                    await enqueue_job(
                        {"type": "sitemap_scan", "website_id": str(site.id)}
                    )
                except Exception as e:
                    # One Redis hiccup must not skip the remaining websites.
                    log_exception(
                        "sitemap.enqueue_failed",
                        e,
                        level=logging.WARNING,
                        website_id=str(site.id),
                    )
                    continue
                await mark_sitemap_scanned(site.id)
                queued.append(str(site.id))
                log_event("sitemap.queued", website_id=str(site.id))
    finally:
        db.close()
    return queued


async def handle_sitemap_scan(data):
    """Diff one website's sitemap and queue one ingest when something changed.

    The order is the safety property (D7): fetch first, and return before
    touching any row when the fetch failed or came back empty — a transient 500
    or an empty sitemap is not evidence that pages vanished. Only a fully
    successful, non-empty fetch may add pages or retire vanished ones; retiring a
    page also deletes its document (the embeddings cascade), matching the admin
    page-delete semantics. Ingest is queued through `claim_ingest`, so a website
    already processing is skipped instead of double-crawled.
    """
    website_id = data.get("website_id")
    if not website_id:
        log_event("sitemap.incomplete_job", level=logging.WARNING, job=data)
        return
    # The job carries the id as a string; coerce once so the query binds a UUID
    # on every dialect (the digest/topic handlers do the same).
    website_id = UUID(str(website_id))

    db = SessionLocal()
    try:
        website = (
            db.query(models.Website)
            .filter(models.Website.id == website_id)
            .first()
        )
        if not website:
            log_event(
                "sitemap.website_not_found",
                level=logging.WARNING,
                website_id=str(website_id),
            )
            return
        if (website.status or "").strip().lower() != "active":
            log_event(
                "sitemap.skipped_disabled_website", website_id=str(website.id)
            )
            return
        sitemap_url = (website.site_map_url or "").strip()
        if not sitemap_url:
            log_event("sitemap.no_sitemap_url", website_id=str(website.id))
            return

        # `extract_urls_from_sitemap` swallows fetch/parse errors and returns an
        # empty list, which is exactly the fail-safe input this handler wants.
        urls = extract_urls_from_sitemap(sitemap_url)
        if not urls:
            log_event("sitemap.nothing_changed", website_id=str(website.id))
            return

        added, truncated = add_missing_pages(db, website.id, urls)

        listed = set(urls)
        pages = (
            db.query(models.WebsitePage)
            .filter(models.WebsitePage.website_id == website.id)
            .all()
        )
        removed = 0
        for page in pages:
            if page.url in listed:
                continue
            # Only a page that is currently serving knowledge can vanish; a row
            # retired by an earlier scan stays as history.
            if (page.status or "active").strip().lower() != "active":
                continue
            documents = (
                db.query(models.Document)
                .filter(
                    models.Document.website_id == website.id,
                    models.Document.url == page.url,
                )
                .all()
            )
            # Every row for that URL, not just the first: one URL can own more
            # than one document (a re-crawl, a manual add), and a survivor would
            # keep answering from a page the sitemap no longer lists.
            # Embeddings cascade via the FK, so deleting the document is enough.
            for document in documents:
                db.delete(document)
            page.status = "inactive"
            removed += 1
        db.commit()

        changed = bool(added or removed)
        queued = False
        if changed and claim_ingest(db, website.id, website.company_id):
            await enqueue_job({"type": "ingest", "website_id": str(website.id)})
            queued = True
        elif changed:
            log_event(
                "sitemap.ingest_already_running", website_id=str(website.id)
            )
        log_event(
            "sitemap.diff_applied",
            website_id=str(website.id),
            added=added,
            removed=removed,
            truncated=truncated,
            queued=queued,
        )
    finally:
        db.close()


async def sitemap_loop():
    """Wake every SITEMAP_SCAN_INTERVAL_SECONDS and queue the opted-in scans."""
    while True:
        await asyncio.sleep(SITEMAP_SCAN_INTERVAL_SECONDS)
        try:
            queued = await enqueue_due_sitemap_scans()
            if queued:
                log_event("sitemap.scans_queued", websites=len(queued))
        except Exception as e:
            log_exception("sitemap.loop_failed", e)


# -- Conversation insights (V4 F2, D3) ---------------------------------------


async def enqueue_due_insights() -> list[str]:
    """Queue one insight run per company that opted in.

    The switch is per company (`conversation_insights_enabled`, off by default), so
    a deployment where nobody opted in makes no provider call and writes no row.
    This loop only enqueues: the run claims each conversation through its unique
    row, so a duplicate job classifies nothing twice and a claim left by a dead
    worker is taken over by the next run.
    """
    db = SessionLocal()
    queued: list[str] = []
    try:
        for company in db.query(models.Company).all():
            if not insights.enabled(db, company.id):
                continue
            await enqueue_job(
                {"type": "insights", "company_id": str(company.id)}
            )
            queued.append(str(company.id))
            log_event("insights.queued", company_id=str(company.id))
    finally:
        db.close()
    return queued


async def handle_insights(data):
    """Classify one company's settled conversations; the run bounds the cost.

    The handler owns the session and the company id only — `run_for_company`
    re-checks the flag, claims each conversation, and records a failed batch
    instead of raising it, so a provider outage never kills the job loop.
    """
    company_id = data.get("company_id")
    if not company_id:
        log_event("insights.incomplete_job", level=logging.WARNING, job=data)
        return

    db = SessionLocal()
    try:
        result = insights.run_for_company(db, UUID(str(company_id)))
        # Counts only: a summary is derived from the transcript and never logged.
        log_event(
            "insights.run_completed",
            company_id=company_id,
            status=result.get("status"),
            eligible=result.get("eligible"),
            claimed=result.get("claimed"),
            completed=result.get("completed"),
            failed=result.get("failed"),
            calls=result.get("calls"),
        )
    finally:
        db.close()


async def insight_loop():
    """Wake every INSIGHT_INTERVAL_SECONDS and queue the opted-in companies.

    Like the topic loop, the interval is only how often the check runs: a company
    with nothing settled, or one whose flag was switched off since the job was
    queued, claims nothing and spends nothing.
    """
    while True:
        await asyncio.sleep(INSIGHT_INTERVAL_SECONDS)
        try:
            await enqueue_due_insights()
        except Exception as e:
            log_exception("insights.loop_failed", e)


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
                log_event(
                    "integrations.deliveries_attempted",
                    attempted=result["attempted"],
                    delivered=result.get("delivered"),
                    failed=result.get("failed"),
                    dead=result.get("dead"),
                )
            if time.monotonic() >= next_purge:
                # Delivery rows carry the visitor's contact details; clear a dead
                # row's payload and drop settled rows past the window.
                purged = purge_deliveries(db)
                next_purge = time.monotonic() + DELIVERY_RETENTION_CHECK_SECONDS
                if purged["cleared_payloads"] or purged["deleted"]:
                    log_event(
                        "integrations.delivery_retention",
                        cleared_payloads=purged["cleared_payloads"],
                        deleted=purged["deleted"],
                    )
        except Exception as e:
            log_exception("integrations.delivery_retry_failed", e)
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
            log_exception("digest.loop_failed", e)


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
                    log_exception(
                        "scheduler.enqueue_failed",
                        e,
                        level=logging.WARNING,
                        website_id=str(site.id),
                    )
                    continue
                log_event("scheduler.refresh_queued", website_id=str(site.id))
            db.close()
        except Exception as e:
            log_exception("scheduler.loop_failed", e)


#: The queue's job types. A type missing here is logged and skipped rather than
#: crashing the loop, and every handler keeps its own delivery/idempotency
#: semantics (V6-20 owns the queue's ack contract, which this dict does not add).
_JOB_HANDLERS = {
    "ingest": handle_ingest,
    "digest": handle_digest,
    "retention": handle_retention,
    "topic_clusters": handle_topic_clusters,
    "sitemap_scan": handle_sitemap_scan,
    "insights": handle_insights,
}


if __name__ == "__main__":
    asyncio.run(worker())
