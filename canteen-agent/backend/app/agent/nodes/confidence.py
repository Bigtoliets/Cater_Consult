"""节点5：Confidence Evaluation —— 置信度评估"""
from app.agent.state import AgentState
from app.config import settings


async def confidence_evaluation(state: AgentState) -> AgentState:
    filtered = state.get("filtered_reviews", [])
    dish_info = state.get("dish_info", {})
    knowledge = state.get("knowledge_context", "")
    conflict = state.get("conflict_analysis", {})

    sample_count = len(filtered)
    sample_density = min(sample_count / 10.0, 1.0) if sample_count > 0 else 0.0

    sop_score = 0.3
    if "SOP标准卡" in knowledge and "检索不可用" not in knowledge:
        sop_score = 0.8
    if "历史客诉" in knowledge and "检索不可用" not in knowledge:
        sop_score += 0.1
    sop_score = min(sop_score, 1.0)

    evidence = conflict.get("evidence", [])
    history_score = min(len(evidence) / 5.0, 1.0) if evidence else 0.2

    confidence = sample_density * 0.3 + sop_score * 0.4 + history_score * 0.3

    if dish_info.get("dish_id") == "UNKNOWN":
        confidence = min(confidence, 0.4)

    threshold = settings.AGENT_CONFIDENCE_THRESHOLD
    human_review = confidence < threshold or state.get("risk_level", 1) >= 4

    return {**state, "confidence": round(confidence, 2), "human_review_required": human_review}
