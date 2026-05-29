"""节点③：RAG 双库经验检索 — 单条评论独立检索"""
from app.state import AgentState
from app.utils.milvus_client import search_with_score
from app.config import agent_settings


async def rag_retrieval(state: AgentState) -> AgentState:
    """
    用当前这一条评论的 dish_name + summary 查双库，
    结果打 [GOLD] / [STANDARD] 标签直接拼接
    """
    dish_info = state.get("dish_info", {})
    review = state.get("filtered_review", {})

    # 短路
    if review.get("sentiment") == "positive":
        return {**state, "knowledge_context": ""}
    if dish_info.get("dish_id") == "UNKNOWN":
        return {**state, "knowledge_context": ""}

    query = f"{dish_info.get('dish_name', '')} {review.get('summary', '')}"
    knowledge_parts = []

    try:
        gold = await search_with_score("gold_collection", query, k=agent_settings.AGENT_RAG_TOP_K)
        std = await search_with_score("standard_collection", query, k=agent_settings.AGENT_RAG_TOP_K)

        if gold or std:
            knowledge_parts.append("## 历史相似客诉处理经验")

        if gold:
            knowledge_parts.append("\n### 🏅 金标经验（管理层认证，请重点参考）")
            for r in gold:
                knowledge_parts.append(f"\n[GOLD] [相似度 {r['score']:.2f}]")
                knowledge_parts.append(r["content"][:600])

        if std:
            knowledge_parts.append("\n### 📋 普通经验（供辅助借鉴）")
            for r in std:
                knowledge_parts.append(f"\n[STANDARD] [相似度 {r['score']:.2f}]")
                knowledge_parts.append(r["content"][:600])
    except Exception:
        knowledge_parts.append("（历史经验检索暂不可用）")

    return {**state, "knowledge_context": "\n".join(knowledge_parts) if knowledge_parts else ""}
