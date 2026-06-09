"""Retriever Agent — 五维知识库并行检索 (v3.0)

基于信号融合结果, 从五库中检索最相关的历史经验/SOP/问题模式/周期规律.
"""
from app.state import AgentState
from app.utils.multi_kb_retriever import multi_kb_search, format_kb_context


async def retriever_node(state: AgentState) -> AgentState:
    """知识检索 Agent 节点"""
    dish_name = state.get("dish_name", "")
    keyword_summary = state.get("keyword_summary", "")

    # 构建检索查询: 菜品名 + 关键问题维度
    query = f"{dish_name} {keyword_summary[:400]}"

    try:
        kb_results = await multi_kb_search(query, top_k=5)
        formatted = format_kb_context(kb_results)

        # 兼容旧版字段
        gold_items = [it for it in kb_results["top_k"] if it["source"] == "gold_collection"]
        std_items = [it for it in kb_results["top_k"] if it["source"] == "standard_collection"]

        gold_context = "\n".join(
            f"[GOLD] [加权分 {it['weighted_score']:.2f}] {it['content'][:400]}"
            for it in gold_items
        )
        standard_context = "\n".join(
            f"[STANDARD] [加权分 {it['weighted_score']:.2f}] {it['content'][:400]}"
            for it in std_items
        )
    except Exception:
        formatted = "（知识库检索暂不可用）"
        gold_context = ""
        standard_context = ""
        kb_results = {}

    return {
        **state,
        "reranked_knowledge": formatted,
        "gold_context": gold_context,
        "standard_context": standard_context,
        "multi_kb_results": kb_results,
        "workflow_stage": "retriever_done",
    }
