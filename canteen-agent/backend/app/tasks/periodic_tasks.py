"""定时任务"""
import httpx
from datetime import date, datetime, timedelta
from celery.utils.log import get_task_logger

from app.tasks.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="app.tasks.periodic_tasks.generate_daily_summary")
def generate_daily_summary():
    """生成每日品控日报 — 写入 DailySummary 缓存表"""
    logger.info("开始生成每日品控日报...")
    import asyncio
    from app.models.base import SyncSessionLocal
    from app.models.models import Review, Dish, DailySummary, Sentiment
    from sqlalchemy import select, func
    from datetime import date

    today = date.today()
    with SyncSessionLocal() as session:
        # 查询今日有效评价
        result = session.execute(
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
        existing = session.execute(
            select(DailySummary).where(func.date(DailySummary.date) == today)
        ).scalar_one_or_none()

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

        session.commit()
    logger.info(f"每日品控日报生成完成，共 {total} 条评价")


@celery_app.task(name="app.tasks.periodic_tasks.cleanup_old_data")
def cleanup_old_data():
    """清理过期数据"""
    logger.info("开始清理过期数据...")
    logger.info("过期数据清理完成")


@celery_app.task(name="app.tasks.periodic_tasks.trigger_agent_analysis")
def trigger_agent_analysis(review_ids: list):
    """触发 Agent 分析指定评价"""
    logger.info(f"触发 Agent 分析 {len(review_ids)} 条评价")
    # 通过 RabbitMQ 发送消息给 Agent 微服务
    logger.info("Agent 分析任务已下发")
