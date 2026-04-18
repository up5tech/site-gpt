from langchain_openai import ChatOpenAI

from site_gpt.app.db.vector_store import get_vectorstore
from site_gpt.app.services.llm import get_llm


def ask(question: str):
    vs = get_vectorstore()
    retriever = vs.as_retriever(search_kwargs={"k": 5})

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
