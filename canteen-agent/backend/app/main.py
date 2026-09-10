"""FastAPI 应用入口 v3.0"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1 import router as v1_router
from app.models.base import engine, Base
from app.push.wechat_work import WechatWorkPusher
from app.push.dingtalk import DingTalkPusher
from app.push.email_pusher import EmailPusher
from app.push.dispatcher import init_dispatcher, get_dispatcher
from app.tasks.scheduler import init_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：创建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 初始化推送调度器
    pushers = []
    if settings.WECOM_WEBHOOK_URL:
        pushers.append(WechatWorkPusher(settings.WECOM_WEBHOOK_URL))
    if settings.DINGTALK_WEBHOOK_URL:
        pushers.append(DingTalkPusher(
            settings.DINGTALK_WEBHOOK_URL,
            settings.DINGTALK_SECRET,
        ))
    if settings.SMTP_HOST:
        pushers.append(EmailPusher(
            settings.SMTP_HOST, settings.SMTP_PORT,
            settings.SMTP_SENDER, settings.SMTP_PASSWORD,
            settings.SMTP_RECIPIENTS.split(",") if settings.SMTP_RECIPIENTS else [],
        ))
    init_dispatcher(pushers)
    print(f"[Push] 已注册 {len(pushers)} 个推送通道: "
          f"{[p.channel_name for p in pushers]}")

    # 启动定时任务调度器
    scheduler = init_scheduler()
    scheduler.start()
    print("[Scheduler] 定时任务调度器已启动")

    yield

    # 关闭时
    scheduler.shutdown(wait=False)
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

    all_ok = all(v == "connected" for v in services.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "services": services,
    }
