from typing import Optional

from site_gpt.app.db.vector_store import get_vectorstore
from site_gpt.app.services.llm import get_llm


def ask(question: str, website_id: Optional[str] = None):
    vs = get_vectorstore()
    
    # Build search kwargs with optional website filter
    search_kwargs: dict = {"k": 5}
    if website_id:
        # Filter embeddings by website_id through document relationship
        search_kwargs["filter"] = {"website_id": website_id}
    
    retriever = vs.as_retriever(search_kwargs=search_kwargs)

    docs = retriever.invoke(question)

    context = "\n\n".join([d.page_content for d in docs])

    llm = get_llm()

    return llm.invoke(
        f"""
    Answer based only on context:

    {context}

    Question: {question}
    """
    )
