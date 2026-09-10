"""内部回调端点 —— 供 Agent 服务回写分析结果

不对外暴露，仅容器网络内可达（agent → backend）。
Agent 不直连 MySQL：写 diagnoses 表、回写评论精判标签、推人工复核告警都在这里完成。
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import get_db, Review, Diagnosis, DiagnosisStatus, Sentiment

router = APIRouter()
logger = logging.getLogger(__name__)


class RefinedReview(BaseModel):
    """Agent 精判后回写单条评论的标签"""
    review_id: int
    sentiment: str | None = None
    # 注意：这里不是 list[str]。reviews.dimensions 的既有形状是
    # [{"dimension": "口味", "keyword": "太咸"}, ...]（前置词典与 Agent 都这么写），
    # 声明成 list[str] 会让整条回调 422，诊断一份都落不了库。
    dimensions: list[Any] | None = None
    risk_level: int | None = None
    dimension_detail: list[dict] | None = None


class DiagnosisIn(BaseModel):
    batch_id: str | None = None
    dish_id: str | None = None
    dish_name: str = ""
    decision_id: str | None = None
    summary: str = ""
    corrective_action: str = ""
    confidence: float = 0.0
    human_review_required: bool = False
    conflict_type: str | None = None
    conflict_analysis: dict | None = None
    reviews: list[RefinedReview] = Field(default_factory=list)


@router.post("/internal/diagnosis")
async def write_diagnosis(body: DiagnosisIn, db: AsyncSession = Depends(get_db)):
    """Agent 深度加工结果落库

    幂等：同一 decision_id 重复回调（消息重投）不重复写诊断。
    """
    if body.decision_id:
        existing = (await db.execute(
            select(Diagnosis).where(Diagnosis.decision_id == body.decision_id)
        )).scalar_one_or_none()
        if existing:
            return {"status": "ok", "diagnosis_id": existing.id, "deduplicated": True}

    dish_id = int(body.dish_id) if (body.dish_id or "").isdigit() else None

    diag = Diagnosis(
        dish_id=dish_id,
        dish_name=body.dish_name or "",
        status=DiagnosisStatus.COMPLETED,
        decision_id=body.decision_id,
        summary=(body.summary or "")[:200],
        corrective_action=body.corrective_action or "",
        conflict_type=body.conflict_type,
        conflict_analysis=body.conflict_analysis,
        confidence=body.confidence,
        human_review_required=body.human_review_required,
        triggered_at=datetime.now(),
    )
    db.add(diag)

    # 回写评论精判标签（前置节点是词典粗判，这里覆盖为 Agent 精判）
    reviews_updated = 0
    if body.reviews:
        ids = [r.review_id for r in body.reviews]
        rows = (await db.execute(select(Review).where(Review.id.in_(ids)))).scalars().all()
        by_id = {r.id: r for r in rows}
        for refined in body.reviews:
            row = by_id.get(refined.review_id)
            if row is None:
                continue
            if refined.sentiment:
                try:
                    row.sentiment = Sentiment(refined.sentiment)
                except ValueError:
                    logger.warning(f"[Internal] 未知情感标签: {refined.sentiment}")
            if refined.dimensions is not None:
                row.dimensions = refined.dimensions
            if refined.risk_level is not None:
                row.risk_level = refined.risk_level
            if refined.dimension_detail is not None:
                row.dimension_detail = refined.dimension_detail
            row.label_source = "llm"
            reviews_updated += 1

    await db.commit()
    await db.refresh(diag)

    if diag.human_review_required:
        await _push_review_alert(
            dish_name=diag.dish_name,
            dish_id=dish_id,
            decision_id=diag.decision_id,
            summary=diag.summary,
            confidence=diag.confidence,
            db=db,
        )

    logger.info(
        f"[Internal] 诊断落库 #{diag.id} 菜品={diag.dish_name} "
        f"回写评论={reviews_updated} 待复核={diag.human_review_required}"
    )
    return {
        "status": "ok",
        "diagnosis_id": diag.id,
        "reviews_updated": reviews_updated,
        "deduplicated": False,
    }


async def _push_review_alert(dish_name, dish_id, decision_id, summary, confidence, db=None):
    """需要人工复核的诊断结果推送告警"""
    try:
        from app.push.dispatcher import get_dispatcher
        from app.push.base import Alert, AlertLevel

        confidence_pct = f"{confidence:.0%}" if confidence else "N/A"
        dispatcher = get_dispatcher()
        await dispatcher.dispatch(Alert(
            level=AlertLevel.WARNING,
            title=f"需人工复核：{dish_name}",
            content=f"**决策ID**：{decision_id or 'N/A'}\n"
                    f"**置信度**：{confidence_pct}\n"
                    f"**摘要**：{summary or '无'}\n\n"
                    f"请在 Dashboard 中查看详情并复核。",
            dish_name=dish_name,
            dish_id=dish_id,
            decision_id=decision_id,
        ), db=db)
    except Exception as e:
        logger.warning(f"[Alert] 复核告警推送失败: {e}")
