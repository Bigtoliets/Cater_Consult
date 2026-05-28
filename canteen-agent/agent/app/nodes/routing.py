"""节点2：Dish Routing —— 菜品实体消歧"""
from app.state import AgentState
from app.prompts.templates import DISH_ROUTING_PROMPT
from app.utils.llm import get_llm
from app.utils.milvus_client import get_milvus_store


async def dish_routing(state: AgentState) -> AgentState:
    """
    将用户口语化的菜品描述精确匹配到系统菜品ID
    三级梯次：L1 精确匹配 → L2 向量模糊匹配 → L3 LLM 语义推断
    """
    filtered = state.get("filtered_reviews", [])
    if not filtered:
        return {
            **state,
            "dish_info": {"dish_id": "UNKNOWN", "match_confidence": 0.0},
            "risk_level": 1,
        }

    # 取第一条负面评价进行消歧
    negative_reviews = [r for r in filtered if r.get("sentiment") == "negative"]
    target = negative_reviews[0] if negative_reviews else filtered[0]
    review_text = target.get("raw_text", "")
    stall_name = target.get("stall_name", "")
    meal_time = target.get("meal_time", "lunch")

    # L1: 精确匹配（此处为示意，生产环境通过 SQL 查询）
    # L2: Milvus 向量模糊匹配
    try:
        vector_store = get_milvus_store("dish_index")
        results = vector_store.similarity_search(review_text, k=3)
        if results and len(results) > 0:
            best = results[0]
            confidence = 0.7 + (1.0 - best.metadata.get("distance", 0.3)) * 0.25
            dish_info = {
                "dish_id": best.metadata.get("dish_id", "UNKNOWN"),
                "dish_name": best.metadata.get("dish_name", "未知菜品"),
                "stall_name": stall_name,
                "meal_time": meal_time,
                "match_confidence": round(confidence, 2),
                "match_method": "vector_L2",
            }
            if confidence >= 0.6:
                return {
                    **state,
                    "dish_info": dish_info,
                    "risk_level": target.get("severity", 3),
                }
    except Exception:
        pass  # Milvus 不可用时降级到 L3

    # L3: LLM 语义推断
    try:
        llm = get_llm()
        prompt = DISH_ROUTING_PROMPT.format(
            meal_time=meal_time,
            stall_name=stall_name,
            review_text=review_text[:500],
            daily_menu="[]",
        )
        result = await llm.ainvoke(prompt)

        import json
        import re
        json_match = re.search(r"\{.*\}", result.content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            dish_info = {
                "dish_id": data.get("dish_id", "UNKNOWN"),
                "dish_name": data.get("dish_name", "未知菜品"),
                "stall_name": stall_name,
                "meal_time": meal_time,
                "match_confidence": data.get("confidence", 0.5),
                "match_method": "llm_L3",
            }
            return {
                **state,
                "dish_info": dish_info,
                "risk_level": target.get("severity", 3),
            }
    except Exception:
        pass

    # 三级匹配全部失败 → 标记 UNKNOWN，提升风险等级
    return {
        **state,
        "dish_info": {
            "dish_id": "UNKNOWN",
            "dish_name": "未知菜品",
            "stall_name": stall_name,
            "meal_time": meal_time,
            "match_confidence": 0.0,
            "match_method": "failed",
        },
        "risk_level": 4,  # 强制提升至 4，触发人工复核
    }
