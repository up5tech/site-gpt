from uuid import UUID
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from site_gpt.app import models
from site_gpt.app.db.vector_store import get_vectorstore
from site_gpt.app.services.llm import get_embedding_model


def split_docs(docs):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    return splitter.split_documents(docs)


def split_text(text: str):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    return splitter.split_text(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    embedding_model = get_embedding_model()
    return embedding_model.embed_documents(texts)


def ingest_documents(chunks, website_id: UUID):
    vs = get_vectorstore()
    vs.add_documents(chunks, metadatas=[{"website_id": website_id} for _ in chunks])


def ingest_document(db: Session, document_id: UUID, content: str):
    chunks = split_text(content)
    vectors = embed_texts(chunks)
    for chunk, vector in zip(chunks, vectors):
        emb = models.Embedding(document_id=document_id, content=chunk, embedding=vector)
        db.add(emb)

    db.commit()


def ingest_extra_document(db: Session, extra_document_id: UUID, content: str):
    chunks = split_text(content)
    vectors = embed_texts(chunks)

    for chunk, vector in zip(chunks, vectors):
        emb = models.Embedding(
            extra_document_id=extra_document_id, content=chunk, embedding=vector
        )
        db.add(emb)

    db.commit()
