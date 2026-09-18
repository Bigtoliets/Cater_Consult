"""Milvus 向量库连接工具 — 双库（standard / gold）+ 问答会话记忆库（memory）"""
import logging

from pymilvus import connections, Collection, utility
from langchain_milvus import Milvus
from app.utils.llm import get_embeddings
from app.config import agent_settings
from openai import OpenAI

logger = logging.getLogger(__name__)

_embed_client = None


def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        _embed_client = OpenAI(
            api_key=agent_settings.OPENAI_EMBED_API_KEY,
            base_url=agent_settings.OPENAI_EMBED_BASE_URL,
        )
    return _embed_client


def _embed_text(text: str) -> list[float]:
    """直接用 OpenAI 客户端调 embedding，绕过 langchain 兼容性问题"""
    client = _get_embed_client()
    resp = client.embeddings.create(model=agent_settings.OPENAI_EMBED_MODEL, input=text)
    return resp.data[0].embedding

_stores = {}
_pymilvus_connected = False


def _ensure_pymilvus():
    """确保 pymilvus 原生连接已建立（用于跨库迁移等底层操作）"""
    global _pymilvus_connected
    if not _pymilvus_connected:
        connections.connect(
            alias="default",
            host=agent_settings.MILVUS_HOST,
            port=str(agent_settings.MILVUS_PORT),
        )
        _pymilvus_connected = True


def get_milvus_store(collection_name: str) -> Milvus:
    """获取 Milvus Collection 实例（按名称缓存，langchain 接口）"""
    global _stores
    if collection_name not in _stores:
        _stores[collection_name] = Milvus(
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


async def search_with_score(
    collection_name: str, query: str, k: int = 3, expr: str | None = None
) -> list[dict]:
    """向量检索（pymilvus 原生，绕过 langchain 兼容问题），返回 [{content, score, metadata}]

    expr: 可选标量过滤表达式（例如只取某个会话的记忆），None = 不过滤。
    """
    import traceback
    _ensure_pymilvus()
    try:
        col = Collection(collection_name)
        col.load()

        query_vec = _embed_text(query)

        search_params = {"metric_type": "IP", "params": {"nprobe": 16}}
        results = col.search(
            data=[query_vec],
            anns_field="vector",
            param=search_params,
            limit=k,
            output_fields=["decision_id", "content"],
            expr=expr,
        )

        items = []
        for hits in results:
            for hit in hits:
                items.append({
                    "content": hit.entity.get("content", ""),
                    "score": hit.distance,
                    "metadata": {"decision_id": hit.entity.get("decision_id", "")},
                })
        return items
    except Exception:
        traceback.print_exc()
        return []


async def write_to_standard(decision_id: str, dish_name: str, content: str) -> dict:
    """
    将新生成的整改单写入 standard_collection（静默沉淀为普通经验）
    绑定 decision_id，供后续检索和飞升
    """
    import traceback
    _ensure_pymilvus()
    try:
        col = Collection("standard_collection")
        col.load()

        # 用原生 OpenAI 客户端调 embedding（避开 langchain 兼容问题）
        vector = _embed_text(content)

        col.insert([
            [decision_id],
            [f"【菜品：{dish_name}】\n{content}"],
            [vector],
        ])
        col.flush()
        print(f"[Milvus] 写入成功 decision_id={decision_id} dish={dish_name}")
        return {"status": "written", "decision_id": decision_id}
    except Exception as e:
        print(f"[Milvus] 写入失败 decision_id={decision_id}: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


async def write_to_memory(decision_id: str, content: str) -> dict:
    """问答会话记忆写入 memory_collection

    单独一个库的原因：会话记忆（Q/A 摘要）和菜品经验是两种东西。以前写进
    standard_collection，会被「普通经验」检索当成整改经验引用，甚至能被飞升成金标。
    """
    import traceback
    _ensure_pymilvus()
    try:
        col = Collection("memory_collection")
        col.load()
        vector = _embed_text(content)
        col.insert([[decision_id], [content], [vector]])
        col.flush()
        logger.info(f"[Milvus] 会话记忆写入成功 id={decision_id}")
        return {"status": "written", "decision_id": decision_id}
    except Exception as e:
        logger.warning(f"[Milvus] 会话记忆写入失败 id={decision_id}: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


async def promote_to_gold(decision_id: str, modified_content: str | None = None) -> dict:
    """
    跨库迁移：从 standard_collection 读取 → 写入 gold_collection → 删除 standard 中该条
    若传了 modified_content，则以人工修改后的版本飞升（重新向量化）
    """
    _ensure_pymilvus()

    standard_col = Collection("standard_collection")
    gold_col = Collection("gold_collection")

    # 1) 从 standard 按 ID 精确查询
    standard_col.load()
    results = standard_col.query(
        expr=f'decision_id == "{decision_id}"',
        output_fields=["*"],
    )
    if not results:
        return {"status": "not_found", "decision_id": decision_id}

    row = results[0]

    # 2) 决定飞升的内容和向量
    if modified_content:
        content = modified_content
        vector = _embed_text(content)
    else:
        content = row.get("content", "")
        vector = row["vector"]

    # 3) 写入 gold_collection
    gold_col.load()
    gold_col.insert([
        [decision_id],
        [content],
        [vector],
    ])
    gold_col.flush()

    # 4) 从 standard 删除
    standard_col.delete(f'decision_id == "{decision_id}"')
    standard_col.flush()

    return {
        "status": "promoted",
        "decision_id": decision_id,
        "from": "standard_collection",
        "to": "gold_collection",
        "modified": modified_content is not None,
    }
