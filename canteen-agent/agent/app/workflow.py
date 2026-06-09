"""LangGraph 工作流 v3.0 —— 4 节点流水线 (NER → 信号融合 → RAG检索 → LLM融合)

未来可升级为 Supervisor 多Agent 模式 (见 agents/ 目录)
"""
from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.nodes.entity_extraction import entity_extraction
from app.nodes.keyword_aggregation import keyword_aggregation
from app.nodes.rag_reranked import rag_reranked
from app.nodes.llm_fusion import llm_fusion


def build_workflow() -> StateGraph:
    """构建 v3.0 工作流: entity_extraction → keyword_aggregation → rag_reranked → llm_fusion"""
    workflow = StateGraph(AgentState)

    workflow.add_node("entity_extraction", entity_extraction)
    workflow.add_node("keyword_aggregation", keyword_aggregation)
    workflow.add_node("rag_reranked", rag_reranked)
    workflow.add_node("llm_fusion", llm_fusion)

    workflow.set_entry_point("entity_extraction")
    workflow.add_edge("entity_extraction", "keyword_aggregation")
    workflow.add_edge("keyword_aggregation", "rag_reranked")
    workflow.add_edge("rag_reranked", "llm_fusion")
    workflow.add_edge("llm_fusion", END)

    return workflow


# 兼容旧版: 不编译 (由 Supervisor 模式按需编译)
agent_workflow = build_workflow().compile()


def build_supervisor_workflow() -> StateGraph:
    """
    Supervisor 多Agent 模式工作流 (v3.0).
    使用条件边路由, 每个节点完成后回到 Supervisor 决策。
    当前为向后兼容保留 4 节点线性模式, 完整 Supervisor 模式见 agents/ 目录。
    """
    return build_workflow()  # 暂用线性模式
