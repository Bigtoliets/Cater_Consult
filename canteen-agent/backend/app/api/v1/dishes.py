"""菜品单项诊断 API —— 含 AI 改进摘要"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import get_db, Dish, Review, Diagnosis, Sentiment

router = APIRouter()


@router.get("/{dish_id}/diagnosis")
async def get_dish_diagnosis(
    dish_id: int,
    db: AsyncSession = Depends(get_db),
):
    dish_result = await db.execute(select(Dish).where(Dish.id == dish_id))
    dish = dish_result.scalar_one_or_none()
    if not dish:
        raise HTTPException(status_code=404, detail="菜品不存在")

    diag_result = await db.execute(
        select(Diagnosis)
        .where(Diagnosis.dish_id == dish_id)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    diagnosis = diag_result.scalar_one_or_none()

    reviews_result = await db.execute(
        select(Review)
        .where(Review.dish_id == dish_id)
        .order_by(Review.created_at.desc())
        .limit(20)
    )
    all_reviews = reviews_result.scalars().all()

    today_reviews_result = await db.execute(
        select(func.count(Review.id))
        .where(Review.dish_id == dish_id, func.date(Review.reviewed_at) == func.current_date())
    )
    today_total = today_reviews_result.scalar() or 0

    today_neg_result = await db.execute(
        select(func.count(Review.id))
        .where(
            Review.dish_id == dish_id,
            Review.sentiment == Sentiment.NEGATIVE,
            func.date(Review.reviewed_at) == func.current_date(),
        )
    )
    today_neg = today_neg_result.scalar() or 0

    return {
        "dish": {
            "id": dish.id,
            "name": dish.name,
            "category": dish.category,
            "unit_cost": dish.unit_cost,
            "price": dish.price,
        },
        "today_stats": {
            "total_reviews": today_total,
            "negative_count": today_neg,
            "negative_rate": round(today_neg / today_total, 2) if today_total > 0 else 0,
        },
        "diagnosis": {
            "id": diagnosis.id,
            "decision_id": diagnosis.decision_id,
            "status": diagnosis.status.value if diagnosis and diagnosis.status else None,
            "conflict_type": diagnosis.conflict_type,
            "confidence": diagnosis.confidence,
            "summary": diagnosis.summary or "",
            "corrective_action": diagnosis.corrective_action,
            "human_review_required": diagnosis.human_review_required,
        } if diagnosis else None,
        "reviews": [
            {
                "id": r.id,
                "raw_text": r.raw_text,
                "sentiment": r.sentiment.value if r.sentiment else None,
                "rating": r.rating,
                "dimensions": r.dimensions,
                "reviewed_at": str(r.reviewed_at) if r.reviewed_at else None,
            }
            for r in all_reviews
        ],
    }


@router.get("/{dish_id}/reviews")
async def get_dish_reviews(
    dish_id: int,
    sentiment: str = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    query = select(Review).where(Review.dish_id == dish_id)
    if sentiment:
        query = query.where(Review.sentiment == sentiment)
    query = query.order_by(Review.created_at.desc()).limit(limit)
    result = await db.execute(query)
    reviews = result.scalars().all()
    return {
        "dish_id": dish_id,
        "count": len(reviews),
        "reviews": [
            {
                "id": r.id,
                "source": r.source,
                "raw_text": r.raw_text,
                "sentiment": r.sentiment.value if r.sentiment else None,
                "rating": r.rating,
                "dimensions": r.dimensions,
                "reviewed_at": str(r.reviewed_at) if r.reviewed_at else None,
            }
            for r in reviews
        ],
    }


@router.post("/{dish_id}/diagnosis/dispatch")
async def dispatch_diagnosis(dish_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Diagnosis).where(Diagnosis.dish_id == dish_id).order_by(Diagnosis.created_at.desc()).limit(1)
    )
    diagnosis = result.scalar_one_or_none()
    if not diagnosis:
        raise HTTPException(status_code=404, detail="诊断报告不存在")
    from app.models.models import DiagnosisStatus
    diagnosis.status = DiagnosisStatus.DISPATCHED
    await db.flush()
    return {"status": "ok"}


@router.post("/{dish_id}/diagnosis/reject")
async def reject_diagnosis(dish_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Diagnosis).where(Diagnosis.dish_id == dish_id).order_by(Diagnosis.created_at.desc()).limit(1)
    )
    diagnosis = result.scalar_one_or_none()
    if not diagnosis:
        raise HTTPException(status_code=404, detail="诊断报告不存在")
    from app.models.models import DiagnosisStatus
    diagnosis.status = DiagnosisStatus.REJECTED
    await db.flush()
    return {"status": "ok"}
