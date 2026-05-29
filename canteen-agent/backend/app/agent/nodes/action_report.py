"""节点④：Action Report — 单条评论生成整改单"""
from app.state import AgentState
from app.prompts.templates import CORRECTIVE_ACTION_PROMPT
from app.utils.llm import get_llm


async def action_report(state: AgentState) -> AgentState:
    """
    基于单条差评 + 双库检索到的历史经验，LLM 柔性生成整改单
    """
    dish_info = state.get("dish_info", {})
    review = state.get("filtered_review", {})
    knowledge = state.get("knowledge_context", "")
    dish_name = dish_info.get("dish_name", "未知菜品")

    # 正面评价 → 不生成整改单
    if review.get("sentiment") == "positive":
        return {**state, "corrective_action": None, "human_review_required": False}

    # 简单风险判定
    emergency_words = ["中毒", "过敏", "拉肚子", "腹泻", "呕吐", "异物", "头发", "虫子", "变质"]
    has_emergency = any(w in review.get("raw_text", "") for w in emergency_words)
    human_review = has_emergency or dish_info.get("dish_id") == "UNKNOWN"

    # 单条评价摘要
    review_sample = f"- [{review.get('sentiment', '?')}] {review.get('summary', review.get('raw_text', '')[:80])}"

    try:
        llm = get_llm()
        prompt = CORRECTIVE_ACTION_PROMPT.format(
            dish_name=dish_name,
            review_samples=review_sample,
            experience_context=knowledge if knowledge else "（无历史相似经验可参考）",
        )
        result = await llm.ainvoke(prompt)
        corrective_action = result.content
    except Exception:
        corrective_action = f"""【品控异常处理单】
■ 问题定位：{dish_name} 收到差评
■ 根因推测：请后厨主管对照标准工艺检查今日出品
■ 操作指令：1.抽检当前批次 2.比对标准工艺 3.调整后重新出餐
■ 验证标准：后厨主管抽检确认"""

    return {**state, "corrective_action": corrective_action, "human_review_required": human_review}
