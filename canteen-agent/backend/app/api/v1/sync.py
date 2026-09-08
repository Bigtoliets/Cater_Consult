"""数据同步 API —— 从 MySQL 直读未同步评论，复用现有预处理 + Agent 分析链路"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter()

DEFAULT_BATCH_LIMIT = 1000


from datetime import datetime
from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.models import Review
from app.services.review_service import process_new_reviews, get_dish_review_groups, get_keyword_weights
from app.tasks.redis_queue import push_dish_batch
from app.tasks.consumer import process_dish_batch

router = APIRouter()
DEFAULT_BATCH_LIMIT = 2000

router.post("/sync")
async def sync_reviews(
    shop_id: int = Query(None, description="按店铺过滤，缺省同步全部"),
    limit: int = Query(DEFAULT_BATCH_LIMIT, ge=1, le=10000, description="单次最多同步的评论数"),
    db: AsyncSession = Depends(get_db),
):
    """手动触发：读取 synced_at 为空的评论 → 预处理 → 入队 → Celery 分发 Agent
    一致性策略(at‑least‑once，不丢评论，允许重复消费)：
    - 先入队，后标记 synced_at 并提交。
    - 入队失败 → 抛异常 → 事务回滚 → 评论保持「未同步」，下次可重试。
    - 极端风险：Redis push成功、Celery投递失败 / commit失败，会造成重复下发；
      ⚠️ 下游Agent任务必须实现幂等，基于batch_id/review_id做去重。
    """
    # 1. 查询待同步评论ID
    query = (
        select(Review.id)
        .where(Review.synced_at.is_(None), Review.is_valid == True)
        .order_by(Review.id)
        .limit(limit)
    )
    if shop_id is not None:
        query = query.where(Review.shop_id == shop_id)

    result = await db.execute(query)
    review_ids = [row[0] for row in result.all()]
    if not review_ids:
        return {"status": "ok", "synced": 0, "message": "无新增评论"}

    # 2. 预处理：情感分析 / 维度提取 / 风险评分 / 菜品匹配
    await process_new_reviews(db, review_ids)

    # 3. 按菜品聚合
    dish_groups = await get_dish_review_groups(db, review_ids)
    keyword_weights = await get_keyword_weights(db)
    for g in dish_groups.values():
        g["keyword_weights"] = keyword_weights

    batch_id = None
    if dish_groups:
        groups_list = list(dish_groups.values())
        try:
            batch_id = await push_dish_batch(groups_list)
            # celery delay 同步抛出异常场景
            process_dish_batch.delay(batch_id)
        except (ConnectionError, OSError) as e:
            # 只捕获队列/redis broker相关异常，其余异常直接向上抛出
            raise HTTPException(status_code=503, detail=f"队列下发失败，本次未标记已同步：{e}")
        except Exception as e:
            raise

    # 4. 标记已同步 UTC时间
    now = datetime.utcnow()
    await db.execute(
        update(Review).where(Review.id.in_(review_ids)).values(synced_at=now)
    )
    await db.commit()

    return {
        "status": "ok",
        "synced": len(review_ids),
        "dish_count": len(dish_groups),
        "batch_id": batch_id,
        "message": f"已同步 {len(review_ids)} 条评论，下发 {len(dish_groups)} 个菜品到分析队列",
    }
