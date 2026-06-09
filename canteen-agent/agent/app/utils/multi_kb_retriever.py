"""五维知识库检索器 (v3.0 新增)

五个 Collection 并行检索 + 自适应加权重排序:
- sop_collection     (权重 0.30): 菜品标准工艺
- pattern_collection (权重 0.25): 问题→根因→方案映射
- cycle_collection   (权重 0.10): 季节/周度/时段规律
- gold_collection    (权重 0.25): 管理层认证金标经验
- standard_collection(权重 0.10): 普通历史经验
"""
import asyncio
from app.utils.milvus_client import search_with_score

KB_WEIGHTS = {
    "sop_collection": 0.30,
    "pattern_collection": 0.25,
    "cycle_collection": 0.10,
    "gold_collection": 0.25,
    "standard_collection": 0.10,
}

COLLECTION_LABELS = {
    "sop_collection": "📋 标准工艺",
    "pattern_collection": "🔍 问题模式",
    "cycle_collection": "📈 周期规律",
    "gold_collection": "🏅 金标经验",
    "standard_collection": "📝 普通经验",
}


async def multi_kb_search(query: str, top_k: int = 5) -> dict:
    """
    五库并行检索 → 加权重排序 → 返回 top_k

    返回:
    {
        "top_k": [{"content":..., "weighted_score":..., "source":..., "label":...}],
        "sources_breakdown": {
            "sop_collection": {"count":..., "max_score":..., "label":...},
            ...
        },
        "has_gold": bool,
        "has_sop": bool,
        "total_candidates": int,
    }
    """
    # 并行检索
    collections = list(KB_WEIGHTS.keys())
    ks = [3, 3, 2, 3, 2]  # 各库检索数量

    try:
        results_list = await asyncio.gather(
            *[search_with_score(col, query, k=k) for col, k in zip(collections, ks)],
            return_exceptions=True,
        )
    except Exception:
        return _empty_result()

    # 加权重排序
    all_items = []
    sources_breakdown = {}

    for col, items, weight in zip(collections, results_list, KB_WEIGHTS.values()):
        if isinstance(items, Exception):
            items = []

        max_score = max((i["score"] for i in items), default=0)
        sources_breakdown[col] = {
            "count": len(items),
            "max_score": round(max_score, 3),
            "label": COLLECTION_LABELS.get(col, col),
            "weight": weight,
        }

        for item in items:
            all_items.append({
                "content": item.get("content", ""),
                "score": item.get("score", 0),
                "weighted_score": round(item.get("score", 0) * weight, 3),
                "source": col,
                "label": COLLECTION_LABELS.get(col, col),
                "metadata": item.get("metadata", {}),
            })

    all_items.sort(key=lambda x: x["weighted_score"], reverse=True)

    return {
        "top_k": all_items[:top_k],
        "sources_breakdown": sources_breakdown,
        "has_gold": sources_breakdown.get("gold_collection", {}).get("count", 0) > 0,
        "has_sop": sources_breakdown.get("sop_collection", {}).get("count", 0) > 0,
        "total_candidates": len(all_items),
    }


def _empty_result() -> dict:
    return {
        "top_k": [],
        "sources_breakdown": {},
        "has_gold": False,
        "has_sop": False,
        "total_candidates": 0,
    }


def format_kb_context(multi_result: dict) -> str:
    """将多库检索结果格式化为 LLM 可用的上下文字符串"""
    top_k = multi_result.get("top_k", [])
    if not top_k:
        return "（知识库中暂无相关经验）"

    parts = ["## 📚 五维知识库检索结果（已按权重重排序）\n"]

    # 来源概览
    breakdown = multi_result.get("sources_breakdown", {})
    parts.append("### 检索覆盖")
    for col, info in breakdown.items():
        if info["count"] > 0:
            parts.append(
                f"- {info['label']} (权重{info['weight']:.0%}): "
                f"命中 {info['count']} 条, 最高相似度 {info['max_score']:.2f}"
            )

    # 详细结果
    parts.append("\n### 详细结果")
    for i, item in enumerate(top_k, 1):
        parts.append(f"\n**[{i}] {item['label']}** [加权分 {item['weighted_score']:.2f}]")
        parts.append(item["content"][:600])

    return "\n".join(parts)
