"""工具①：五维知识库检索"""
from app.tools.base import BaseTool, ToolResult
from app.utils.multi_kb_retriever import multi_kb_search, format_kb_context


class KnowledgeBaseSearchTool(BaseTool):
    name = "search_knowledge_base"
    description = (
        "在五维品控知识库中检索相关信息。包含: 标准工艺(SOP)、问题模式(Pattern)、"
        "周期规律(Cycle)、金标经验(Gold)、普通经验(Standard)。"
        "适用场景: 需要查找历史整改方案、SOP工艺标准、相似问题案例时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索查询文本，建议包含菜品名+问题维度，如'红烧肉 太咸 调味'",
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量，默认5",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, top_k: int = 5, **kwargs) -> ToolResult:
        results = await multi_kb_search(query, top_k=top_k)
        formatted = format_kb_context(results)

        # 标记高置信度结果
        has_gold = results.get("has_gold", False)
        confidence = 0.9 if has_gold else 0.6
        if results.get("has_sop"):
            confidence = max(confidence, 0.7)

        return ToolResult(
            success=True,
            data=formatted,
            source="五维知识库 (sop/pattern/cycle/gold/standard)",
            confidence=confidence,
            metadata={
                "sources_breakdown": results.get("sources_breakdown", {}),
                "total_candidates": results.get("total_candidates", 0),
                "has_gold": has_gold,
            },
        )

    async def validate_result(self, result: ToolResult) -> ToolResult:
        """验证: 结果为空时标记低置信度"""
        if result.success and result.data:
            if "暂无相关经验" in str(result.data) or "知识库中暂无" in str(result.data):
                result.confidence = 0.3
                result.metadata["warning"] = "知识库无匹配结果"
        return result

    async def fallback(self, query: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data="（知识库检索暂时不可用，请基于评价数据和专业知识给出建议）",
            source="fallback",
            confidence=0.2,
        )
