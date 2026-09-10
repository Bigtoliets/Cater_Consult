"""定时任务（由 APScheduler 调度，替代 Celery Beat）"""
import logging
from datetime import date

from sqlalchemy import select, func

from app.models.base import AsyncSessionLocal
from app.models.models import Review, DailySummary, Sentiment

logger = logging.getLogger(__name__)


async def auto_sync_new_reviews():
    """自动同步：把「未同步」评论推入分析队列（默认每 5 分钟）

    这是链路的自动入口 —— 只要评论进了 reviews 表（外部系统写入 / 导入脚本 /
    直接 insert），下一轮就会自动走预处理与 Agent 深度加工，不需要人点按钮。
    """
    from app.services.sync_service import sync_pending_reviews

    try:
        async with AsyncSessionLocal() as session:
            result = await sync_pending_reviews(session)
    except Exception as e:  # noqa: BLE001 — 一轮失败不该让调度器停摆
        logger.error(f"[AutoSync] 自动同步失败: {e}")
        return

    if result.get("synced"):
        logger.info(
            f"[AutoSync] 已下发 {result['synced']} 条评论 / "
            f"{result['dish_count']} 个菜品 batch_id={result['batch_id']}"
        )


async def generate_daily_summary():
    """生成每日品控日报 — 写入 DailySummary 缓存表（每小时）"""
    logger.info("开始生成每日品控日报...")
    today = date.today()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Review).where(
                func.date(Review.reviewed_at) == today,
                Review.is_valid == True,
            )
        )
        reviews = result.scalars().all()

        total = len(reviews)
        if total == 0:
            logger.info("今日无评价数据，跳过日报生成")
            return

        pos = sum(1 for r in reviews if r.sentiment == Sentiment.POSITIVE)
        neu = sum(1 for r in reviews if r.sentiment == Sentiment.NEUTRAL)
        neg = sum(1 for r in reviews if r.sentiment == Sentiment.NEGATIVE)

        # 按菜品分组统计
        dish_pos: dict = {}
        dish_neg: dict = {}
        for r in reviews:
            key = r.dish_id or r.dish_name_raw
            label = r.dish_name_raw or f"菜品#{r.dish_id}"
            if not key:
                continue
            if r.sentiment == Sentiment.POSITIVE:
                if key not in dish_pos:
                    dish_pos[key] = {"dish_id": r.dish_id, "dish_name": label, "count": 0}
                dish_pos[key]["count"] += 1
            elif r.sentiment == Sentiment.NEGATIVE:
                if key not in dish_neg:
                    dish_neg[key] = {"dish_id": r.dish_id, "dish_name": label, "count": 0}
                dish_neg[key]["count"] += 1

        top_good = sorted(dish_pos.values(), key=lambda x: x["count"], reverse=True)[:3]
        top_bad = sorted(dish_neg.values(), key=lambda x: x["count"], reverse=True)[:3]

        # 写入或更新 DailySummary
        existing = (await session.execute(
            select(DailySummary).where(func.date(DailySummary.date) == today)
        )).scalar_one_or_none()

        if existing:
            existing.total_reviews = total
            existing.positive_rate = round(pos / total, 2) if total else 0
            existing.neutral_rate = round(neu / total, 2) if total else 0
            existing.negative_rate = round(neg / total, 2) if total else 0
            existing.top_good = top_good
            existing.top_bad = top_bad
        else:
            summary = DailySummary(
                date=today,
                total_reviews=total,
                positive_rate=round(pos / total, 2) if total else 0,
                neutral_rate=round(neu / total, 2) if total else 0,
                negative_rate=round(neg / total, 2) if total else 0,
                top_good=top_good,
                top_bad=top_bad,
            )
            session.add(summary)

        await session.commit()
    logger.info(f"每日品控日报生成完成，共 {total} 条评价")


async def track_feedback_effectiveness():
    """追踪整改效果 — 每天一次，自动飞升/降级方案权重"""
    from app.services.feedback_tracker import FeedbackTracker

    try:
        async with AsyncSessionLocal() as db:
            tracker = FeedbackTracker(db)
            stats = await tracker.track_all_active_diagnoses()
            logger.info(f"[FeedbackTracker] 效果追踪完成: {stats}")
    except Exception as e:
        logger.error(f"[FeedbackTracker] 追踪失败: {e}")


async def sync_sop_to_milvus():
    """将 MySQL SOP 知识条目同步到 Milvus 向量库 (sop_collection)"""
    logger.info("[SOP Sync] 开始同步 SOP 到 Milvus...")
    # TODO: 实现 SOP → Milvus 同步
    logger.info("[SOP Sync] 同步完成")


async def cleanup_old_data():
    """清理过期数据"""
    logger.info("开始清理过期数据...")
    # TODO: 实现清理逻辑
    logger.info("过期数据清理完成")
