"""LLM / Embedding 连接工具 —— OpenAI 兼容接口"""
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.config import agent_settings

_llm = None
_embeddings = None


def get_llm(temperature: float = 0.3, max_tokens: int = 1024) -> ChatOpenAI:
    """获取 OpenAI LLM 实例，支持自定义 temperature

    注意: 每次调用可能返回不同实例 (temperature 不同时).
    对于默认 temperature=0.3 使用单例，其他 temperature 创建新实例.
    """
    global _llm
    if temperature == 0.3 and _llm is not None:
        return _llm

    instance = ChatOpenAI(
        model=agent_settings.OPENAI_LLM_MODEL,
        openai_api_key=agent_settings.OPENAI_API_KEY,
        openai_api_base=agent_settings.OPENAI_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if temperature == 0.3:
        _llm = instance
    return instance


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
