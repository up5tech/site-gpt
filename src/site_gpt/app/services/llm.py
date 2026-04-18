import base64

from langchain_openrouter import ChatOpenRouter
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

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
                headers={"Authorization": f"Basic {b64_auth}"},
            )
        else:
            return ChatOllama(model=LLM_MODEL, temperature=0.5)
    elif LLM_AI == "openrouter":
        return ChatOpenRouter(
            model=LLM_MODEL, temperature=temperature, api_key=OPEN_ROUTER_API_KEY
        )
    elif LLM_AI == "groq":
        return ChatGroq(model=LLM_MODEL, temperature=temperature, api_key=GROQ_API_KEY)
    elif LLM_AI == "gemini":
        return ChatGoogleGenerativeAI(
            model=LLM_MODEL, temperature=temperature, api_key=GEMINI_API_KEY
        )
    elif LLM_AI == "custom_openai":
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE_URL,
        )
    else:
        return ChatOpenAI(
            model=LLM_MODEL, temperature=temperature, api_key=OPENAI_API_KEY
        )


def get_embedding_model():
    if LLM_AI == "ollama":
        if OLLAMA_USERNAME and OLLAMA_PASSWORD:
            auth_str = f"{OLLAMA_USERNAME}:{OLLAMA_PASSWORD}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            return OllamaEmbeddings(
                model=LLM_EMBEDDING_MODEL,
                base_url=OLLAMA_HOST,
                headers={"Authorization": f"Basic {b64_auth}"},
            )
        else:
            return OllamaEmbeddings(model=LLM_EMBEDDING_MODEL)
    elif LLM_AI == "openrouter":
        return OpenAIEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=OPEN_ROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
    elif LLM_AI == "groq":
        return OpenAIEmbeddings(model=LLM_EMBEDDING_MODEL, api_key=GROQ_API_KEY)
    elif LLM_AI == "gemini":
        return OpenAIEmbeddings(model=LLM_EMBEDDING_MODEL, api_key=GEMINI_API_KEY)
    elif LLM_AI == "custom_openai":
        return OpenAIEmbeddings(
            model=LLM_EMBEDDING_MODEL,
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE_URL,
        )
    else:
        return OpenAIEmbeddings(model=LLM_EMBEDDING_MODEL, api_key=OPENAI_API_KEY)
