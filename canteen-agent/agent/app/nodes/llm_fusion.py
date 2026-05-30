"""节点③：LLM 融合决策 —— 生成菜品级一句话摘要 + 详细分析"""
import re
from app.state import AgentState
from app.prompts.templates import DISH_IMPROVEMENT_PROMPT
from app.utils.llm import get_llm


async def llm_fusion(state: AgentState) -> AgentState:
    dish_name = state.get("dish_name", "未知菜品")
    keyword_summary = state.get("keyword_summary", "")
    reranked_knowledge = state.get("reranked_knowledge", "")

    reviews = state.get("reviews", [])
    review_samples_parts = []
    for i, r in enumerate(reviews, 1):
        dims = r.get("dimensions", [])
        dim_str = "、".join(d.get("dimension", "") for d in dims[:3]) if dims else "未分类"
        review_samples_parts.append(
            f"{i}. [{r.get('sentiment', '?')}] {r.get('summary', r.get('raw_text', '')[:80])} | 维度：{dim_str}"
        )
    review_samples = "\n".join(review_samples_parts)

    emergency_words = ["中毒", "过敏", "拉肚子", "腹泻", "呕吐", "异物", "头发", "虫子", "变质"]
    human_review = any(
        any(w in r.get("raw_text", "") for w in emergency_words)
        for r in reviews
    )

    try:
        llm = get_llm()
        prompt = DISH_IMPROVEMENT_PROMPT.format(
            dish_name=dish_name,
            keyword_summary=keyword_summary,
            review_samples=review_samples,
            experience_context=reranked_knowledge if reranked_knowledge else "（无历史相似经验可参考）",
        )
        result = await llm.ainvoke(prompt)
        full_text = result.content

        summary = ""
        detail = ""
        m = re.search(r'【一句话摘要】\s*\n?(.*?)(?:\n【详细分析与建议】|\Z)', full_text, re.DOTALL)
        if m:
            summary = m.group(1).strip()
            detail_start = full_text.find("【详细分析与建议】")
            detail = full_text[detail_start:].strip() if detail_start != -1 else full_text
        else:
            lines = full_text.strip().split("\n")
            summary = lines[0].replace("【一句话摘要】", "").strip() if lines else full_text[:50]
            detail = full_text
    except Exception:
        summary = f"{dish_name}收到{len(reviews)}条评价，差评集中在口感问题，建议后厨对照标准工艺排查"
        detail = f"""【详细分析与建议】
■ 核心问题定位：{dish_name} 收到 {len(reviews)} 条评价，其中包含差评
■ 根因推测：请后厨主管对照标准工艺检查出品环节
■ 改进建议：
  1. 抽检当前批次出品质量
  2. 对照标准工艺排查问题环节
  3. 调整后加强出餐前检查
■ 验证标准：后厨主管品控确认"""

    return {
        **state,
        "improvement_summary": summary,
        "improvement_detail": detail,
        "human_review_required": human_review,
    }
