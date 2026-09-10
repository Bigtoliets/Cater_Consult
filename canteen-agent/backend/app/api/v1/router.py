"""API v1 路由聚合"""
from fastapi import APIRouter

from app.api.v1 import dashboard, dishes, config, chat, sync, shops, internal

router = APIRouter()

router.include_router(dashboard.router, prefix="/dashboard", tags=["日报看板"])
router.include_router(dishes.router, prefix="/dishes", tags=["菜品诊断"])
router.include_router(config.router, prefix="/config", tags=["系统配置"])
router.include_router(chat.router, prefix="/chat", tags=["智能问答"])
router.include_router(sync.router, tags=["数据同步"])
router.include_router(shops.router, prefix="/shops", tags=["店铺管理"])
router.include_router(internal.router, tags=["内部回调"])
