"""Supervisor Agent — 决策路由 + 异常升级 (v3.0)

模拟后厨品控总监: 根据当前状态决定下一步路由
路由策略: 规则优先, LLM 兜底
"""
from app.state import AgentState

# 路由常量
ROUTE_CLASSIFIER = "classifier"
ROUTE_DIAGNOSTICIAN = "diagnostician"
ROUTE_RETRIEVER = "retriever"
ROUTE_PRESCRIBER = "prescriber"
ROUTE_REPORTER = "reporter"
ROUTE_ESCALATE = "escalate"
ROUTE_FINISH = "FINISH"


async def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor 路由节点:
    - 检查 workflow_stage 决定下一步
    - 食安事件直接升级人工
    """
    stage = state.get("workflow_stage", "")

    # 安全事件强制升级
    reviews = state.get("reviews", [])
    has_safety = any(
        r.get("ner_entities", {}).get("event_type") == "safety_incident"
        for r in reviews
    )
    if has_safety and not state.get("improvement_detail"):
        return {**state, "workflow_stage": ROUTE_ESCALATE}

    return {**state}


def rule_router(state: AgentState) -> str:
    """规则路由: 根据 workflow_stage 决定下一节点"""

    # 食安事件 → 直接升级
    reviews = state.get("reviews", [])
    has_safety = any(
        r.get("ner_entities", {}).get("severity", 0) >= 5
        for r in reviews
    )
    if has_safety and not state.get("improvement_detail"):
        return ROUTE_ESCALATE

    # 按阶段路由
    ner_results = state.get("ner_results")
    keyword_summary = state.get("keyword_summary")
    reranked_knowledge = state.get("reranked_knowledge")
    improvement_detail = state.get("improvement_detail")

    if improvement_detail:
        return ROUTE_FINISH

    if not ner_results:
        return ROUTE_CLASSIFIER

    if not keyword_summary:
        return ROUTE_DIAGNOSTICIAN

    if not reranked_knowledge:
        return ROUTE_RETRIEVER

    return ROUTE_PRESCRIBER
