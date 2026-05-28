"""LangGraph 工作流编排"""
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes.cleansing import review_cleansing
from app.agent.nodes.routing import dish_routing
from app.agent.nodes.rag_retrieval import rag_retrieval
from app.agent.nodes.conflict import conflict_detection
from app.agent.nodes.confidence import confidence_evaluation
from app.agent.nodes.action_report import action_report


def should_route_to_rag(state: AgentState) -> str:
    filtered = state.get("filtered_reviews", [])
    if filtered and all(r.get("sentiment") == "positive" for r in filtered):
        return "end"
    return "rag"


def should_route_to_report(state: AgentState) -> str:
    if state.get("human_review_required", False):
        return "human_review"
    return "report"


def build_workflow() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("cleansing", review_cleansing)
    workflow.add_node("routing", dish_routing)
    workflow.add_node("rag", rag_retrieval)
    workflow.add_node("conflict", conflict_detection)
    workflow.add_node("confidence", confidence_evaluation)
    workflow.add_node("report", action_report)

    workflow.set_entry_point("cleansing")
    workflow.add_edge("cleansing", "routing")
    workflow.add_conditional_edges("routing", should_route_to_rag, {"rag": "rag", "end": END})
    workflow.add_edge("rag", "conflict")
    workflow.add_edge("conflict", "confidence")
    workflow.add_conditional_edges("confidence", should_route_to_report, {"report": "report", "human_review": END})
    workflow.add_edge("report", END)

    return workflow


agent_workflow = build_workflow().compile()
