"""待同步评论 → 预处理 → 分片入队 —— 唯一实现

HTTP 端点（POST /api/v1/sync）与定时任务（periodic_tasks.auto_sync_new_reviews）
共用这一份逻辑，避免「手动同步」和「自动同步」长出两套不同行为。

一致性策略（at-least-once，不丢评论）：
- 先入队，后标记 synced_at 并提交；入队失败 → 抛 EnqueueFailed → 回滚 →
  评论保持未同步，下次同步重试。
- 下游靠消费组 + ACK 保证可靠消费，分片聚合用 INCR 原子计数。
"""
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Review
from app.services.review_processor import (
    get_dish_review_groups,
    get_keyword_weights,
    process_new_reviews,
)
from app.tasks.redis_queue import push_dish_chunks

logger = logging.getLogger(__name__)

DEFAULT_BATCH_LIMIT = 1000


class EnqueueFailed(RuntimeError):
    """入队失败（HTTP 层转 503，让调用方知道本次没有标记已同步）"""


async def sync_pending_reviews(
    db: AsyncSession,
    shop_id: int | None = None,
    limit: int = DEFAULT_BATCH_LIMIT,
) -> dict:
    """读未同步评论 → 预处理 → 按菜品聚组 → 分片入队 → 标记已同步"""
    # 1. 查询待同步评论
    query = (
        select(Review.id)
        .where(Review.synced_at.is_(None), Review.is_valid.is_(True))
        .order_by(Review.id)
        .limit(limit)
    )
    if shop_id is not None:
        query = query.where(Review.shop_id == shop_id)

    review_ids = [row[0] for row in (await db.execute(query)).all()]
    if not review_ids:
        return {
            "status": "ok", "synced": 0, "dish_count": 0,
            "batch_id": None, "message": "无新增评论",
        }

    # 2. 预处理：情感分析 / 维度提取 / 风险评分 / 菜品匹配（词典粗判，Agent 之后会覆盖）
    await process_new_reviews(db, review_ids)

    # 3. 按菜品聚合 + 附权重
    dish_groups = await get_dish_review_groups(db, review_ids)
    keyword_weights = await get_keyword_weights(db)
    for group in dish_groups.values():
        group["keyword_weights"] = keyword_weights

    # 4. 分片入 Redis Stream（agent-consumer 异步消费）
    batch_id = None
    if dish_groups:
        try:
            batch_id = await push_dish_chunks(list(dish_groups.values()))
        except Exception as e:  # noqa: BLE001
            logger.error(f"[Sync] 入队失败，本次不标记已同步（下次会重试）: {e}")
            raise EnqueueFailed(str(e)) from e

    # 5. 标记已同步 + 提交（放在入队之后，保证不丢评论）
    await db.execute(
        update(Review).where(Review.id.in_(review_ids)).values(synced_at=datetime.now())
    )
    await db.commit()

    return {
        "status": "ok",
        "synced": len(review_ids),
        "dish_count": len(dish_groups),
        "batch_id": batch_id,
        "message": f"已同步 {len(review_ids)} 条评论，下发 {len(dish_groups)} 个菜品到分析队列",
    }
