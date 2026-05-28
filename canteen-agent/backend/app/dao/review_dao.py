"""DAO 数据访问层"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.models import Review, Diagnosis, Dish, DailySummary, Sentiment


class ReviewDAO:
    """评价数据访问"""

    @staticmethod
    async def get_by_dish(db: AsyncSession, dish_id: int, sentiment: str = None, limit: int = 20):
        query = select(Review).where(Review.dish_id == dish_id)
        if sentiment:
            query = query.where(Review.sentiment == sentiment)
        query = query.order_by(Review.created_at.desc()).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count_today(db: AsyncSession, dish_id: int = None, sentiment: str = None):
        query = select(func.count(Review.id)).where(
            func.date(Review.reviewed_at) == func.current_date()
        )
        if dish_id:
            query = query.where(Review.dish_id == dish_id)
        if sentiment:
            query = query.where(Review.sentiment == sentiment)
        result = await db.execute(query)
        return result.scalar() or 0


class DiagnosisDAO:
    """诊断数据访问"""

    @staticmethod
    async def get_latest(db: AsyncSession, dish_id: int):
        result = await db.execute(
            select(Diagnosis)
            .where(Diagnosis.dish_id == dish_id)
            .order_by(Diagnosis.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, dish_id: int, **kwargs):
        diag = Diagnosis(dish_id=dish_id, **kwargs)
        db.add(diag)
        await db.flush()
        return diag
