"""工具⑧：输出格式验证 — 验证LLM输出是否符合预期格式，检测自相矛盾"""
import re
import json
from app.tools.base import BaseTool, ToolResult


class OutputValidatorTool(BaseTool):
    name = "validate_output"
    description = (
        "验证LLM生成的输出是否符合预期格式，以及是否存在自相矛盾或明显幻觉。"
        "检查项: 格式完整性、数值一致性、来源引用、矛盾检测。"
        "适用场景: 在输出最终结果前，对LLM生成的内容做最后一道校验。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "output_text": {
                "type": "string",
                "description": "LLM生成的输出文本",
            },
            "expected_format": {
                "type": "string",
                "enum": ["improvement_plan", "chat_answer", "daily_report", "diagnosis_report"],
                "description": "期望的输出格式类型",
                "default": "improvement_plan",
            },
            "known_facts": {
                "type": "array",
                "description": "已知事实列表，用于检测矛盾",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["output_text"],
    }

    async def execute(
        self, output_text: str, expected_format: str = "improvement_plan",
        known_facts: list[str] = None, **kwargs
    ) -> ToolResult:
        issues = []
        warnings = []

        # 1. 格式完整性检查
        if expected_format == "improvement_plan":
            if "【一句话摘要】" not in output_text:
                issues.append("缺少「一句话摘要」标记")
            if "【改进建议】" not in output_text:
                issues.append("缺少「改进建议」标记")
            if output_text.count("1.") == 0 and "1." not in output_text:
                warnings.append("改进建议未使用编号列表")

        # 2. 数值一致性检查
        numbers = re.findall(r'\d+', output_text)
        if len(numbers) > 0 and len(set(numbers)) > len(numbers) * 0.8:
            # 大量不同数字 — 可能幻觉
            warnings.append(f"输出包含 {len(numbers)} 个不同的数字参数，建议核查准确性")

        # 3. 极端值检测
        if re.search(r'(100%|绝对|一定|肯定|保证|绝不)', output_text):
            warnings.append("包含绝对化表述(100%/一定/保证)，建议改为概率性表述")

        # 4. 来源引用检查
        if expected_format in ("improvement_plan", "diagnosis_report"):
            if "SOP" not in output_text and "工艺" not in output_text and "标准" not in output_text:
                warnings.append("未引用SOP或工艺标准，建议补充具体参考来源")

        # 5. 矛盾检测
        if known_facts:
            for fact in known_facts:
                # 简化: 检查输出是否直接与已知事实矛盾
                negative_fact = fact.replace("应该", "不应该").replace("需要", "不需要")
                if negative_fact in output_text or fact.replace("≥", "<") in output_text:
                    issues.append(f"与已知事实矛盾: {fact}")

        # 6. 幻觉关键词检测
        hallucination_markers = ["据我所知", "根据我的经验", "一般来说", "通常情况下"]
        for marker in hallucination_markers:
            if marker in output_text:
                warnings.append(f"使用模糊表述'{marker}'，建议改为引用具体知识库来源")

        is_valid = len(issues) == 0
        result_data = {
            "valid": is_valid,
            "issues": issues,
            "warnings": warnings,
            "summary": "✅ 验证通过" if is_valid else f"🔴 发现 {len(issues)} 个问题, {len(warnings)} 个警告",
        }

        return ToolResult(
            success=True,
            data=json.dumps(result_data, ensure_ascii=False, indent=2),
            source="输出验证器",
            confidence=0.5 if is_valid else 0.2,
            metadata=result_data,
        )
