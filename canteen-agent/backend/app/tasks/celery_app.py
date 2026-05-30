"""Celery 应用与异步任务"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "canteen_agent",
    broker=settings.RABBITMQ_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.periodic_tasks", "app.tasks.consumer"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    beat_schedule={
        "generate-daily-summary": {
            "task": "app.tasks.periodic_tasks.generate_daily_summary",
            "schedule": 3600.0,
        },
        "cleanup-old-reviews": {
            "task": "app.tasks.periodic_tasks.cleanup_old_data",
            "schedule": 86400.0,
        },
    },
)
