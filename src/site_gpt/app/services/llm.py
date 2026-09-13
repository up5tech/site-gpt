import base64

from langchain_openrouter import ChatOpenRouter
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from openai import OpenAI

from site_gpt.app.core.config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    LLM_AI,
    LLM_EMBEDDING_MODEL,
    LLM_MODEL,
    OLLAMA_HOST,
    OLLAMA_PASSWORD,
    OLLAMA_USERNAME,
    OPEN_ROUTER_API_KEY,
    OPENAI_API_BASE_URL,
    OPENAI_API_KEY,
)


class _OpenAICompatibleEmbeddings:
    """Thin embedding client using the OpenAI SDK directly.

    We avoid LangChain's ``OpenAIEmbeddings`` wrapper here: with some
    OpenAI-compatible gateways (e.g. a local router at a custom base_url) it
    POSTs the request in a shape the gateway rejects with
    ``400 input is required``, even though the raw SDK works. Going through
    the SDK directly is reliable.

    Also requests ``dimensions=1536`` when the model supports OpenAI's
    ``dimensions`` param, so the produced vectors match the ``Vector(1536)``
    column regardless of what the gateway's ``auto`` router would otherwise
    return (it defaults to 3072).
    """

    def __init__(self, model: str, *, api_key=None, base_url=None, dimensions=None):
        self.model = model
        self.dimensions = dimensions
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def embed_documents(self, texts):
        kwargs = {"input": list(texts), "model": self.model}
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        resp = self._client.embeddings.create(**kwargs)
        return [list(d.embedding) for d in resp.data]

    def embed_query(self, text: str):
        return self.embed_documents([text])[0]


def _embedding_dimensions(model: str):
    """1536 when the model supports OpenAI's ``dimensions`` param, else None."""
    if model == "auto" or model.startswith("text-embedding-3"):
        return 1536
    return None


def get_llm():
    temperature = 0.5
    if LLM_AI == "ollama":
        if OLLAMA_USERNAME and OLLAMA_PASSWORD:
            auth_str = f"{OLLAMA_USERNAME}:{OLLAMA_PASSWORD}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            return ChatOllama(
                model=LLM_MODEL,
                temperature=0.5,
                base_url=OLLAMA_HOST,
                headers={"Authorization": f"Basic {b64_auth}"},  # type: ignore
            )
        else:
            return ChatOllama(model=LLM_MODEL, temperature=0.5)
    elif LLM_AI == "openrouter":
        return ChatOpenRouter(
            model=LLM_MODEL, temperature=temperature, api_key=OPEN_ROUTER_API_KEY  # type: ignore
        )
    elif LLM_AI == "groq":
        return ChatGroq(model=LLM_MODEL, temperature=temperature, api_key=GROQ_API_KEY)  # type: ignore
    elif LLM_AI == "gemini":
        return ChatGoogleGenerativeAI(
            model=LLM_MODEL, temperature=temperature, api_key=GEMINI_API_KEY
        )
    elif LLM_AI == "custom_openai":
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY,  # type: ignore
            base_url=OPENAI_API_BASE_URL,
        )
    else:
        return ChatOpenAI(
            model=LLM_MODEL, temperature=temperature, api_key=OPENAI_API_KEY  # type: ignore
        )


def get_embedding_model():
    dims = _embedding_dimensions(LLM_EMBEDDING_MODEL)
    if LLM_AI == "ollama":
        if OLLAMA_USERNAME and OLLAMA_PASSWORD:
            auth_str = f"{OLLAMA_USERNAME}:{OLLAMA_PASSWORD}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            return OllamaEmbeddings(
                model=LLM_EMBEDDING_MODEL,
                base_url=OLLAMA_HOST,
                headers={"Authorization": f"Basic {b64_auth}"},  # type: ignore
            )
        else:
            return OllamaEmbeddings(model=LLM_EMBEDDING_MODEL)
    elif LLM_AI == "openrouter":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=OPEN_ROUTER_API_KEY,  # type: ignore
            base_url="https://openrouter.ai/api/v1",
            dimensions=dims,
        )
    elif LLM_AI == "groq":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=GROQ_API_KEY,  # type: ignore
            base_url="https://api.groq.com/openai/v1",
            dimensions=dims,
        )
    elif LLM_AI == "gemini":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=GEMINI_API_KEY,  # type: ignore
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            dimensions=dims,
        )
    elif LLM_AI == "custom_openai":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=OPENAI_API_KEY,  # type: ignore
            base_url=OPENAI_API_BASE_URL,
            dimensions=dims,
        )
    else:
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=OPENAI_API_KEY,  # type: ignore
            dimensions=dims,
        )
