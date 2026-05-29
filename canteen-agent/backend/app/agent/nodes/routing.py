"""节点②：Dish Routing — 单条评论菜品消歧"""
from app.state import AgentState
from app.prompts.templates import DISH_ROUTING_PROMPT
from app.utils.llm import get_llm
from app.utils.milvus_client import get_milvus_store


async def dish_routing(state: AgentState) -> AgentState:
    """
    对单条评论做菜品消歧，三级梯次：L2 Milvus 向量 → L3 LLM 语义 → 失败标记 UNKNOWN
    """
    review = state.get("filtered_review", {})
    if not review or not review.get("raw_text"):
        return {**state, "dish_info": {"dish_id": "UNKNOWN", "match_confidence": 0.0}, "risk_level": 1}

    review_text = review.get("raw_text", "")
    stall_name = review.get("stall_name", "")
    meal_time = review.get("meal_time", "lunch")

    # L2: Milvus 向量
    try:
        vector_store = get_milvus_store("dish_index")
        results = vector_store.similarity_search(review_text, k=3)
        if results:
            best = results[0]
            confidence = 0.7 + (1.0 - best.metadata.get("distance", 0.3)) * 0.25
            if confidence >= 0.6:
                return {
                    **state,
                    "dish_info": {
                        "dish_id": best.metadata.get("dish_id", "UNKNOWN"),
                        "dish_name": best.metadata.get("dish_name", "未知菜品"),
                        "stall_name": stall_name,
                        "meal_time": meal_time,
                        "match_confidence": round(confidence, 2),
                        "match_method": "vector_L2",
                    },
                    "risk_level": review.get("severity", 3),
                }
    except Exception:
        pass

    # L3: LLM 语义
    try:
        llm = get_llm()
        prompt = DISH_ROUTING_PROMPT.format(
            meal_time=meal_time, stall_name=stall_name,
            review_text=review_text[:500], daily_menu="[]",
        )
        result = await llm.ainvoke(prompt)
        import json, re
        json_match = re.search(r"\{.*\}", result.content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return {
                **state,
                "dish_info": {
                    "dish_id": data.get("dish_id", "UNKNOWN"),
                    "dish_name": data.get("dish_name", "未知菜品"),
                    "stall_name": stall_name,
                    "meal_time": meal_time,
                    "match_confidence": data.get("confidence", 0.5),
                    "match_method": "llm_L3",
                },
                "risk_level": review.get("severity", 3),
            }
    except Exception:
        pass

    return {
        **state,
        "dish_info": {"dish_id": "UNKNOWN", "dish_name": "未知菜品", "stall_name": stall_name, "meal_time": meal_time, "match_confidence": 0.0, "match_method": "failed"},
        "risk_level": 4,
    }
