"""节点②：RAG 双库检索 + 加权重排序"""
from app.state import AgentState
from app.agent.utils.milvus_client import search_with_score

GOLD_WEIGHT = 0.7
STANDARD_WEIGHT = 0.3


async def rag_reranked(state: AgentState) -> AgentState:
    dish_name = state.get("dish_name", "")
    keyword_summary = state.get("keyword_summary", "")

    query = f"{dish_name} {keyword_summary[:300]}"
    gold_context = ""
    standard_context = ""
    reranked_parts = []

    try:
        gold = await search_with_score("gold_collection", query, k=3)
        std = await search_with_score("standard_collection", query, k=3)

        all_items = []
        for r in gold:
            all_items.append({
                "content": r["content"],
                "score": r["score"],
                "source": "GOLD",
                "weighted_score": r["score"] * GOLD_WEIGHT,
            })
        for r in std:
            all_items.append({
                "content": r["content"],
                "score": r["score"],
                "source": "STANDARD",
                "weighted_score": r["score"] * STANDARD_WEIGHT,
            })

        all_items.sort(key=lambda x: x["weighted_score"], reverse=True)

        gold_items = [it for it in all_items if it["source"] == "GOLD"]
        std_items = [it for it in all_items if it["source"] == "STANDARD"]

        if gold_items or std_items:
            reranked_parts.append("## 历史相似客诉处理经验（已按权重重排序）")

        if gold_items:
            gold_context = "\n".join(
                f"[GOLD] [加权分 {it['weighted_score']:.2f}] {it['content'][:400]}"
                for it in gold_items
            )
            reranked_parts.append("\n### 🏅 金标经验（管理层认证，权重 0.7，请重点参考）")
            for it in gold_items:
                reranked_parts.append(f"\n[GOLD] [加权分 {it['weighted_score']:.2f}]")
                reranked_parts.append(it["content"][:600])

        if std_items:
            standard_context = "\n".join(
                f"[STANDARD] [加权分 {it['weighted_score']:.2f}] {it['content'][:400]}"
                for it in std_items
            )
            reranked_parts.append("\n### 📋 普通经验（供辅助借鉴，权重 0.3）")
            for it in std_items:
                reranked_parts.append(f"\n[STANDARD] [加权分 {it['weighted_score']:.2f}]")
                reranked_parts.append(it["content"][:600])
    except Exception:
        reranked_parts.append("（历史经验检索暂不可用）")

    return {
        **state,
        "gold_context": gold_context,
        "standard_context": standard_context,
        "reranked_knowledge": "\n".join(reranked_parts),
    }
