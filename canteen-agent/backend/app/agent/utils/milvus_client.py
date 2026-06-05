"""Milvus 向量库连接工具 —— 双库（standard / gold）"""
from pymilvus import connections, Collection
from langchain_milvus import MilvusVectorStore
from app.agent.utils.llm import get_embeddings
from app.agent.config import agent_settings

_stores = {}
_pymilvus_connected = False


def _ensure_pymilvus():
    global _pymilvus_connected
    if not _pymilvus_connected:
        connections.connect(
            alias="default",
            host=agent_settings.MILVUS_HOST,
            port=str(agent_settings.MILVUS_PORT),
        )
        _pymilvus_connected = True


def get_milvus_store(collection_name: str) -> MilvusVectorStore:
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


async def search_with_score(collection_name: str, query: str, k: int = 3) -> list[dict]:
    store = get_milvus_store(collection_name)
    try:
        docs_with_scores = store.similarity_search_with_score(query, k=k)
        return [
            {
                "content": doc.page_content,
                "score": score,
                "metadata": doc.metadata or {},
            }
            for doc, score in docs_with_scores
        ]
    except Exception:
        return []


async def write_to_standard(decision_id: str, dish_name: str, content: str) -> dict:
    _ensure_pymilvus()
    try:
        col = Collection("standard_collection")
        col.load()

        embeddings = get_embeddings()
        vector = embeddings.embed_query(content)

        col.insert([
            [decision_id],
            [f"【菜品：{dish_name}】\n{content}"],
            [vector],
        ])
        col.flush()
        return {"status": "written", "decision_id": decision_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def promote_to_gold(decision_id: str, modified_content: str | None = None) -> dict:
    _ensure_pymilvus()

    standard_col = Collection("standard_collection")
    gold_col = Collection("gold_collection")

    standard_col.load()
    results = standard_col.query(
        expr=f'decision_id == "{decision_id}"',
        output_fields=["*"],
    )
    if not results:
        return {"status": "not_found", "decision_id": decision_id}

    row = results[0]

    if modified_content:
        content = modified_content
        embeddings = get_embeddings()
        vector = embeddings.embed_query(content)
    else:
        content = row.get("content", "")
        vector = row["vector"]

    gold_col.load()
    gold_col.insert([
        [decision_id],
        [content],
        [vector],
    ])
    gold_col.flush()

    standard_col.delete(f'decision_id == "{decision_id}"')
    standard_col.flush()

    return {
        "status": "promoted",
        "decision_id": decision_id,
        "from": "standard_collection",
        "to": "gold_collection",
        "modified": modified_content is not None,
    }
