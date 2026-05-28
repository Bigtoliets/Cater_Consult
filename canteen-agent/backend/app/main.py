"""FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1 import router as v1_router
from app.models.base import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：创建表（生产环境应使用 Alembic 迁移）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # 关闭时
    await engine.dispose()


app = FastAPI(
    title="食堂品控智能Agent系统",
    description="Canteen Quality Control Agent System API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(v1_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health_check():
    """健康检查端点"""
    import pymysql
    import redis as redis_lib

    services = {}

    # MySQL
    try:
        conn = pymysql.connect(
            host=settings.MYSQL_HOST,
            port=settings.MYSQL_PORT,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            database=settings.MYSQL_DATABASE,
            connect_timeout=3,
        )
        conn.close()
        services["mysql"] = "connected"
    except Exception:
        services["mysql"] = "disconnected"

    # Redis
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.ping()
        r.close()
        services["redis"] = "connected"
    except Exception:
        services["redis"] = "disconnected"

    # RabbitMQ
    try:
        import pika
        params = pika.URLParameters(settings.RABBITMQ_URL)
        conn = pika.BlockingConnection(params)
        conn.close()
        services["rabbitmq"] = "connected"
    except Exception:
        services["rabbitmq"] = "disconnected"

    all_ok = all(v == "connected" for v in services.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "services": services,
    }
