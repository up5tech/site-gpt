import base64

from langchain_openrouter import ChatOpenRouter
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from openai import OpenAI

from site_gpt.app.core.config import (
    EMBEDDING_AI,
    EMBEDDING_DIMENSIONS,
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

    Also requests ``dimensions=EMBEDDING_DIMENSIONS`` when the model supports
    OpenAI's ``dimensions`` param, so the produced vectors match the
    ``Vector(EMBEDDING_DIMENSIONS)`` column regardless of what the gateway's
    ``auto`` router would otherwise return.
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
    """Return the ``dimensions`` value to request from OpenAI-style embedding
    APIs that support it (``text-embedding-3-*`` and ``auto``). ``None`` for
    models that emit a fixed native dimension (e.g. Ollama ``bge-m3``,
    ``nomic-embed-text``) — there the column dimension must match the model's
    native dimension (see ``EMBEDDING_DIMENSIONS``).
    """
    if model == "auto" or model.startswith("text-embedding-3"):
        return EMBEDDING_DIMENSIONS
    return None


# Runtime model switching (F3). An admin picks one of these labels and the
# server resolves it to a (provider, model) pair, so a request can never name an
# arbitrary model. `default` means "whatever LLM_AI / LLM_MODEL are set to"; the
# other labels are the models the product advertises and need that provider's
# own API key.
ALLOWED_CHAT_MODELS: dict[str, tuple[str | None, str | None]] = {
    "default": (None, None),
    "fast": ("openai", "gpt-4.1-mini"),
    "accurate": ("openai", "gpt-4.1"),
}


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.5,
):
    """Build the chat client.

    `provider` and `model` fall back to the environment (`LLM_AI` / `LLM_MODEL`),
    which is exactly what every pre-V2 caller gets. Only the *chat* model is
    switchable at runtime: the embedding provider stays fixed, because changing
    it needs a column migration and a re-ingest.
    """
    provider = provider or LLM_AI
    model = model or LLM_MODEL
    if provider == "ollama":
        if OLLAMA_USERNAME and OLLAMA_PASSWORD:
            auth_str = f"{OLLAMA_USERNAME}:{OLLAMA_PASSWORD}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            return ChatOllama(
                model=model,
                temperature=temperature,
                base_url=OLLAMA_HOST,
                headers={"Authorization": f"Basic {b64_auth}"},  # type: ignore
            )
        else:
            return ChatOllama(model=model, temperature=temperature)
    elif provider == "openrouter":
        return ChatOpenRouter(
            model=model, temperature=temperature, api_key=OPEN_ROUTER_API_KEY  # type: ignore
        )
    elif provider == "groq":
        return ChatGroq(model=model, temperature=temperature, api_key=GROQ_API_KEY)  # type: ignore
    elif provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=model, temperature=temperature, api_key=GEMINI_API_KEY
        )
    elif provider == "custom_openai":
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=OPENAI_API_KEY,  # type: ignore
            base_url=OPENAI_API_BASE_URL,
        )
    else:
        return ChatOpenAI(
            model=model, temperature=temperature, api_key=OPENAI_API_KEY  # type: ignore
        )


def get_embedding_model():
    """Build the embedding client for the *embedding* provider (EMBEDDING_AI),
    which is fully independent of the chat provider (LLM_AI)."""
    dims = _embedding_dimensions(LLM_EMBEDDING_MODEL)
    if EMBEDDING_AI == "ollama":
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
    elif EMBEDDING_AI == "openrouter":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=OPEN_ROUTER_API_KEY,  # type: ignore
            base_url="https://openrouter.ai/api/v1",
            dimensions=dims,
        )
    elif EMBEDDING_AI == "groq":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=GROQ_API_KEY,  # type: ignore
            base_url="https://api.groq.com/openai/v1",
            dimensions=dims,
        )
    elif EMBEDDING_AI == "gemini":
        return _OpenAICompatibleEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=GEMINI_API_KEY,  # type: ignore
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            dimensions=dims,
        )
    elif EMBEDDING_AI == "custom_openai":
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
