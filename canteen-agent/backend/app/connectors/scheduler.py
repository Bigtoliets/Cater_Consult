"""定时数据拉取调度器 — 基于 APScheduler"""
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import BaseConnector, RawReview
from app.models.models import Review
from app.services.review_processor import process_new_reviews, get_dish_review_groups


class FetchScheduler:
    """定时拉取调度器 — 在 FastAPI lifespan 中启动和关闭"""

    def __init__(self, db_factory):
        self.scheduler = AsyncIOScheduler()
        self.db_factory = db_factory
        self.connectors: list[BaseConnector] = []

    def register(self, connector: BaseConnector):
        """注册数据连接器"""
        self.connectors.append(connector)

    async def _fetch_and_ingest(self, connector: BaseConnector):
        """拉取 → 去重 → 入库 → 预处理 → 分发 Agent"""
        async with self.db_factory() as db:
            now = datetime.now()
            last_fetch = now - timedelta(hours=1)

            try:
                raw_reviews = await connector.fetch(last_fetch, now)
            except Exception as e:
                print(f"[FetchScheduler] {connector.source_name} 拉取失败: {e}")
                return

            if not raw_reviews:
                return

            # 去重 + 入库
            new_ids = []
            for rr in raw_reviews:
                if rr.external_id:
                    # 检查 external_id 是否已存在
                    existing = await db.execute(
                        select(Review.id).where(
                            Review.source == connector.source_name,
                            Review.external_id == rr.external_id,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                review_data = connector.normalize(rr)
                review = Review(**review_data)
                db.add(review)
                await db.flush()
                new_ids.append(review.id)

            if not new_ids:
                return

            print(f"[FetchScheduler] {connector.source_name}: {len(new_ids)} 条新评价入库")

            # 预处理
            await process_new_reviews(db, new_ids)

            # 按菜品聚合 → 分发 Agent
            dish_groups = await get_dish_review_groups(db, new_ids)
            if dish_groups:
                from app.tasks.redis_queue import push_dish_batch
                from app.tasks.consumer import process_dish_batch
                batch_id = await push_dish_batch(list(dish_groups.values()))
                process_dish_batch.delay(batch_id)

    def start(self):
        """启动所有连接器的定时拉取任务"""
        for connector in self.connectors:
            self.scheduler.add_job(
                self._fetch_and_ingest,
                trigger=IntervalTrigger(minutes=30),
                args=[connector],
                id=f"fetch_{connector.source_name}",
                replace_existing=True,
            )
        if self.connectors:
            self.scheduler.start()
            print(f"[FetchScheduler] 已启动 {len(self.connectors)} 个连接器: "
                  f"{[c.source_name for c in self.connectors]}")

    def stop(self):
        """关闭调度器"""
        self.scheduler.shutdown(wait=False)
