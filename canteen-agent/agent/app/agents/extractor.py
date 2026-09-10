"""提取专家 Worker（A）—— 结构化事实提取

职责：把顾客评价抽成结构化事实（问题维度 / 严重度 / 频次 / 证据原文），供分析专家使用。
内部线路固定：LLM 语义 NER（失败降级词典）→ 按维度归并计数。
工具权限：extract_entities、get_dish_info
"""
from app.nodes.entity_extraction import entity_extraction
from app.state import AgentState


def _build_facts(reviews: list[dict], ner_results: list[dict], weights: dict) -> dict:
    """把 NER 结果归并成「按维度」的结构化事实"""
    dim_stats: dict[str, dict] = {}
    safety_flags: list[dict] = []

    for review, ner in zip(reviews, ner_results):
        dim = ner.get("dimension") or "其他"
        severity = ner.get("severity", 1)

        stat = dim_stats.setdefault(dim, {
            "count": 0,
            "severity_sum": 0,
            "keywords": [],
            "evidence": [],
            "is_preference": 0,
            "weight": weights.get(dim, 1.0),
        })
        stat["count"] += 1
        stat["severity_sum"] += severity
        if ner.get("issue"):
            stat["keywords"].append(ner["issue"])
        if review.get("review_id") is not None:
            stat["evidence"].append(review["review_id"])
        if ner.get("is_preference"):
            stat["is_preference"] += 1

        if ner.get("event_type") == "safety_incident" or dim == "安全":
            safety_flags.append({
                "review_id": review.get("review_id"),
                "issue": ner.get("issue", ""),
                "severity": severity,
            })

    for stat in dim_stats.values():
        count = stat["count"] or 1
        stat["avg_severity"] = round(stat["severity_sum"] / count, 2)
        stat["keywords"] = list(dict.fromkeys(stat["keywords"]))[:5]
        del stat["severity_sum"]

    return {
        "dimension_stats": dim_stats,
        "safety_flags": safety_flags,
        "review_count": len(reviews),
        "negative_count": sum(1 for r in reviews if r.get("sentiment") == "negative"),
    }


async def extractor_node(state: AgentState) -> dict:
    """只返回本 Worker 负责的键，不返回 {**state}（见 state.py 约定）"""
    enriched = await entity_extraction(dict(state))
    reviews = enriched.get("reviews", [])
    ner_results = enriched.get("ner_results", [])

    return {
        "reviews": reviews,
        "ner_results": ner_results,
        "facts": _build_facts(reviews, ner_results, state.get("keyword_weights") or {}),
    }
