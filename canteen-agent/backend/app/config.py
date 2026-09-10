"""应用配置管理 —— 从环境变量加载"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === MySQL ===
    MYSQL_HOST: str = "192.168.10.20"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "changeme_2024"
    MYSQL_DATABASE: str = "canteen_agent"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    # === Redis ===
    REDIS_HOST: str = "192.168.10.20"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

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

    # === Agent ===
    AGENT_CONFIDENCE_THRESHOLD: float = 0.75
    AGENT_RAG_TOP_K: int = 3
    AGENT_RAG_SIMILARITY_THRESHOLD: float = 0.6

    # === Agent 微服务 ===
    AGENT_INTERNAL_URL: str = "http://agent:8001"

    # === Backend ===
    BACKEND_SECRET_KEY: str = "dev-secret-change-in-production"
    BACKEND_PORT: int = 8000

    # === 自动同步 ===
    # 每隔多少分钟把「synced_at 为空」的评论推入分析队列；设为 0 表示关闭自动同步，
    # 只保留 POST /api/v1/sync 手动触发。
    AUTO_SYNC_INTERVAL_MINUTES: int = 5

    # === 推送通道 (v3.0 新增) ===
    WECOM_WEBHOOK_URL: str = ""         # 企业微信 Bot Webhook
    DINGTALK_WEBHOOK_URL: str = ""      # 钉钉 Bot Webhook
    DINGTALK_SECRET: str = ""           # 钉钉加签密钥
    SMTP_HOST: str = ""                 # 邮件 SMTP
    SMTP_PORT: int = 465
    SMTP_SENDER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_RECIPIENTS: str = ""           # 逗号分隔

    class Config:
        env_file = "../.env"
        extra = "allow"


settings = Settings()
