"""LLM / Embedding 连接工具 —— OpenAI 兼容接口"""
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.config import agent_settings

_llm = None
_embeddings = None


def get_llm() -> ChatOpenAI:
    """获取 OpenAI LLM 实例（单例），支持自定义 base_url 兼容第三方"""
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=agent_settings.OPENAI_LLM_MODEL,
            openai_api_key=agent_settings.OPENAI_API_KEY,
            openai_api_base=agent_settings.OPENAI_BASE_URL,
            temperature=0.3,
            max_tokens=1024,
        )
    return _llm


def get_embeddings() -> OpenAIEmbeddings:
    """获取 OpenAI Embeddings 实例（单例），使用独立的 key 和 base_url"""
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=agent_settings.OPENAI_EMBED_MODEL,
            openai_api_key=agent_settings.OPENAI_EMBED_API_KEY,
            openai_api_base=agent_settings.OPENAI_EMBED_BASE_URL,
        )
    return _embeddings
