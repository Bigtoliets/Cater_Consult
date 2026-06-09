"""Diagnostician Agent — 多维度信号融合 + 冲突检测 (v3.0)

消费 NER 结果, 执行:
1. 三维信号提取 (基本面/频次面/关联面)
2. 冲突检测 (偏好差异 vs 品控波动)
3. 根因分析
"""
from app.state import AgentState
from app.nodes.signal_fusion import keyword_aggregation


async def diagnostician_node(state: AgentState) -> AgentState:
    """诊断 Agent 节点"""
    result = await keyword_aggregation(state)
    return {**result, "workflow_stage": "diagnostician_done"}
