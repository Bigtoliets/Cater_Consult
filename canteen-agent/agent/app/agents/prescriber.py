"""Prescriber Agent — 整改方案生成 + 置信度评估 (v3.0)

消费所有上游数据, 调用 LLM 生成专业整改单.
"""
from app.state import AgentState
from app.nodes.llm_fusion import llm_fusion
from app.nodes.confidence import confidence_evaluation


async def prescriber_node(state: AgentState) -> AgentState:
    """处方 Agent 节点: 置信度评估 → LLM 融合决策"""

    # 先跑置信度评估
    state = await confidence_evaluation(state)

    # 再跑 LLM 融合
    result = await llm_fusion(state)

    return {**result, "workflow_stage": "prescriber_done"}
