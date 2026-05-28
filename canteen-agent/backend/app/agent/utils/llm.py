"""LLM / Embedding 连接工具 —— OpenAI 兼容接口"""
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.config import settings

_llm = None
_embeddings = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.OPENAI_LLM_MODEL,
            openai_api_key=settings.OPENAI_API_KEY,
            openai_api_base=settings.OPENAI_BASE_URL,
            temperature=0.3,
            max_tokens=1024,
        )
    return _llm


def get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=settings.OPENAI_EMBED_MODEL,
            openai_api_key=settings.OPENAI_EMBED_API_KEY,
            openai_api_base=settings.OPENAI_EMBED_BASE_URL,
        )
    return _embeddings
