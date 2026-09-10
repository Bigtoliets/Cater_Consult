"""APScheduler 定时任务调度器（内嵌在 backend 进程，替代 Celery Beat）

注意：任务跑在 backend 进程里，多开 backend 副本会重复执行 —— 生产环境请保持单副本，
或把 N 个副本的 AUTO_SYNC_INTERVAL_MINUTES/定时任务关掉再集中到一个实例上跑。
每个任务都设了 max_instances=1 + coalesce，避免上一轮没跑完就叠下一轮。
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.tasks import periodic_tasks

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _add(scheduler: AsyncIOScheduler, fn, trigger: IntervalTrigger, job_id: str):
    scheduler.add_job(
        fn, trigger,
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def init_scheduler() -> AsyncIOScheduler:
    """创建并配置定时任务（在 FastAPI lifespan 中启动）"""
    global _scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 自动同步：把 MySQL 里未同步的评论推入分析队列（AUTO_SYNC_INTERVAL_MINUTES=0 关闭）
    interval = settings.AUTO_SYNC_INTERVAL_MINUTES
    if interval > 0:
        _add(scheduler, periodic_tasks.auto_sync_new_reviews,
             IntervalTrigger(minutes=interval), "auto-sync-reviews")
    else:
        logger.info("[Scheduler] 自动同步已关闭（AUTO_SYNC_INTERVAL_MINUTES=0）")

    _add(scheduler, periodic_tasks.generate_daily_summary,
         IntervalTrigger(hours=1), "generate-daily-summary")
    _add(scheduler, periodic_tasks.track_feedback_effectiveness,
         IntervalTrigger(hours=24), "track-feedback")
    _add(scheduler, periodic_tasks.sync_sop_to_milvus,
         IntervalTrigger(hours=12), "sync-sop-to-milvus")
    _add(scheduler, periodic_tasks.cleanup_old_data,
         IntervalTrigger(hours=24), "cleanup-old-data")

    _scheduler = scheduler
    return scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
