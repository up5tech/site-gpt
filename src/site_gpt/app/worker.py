import asyncio
import json

from site_gpt.app.services.crawler import crawl_website
from site_gpt.app.services.ingest import ingest_document, ingest_extra_document
from site_gpt.app.services.redis import redis_client
from site_gpt.app.db.session import SessionLocal
from site_gpt.app import models


async def worker():
    while True:
        _, job = await redis_client.brpop("queue:jobs")  # type: ignore
        data = json.loads(job)

        print("Processing:", data)

        if data["type"] == "ingest":
            await handle_ingest(data)


async def handle_ingest(data):
    if not data.get("website_id"):
        print("Missing website_id")
        return
    db = SessionLocal()
    website = (
        db.query(models.Website).filter(models.Website.id == data["website_id"]).first()
    )
    if not website:
        print("Website not found")
        return

    website.ingest_status = "processing"
    db.commit()

    # ingest sitemap
    docs = crawl_website(db, website.id)
    for doc in docs:
        document = models.Document(
            title=doc.metadata["title"],
            content=doc.page_content,
            url=doc.metadata["source"],
            website_id=website.id,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        # save embedding
        ingest_document(db, document.id, document.content)

    # ingest extra documents
    extra_documents = (
        db.query(models.ExtraDocument)
        .filter(models.ExtraDocument.website_id == website.id)
        .all()
    )
    for extra_document in extra_documents:
        ingest_extra_document(db, extra_document.id, extra_document.content)

    website.ingest_status = "completed"
    db.commit()


asyncio.run(worker())
