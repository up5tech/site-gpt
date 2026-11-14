import asyncio
import json
import os
import traceback
from datetime import datetime, timedelta, UTC

from site_gpt.app.services.crawler import crawl_website
from site_gpt.app.services.ingest import ingest_document, ingest_extra_document
from site_gpt.app.services.parse import extract_text_from_file
from site_gpt.app.services.redis import redis_client, enqueue_job
from site_gpt.app.core.config import CRAWL_REFRESH_HOURS
from site_gpt.app.db.session import SessionLocal
from site_gpt.app import models

# A website still in `processing` longer than this is assumed to belong to a
# worker that died mid-ingest (deploy, OOM kill, hard reboot). It must be
# recovered explicitly: the scheduler only picks up `completed` sites, so an
# orphaned `processing` row would otherwise never be re-ingested again.
# Deliberately generous so a legitimately slow crawl is not re-queued.
STUCK_INGEST_AFTER = timedelta(hours=6)


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
