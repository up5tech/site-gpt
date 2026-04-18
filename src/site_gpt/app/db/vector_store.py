from langchain_postgres import PGVector

from site_gpt.app.core.config import DB_URL
from site_gpt.app.services.llm import get_embedding_model


def get_vectorstore():
    return PGVector(
        connection_string=DB_URL,
        embedding_function=get_embedding_model(),
    )
