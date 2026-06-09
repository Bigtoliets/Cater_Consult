"""Classifier Agent — NER 实体提取 + 事件分类 (v3.0)

委托给 entity_extraction 节点, 此处为 Supervisor 模式的包装入口.
"""
from app.state import AgentState
from app.nodes.entity_extraction import entity_extraction


async def classifier_node(state: AgentState) -> AgentState:
    """分类 Agent 节点"""
    result = await entity_extraction(state)
    return {**result, "workflow_stage": "classifier_done"}
