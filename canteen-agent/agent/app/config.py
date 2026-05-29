"""Agent 微服务配置"""
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    # === OpenAI LLM ===
    OPENAI_API_KEY: str = "sk-your-api-key-here"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_LLM_MODEL: str = "gpt-4o"

    # === OpenAI Embedding ===
    OPENAI_EMBED_API_KEY: str = "sk-your-api-key-here"
    OPENAI_EMBED_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"

    # === Milvus ===
    MILVUS_HOST: str = "192.168.10.20"
    MILVUS_PORT: int = 19530

    # === Redis ===
    REDIS_HOST: str = "192.168.10.20"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

    # === RabbitMQ ===
    RABBITMQ_HOST: str = "192.168.10.20"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "admin"
    RABBITMQ_PASSWORD: str = "changeme_2024"

    @property
    def RABBITMQ_URL(self) -> str:
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/"
        )

    # === Agent ===
    AGENT_CONFIDENCE_THRESHOLD: float = 0.75
    AGENT_RAG_TOP_K: int = 3
    AGENT_RAG_SIMILARITY_THRESHOLD: float = 0.6



    class Config:
        env_file = "../.env"
        extra = "allow"


agent_settings = AgentSettings()
