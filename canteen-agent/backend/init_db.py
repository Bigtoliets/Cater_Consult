"""初始化数据库 —— 创建 canteen_agent 库（若不存在）+ 全部表结构

推荐用法（与 SQLAlchemy 模型完全一致，不会出现字段漂移）：
    cd backend && python init_db.py

说明：
- 后端启动时 Base.metadata.create_all 只会「新建不存在的表」，不会建库，
  因此首次部署需要先执行本脚本（或 init_db.sql）建库建表。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text

from app.config import settings
from app.models.base import Base, sync_engine
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
    """按 SQLAlchemy 模型创建全部表"""
    Base.metadata.create_all(sync_engine)
    table_names = sorted(Base.metadata.tables.keys())
    print(f"[init_db] 已创建 {len(table_names)} 张表: {', '.join(table_names)}")


if __name__ == "__main__":
    create_database_if_not_exists()
    create_tables()
    print("✅ 数据库初始化完成")
