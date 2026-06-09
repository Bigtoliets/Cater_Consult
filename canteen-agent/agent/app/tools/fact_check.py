"""工具⑤：事实核查 — 验证LLM生成的claim是否有知识库支撑"""
from app.tools.base import BaseTool, ToolResult
from app.utils.multi_kb_retriever import multi_kb_search


class FactCheckTool(BaseTool):
    name = "check_fact"
    description = (
        "验证一个事实性声明是否在知识库中有支撑。返回匹配度(0-1)和匹配到的原文。"
        "适用场景: LLM生成整改建议后，需要验证建议中的具体参数(温度/时间/用量)是否准确时调用。"
        "特别注意: 如果匹配度<0.5，说明该声明可能为LLM编造(幻觉)，应标记为不确定。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "claim": {
                "type": "string",
                "description": "需要验证的事实声明，如'红烧肉需要压制20分钟'",
            },
            "context": {
                "type": "string",
                "description": "相关上下文(菜品名等)，用于缩小检索范围",
                "default": "",
            },
        },
        "required": ["claim"],
    }

    # 常见幻觉模式 (纯数字/时间编造)
    HALLUCINATION_PATTERNS = [
        ("分钟", "min"),
        ("小时", "hour"),
        ("克", "g"),
        ("毫升", "ml"),
        ("°C", "temp"),
        ("摄氏度", "temp"),
        ("元", "price"),
        ("¥", "price"),
    ]

    async def execute(self, claim: str, context: str = "", **kwargs) -> ToolResult:
        query = f"{context} {claim}" if context else claim

        try:
            results = await multi_kb_search(query, top_k=3)
            top_items = results.get("top_k", [])

            if not top_items:
                return ToolResult(
                    success=True,
                    data=f"⚠️ 未找到支撑「{claim[:80]}」的知识库条目。该声明可能不准确。",
                    source="事实核查引擎",
                    confidence=0.1,
                    metadata={"matched": False, "warning": "UNVERIFIED_CLAIM"},
                )

            best = top_items[0]
            match_score = best["weighted_score"]

            if match_score >= 0.7:
                verdict = "✅ 验证通过"
            elif match_score >= 0.4:
                verdict = "⚠️ 部分匹配，建议标注不确定性"
            else:
                verdict = "🔴 低匹配度，可能为幻觉"

            return ToolResult(
                success=True,
                data=(
                    f"{verdict}\n"
                    f"声明: {claim[:120]}\n"
                    f"最匹配条目 (相似度 {match_score:.2f}): {best['content'][:300]}\n"
                    f"来源: {best['label']} ({best['source']})"
                ),
                source="事实核查引擎",
                confidence=match_score,
                metadata={
                    "matched": match_score >= 0.4,
                    "match_score": match_score,
                    "source_collection": best["source"],
                },
            )
        except Exception:
            return ToolResult(success=False, error="事实核查服务异常")

    async def fallback(self, claim: str = "", **kwargs) -> ToolResult:
        # 降级: 检查是否包含可疑的数字声明
        import re
        numbers_found = re.findall(r'\d+', claim)
        if numbers_found:
            return ToolResult(
                success=True,
                data=f"⚠️ 事实核查不可用。声明「{claim[:80]}」包含数字参数({', '.join(numbers_found)})，"
                     f"建议人工验证这些数值的准确性。",
                source="fallback",
                confidence=0.3,
                metadata={"warning": "UNVERIFIED_NUMBERS", "numbers": numbers_found},
            )
        return ToolResult(
            success=True,
            data=f"事实核查不可用，建议对关键声明进行人工复核。",
            source="fallback",
            confidence=0.3,
        )
