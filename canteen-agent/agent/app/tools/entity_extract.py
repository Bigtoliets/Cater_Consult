"""工具④：实体提取 (复用NER节点)"""
from app.tools.base import BaseTool, ToolResult
from app.nodes.entity_extraction import entity_extraction


class EntityExtractionTool(BaseTool):
    name = "extract_entities"
    description = (
        "从顾客评价文本中提取结构化信息: 菜品名、问题描述、涉及工艺环节、"
        "事件类型(taste_complaint/safety_incident/service_issue等)、严重度(1-5)、"
        "是否为口味偏好差异。适用场景: 需要逐条分析评价内容时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "description": "评价列表，每条包含 raw_text 和 sentiment 字段",
                "items": {"type": "object"},
            },
        },
        "required": ["reviews"],
    }

    async def execute(self, reviews: list[dict], **kwargs) -> ToolResult:
        # 复用NER节点
        state = {"reviews": reviews, "dish_name": "", "dish_id": ""}
        result_state = await entity_extraction(state)

        ner_results = result_state.get("ner_results", [])
        if not ner_results:
            return ToolResult(success=False, error="实体提取无结果")

        # 格式化为可读文本
        parts = []
        for i, (r, ner) in enumerate(zip(reviews, ner_results)):
            parts.append(
                f"[{i+1}] {r.get('raw_text', '')[:80]}\n"
                f"    菜品: {ner.get('dish', '?')} | "
                f"问题: {ner.get('issue', '无')} | "
                f"工艺: {ner.get('process', '?')} | "
                f"类型: {ner.get('event_type', '?')} | "
                f"严重度: {ner.get('severity', 1)}/5 | "
                f"{'🔸偏好差异' if ner.get('is_preference') else '🔹品控问题'}"
            )

        return ToolResult(
            success=True,
            data="\n".join(parts),
            source="NER实体提取引擎",
            confidence=0.75,
            metadata={"ner_raw": ner_results},
        )

    async def fallback(self, reviews: list[dict] = None, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data="实体提取暂时不可用，请基于评价原文直接分析。",
            source="fallback",
            confidence=0.3,
        )
