"""API v1 路由聚合"""
from fastapi import APIRouter

from app.api.v1 import dashboard, dishes, config, chat, upload

router = APIRouter()

router.include_router(dashboard.router, prefix="/dashboard", tags=["日报看板"])
router.include_router(dishes.router, prefix="/dishes", tags=["菜品诊断"])
router.include_router(config.router, prefix="/config", tags=["系统配置"])
router.include_router(chat.router, prefix="/chat", tags=["智能问答"])
router.include_router(upload.router, prefix="/upload", tags=["数据上传"])
