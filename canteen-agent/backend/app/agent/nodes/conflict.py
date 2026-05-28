"""节点4：Conflict Detection —— 冲突检测"""
from app.agent.state import AgentState
from app.agent.prompts.templates import CONFLICT_DETECTION_PROMPT
from app.agent.utils.llm import get_llm


async def conflict_detection(state: AgentState) -> AgentState:
    filtered = state.get("filtered_reviews", [])
    dish_info = state.get("dish_info", {})
    knowledge = state.get("knowledge_context", "")

    if not filtered:
        return {**state, "conflict_analysis": {
            "conflict_type": "INSUFFICIENT_DATA", "evidence": [],
            "summary": "无有效评价数据", "is_batch_issue": False,
        }}

    dimension_scores = {}
    for review in filtered:
        for dim in review.get("dimensions", []):
            key = dim.get("dimension", "其他")
            if key not in dimension_scores:
                dimension_scores[key] = []
            dimension_scores[key].append(dim.get("severity", 1))

    high_variance_dims = []
    for dim, scores in dimension_scores.items():
        if len(scores) >= 2:
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            if variance > 1.5:
                high_variance_dims.append(dim)

    try:
        llm = get_llm()
        review_samples = "\n".join([
            f"- {r.get('summary', r.get('raw_text', '')[:100])}" for r in filtered[:10]
        ])
        prompt = CONFLICT_DETECTION_PROMPT.format(
            dish_name=dish_info.get("dish_name", "未知菜品"),
            sop_context=knowledge[:2000], review_samples=review_samples,
        )
        result = await llm.ainvoke(prompt)
        import json, re
        json_match = re.search(r"\{.*\}", result.content, re.DOTALL)
        analysis = json.loads(json_match.group(0)) if json_match else {}
    except Exception:
        analysis = {
            "conflict_type": "TASTE_PREFERENCE" if high_variance_dims else "QUALITY_FLUCTUATION",
            "evidence": [
                f"维度 '{dim}' 存在高方差 (众口难调)" if dim in high_variance_dims
                else f"维度 '{dim}' 共识度高 (品控波动)"
                for dim in dimension_scores
            ],
            "summary": "基于规则引擎的初步分析",
            "is_batch_issue": len(high_variance_dims) < len(dimension_scores) * 0.5,
        }

    return {**state, "conflict_analysis": analysis}
