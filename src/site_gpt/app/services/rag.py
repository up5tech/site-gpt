from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from langchain_core.messages import HumanMessage, SystemMessage

from site_gpt.app import models
from site_gpt.app.services.ingest import embed_texts
from site_gpt.app.services.llm import get_llm


def search(db: Session, query_vector: list[float], website_id: UUID, limit: int = 5):
    """Search both crawled pages (documents) and uploaded docs (extra_documents).

    A chunk is eligible when it comes from a `documents` row of this website,
    OR from an `extra_documents` row that is either linked to this website or
    belongs to the same company (company-wide knowledge base).
    """
    vector_str = "[" + ",".join(map(str, query_vector)) + "]"

    website = (
        db.query(models.Website)
        .filter(models.Website.id == website_id)
        .first()
    )
    company_id = website.company_id if website else None

    sql = text("""
        SELECT e.content
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
        ORDER BY e.embedding <-> CAST(:vector AS vector)
        LIMIT :limit
    """)

    return db.execute(
        sql,
        {
            "website_id": website_id,
            "company_id": company_id,
            "vector": vector_str,
            "limit": limit,
        },
    ).fetchall()


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
    db: Session, website_id: UUID, session_id: str, role: str, message: str
):
    msg = models.ChatMessage(
        session_id=session_id, role=role, message=message, website_id=website_id
    )
    db.add(msg)
    db.commit()


SYSTEM_PROMPT = (
    "You are a helpful assistant embedded on a company website. "
    "Answer the user's question using ONLY the provided context. "
    "If the context does not contain the information needed to answer, "
    "politely say you don't have that information and suggest contacting the company. "
    "Do not make up facts. Be concise and friendly."
)


def ask(db: Session, website_id: UUID, session_id: str, question: str):
    # embed question
    query_vector = embed_texts([question])[0]
    # search in vector store (pages + uploaded documents)
    results = search(db, query_vector, website_id)
    # build context
    context = "\n\n".join([row[0] for row in results])
    # load memory
    messages = get_chat_history(db, website_id, session_id)
    history = format_history(messages)
    # ask llm
    llm = get_llm()
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
    save_message(db, website_id, session_id, "assistant", str(content))
    return content
