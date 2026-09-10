"""分析专家 Worker（B）—— 逻辑推理与冲突分析

职责：在提取专家给出的结构化事实之上做推理 ——
区分「口味偏好差异」和「生产品控波动」，定位根因，给出可执行的判断。
内部线路固定：信号融合 → 冲突检测 → 结论生成。
工具权限：calculate_confidence
"""
from app.nodes.signal_fusion import keyword_aggregation
from app.state import AgentState


async def analyst_node(state: AgentState) -> dict:
    """只返回本 Worker 负责的键，不返回 {**state}（见 state.py 约定）"""
    enriched = await keyword_aggregation(dict(state))

    conflicts = enriched.get("conflict_analysis", [])
    actionable = [c for c in conflicts if c.get("should_trigger")]
    instruction = (state.get("instructions") or {}).get("analyst", "")

    return {
        "keyword_summary": enriched.get("keyword_summary", ""),
        "conflict_analysis": conflicts,
        "should_trigger_improvement": enriched.get("should_trigger_improvement", False),
        "analysis": {
            "conflicts": conflicts,
            "actionable_count": len(actionable),
            "should_trigger": enriched.get("should_trigger_improvement", False),
            "root_causes": [c.get("reason", "") for c in actionable],
            "summary": enriched.get("keyword_summary", ""),
            "instruction": instruction,  # Supervisor 的定向指令，便于审计轨迹
        },
    }
