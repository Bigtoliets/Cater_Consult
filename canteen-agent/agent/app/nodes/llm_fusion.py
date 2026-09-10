"""节点③：LLM 融合决策 v3.0 —— 消费信号融合 + 置信度评估, 生成专业整改单

v3.0 改进:
- 输入包含 NER 提取的问题实体 (process/event_type)
- 输入包含冲突分析结果 (区分偏好差异 vs 品控波动)
- 输入包含置信度评估 (自动发布 / 建议复核 / 升级人工)
- 敏感词检测保留为兜底
"""
import re
from app.state import AgentState
from app.prompts.templates import DISH_IMPROVEMENT_PROMPT
from app.utils.llm import get_llm


async def llm_fusion(state: AgentState) -> AgentState:
    dish_name = state.get("dish_name", "未知菜品")
    keyword_summary = state.get("keyword_summary", "")
    reranked_knowledge = state.get("reranked_knowledge", "")
    confidence_score = state.get("confidence_score", 0.5)
    confidence_action = state.get("confidence_action", "publish_with_review")

    # 构建评价样本（含 NER 信息）
    reviews = state.get("reviews", [])
    review_samples_parts = []
    for i, r in enumerate(reviews, 1):
        ner = r.get("ner_entities", {})
        process = ner.get("process", "未识别")
        issue = ner.get("issue", "")
        issue_str = f" | 问题: {issue}" if issue else ""
        review_samples_parts.append(
            f"{i}. [{r.get('sentiment', '?')}] {r.get('summary', r.get('raw_text', '')[:80])}"
            f" | 工艺环节: {process}{issue_str}"
            f" | {'🔸偏好差异' if ner.get('is_preference') else '🔹品控问题'}"
        )
    review_samples = "\n".join(review_samples_parts)

    # 冲突分析摘要
    conflicts = state.get("conflict_analysis", [])
    conflict_text = ""
    if conflicts:
        conflict_parts = []
        for c in conflicts:
            icon = "🔴需要整改" if c.get("should_trigger") else "🟢无需处理"
            conflict_parts.append(f"- {icon} [{c.get('signal_type', '')}] {c.get('description', '')}")
            conflict_parts.append(f"  置信度: {c.get('confidence', 0):.0%} | {c.get('reason', '')}")
        conflict_text = "\n".join(conflict_parts)

    # 置信度标签
    confidence_labels = {
        "auto_publish": "✅ 高置信度 — 建议自动发布整改单",
        "publish_with_review": "⚠️ 中置信度 — 建议发布但标注人工复核",
        "escalate_to_human": "🔴 低置信度/安全事件 — 建议升级人工处理",
    }
    confidence_label = confidence_labels.get(confidence_action, "")

    # 敏感词兜底检测
    emergency_words = ["中毒", "过敏", "拉肚子", "腹泻", "呕吐", "异物", "头发", "虫子", "变质"]
    has_emergency = any(
        any(w in r.get("raw_text", "") for w in emergency_words)
        for r in reviews
    )

    # 终审打回时的修改意见：只有把它喂回 Prompt，「打回重写」才不是重抽一次
    review_feedback = (state.get("rework_feedback") or "").strip() or "（无，本次为初版）"

    try:
        llm = get_llm()
        prompt = DISH_IMPROVEMENT_PROMPT.format(
            dish_name=dish_name,
            keyword_summary=keyword_summary,
            review_samples=review_samples,
            experience_context=reranked_knowledge if reranked_knowledge else "（无历史相似经验可参考）",
            conflict_analysis=conflict_text if conflict_text else "（未检测到冲突信号）",
            confidence_score=f"{confidence_score:.0%}",
            confidence_label=confidence_label,
            review_feedback=review_feedback,
        )
        result = await llm.ainvoke(prompt)
        full_text = result.content

        summary = ""
        detail = ""
        m = re.search(r'【一句话摘要】\s*\n?(.*?)(?:\n【改进建议】|\Z)', full_text, re.DOTALL)
        if m:
            summary = m.group(1).strip()
            detail_start = full_text.find("【改进建议】")
            detail = full_text[detail_start:].strip() if detail_start != -1 else full_text
        else:
            lines = full_text.strip().split("\n")
            summary = lines[0].replace("【一句话摘要】", "").strip() if lines else full_text[:50]
            detail = full_text
    except Exception:
        conflicts_list = state.get("conflict_analysis", [])
        actionable = [c for c in conflicts_list if c.get("should_trigger")]
        if actionable:
            top_issue = actionable[0]
            summary = f"{dish_name}{top_issue.get('description', '存在品控问题')}"
        else:
            summary = f"{dish_name}整体品控正常，建议持续关注"
        detail = f"""【改进建议】
1. 根据信号分析结果排查对应工艺环节
2. 对照标准 SOP 验证出餐质量
3. 加强出餐前抽检

【置信度】{confidence_score:.0%} ({confidence_action})
"""

    # 安全事件强制标记人工复核
    human_review = has_emergency or confidence_action == "escalate_to_human"

    return {
        **state,
        "improvement_summary": summary,
        "improvement_detail": detail,
        "human_review_required": human_review,
        "workflow_stage": "done",
    }
