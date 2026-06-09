"""节点 2.5：多因子置信度评估 (v3.0 新增)

五因子置信度模型:
1. data_sufficiency (0.15): 评价数量充裕度
2. review_consistency (0.20): 评价一致性 (1 - 矛盾占比)
3. knowledge_match (0.30): RAG 检索最高相似度
4. sop_coverage (0.20): 该菜品 SOP 覆盖度
5. problem_solvability (0.15): 问题可解度

输出:
- confidence_score ≥ 0.75 → auto_publish
- 0.50 ≤ score < 0.75 → publish_with_review
- score < 0.50 → escalate_to_human
"""
import re
from app.state import AgentState

FACTOR_WEIGHTS = {
    "data_sufficiency": 0.15,
    "review_consistency": 0.20,
    "knowledge_match": 0.30,
    "sop_coverage": 0.20,
    "problem_solvability": 0.15,
}


async def confidence_evaluation(state: AgentState) -> AgentState:
    """多因子置信度评估节点"""
    reviews = state.get("reviews", [])
    total = len(reviews)

    # ── 1. 数据充分度: 评价数量 / 最低样本量 (≥5) ──
    data_suff = min(1.0, total / 5)

    # ── 2. 评价一致性: 1 - (偏好差异评价占比) ──
    pref_count = sum(
        1 for r in reviews
        if r.get("ner_entities", {}).get("is_preference", False)
    )
    consistency = 1 - (pref_count / total if total > 0 else 0)

    # ── 3. 知识匹配度: 从 RAG 结果解析最高加权分 ──
    reranked = state.get("reranked_knowledge", "")
    knowledge_match = 0.3  # 默认低匹配
    if "加权分" in reranked:
        scores = re.findall(r'加权分\s*([\d.]+)', reranked)
        if scores:
            knowledge_match = min(1.0, max(float(s) for s in scores))

    # ── 4. SOP 覆盖度 ──
    keyword_summary = state.get("keyword_summary", "")
    sop_coverage = 0.0
    if "SOP" in keyword_summary or "工艺" in keyword_summary:
        sop_coverage = 0.5
    if state.get("gold_context"):
        sop_coverage = max(sop_coverage, 0.7)
    if state.get("standard_context"):
        sop_coverage = max(sop_coverage, 0.5)

    # ── 5. 问题可解度 ──
    conflicts = state.get("conflict_analysis", [])
    if conflicts:
        actionable = [c for c in conflicts if c.get("should_trigger", False)]
        solvable_ratio = len(actionable) / len(conflicts)
        problem_solvability = 0.3 + 0.7 * solvable_ratio
    else:
        problem_solvability = 0.5

    # ── 加权计算 ──
    confidence = (
        data_suff * FACTOR_WEIGHTS["data_sufficiency"]
        + consistency * FACTOR_WEIGHTS["review_consistency"]
        + knowledge_match * FACTOR_WEIGHTS["knowledge_match"]
        + sop_coverage * FACTOR_WEIGHTS["sop_coverage"]
        + problem_solvability * FACTOR_WEIGHTS["problem_solvability"]
    )
    confidence = round(confidence, 2)

    # ── 决策 ──
    if confidence >= 0.75:
        action = "auto_publish"
    elif confidence >= 0.50:
        action = "publish_with_review"
    else:
        action = "escalate_to_human"

    # 安全事件强制升级
    has_safety = any(
        r.get("ner_entities", {}).get("event_type") == "safety_incident"
        for r in reviews
    )
    if has_safety:
        action = "escalate_to_human"

    return {
        **state,
        "confidence_score": confidence,
        "confidence_action": action,
        "confidence_factors": {
            "data_sufficiency": round(data_suff, 2),
            "review_consistency": round(consistency, 2),
            "knowledge_match": round(knowledge_match, 2),
            "sop_coverage": round(sop_coverage, 2),
            "problem_solvability": round(problem_solvability, 2),
        },
        "human_review_required": action != "auto_publish",
        "workflow_stage": "confidence_done",
    }
