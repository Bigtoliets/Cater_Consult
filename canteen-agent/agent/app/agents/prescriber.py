"""处方专家 Worker —— 整改方案生成 + 置信度评估

职责：消费上游全部产物，调用 LLM 生成专业整改单。
内部线路固定：多因子置信度评估 → LLM 融合决策。
"""
from app.nodes.confidence import confidence_evaluation
from app.nodes.llm_fusion import llm_fusion
from app.state import AgentState


async def prescriber_node(state: AgentState) -> dict:
    """只返回本 Worker 负责的键，不返回 {**state}（见 state.py 约定）"""
    evaluated = await confidence_evaluation(dict(state))

    # 把 Supervisor 的定向指令 / 上一版整改单的终审意见带进 Prompt。
    # 没有这一步，「打回重写」拿到的输入和第一版完全一样，等于换个随机种子。
    instruction = (state.get("instructions") or {}).get("prescriber", "")
    notes = [n for n in (state.get("review_notes") or []) if n]
    evaluated["rework_feedback"] = instruction or "；".join(notes)

    result = await llm_fusion(evaluated)

    return {
        "confidence_score": result.get("confidence_score", 0.0),
        "confidence_action": result.get("confidence_action", ""),
        "confidence_factors": result.get("confidence_factors", {}),
        "improvement_summary": result.get("improvement_summary", ""),
        "improvement_detail": result.get("improvement_detail", ""),
        # 版本号：重写一次 +1，审核员据此判断终审结论是不是针对当前这一版
        "improvement_revision": (state.get("improvement_revision") or 0) + 1,
        # 审核员标记的人工复核不可被覆盖
        "human_review_required": bool(
            result.get("human_review_required") or state.get("human_review_required")
        ),
    }
