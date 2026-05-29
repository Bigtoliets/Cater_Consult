"""节点①：Review Cleansing — 单条评价清洗与结构化"""
from app.state import AgentState
from app.prompts.templates import REVIEW_FILTER_PROMPT, REVIEW_ANALYSIS_PROMPT
from app.utils.llm import get_llm


async def review_cleansing(state: AgentState) -> AgentState:
    """
    处理单条评价：
      1. 前置拼接菜品名
      2. 快速规则过滤
      3. LLM 有效性判断
      4. LLM 结构化提取 (sentiment/dimensions/severity/summary)
    """
    review = state.get("review", {})
    review_text = review.get("raw_text", "").strip()
    dish_name = review.get("dish_name_raw", "").strip()

    # 前置拼接菜品名
    if dish_name:
        review_text = f"【菜品：{dish_name}】{review_text}"

    # 规则过滤
    if not review_text or len(review_text) < 2:
        return {**state, "filtered_review": {}}
    if review_text in ("...", "👍", "好", "嗯", ".", "。。。"):
        return {**state, "filtered_review": {}}

    llm = get_llm()

    # LLM 有效性
    try:
        prompt = REVIEW_FILTER_PROMPT.format(review_text=review_text[:500])
        result = await llm.ainvoke(prompt)
        is_valid = "VALID" in result.content.upper()
    except Exception:
        is_valid = True

    if not is_valid:
        return {**state, "filtered_review": {}}

    # LLM 结构化
    try:
        analysis_prompt = REVIEW_ANALYSIS_PROMPT.format(review_text=review_text[:500])
        analysis_result = await llm.ainvoke(analysis_prompt)
        import json, re
        json_match = re.search(r"\{.*\}", analysis_result.content, re.DOTALL)
        analysis = json.loads(json_match.group(0)) if json_match else {}
    except Exception:
        analysis = {"sentiment": "neutral", "dimensions": [], "severity": 1, "summary": review_text[:50]}

    return {
        **state,
        "filtered_review": {
            "raw_text": review_text,
            "stall_name": review.get("stall_name", ""),
            "dish_name_raw": dish_name,
            "sentiment": analysis.get("sentiment", "neutral"),
            "dimensions": analysis.get("dimensions", []),
            "severity": analysis.get("severity", 1),
            "summary": analysis.get("summary", ""),
        },
    }
