"""节点6：Action Report —— 整改单生成"""
from app.agent.state import AgentState
from app.agent.prompts.templates import CORRECTIVE_ACTION_PROMPT
from app.agent.utils.llm import get_llm


async def action_report(state: AgentState) -> AgentState:
    dish_info = state.get("dish_info", {})
    conflict = state.get("conflict_analysis", {})
    knowledge = state.get("knowledge_context", "")
    confidence = state.get("confidence", 0.0)

    if state.get("human_review_required", False):
        return {**state, "corrective_action": f"""【品控异常处理单 - 待人工复核】
■ 问题定位：{dish_info.get('dish_name', '未知菜品')} 收到差评，系统置信度 {confidence:.0%} 不足
■ 根因推测：需人工介入分析
■ 操作指令：
  1. 请后厨主管查看客诉原声
  2. 对照标准SOP检查今日出品
  3. 确认后填写整改意见
■ 验证标准：人工确认后下发"""}

    conflict_type = conflict.get("conflict_type", "QUALITY_FLUCTUATION")
    summary = conflict.get("summary", "系统检测到品控异常")

    try:
        llm = get_llm()
        prompt = CORRECTIVE_ACTION_PROMPT.format(
            dish_name=dish_info.get("dish_name", "未知菜品"),
            sop_context=knowledge[:2000],
            diagnosis_summary=f"[{conflict_type}] {summary}",
            cost_limit="15.00",
        )
        result = await llm.ainvoke(prompt)
        corrective_action = result.content
    except Exception:
        corrective_action = f"""【品控异常处理单】
■ 问题定位：{dish_info.get('dish_name', '未知菜品')} 收到集中差评
■ 根因推测：{summary}
■ 操作指令：
  1. 对照标准SOP检查今日出品流程
  2. 抽检当前批次产品
  3. 调整后重新出餐
■ 验证标准：后厨主管抽检确认"""

    return {**state, "corrective_action": corrective_action}
