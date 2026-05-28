"""数据库初始化脚本 —— 插入全局默认配置与种子数据"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.models.base import AsyncSessionLocal, engine, Base
from app.models.models import (
    Canteen, Stall, Chef, Dish, SystemConfig, SOPEntry
)


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # ===== 检查是否已初始化 =====
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.config_key == "system_initialized")
        )
        if result.scalar_one_or_none():
            print("✅ 系统已初始化，跳过种子数据")
            return

        # ===== 1. 创建默认食堂和档口 =====
        canteen1 = Canteen(name="一食堂", location="一楼东侧")
        canteen2 = Canteen(name="二食堂", location="二楼西侧")
        session.add_all([canteen1, canteen2])
        await session.flush()

        # 创建厨师
        chefs = [
            Chef(name="张师傅", phone="13800001001", speciality="川湘菜"),
            Chef(name="李师傅", phone="13800001002", speciality="面食"),
            Chef(name="王师傅", phone="13800001003", speciality="粤菜"),
            Chef(name="赵师傅", phone="13800001004", speciality="鲁菜"),
            Chef(name="刘师傅", phone="13800001005", speciality="家常菜"),
        ]
        session.add_all(chefs)
        await session.flush()

        # 创建档口
        stalls = [
            Stall(name="二楼川湘档口", canteen_id=canteen1.id, chef_id=chefs[0].id),
            Stall(name="面食档口", canteen_id=canteen1.id, chef_id=chefs[1].id),
            Stall(name="粤菜档口", canteen_id=canteen1.id, chef_id=chefs[2].id),
            Stall(name="鲁菜档口", canteen_id=canteen2.id, chef_id=chefs[3].id),
            Stall(name="家常菜档口", canteen_id=canteen2.id, chef_id=chefs[4].id),
            Stall(name="小吃档口", canteen_id=canteen2.id, chef_id=None),
        ]
        session.add_all(stalls)
        await session.flush()

        # 创建示例菜品
        dishes = [
            Dish(name="红烧肉", stall_id=stalls[0].id, category="热菜", unit_cost=4.20, price=12.00),
            Dish(name="麻婆豆腐", stall_id=stalls[0].id, category="热菜", unit_cost=2.50, price=8.00),
            Dish(name="宫保鸡丁", stall_id=stalls[0].id, category="热菜", unit_cost=3.80, price=10.00),
            Dish(name="兰州拉面", stall_id=stalls[1].id, category="面食", unit_cost=2.00, price=8.00),
            Dish(name="炸酱面", stall_id=stalls[1].id, category="面食", unit_cost=2.50, price=9.00),
            Dish(name="白切鸡", stall_id=stalls[2].id, category="热菜", unit_cost=5.00, price=15.00),
            Dish(name="清炒时蔬", stall_id=stalls[2].id, category="热菜", unit_cost=1.50, price=6.00),
            Dish(name="糖醋里脊", stall_id=stalls[3].id, category="热菜", unit_cost=4.50, price=12.00),
            Dish(name="番茄炒蛋", stall_id=stalls[4].id, category="热菜", unit_cost=1.80, price=6.00),
            Dish(name="土豆肉丝", stall_id=stalls[4].id, category="热菜", unit_cost=2.80, price=8.00),
        ]
        session.add_all(dishes)
        await session.flush()

        # ===== 2. 插入系统全局默认配置 =====
        default_configs = [
            SystemConfig(
                scope="global",
                config_key="sensitive_words",
                config_value={"words": ["拉肚子", "食物中毒", "钢丝球", "变质", "异味", "头发", "虫子"]},
                description="敏感词订阅列表",
            ),
            SystemConfig(
                scope="global",
                config_key="warning_thresholds",
                config_value={
                    "food_safety": 3,       # 1小时内同一菜品N条异物投诉即告警
                    "negative_rate": 0.10,  # 当日差评率阈值
                    "batch_size": 50,       # 批处理大小
                },
                description="预警阈值配置",
            ),
            SystemConfig(
                scope="global",
                config_key="rag_params",
                config_value={
                    "top_k": 3,
                    "similarity_threshold": 0.6,
                    "pool_size": 20,
                },
                description="RAG 检索参数",
            ),
            SystemConfig(
                scope="global",
                config_key="ai_inference",
                config_value={
                    "confidence_threshold": 0.75,
                    "weight_sample_density": 0.3,
                    "weight_sop_mapping": 0.4,
                    "weight_history_similarity": 0.3,
                },
                description="AI 推理权重配置",
            ),
            SystemConfig(
                scope="global",
                config_key="system_initialized",
                config_value={"version": "1.0.0", "initialized_at": "2024-01-01T00:00:00"},
                description="系统初始化标记",
            ),
        ]
        session.add_all(default_configs)

        # ===== 3. 插入示例 SOP 知识条目 =====
        sop_entries = [
            SOPEntry(
                dish_id=dishes[0].id,
                dimension="sop",
                title="红烧肉标准工艺",
                content="【红烧肉标准工艺】\n- 五花肉切 3cm 方块，焯水去血沫\n- 炒糖色：冰糖 30g，小火熬至枣红色\n- 炖煮：高压锅上汽后压制 20 分钟\n- 调味：生抽 15ml、老抽 5ml、盐 5g、料酒 10ml\n- 收汁：大火收至汤汁浓稠\n- 出餐温度：≥ 75°C",
                metadata_json={"cook_time_min": 20, "salt_g": 5, "temp_c": 75},
            ),
            SOPEntry(
                dish_id=dishes[0].id,
                dimension="cost",
                title="红烧肉成本卡",
                content="【红烧肉单份成本 ¥4.20】\n- 五花肉 150g: ¥3.00\n- 调料（酱油/糖/料酒）: ¥0.60\n- 辅料（葱姜八角）: ¥0.30\n- 能耗分摊: ¥0.30",
                metadata_json={"unit_cost": 4.20, "meat_g": 150},
            ),
            SOPEntry(
                dish_id=dishes[0].id,
                dimension="food_safety",
                title="红烧肉食安规范",
                content="【红烧肉食安要点】\n- 猪肉中心温度 ≥ 75°C\n- 炖煮时间 ≥ 20 分钟确保熟透\n- 成品常温存放 ≤ 2 小时\n- 回锅加热需达到 75°C 以上",
                metadata_json={"min_cook_temp": 75, "max_room_temp_hours": 2},
            ),
        ]
        session.add_all(sop_entries)

        await session.commit()
        print("✅ 种子数据初始化完成！")
        print(f"   - 食堂：2 个")
        print(f"   - 档口：{len(stalls)} 个")
        print(f"   - 厨师：{len(chefs)} 位")
        print(f"   - 菜品：{len(dishes)} 道")
        print(f"   - 系统配置：{len(default_configs)} 项")
        print(f"   - SOP 条目：{len(sop_entries)} 条")


if __name__ == "__main__":
    asyncio.run(seed())
