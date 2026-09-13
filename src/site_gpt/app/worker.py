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


async def worker():
    print("Worker started, waiting for jobs...")
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
                await enqueue_job(
                    {"type": "ingest", "website_id": str(site.id)}
                )
                print(f"[scheduler] queued refresh for website {site.id}")
            db.close()
        except Exception as e:
            print(f"[scheduler] error: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(worker())
