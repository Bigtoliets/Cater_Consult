"""节点5：Confidence Evaluation —— 置信度评估"""
from app.state import AgentState


async def confidence_evaluation(state: AgentState) -> AgentState:
    """
    三维加权计算综合置信度：
    - 样本密度权重 (0.3)
    - SOP 映射度权重 (0.4)
    - 历史相似度权重 (0.3)
    """
    filtered = state.get("filtered_reviews", [])
    dish_info = state.get("dish_info", {})
    knowledge = state.get("knowledge_context", "")
    conflict = state.get("conflict_analysis", {})

    # 1. 样本密度 (0.3) —— 评价数量越多置信度越高
    sample_count = len(filtered)
    sample_density = min(sample_count / 10.0, 1.0) if sample_count > 0 else 0.0

    # 2. SOP 映射度 (0.4) —— 知识库中有相关 SOP 则置信度高
    sop_score = 0.3  # 基础分
    if "SOP标准卡" in knowledge and "检索不可用" not in knowledge:
        sop_score = 0.8
    if "历史客诉" in knowledge and "检索不可用" not in knowledge:
        sop_score += 0.1
    sop_score = min(sop_score, 1.0)

    # 3. 历史相似度 (0.3) —— 冲突检测证据充分度
    evidence = conflict.get("evidence", [])
    history_score = min(len(evidence) / 5.0, 1.0) if evidence else 0.2

    # 综合计算
    confidence = (
        sample_density * 0.3 +
        sop_score * 0.4 +
        history_score * 0.3
    )

    # 消歧失败 → 强制降低置信度
    if dish_info.get("dish_id") == "UNKNOWN":
        confidence = min(confidence, 0.4)

    from app.config import agent_settings
    threshold = agent_settings.AGENT_CONFIDENCE_THRESHOLD
    human_review = confidence < threshold or state.get("risk_level", 1) >= 4

    return {
        **state,
        "confidence": round(confidence, 2),
        "human_review_required": human_review,
    }
