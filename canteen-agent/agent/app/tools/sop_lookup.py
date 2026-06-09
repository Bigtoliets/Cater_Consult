"""工具③：SOP工艺标准查询"""
from app.tools.base import BaseTool, ToolResult


class SOPLookupTool(BaseTool):
    name = "lookup_sop"
    description = (
        "查询菜品的标准操作流程(SOP)，可指定维度: sop(标准工艺)/cost(成本卡)/food_safety(食安规范)。"
        "适用场景: 需要引用具体SOP条目来支撑整改建议时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "dish_name": {
                "type": "string",
                "description": "菜品名称",
            },
            "dimension": {
                "type": "string",
                "enum": ["sop", "cost", "food_safety", "all"],
                "description": "SOP维度，默认all返回所有",
                "default": "all",
            },
        },
        "required": ["dish_name"],
    }

    async def execute(self, dish_name: str, dimension: str = "all", **kwargs) -> ToolResult:
        # SOP知识库 (后续从Milvus+sop_collection读取)
        SOP_DB = {
            "红烧肉": {
                "sop": "五花肉切3cm方块→焯水去血沫→炒糖色(冰糖30g,小火至枣红)→"
                       "高压锅上汽后压制20分钟→调味(生抽15ml/老抽5ml/盐5g/料酒10ml)→"
                       "大火收汁至浓稠→出餐温度≥75°C",
                "cost": "五花肉150g:¥3.00 + 调料:¥0.60 + 辅料:¥0.30 + 能耗:¥0.30 = ¥4.20",
                "food_safety": "猪肉中心温度≥75°C / 炖煮≥20分钟 / 常温存放≤2小时 / 回锅需达75°C",
            },
            "麻婆豆腐": {
                "sop": "豆腐切2cm方块→沸水焯2分钟→肉末煸香→加豆瓣酱炒出红油→"
                       "加高汤煮沸→入豆腐小火煨3分钟→勾芡收汁→撒花椒面",
                "cost": "豆腐200g:¥1.00 + 肉末50g:¥0.80 + 调料:¥0.50 + 能耗:¥0.20 = ¥2.50",
                "food_safety": "豆腐中心温度≥75°C / 肉末需炒至全熟变色 / 成品存放≤2小时",
            },
        }

        sop = SOP_DB.get(dish_name, {})
        if not sop:
            return ToolResult(
                success=True,
                data=f"未找到「{dish_name}」的SOP记录，建议尽快建立该菜品的标准工艺。",
                source="SOP知识库",
                confidence=0.1,
            )

        if dimension == "all":
            parts = [f"【{dish_name} SOP】"]
            for dim, content in sop.items():
                label = {"sop": "标准工艺", "cost": "成本卡", "food_safety": "食安规范"}.get(dim, dim)
                parts.append(f"\n■ {label}:\n{content}")
            data = "\n".join(parts)
        else:
            content = sop.get(dimension, "该维度暂无记录")
            label = {"sop": "标准工艺", "cost": "成本卡", "food_safety": "食安规范"}.get(dimension, dimension)
            data = f"【{dish_name} - {label}】\n{content}"

        return ToolResult(
            success=True,
            data=data,
            source="SOP知识库",
            confidence=0.9,
        )

    async def fallback(self, dish_name: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data=f"SOP查询暂不可用。请根据后厨专业知识给出建议。",
            source="fallback",
            confidence=0.2,
        )
