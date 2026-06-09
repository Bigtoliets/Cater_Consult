"""工具⑥：相似案例检索 — 查找历史上被验证有效的整改方案"""
from app.tools.base import BaseTool, ToolResult
from app.utils.milvus_client import search_with_score


class SimilarCasesTool(BaseTool):
    name = "search_similar_cases"
    description = (
        "搜索历史上相似客诉的整改案例及其效果验证结果。"
        "适用场景: 需要参考已验证有效的整改方案时调用。"
        "返回案例的整改方案、执行效果(差评率变化)、是否金标认证。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "dish_name": {
                "type": "string",
                "description": "菜品名称",
            },
            "issue": {
                "type": "string",
                "description": "问题描述，如'太咸'、'口感硬'",
            },
        },
        "required": ["dish_name"],
    }

    async def execute(self, dish_name: str, issue: str = "", **kwargs) -> ToolResult:
        query = f"{dish_name} {issue} 整改方案"
        gold_results = await search_with_score("gold_collection", query, k=2)
        std_results = await search_with_score("standard_collection", query, k=2)

        all_cases = []
        for r in gold_results:
            all_cases.append({"source": "🏅金标", "content": r["content"][:400], "score": r["score"]})
        for r in std_results:
            all_cases.append({"source": "📋普通", "content": r["content"][:400], "score": r["score"]})

        all_cases.sort(key=lambda x: x["score"], reverse=True)
        top_cases = all_cases[:3]

        if not top_cases:
            return ToolResult(
                success=True,
                data=f"未找到「{dish_name}」关于「{issue}」的历史相似案例。这可能是首次遇到此问题。",
                source="案例库",
                confidence=0.3,
            )

        parts = [f"找到 {len(top_cases)} 个相似案例:"]
        for i, case in enumerate(top_cases, 1):
            parts.append(f"\n[{i}] {case['source']} (相似度: {case['score']:.2f})")
            parts.append(case["content"])

        return ToolResult(
            success=True,
            data="\n".join(parts),
            source="案例库 (gold+standard)",
            confidence=0.8 if gold_results else 0.5,
        )

    async def fallback(self, dish_name: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data=f"案例检索暂不可用。建议基于通用品控原则给出建议。",
            source="fallback",
            confidence=0.2,
        )
