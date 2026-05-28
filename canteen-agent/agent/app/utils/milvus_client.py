"""Milvus 向量库连接工具"""
from langchain_milvus import MilvusVectorStore
from app.utils.llm import get_embeddings
from app.config import agent_settings

_stores = {}


def get_milvus_store(collection_name: str) -> MilvusVectorStore:
    """获取 Milvus Collection 实例（按名称缓存）"""
    global _stores
    if collection_name not in _stores:
        _stores[collection_name] = MilvusVectorStore(
            collection_name=collection_name,
            embedding_function=get_embeddings(),
            connection_args={
                "host": agent_settings.MILVUS_HOST,
                "port": str(agent_settings.MILVUS_PORT),
            },
            index_params={
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128},
            },
        )
    return _stores[collection_name]
