"""数据同步 API —— 把未同步的评论推入分析队列

真正的逻辑在 services/sync_service.py（定时任务复用同一份实现），
这里只做参数校验与错误码转换。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import get_db
from app.services.sync_service import DEFAULT_BATCH_LIMIT, EnqueueFailed, sync_pending_reviews

router = APIRouter()


@router.post("/sync")
async def sync_reviews(
    shop_id: int = Query(None, description="按店铺过滤，缺省同步全部"),
    limit: int = Query(DEFAULT_BATCH_LIMIT, ge=1, le=10000, description="单次最多同步的评论数"),
    db: AsyncSession = Depends(get_db),
):
    """手动触发一次同步：未同步评论 → 预处理 → 分片入队"""
    try:
        return await sync_pending_reviews(db, shop_id=shop_id, limit=limit)
    except EnqueueFailed as e:
        raise HTTPException(status_code=503, detail=f"入队失败，本次未标记已同步：{e}")
