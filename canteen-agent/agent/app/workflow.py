"""LangGraph 工作流编排"""
from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.cleansing import review_cleansing
from app.nodes.routing import dish_routing
from app.nodes.rag_retrieval import rag_retrieval
from app.nodes.conflict import conflict_detection
from app.nodes.confidence import confidence_evaluation
from app.nodes.action_report import action_report


def should_route_to_rag(state: AgentState) -> str:
    """条件路由：判断是否需要进入 RAG 检索"""
    dish_info = state.get("dish_info", {})
    filtered = state.get("filtered_reviews", [])

    # 全是正面评价 → 跳过 RAG，直接结束
    if filtered and all(r.get("sentiment") == "positive" for r in filtered):
        return "end"

    # 菜品未识别 → 也尝试用通用上下文生成报告
    return "rag"


def should_route_to_report(state: AgentState) -> str:
    """条件路由：判断是自动生成报告还是推人工"""
    if state.get("human_review_required", False):
        return "human_review"
    return "report"


def build_workflow() -> StateGraph:
    """构建 Agent 工作流"""
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("cleansing", review_cleansing)
    workflow.add_node("routing", dish_routing)
    workflow.add_node("rag", rag_retrieval)
    workflow.add_node("conflict", conflict_detection)
    workflow.add_node("confidence", confidence_evaluation)
    workflow.add_node("report", action_report)

    # 设置入口
    workflow.set_entry_point("cleansing")

    # 添加边
    workflow.add_edge("cleansing", "routing")

    # 条件路由：routing → rag 或 END
    workflow.add_conditional_edges(
        "routing",
        should_route_to_rag,
        {
            "rag": "rag",
            "end": END,
        },
    )

    workflow.add_edge("rag", "conflict")
    workflow.add_edge("conflict", "confidence")

    # 条件路由：confidence → report 或 END（人工复核）
    workflow.add_conditional_edges(
        "confidence",
        should_route_to_report,
        {
            "report": "report",
            "human_review": END,  # 人工复核流程在实际系统中推送至审核队列
        },
    )

    workflow.add_edge("report", END)

    return workflow


# 导出编译后的工作流
agent_workflow = build_workflow().compile()
