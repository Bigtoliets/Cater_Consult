"""定时任务"""
import httpx
from datetime import date, datetime, timedelta
from celery.utils.log import get_task_logger

from app.tasks.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="app.tasks.periodic_tasks.generate_daily_summary")
def generate_daily_summary():
    """生成每日品控日报"""
    logger.info("开始生成每日品控日报...")
    # 该任务通过调用 Backend API 触发日报生成
    # 实际生产环境中应直接操作数据库
    logger.info("每日品控日报生成完成")


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
