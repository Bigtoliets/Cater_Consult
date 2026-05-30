"""Agent 配置"""
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    MILVUS_HOST: str = "192.168.10.20"
    MILVUS_PORT: int = 19530

    class Config:
        env_file = ".env"
        extra = "allow"


agent_settings = AgentSettings()
