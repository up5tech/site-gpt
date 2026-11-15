"""Approved Q&A pairs turned into retrievable knowledge (F4, ADR-3).

Training does not add a table, a column or a second search path: the approved
pairs are rendered into one `ExtraDocument` per website and pushed through the
normal `split_text` + `embed_texts` pipeline. `rag.search` therefore finds them
like any other uploaded document, and `embeddings` keeps exactly two possible
sources.

The rebuild is idempotent in both directions: the document is updated in place
and `ingest_extra_document` deletes its previous chunks before writing new ones,
so rebuilding twice cannot duplicate chunks, and a website with nothing approved
loses the document (and with it the chunks of rejected pairs).
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.services.conversations import question_for_answer
from site_gpt.app.services.ingest import ingest_extra_document, split_text

logger = logging.getLogger(__name__)

# One document per website owns the whole corpus, so it can be found and
# replaced without touching any document the owner uploaded.
QA_DOCUMENT_NAME = "__qa_training__"


def approved_pairs(db: Session, website_id: UUID) -> list[tuple[str, str]]:
    """(question, answer) for every approved rating of this website.

    The answer is the admin's correction when there is one, otherwise the answer
    that was actually given. Pairs whose message or question has disappeared are
    skipped rather than guessed.
    """
    rows = (
        db.query(models.ChatFeedback)
        .filter(
            models.ChatFeedback.website_id == website_id,
            models.ChatFeedback.status == "approved",
            models.ChatFeedback.message_id.isnot(None),
        )
        .order_by(models.ChatFeedback.created_at.asc())
        .all()
    )

    pairs: list[tuple[str, str]] = []
    for row in rows:
        answer = (
            db.query(models.ChatMessage)
            .filter(models.ChatMessage.id == row.message_id)
            .first()
        )
        if answer is None:
            continue
        question = question_for_answer(
            db, website_id, row.session_id, answer
        )
        if question is None:
            continue
        text = (row.reviewed_answer or answer.message or "").strip()
        asked = (question.message or "").strip()
        if not text or not asked:
            continue
        pairs.append((asked, text))
    return pairs


def render_pairs(pairs: list[tuple[str, str]]) -> str:
    """Render pairs as `Q: …\\nA: …\\n\\n`, the format the corpus uses."""
    return "".join(f"Q: {question}\nA: {answer}\n\n" for question, answer in pairs)


def rebuild_qa_document(db: Session, website_id: UUID) -> dict:
    """Rebuild and re-embed this website's Q&A document.

    Returns `{"approved": n, "chunks": m, "extra_document_id": id | None}`.
    Raises `ValueError` for an unknown website; embedding failures propagate so
    the explicit rebuild endpoint can report them.
    """
    website = (
        db.query(models.Website)
        .filter(models.Website.id == website_id)
        .first()
    )
    if website is None:
        raise ValueError("Website not found")

    pairs = approved_pairs(db, website_id)
    body = render_pairs(pairs)
    document = (
        db.query(models.ExtraDocument)
        .filter(
            models.ExtraDocument.website_id == website_id,
            models.ExtraDocument.name == QA_DOCUMENT_NAME,
        )
        .first()
    )

    if not body:
        # Nothing approved: remove the document so rejected pairs really stop
        # being retrievable instead of lingering as stale chunks.
        if document is not None:
            db.delete(document)
            db.commit()
        return {"approved": 0, "chunks": 0, "extra_document_id": None}

    if document is None:
        document = models.ExtraDocument(
            name=QA_DOCUMENT_NAME,
            content=body,
            website_id=website_id,
            company_id=website.company_id,
        )
        db.add(document)
    else:
        document.content = body
    db.commit()
    db.refresh(document)

    # Same chunking/embedding path as any other document (ADR-3).
    chunks = len(split_text(body))
    ingest_extra_document(db, document.id, body)
    return {
        "approved": len(pairs),
        "chunks": chunks,
        "extra_document_id": str(document.id),
    }
