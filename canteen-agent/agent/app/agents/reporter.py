"""Reporter Agent — 报告范式化生成 (v3.0)

基于整改方案，按报告范式生成日报/单品诊断/周报.
"""
from app.state import AgentState


async def reporter_node(state: AgentState) -> AgentState:
    """报告 Agent 节点 — 对 LLM 输出做后处理和范式化包装"""

    improvement_detail = state.get("improvement_detail", "")
    confidence_score = state.get("confidence_score", 0)
    confidence_action = state.get("confidence_action", "")
    dish_name = state.get("dish_name", "")

    # 追加置信度元信息到报告末尾
    meta_footer = f"""

---
*报告由食堂品控 Agent v3.0 自动生成*
*菜品：{dish_name}*
*置信度：{confidence_score:.0%} ({confidence_action})*
"""

    enhanced_detail = improvement_detail + meta_footer

    return {
        **state,
        "improvement_detail": enhanced_detail,
        "workflow_stage": "reporter_done",
    }
