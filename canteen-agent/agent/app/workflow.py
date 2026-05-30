"""LangGraph 工作流 —— 菜品级 3 节点流水线"""
from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.keyword_aggregation import keyword_aggregation
from app.nodes.rag_reranked import rag_reranked
from app.nodes.llm_fusion import llm_fusion


def build_workflow() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("keyword_aggregation", keyword_aggregation)
    workflow.add_node("rag_reranked", rag_reranked)
    workflow.add_node("llm_fusion", llm_fusion)

    workflow.set_entry_point("keyword_aggregation")
    workflow.add_edge("keyword_aggregation", "rag_reranked")
    workflow.add_edge("rag_reranked", "llm_fusion")
    workflow.add_edge("llm_fusion", END)

    return workflow


agent_workflow = build_workflow().compile()
