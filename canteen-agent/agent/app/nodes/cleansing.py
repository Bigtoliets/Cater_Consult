"""节点1：Review Cleansing —— 评价清洗与过滤"""
from app.state import AgentState
from app.prompts.templates import REVIEW_FILTER_PROMPT, REVIEW_ANALYSIS_PROMPT
from app.utils.llm import get_llm


async def review_cleansing(state: AgentState) -> AgentState:
    """
    过滤无意义内容，提取结构化字段
    输入：raw_reviews
    输出：filtered_reviews
    """
    raw = state.get("raw_reviews", [])
    if not raw:
        return {**state, "filtered_reviews": []}

    llm = get_llm()
    filtered = []

    for review in raw:
        review_text = review.get("raw_text", "").strip()

        # 快速规则过滤
        if not review_text or len(review_text) < 2:
            continue
        if review_text in ("...", "👍", "好", "嗯", ".", "。。。"):
            continue

        # LLM 有效性判断
        try:
            prompt = REVIEW_FILTER_PROMPT.format(review_text=review_text[:500])
            result = await llm.ainvoke(prompt)
            is_valid = "VALID" in result.content.upper()
        except Exception:
            is_valid = True  # LLM 不可用时兜底放行

        if not is_valid:
            continue

        # 结构化分析
        try:
            analysis_prompt = REVIEW_ANALYSIS_PROMPT.format(review_text=review_text[:500])
            analysis_result = await llm.ainvoke(analysis_prompt)

            import json
            import re
            json_match = re.search(r"\{.*\}", analysis_result.content, re.DOTALL)
            analysis = json.loads(json_match.group(0)) if json_match else {}
        except Exception:
            analysis = {
                "sentiment": "neutral",
                "dimensions": [],
                "severity": 1,
                "summary": review_text[:50],
            }

        filtered.append({
            **review,
            "sentiment": analysis.get("sentiment", "neutral"),
            "dimensions": analysis.get("dimensions", []),
            "severity": analysis.get("severity", 1),
            "summary": analysis.get("summary", ""),
        })

    return {
        **state,
        "filtered_reviews": filtered,
    }
