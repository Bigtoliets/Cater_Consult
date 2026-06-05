"""每日菜品质量日报 API"""
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date

from app.models import get_db, Review, DailySummary, Sentiment, Diagnosis

router = APIRouter()


@router.get("/summary")
async def get_daily_summary(
    target_date: date = Query(None, description="查询日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """获取日报摘要：全局情绪指数、红黑榜"""
    if target_date is None:
        target_date = date.today()

    result = await db.execute(
        select(DailySummary).where(func.date(DailySummary.date) == target_date)
    )
    summary = result.scalar_one_or_none()

    if summary:
        return {
            "date": str(target_date),
            "total_reviews": summary.total_reviews,
            "positive_rate": summary.positive_rate,
            "neutral_rate": summary.neutral_rate,
            "negative_rate": summary.negative_rate,
            "top_good": summary.top_good,
            "top_bad": summary.top_bad,
            "ai_summary": summary.ai_summary,
            "cached": True,
        }

    reviews_query = select(Review).where(
        func.date(Review.reviewed_at) == target_date,
        Review.is_valid == True,
    )
    result = await db.execute(reviews_query)
    reviews = result.scalars().all()

    total = len(reviews)
    if total == 0:
        return {
            "date": str(target_date),
            "total_reviews": 0,
            "positive_rate": 0,
            "neutral_rate": 0,
            "negative_rate": 0,
            "top_good": [],
            "top_bad": [],
            "ai_summary": "今日暂无评价数据。",
            "cached": False,
        }

    pos = sum(1 for r in reviews if r.sentiment == Sentiment.POSITIVE)
    neu = sum(1 for r in reviews if r.sentiment == Sentiment.NEUTRAL)
    neg = sum(1 for r in reviews if r.sentiment == Sentiment.NEGATIVE)

    matched_dish_ids = list({r.dish_id for r in reviews if r.dish_id})
    dish_name_map = {}
    if matched_dish_ids:
        from app.models.models import Dish
        dish_result = await db.execute(
            select(Dish.id, Dish.name).where(Dish.id.in_(matched_dish_ids))
        )
        dish_name_map = {did: dname for did, dname in dish_result.all()}

    dish_neg_count: dict = {}
    dish_pos_count: dict = {}

    def _get_dish_key(r) -> str | None:
        if r.dish_id:
            return f"id:{r.dish_id}"
        if r.dish_name_raw and r.dish_name_raw.strip():
            return f"raw:{r.dish_name_raw.strip()}"
        return None

    def _get_dish_label(r) -> str:
        if r.dish_id and r.dish_id in dish_name_map:
            return dish_name_map[r.dish_id]
        if r.dish_name_raw and r.dish_name_raw.strip():
            return r.dish_name_raw.strip()
        return "未知菜品"

    for r in reviews:
        key = _get_dish_key(r)
        if not key:
            continue
        label = _get_dish_label(r)
        if r.sentiment == Sentiment.NEGATIVE:
            if key not in dish_neg_count:
                dish_neg_count[key] = {"count": 0, "dish_id": r.dish_id, "dish_name": label}
            dish_neg_count[key]["count"] += 1
        elif r.sentiment == Sentiment.POSITIVE:
            if key not in dish_pos_count:
                dish_pos_count[key] = {"count": 0, "dish_id": r.dish_id, "dish_name": label}
            dish_pos_count[key]["count"] += 1

    top_bad = sorted(dish_neg_count.values(), key=lambda x: x["count"], reverse=True)[:3]
    top_good = sorted(dish_pos_count.values(), key=lambda x: x["count"], reverse=True)[:3]

    return {
        "date": str(target_date),
        "total_reviews": total,
        "positive_rate": round(pos / total, 2),
        "neutral_rate": round(neu / total, 2),
        "negative_rate": round(neg / total, 2),
        "top_good": top_good,
        "top_bad": top_bad,
        "ai_summary": "",
        "cached": False,
    }


@router.get("/summary-table")
async def get_summary_table(
    target_date: date = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取菜品级 AI 融合改进摘要表格"""
    if target_date is None:
        target_date = date.today()

    result = await db.execute(
        select(Diagnosis)
        .where(func.date(Diagnosis.created_at) == target_date)
        .order_by(Diagnosis.created_at.desc())
    )
    diagnoses = result.scalars().all()

    table = []
    for d in diagnoses:
        dish_name = d.dish_name or f"菜品#{d.dish_id}"
        table.append({
            "id": d.id,
            "dish_id": d.dish_id,
            "dish_name": dish_name,
            "decision_id": d.decision_id,
            "summary": d.summary or "",
            "corrective_action": d.corrective_action,
            "conflict_type": d.conflict_type,
            "confidence": d.confidence,
            "human_review_required": d.human_review_required,
        })

    return {"date": str(target_date), "table": table, "total": len(table)}
