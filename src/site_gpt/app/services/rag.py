import asyncio
import json
import logging
import traceback
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from langchain_core.messages import HumanMessage, SystemMessage

from site_gpt.app import models
from site_gpt.app.core.config import RAG_MAX_DISTANCE
from site_gpt.app.services import conversations, model_settings
from site_gpt.app.services.ingest import embed_texts
from site_gpt.app.services.llm import get_llm

logger = logging.getLogger(__name__)


def search(
    db: Session,
    query_vector: list[float],
    website_id: UUID,
    limit: int = 5,
    max_distance: float | None = None,
):
    """Search both crawled pages (documents) and uploaded docs (extra_documents).

    A chunk is eligible when it comes from a `documents` row of this website,
    OR from an `extra_documents` row that is either linked to this website or
    belongs to the same company (company-wide knowledge base).

    Returns a list of RowMapping with keys: `content`, `title`, `url`,
    `source_type` ("page" for crawled website pages, "document" for uploaded
    docs) and `distance` (cosine distance to the query). `title`/`url` are used
    to render citations in the answer.

    Chunks whose `distance` is above `max_distance` are excluded **in the
    query**, so the `LIMIT` applies to chunks that actually qualify (and junk
    chunks never leave the database). An out-of-scope question therefore yields
    no context instead of the five least-bad matches. `max_distance=None` uses
    `RAG_MAX_DISTANCE`; a negative threshold disables the filter (V1 behaviour).
    """
    if max_distance is None:
        max_distance = RAG_MAX_DISTANCE
    vector_str = "[" + ",".join(map(str, query_vector)) + "]"

    website = (
        db.query(models.Website)
        .filter(models.Website.id == website_id)
        .first()
    )
    company_id = website.company_id if website else None

    params: dict = {
        "website_id": website_id,
        "company_id": company_id,
        "vector": vector_str,
        "limit": limit,
    }

    # Threshold in the WHERE clause, not after the fact: the limit then applies
    # to qualifying chunks only. `distance` is a SELECT alias, which Postgres
    # does not allow in WHERE, so the expression is repeated (still index-usable
    # by the HNSW index on embeddings.embedding).
    distance_filter = ""
    if max_distance is not None and max_distance >= 0:
        distance_filter = (
            "            AND (e.embedding <-> CAST(:vector AS vector))"
            " <= :max_distance\n"
        )
        params["max_distance"] = float(max_distance)

    sql = text(f"""
        SELECT e.content AS content,
               COALESCE(d.title, ed.name) AS title,
               d.url AS url,
               CASE WHEN e.document_id IS NOT NULL THEN 'page'
                    ELSE 'document' END AS source_type,
               e.embedding <-> CAST(:vector AS vector) AS distance
        FROM embeddings e
        LEFT JOIN documents d ON e.document_id = d.id
        LEFT JOIN extra_documents ed ON e.extra_document_id = ed.id
        WHERE (
            (e.document_id IS NOT NULL AND d.website_id = :website_id)
            OR (
                e.extra_document_id IS NOT NULL
                AND (
                    ed.website_id = :website_id
                    OR (:company_id IS NOT NULL AND ed.company_id = :company_id)
                )
            )
        )
{distance_filter}        ORDER BY distance
        LIMIT :limit
    """)

    return db.execute(sql, params).mappings().all()


def collect_sources(results) -> list[dict]:
    """Deduplicate retrieved chunks into a clean citation list.

    Two chunks from the same page share a URL, so we key on URL (falling back
    to title) to avoid repeating the same source multiple times in the UI.
    """
    sources: list[dict] = []
    seen: set[str] = set()
    for r in results:
        title = r["title"]
        url = r["url"]
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append(
            {"title": title, "url": url, "source_type": r["source_type"]}
        )
    return sources


def get_chat_history(db: Session, website_id: UUID, session_id: str, limit: int = 10):
    messages = (
        db.query(models.ChatMessage)
        .filter_by(website_id=website_id, session_id=session_id)
        .order_by(models.ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )

    return list(reversed(messages))


def format_history(messages):
    history = ""
    for m in messages:
        role = "User" if m.role == "user" else "Assistant"
        history += f"{role}: {m.message}\n"
    return history


def save_message(
    db: Session,
    website_id: UUID,
    session_id: str,
    role: str,
    message: str,
    answered: bool | None = None,
    author_user_id: UUID | None = None,
) -> models.ChatMessage:
    """Persist one message and return it.

    The assistant row's id is what the widget sends back with a rating (F4), so
    callers need the refreshed row — `created_at` is a server default.
    `answered` is the digest's signal (F6): True/False only for a complete
    answer, left NULL for a partial one and for pre-V2 rows. `author_user_id` is
    the agent who wrote an `agent` row (M9); the transcript and the inbox are
    updated in the same transaction, so the queue can never disagree with the
    messages.
    """
    msg = models.ChatMessage(
        session_id=session_id,
        role=role,
        message=message,
        website_id=website_id,
        answered=answered,
        author_user_id=author_user_id,
    )
    db.add(msg)
    # M9: the inbox row is created lazily here, on the session's first message,
    # and every message refreshes its `last_message_at` clock.
    conversations.note_message(db, website_id, session_id, role)
    db.commit()
    db.refresh(msg)
    return msg


# Static reply used when retrieval returns nothing above the distance threshold.
# Answered without an LLM call on purpose: with no usable context a model can
# only guess, so this keeps the failure mode honest and saves a request.
NO_CONTEXT_ANSWER = (
    "I'm sorry, I don't have information about that. "
    "Please contact the team for more details."
)


def _no_context_answer(db: Session, website_id: UUID, session_id: str, question: str):
    """Persist the exchange and return the canned "no information" reply."""
    save_message(db, website_id, session_id, "user", question)
    answer = save_message(
        db, website_id, session_id, "assistant", NO_CONTEXT_ANSWER, False
    )
    return {
        "answer": NO_CONTEXT_ANSWER,
        "sources": [],
        "message_id": answer.id,
    }


SYSTEM_PROMPT = (
    "You are a helpful assistant embedded on a company website. "
    "Answer the user's question using ONLY the provided context. "
    "If the context does not contain the information needed to answer, "
    "politely say you don't have that information and suggest contacting the company. "
    "Do not make up facts. Be concise and friendly. "
    # F1: the language rule lives in the shared prompt, so the synchronous
    # `ask` and the streaming `ask_stream` cannot drift apart. The widget's
    # language setting is a UI concern and never overrides this.
    "Detect the language of the user's question and always answer in that same "
    "language. If the context is in another language, translate the relevant "
    "information rather than answering in the context's language."
)


def ask(db: Session, website_id: UUID, session_id: str, question: str):
    # embed question
    query_vector = embed_texts([question])[0]
    # search in vector store (pages + uploaded documents)
    results = search(db, query_vector, website_id)
    # Nothing relevant enough: answer without spending an LLM call.
    if not results:
        return _no_context_answer(db, website_id, session_id, question)
    # build context
    context = "\n\n".join([row["content"] for row in results])
    # load memory
    messages = get_chat_history(db, website_id, session_id)
    history = format_history(messages)
    # ask llm, honouring the company's model choice when it is allowlisted
    provider, model = model_settings.resolve(db, website_id)
    llm = get_llm(provider=provider, model=model)
    answer = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Context:\n{context}\n\n"
                    f"Conversation history:\n{history}\n\n"
                    f"Question: {question}"
                )
            ),
        ]
    )
    # save user message
    save_message(db, website_id, session_id, "user", question)
    # save response
    content = answer.content if hasattr(answer, "content") else str(answer)
    saved = save_message(
        db,
        website_id,
        session_id,
        "assistant",
        str(content),
        bool(results),
    )
    return {
        "answer": content,
        "sources": collect_sources(results),
        "message_id": saved.id,
    }


def _safe_error_message(exc: Exception) -> str:
    """Concise, user-safe error string for the SSE `error` event.

    The full traceback is logged server-side; the client only gets a short,
    secret-free message so we don't leak API keys or internals.
    """
    msg = str(exc)
    if not msg:
        msg = exc.__class__.__name__
    return f"{exc.__class__.__name__}: {msg[:300]}"


async def ask_stream(db: Session, website_id: UUID, session_id: str, question: str):
    """Stream the answer token-by-token as SSE `data: {chunk}` events.

    Yields already-formatted SSE lines. Network-bound work (embedding, search,
    DB writes) is offloaded to a thread so the event loop stays responsive.

    The whole flow is guarded so that any failure (embedding API error, DB
    error, LLM error, ...) is reported as a single `data: {"error": ...}` event
    followed by `data: {"done": true}`. This guarantees the SSE stream always
    terminates cleanly — without it a mid-stream exception closes the connection
    early and the browser reports ERR_INCOMPLETE_CHUNKED_ENCODING.
    """
    full: list[str] = []
    sources: list[dict] = []
    try:
        # embed_texts returns list[list[float]]; take the single vector for
        # this one question (matches the synchronous `ask`).
        query_vector = (await asyncio.to_thread(embed_texts, [question]))[0]
        results = await asyncio.to_thread(search, db, query_vector, website_id)
        if not results:
            # No chunk passed the threshold: answer without calling the LLM.
            await asyncio.to_thread(
                save_message, db, website_id, session_id, "user", question
            )
            yield f"data: {json.dumps({'chunk': NO_CONTEXT_ANSWER})}\n\n"
            saved = await asyncio.to_thread(
                save_message,
                db,
                website_id,
                session_id,
                "assistant",
                NO_CONTEXT_ANSWER,
                False,
            )
            yield f"data: {json.dumps({'done': True, 'sources': [], 'message_id': str(saved.id)})}\n\n"
            return
        context = "\n\n".join([row["content"] for row in results])
        sources = collect_sources(results)
        messages = await asyncio.to_thread(get_chat_history, db, website_id, session_id)
        history = format_history(messages)

        # One extra query per answer. An unknown or half-written pair resolves
        # to (None, None), which is the environment default.
        provider, model = await asyncio.to_thread(
            model_settings.resolve, db, website_id
        )
        llm = get_llm(provider=provider, model=model)
        await asyncio.to_thread(
            save_message, db, website_id, session_id, "user", question
        )

        async for chunk in llm.astream(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"Context:\n{context}\n\n"
                        f"Conversation history:\n{history}\n\n"
                        f"Question: {question}"
                    )
                ),
            ]
        ):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            if not text:
                continue
            full.append(text)
            yield f"data: {json.dumps({'chunk': text})}\n\n"

        answer_text = "".join(full)
        saved = await asyncio.to_thread(
            save_message,
            db,
            website_id,
            session_id,
            "assistant",
            answer_text,
            bool(results),
        )
        yield f"data: {json.dumps({'done': True, 'sources': sources, 'message_id': str(saved.id)})}\n\n"

    except Exception as exc:
        # Log the full traceback server-side for diagnostics.
        logger.error("ask_stream failed: %s\n%s", exc, traceback.format_exc())
        # Persist whatever we managed to stream so far (best effort).
        if full:
            try:
                await asyncio.to_thread(
                    save_message, db, website_id, session_id, "assistant", "".join(full)
                )
            except Exception:
                pass
        yield f"data: {json.dumps({'error': _safe_error_message(exc)})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
