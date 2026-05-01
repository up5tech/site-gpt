from langchain_postgres import PGVector

from site_gpt.app.core.config import DB_URL
from site_gpt.app.services.llm import get_embedding_model


def get_vectorstore():
    embedding_model = get_embedding_model()
    return PGVector(
        connection_string=DB_URL,  # type: ignore
        embeddings=embedding_model,
    )
