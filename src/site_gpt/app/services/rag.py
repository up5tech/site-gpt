from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from site_gpt.app.db.vector_store import get_vectorstore
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


def ask(db: Session, question: str, website_id: UUID):
    # 1. embed question
    query_vector = embed_texts([question])[0]
    # 2. search in vector store
    results = search(db, query_vector, website_id)
    # 3. build context
    context = "\n\n".join([row[0] for row in results])
    # 4. ask llm
    llm = get_llm()
    return llm.invoke(
        f"""
        Answer based only on context:
        {context}
        Question: {question}
        """
    )
