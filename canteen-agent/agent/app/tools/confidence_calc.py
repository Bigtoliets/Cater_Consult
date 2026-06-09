"""工具⑦：置信度计算 — 多因子置信度评估"""
from app.tools.base import BaseTool, ToolResult


class ConfidenceCalcTool(BaseTool):
    name = "calculate_confidence"
    description = (
        "计算当前分析的置信度分数(0-1)。输入各因子得分，返回综合置信度。"
        "因子: data_sufficiency(数据量), consistency(一致性), knowledge_match(知识匹配), "
        "sop_coverage(SOP覆盖), solvability(可解度)。"
        "适用场景: 在生成最终建议前，评估当前分析的可靠性。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "factors": {
                "type": "object",
                "description": "各因子得分对象",
                "properties": {
                    "data_sufficiency": {"type": "number", "minimum": 0, "maximum": 1},
                    "consistency": {"type": "number", "minimum": 0, "maximum": 1},
                    "knowledge_match": {"type": "number", "minimum": 0, "maximum": 1},
                    "sop_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                    "solvability": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "required": ["factors"],
    }

    FACTOR_WEIGHTS = {
        "data_sufficiency": 0.15,
        "consistency": 0.20,
        "knowledge_match": 0.30,
        "sop_coverage": 0.20,
        "solvability": 0.15,
    }

    async def execute(self, factors: dict, **kwargs) -> ToolResult:
        score = sum(
            factors.get(k, 0.5) * w
            for k, w in self.FACTOR_WEIGHTS.items()
        )
        score = round(min(1.0, max(0.0, score)), 2)

        if score >= 0.75:
            level = "高 — 可自动发布整改单"
        elif score >= 0.50:
            level = "中 — 建议发布但标注人工复核"
        else:
            level = "低 — 建议升级人工处理"

        return ToolResult(
            success=True,
            data=(
                f"综合置信度: {score:.0%}\n"
                f"等级: {level}\n"
                f"各因子: data_sufficiency={factors.get('data_sufficiency',0.5):.0%}, "
                f"consistency={factors.get('consistency',0.5):.0%}, "
                f"knowledge_match={factors.get('knowledge_match',0.5):.0%}, "
                f"sop_coverage={factors.get('sop_coverage',0.5):.0%}, "
                f"solvability={factors.get('solvability',0.5):.0%}"
            ),
            source="置信度引擎",
            confidence=1.0,
            metadata={"score": score, "level": level, "factors": factors},
        )

    async def fallback(self, factors: dict = None, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data="置信度评估不可用。建议保守处理: 标注为需人工复核。",
            source="fallback",
            confidence=0.5,
        )
