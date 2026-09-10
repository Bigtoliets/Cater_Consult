"""数据库初始化 —— 建库 + 建表 + 种子数据（唯一入口，可重复执行）

    cd backend && python init_db.py

为什么只有这一个入口：
- 建表以 SQLAlchemy 模型为唯一事实来源（backend/app/models/models.py），
  不再维护手工 SQL 建表脚本 —— 那种写法一旦和模型漂移，新建库就会缺列，
  而启动时的 `create_all` 只建「不存在的表」，不会给已有表补列。
- 种子数据用 ORM 幂等写入（存在即跳过），重复执行不会产生脏数据。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, select, text

from app.config import settings
from app.models.base import Base, sync_engine
from app.models.models import Dish, SOPEntry, Shop, SystemConfig
from app import models  # noqa: F401  确保所有模型注册到 Base.metadata


def create_database_if_not_exists() -> None:
    """连接 MySQL 服务器（不指定库），创建目标数据库"""
    server_url = (
        f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
        f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/"
    )
    server_engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with server_engine.connect() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DATABASE}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
    server_engine.dispose()
    print(f"[init_db] 数据库 `{settings.MYSQL_DATABASE}` 已就绪")


def create_tables() -> None:
    """按 SQLAlchemy 模型创建全部表（只建缺失的表，不动已有表）"""
    Base.metadata.create_all(sync_engine)
    table_names = sorted(Base.metadata.tables.keys())
    print(f"[init_db] 共 {len(table_names)} 张表: {', '.join(table_names)}")


SEED_SHOPS = [
    {"id": 1, "name": "一食堂", "address": "一楼东侧"},
    {"id": 2, "name": "二食堂", "address": "二楼西侧"},
]

SEED_DISHES = [
    # name, category, unit_cost, price, shop_id
    ("红烧肉", "热菜", 4.20, 12.00, 1),
    ("麻婆豆腐", "热菜", 2.50, 8.00, 1),
    ("宫保鸡丁", "热菜", 3.80, 10.00, 1),
    ("兰州拉面", "面食", 2.00, 8.00, 2),
    ("炸酱面", "面食", 2.50, 9.00, 2),
    ("白切鸡", "热菜", 5.00, 15.00, 1),
    ("清炒时蔬", "热菜", 1.50, 6.00, 1),
    ("糖醋里脊", "热菜", 4.50, 12.00, 1),
    ("番茄炒蛋", "热菜", 1.80, 6.00, 2),
    ("土豆肉丝", "热菜", 2.80, 8.00, 2),
]

SEED_SOP = [
    (1, "sop", "红烧肉标准工艺",
     "【红烧肉标准工艺】\n- 五花肉切 3cm 方块，焯水去血沫\n- 炒糖色：冰糖 30g，小火熬至枣红色\n"
     "- 炖煮：高压锅上汽后压制 20 分钟\n- 调味：生抽 15ml、老抽 5ml、盐 5g、料酒 10ml\n"
     "- 收汁：大火收至汤汁浓稠\n- 出餐温度：≥ 75°C",
     {"cook_time_min": 20, "salt_g": 5, "temp_c": 75}),
    (1, "cost", "红烧肉成本卡",
     "【红烧肉单份成本 ¥4.20】\n- 五花肉 150g: ¥3.00\n- 调料: ¥0.60\n- 辅料: ¥0.30\n- 能耗分摊: ¥0.30",
     {"unit_cost": 4.20, "meat_g": 150}),
    (1, "food_safety", "红烧肉食安规范",
     "【红烧肉食安要点】\n- 猪肉中心温度 ≥ 75°C\n- 炖煮时间 ≥ 20 分钟\n- 成品常温存放 ≤ 2 小时\n- 回锅加热需达 75°C 以上",
     {"min_cook_temp": 75, "max_room_temp_hours": 2}),
]

SEED_CONFIGS = [
    ("sensitive_words",
     {"words": ["拉肚子", "食物中毒", "钢丝球", "变质", "异味", "头发", "虫子"]}, "敏感词订阅"),
    ("warning_thresholds",
     {"food_safety": 3, "negative_rate": 0.10, "batch_size": 50}, "预警阈值"),
    ("rag_params",
     {"top_k": 3, "similarity_threshold": 0.6, "pool_size": 20}, "RAG检索参数"),
    ("ai_inference",
     {"confidence_threshold": 0.75, "weight_sample_density": 0.3,
      "weight_sop_mapping": 0.4, "weight_history_similarity": 0.3}, "AI推理权重"),
    ("keyword_weights",
     {"口味": 1.0, "卫生": 3.0, "分量": 1.0, "温度": 1.0,
      "口感": 1.5, "价格": 1.0, "服务": 1.0, "安全": 5.0}, "维度关键词权重"),
    ("push_rules",
     {"critical": ["wechat_work", "dingtalk"], "warning": ["wechat_work"],
      "info": ["wechat_work"], "update": []}, "推送路由规则"),
    ("system_initialized", {"version": "4.1.0"}, "系统初始化标记"),
]


def seed_data() -> None:
    """幂等写入种子数据（存在即跳过，可重复执行）"""
    from sqlalchemy.orm import Session

    added = {"shops": 0, "dishes": 0, "sop": 0, "configs": 0}
    with Session(sync_engine) as session:
        for shop in SEED_SHOPS:
            if session.get(Shop, shop["id"]) is None:
                session.add(Shop(**shop))
                added["shops"] += 1
        session.flush()

        for name, category, unit_cost, price, shop_id in SEED_DISHES:
            exists = session.execute(select(Dish.id).where(Dish.name == name)).scalar_one_or_none()
            if exists is None:
                session.add(Dish(
                    name=name, category=category,
                    unit_cost=unit_cost, price=price, shop_id=shop_id,
                ))
                added["dishes"] += 1

        for dish_id, dimension, title, content, meta in SEED_SOP:
            exists = session.execute(
                select(SOPEntry.id).where(SOPEntry.dish_id == dish_id, SOPEntry.title == title)
            ).scalar_one_or_none()
            if exists is None:
                session.add(SOPEntry(
                    dish_id=dish_id, dimension=dimension, title=title,
                    content=content, metadata_json=meta,
                ))
                added["sop"] += 1

        for key, value, description in SEED_CONFIGS:
            exists = session.execute(
                select(SystemConfig.id).where(
                    SystemConfig.scope == "global", SystemConfig.config_key == key
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(SystemConfig(
                    scope="global", config_key=key,
                    config_value=value, description=description,
                ))
                added["configs"] += 1

        session.commit()

    print(
        f"[init_db] 种子数据: 新增 店铺 {added['shops']} / 菜品 {added['dishes']} / "
        f"SOP {added['sop']} / 配置 {added['configs']}（已存在的跳过）"
    )


if __name__ == "__main__":
    create_database_if_not_exists()
    create_tables()
    seed_data()
    print("✅ 数据库初始化完成")
