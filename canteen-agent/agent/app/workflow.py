"""LangGraph 工作流 — 4 节点单条流水线"""
from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.cleansing import review_cleansing
from app.nodes.routing import dish_routing
from app.nodes.rag_retrieval import rag_retrieval
from app.nodes.action_report import action_report


def should_route_to_rag(state: AgentState) -> str:
    """正面评价或无有效内容 → 跳过 RAG 直接结束"""
    review = state.get("filtered_review", {})
    if not review or review.get("sentiment") == "positive":
        return "end"
    return "rag"


def build_workflow() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("cleansing", review_cleansing)
    workflow.add_node("routing", dish_routing)
    workflow.add_node("rag", rag_retrieval)
    workflow.add_node("report", action_report)

    workflow.set_entry_point("cleansing")
    workflow.add_edge("cleansing", "routing")

    workflow.add_conditional_edges("routing", should_route_to_rag, {"rag": "rag", "end": END})

    workflow.add_edge("rag", "report")
    workflow.add_edge("report", END)

    return workflow


agent_workflow = build_workflow().compile()
