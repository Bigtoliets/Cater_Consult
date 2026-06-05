"""SQLAlchemy 基础"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_sync_url = settings.DATABASE_URL
_async_url = _sync_url.replace("mysql+pymysql://", "mysql+aiomysql://")

engine = create_async_engine(
    _async_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,          # ✅ 连接前检测存活，防止使用已断开的连接
    pool_recycle=3600,           # ✅ 每小时回收连接，避免 MySQL wait_timeout 断连
    connect_args={
        "connect_timeout": 10,   # 连接超时 10s
    },
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

sync_engine = create_engine(
    _sync_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SyncSessionLocal = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
