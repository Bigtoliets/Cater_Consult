"""工具②：菜品信息查询"""
from app.tools.base import BaseTool, ToolResult


class DishInfoTool(BaseTool):
    name = "get_dish_info"
    description = (
        "查询菜品的基础信息，包括分类、成本、售价、SOP条目数等。"
        "适用场景: 需要了解菜品基本属性或判断是否为已知菜品时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "dish_name": {
                "type": "string",
                "description": "菜品名称，如'红烧肉'、'麻婆豆腐'",
            },
        },
        "required": ["dish_name"],
    }

    async def execute(self, dish_name: str, **kwargs) -> ToolResult:
        # 静态菜品知识 (后续可对接数据库)
        DISH_DB = {
            "红烧肉": {"category": "热菜", "unit_cost": 4.20, "price": 12.00,
                       "key_process": "高压锅上汽压制20分钟", "salt_g": 5, "temp_c": 75},
            "麻婆豆腐": {"category": "热菜", "unit_cost": 2.50, "price": 8.00,
                         "key_process": "豆腐焯水2分钟，肉末煸香后加豆瓣酱", "salt_g": 3, "temp_c": 75},
            "宫保鸡丁": {"category": "热菜", "unit_cost": 3.80, "price": 10.00,
                         "key_process": "鸡丁滑油至变色，花生米炸酥", "salt_g": 3, "temp_c": 75},
            "兰州拉面": {"category": "面食", "unit_cost": 2.00, "price": 8.00,
                         "key_process": "手工拉制，沸水煮90秒", "salt_g": 2, "temp_c": 80},
            "白切鸡": {"category": "热菜", "unit_cost": 5.00, "price": 15.00,
                       "key_process": "浸煮20分钟，冰水过冷", "salt_g": 3, "temp_c": 75},
        }

        info = DISH_DB.get(dish_name)
        if info:
            return ToolResult(
                success=True,
                data=(
                    f"【{dish_name}】\n"
                    f"- 分类: {info['category']}\n"
                    f"- 成本: ¥{info['unit_cost']} / 售价: ¥{info['price']}\n"
                    f"- 关键工艺: {info['key_process']}\n"
                    f"- 标准盐量: {info['salt_g']}g\n"
                    f"- 出餐温度: ≥{info['temp_c']}°C"
                ),
                source="菜品数据库",
                confidence=0.95,
            )
        return ToolResult(
            success=True,
            data=f"未找到菜品「{dish_name}」的详细信息，可能是新菜品或名称不匹配。",
            source="菜品数据库",
            confidence=0.1,
            metadata={"warning": "菜品不存在"},
        )

    async def fallback(self, dish_name: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data=f"菜品「{dish_name}」信息查询暂不可用，请根据评价数据自行判断。",
            source="fallback",
            confidence=0.1,
        )
