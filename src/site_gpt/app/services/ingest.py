from langchain_text_splitters import RecursiveCharacterTextSplitter

from site_gpt.app.db.vector_store import get_vectorstore


def split_docs(docs):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    return splitter.split_documents(docs)


def ingest_documents(chunks):
    vs = get_vectorstore()
    vs.add_documents(chunks)
