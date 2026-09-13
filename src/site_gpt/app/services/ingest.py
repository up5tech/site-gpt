from uuid import UUID
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.services.llm import get_embedding_model


def split_text(text: str):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    return splitter.split_text(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    embedding_model = get_embedding_model()
    return embedding_model.embed_documents(texts)


def ingest_document(db: Session, document_id: UUID, content: str):
    # Re-ingest must be idempotent: drop previously stored chunks first.
    db.query(models.Embedding).filter(
        models.Embedding.document_id == document_id
    ).delete()
    db.commit()

    chunks = split_text(content)
    vectors = embed_texts(chunks)
    for chunk, vector in zip(chunks, vectors):
        emb = models.Embedding(
            document_id=document_id, content=chunk, embedding=vector
        )
        db.add(emb)

    db.commit()


def ingest_extra_document(db: Session, extra_document_id: UUID, content: str):
    # Re-ingest must be idempotent: drop previously stored chunks first.
    db.query(models.Embedding).filter(
        models.Embedding.extra_document_id == extra_document_id
    ).delete()
    db.commit()

    chunks = split_text(content)
    vectors = embed_texts(chunks)

    for chunk, vector in zip(chunks, vectors):
        emb = models.Embedding(
            extra_document_id=extra_document_id, content=chunk, embedding=vector
        )
        db.add(emb)

    db.commit()
