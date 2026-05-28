"""节点3：RAG Knowledge Retrieval —— 知识检索"""
from app.agent.state import AgentState
from app.agent.utils.milvus_client import get_milvus_store
from app.config import settings


async def rag_retrieval(state: AgentState) -> AgentState:
    dish_info = state.get("dish_info", {})
    dish_id = dish_info.get("dish_id", "UNKNOWN")
    filtered = state.get("filtered_reviews", [])

    if filtered and all(r.get("sentiment") == "positive" for r in filtered):
        return {**state, "knowledge_context": "（正面评价，无需检索）"}
    if dish_id == "UNKNOWN":
        return {**state, "knowledge_context": "（菜品未识别，使用通用烹饪知识）"}

    knowledge_parts = []
    collections = [
        ("sop_collection", "SOP标准卡"),
        ("history_complaints", "历史客诉"),
        ("cost_card", "成本约束"),
        ("food_safety", "食安规范"),
    ]

    for col_name, label in collections:
        try:
            store = get_milvus_store(col_name)
            query = f"{dish_info.get('dish_name', '')} {' '.join([r.get('summary', '') for r in filtered[:3]])}"
            docs = store.similarity_search(query, k=settings.AGENT_RAG_TOP_K)
            if docs:
                knowledge_parts.append(f"## {label}")
                for doc in docs:
                    knowledge_parts.append(doc.page_content[:500])
        except Exception:
            knowledge_parts.append(f"## {label}\n（检索不可用）")

    return {**state, "knowledge_context": "\n\n".join(knowledge_parts) if knowledge_parts else "（知识库为空）"}
