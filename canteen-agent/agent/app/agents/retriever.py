"""检索专家 Worker —— 五维知识库并行检索

职责：从五库（SOP 工艺 / 问题模式 / 周期规律 / 金标经验 / 普通经验）检索依据。
简单客诉可被 Supervisor 跳过，只在结论需要标准或先例支撑时才调。

内部线路固定：五库并行检索 → 加权合并 → 格式化上下文。
工具权限：search_knowledge_base、lookup_sop、search_similar_cases
"""
from app.state import AgentState
from app.utils.multi_kb_retriever import multi_kb_search, format_kb_context


async def retriever_node(state: AgentState) -> dict:
    """只返回本 Worker 负责的键，不返回 {**state}（见 state.py 约定）"""
    dish_name = state.get("dish_name", "")
    keyword_summary = state.get("keyword_summary", "")

    # 检索查询 = 菜品名 + 关键问题维度
    query = f"{dish_name} {keyword_summary[:400]}"

    retrieval_ok = True
    try:
        kb_results = await multi_kb_search(query, top_k=5)
        formatted = format_kb_context(kb_results)

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
        # 失败时不要把哨兵字符串写进 reranked_knowledge —— 它是真值，
        # 会让 Supervisor 的进度表显示「✅ 已完成」，也会让兜底链路跳过检索。
        # 用 retrieved/retrieval_ok 两个布尔位表达「跑过了」和「跑成了」。
        retrieval_ok = False
        formatted = ""
        gold_context = ""
        standard_context = ""
        kb_results = {}

    return {
        "reranked_knowledge": formatted,
        "gold_context": gold_context,
        "standard_context": standard_context,
        "multi_kb_results": kb_results,
        "retrieved": True,
        "retrieval_ok": retrieval_ok,
    }
