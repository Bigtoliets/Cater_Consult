"""报告专家 Worker —— 报告范式化

职责：把整改方案按报告范式输出，附加置信度、审核结论与调用轨迹等元信息。
内部线路固定：范式包装（不调 LLM）。

两种结果，都必须显式写回 report_ok（Supervisor 用这个键判断能否结束）：
- 有正文 → 追加元信息页脚，report_ok=True
- 没正文 → 拒发（report_ok=False），由 Supervisor 标记人工复核后收口。
  绝不能把「只有页脚的空报告」当成交付物写进向量库 —— 空串拼页脚是真值，
  会一路被当成「有报告」落库，这是本模块最容易踩的坑。
"""
from app.state import AgentState

# 只匹配「报告由食堂品控 Agent」，老版本页脚（v4.0）也能命中，避免重跑时叠加
FOOTER_MARK = "报告由食堂品控 Agent"


def _audit_label(audit: dict) -> str:
    if not audit:
        return "未做"
    if audit.get("passed"):
        score = audit.get("score")
        return f"通过（得分 {score}）" if score is not None else "通过"
    return f"不通过（{len(audit.get('issues') or [])} 个问题）"


async def reporter_node(state: AgentState) -> dict:
    """只返回本 Worker 负责的键，不返回 {**state}（见 state.py 约定）"""
    improvement_detail = (state.get("improvement_detail") or "").strip()

    if not improvement_detail:
        return {"report_ok": False, "human_review_required": True}

    # 报告被打回后重跑时不要重复追加元信息
    if FOOTER_MARK in improvement_detail:
        return {"report_ok": True}

    dish_name = state.get("dish_name", "")
    confidence_score = state.get("confidence_score", 0.0)
    confidence_action = state.get("confidence_action", "")
    used = state.get("agents_used") or []

    meta_footer = f"""

---
*报告由食堂品控 Agent v4.1 自动生成*
*菜品：{dish_name}*
*置信度：{confidence_score:.0%}（{confidence_action or '未评估'}）*
*结论预审：{_audit_label(state.get('audit') or {})}*
*整改单终审：{_audit_label(state.get('report_audit') or {})}*
*分析链路：{' → '.join(used)}*
"""

    # 审核员的记录级提示（不阻断，但要让看报告的人看见）
    warnings = list((state.get("report_audit") or {}).get("warnings") or [])
    if warnings:
        meta_footer += "*待留意：" + "；".join(warnings[:5]) + "*\n"

    return {"improvement_detail": improvement_detail + meta_footer, "report_ok": True}
