from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.services.ingest import embed_texts
from site_gpt.app.services.llm import get_llm


def search(db: Session, query_vector: list[float], website_id: UUID):
    sql = text(
        """
        SELECT e.content
        FROM embeddings e
        JOIN documents d ON e.document_id = d.id
        WHERE d.website_id = :website_id
        ORDER BY e.embedding <-> :vector
        LIMIT 5
    """
    )

    return db.execute(
        sql, {"website_id": website_id, "vector": query_vector}
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


def ask(db: Session, website_id: UUID, session_id: str, question: str):
    # embed question
    query_vector = embed_texts([question])[0]
    # search in vector store
    results = search(db, query_vector, website_id)
    # build context
    context = "\n\n".join([row[0] for row in results])
    # load memory
    messages = get_chat_history(db, website_id, session_id)
    history = format_history(messages)
    # ask llm
    llm = get_llm()
    answer = llm.invoke(
        f"""
        Answer based only on context:
        {context}

        Conversation history:
        {history}

        Question: {question}
        """
    )
    # save user message
    save_message(db, website_id, session_id, "user", question)
    # save response
    content = answer.content if hasattr(answer, "content") else str(answer)
    save_message(db, website_id, session_id, "assistant", str(content))
    return content
