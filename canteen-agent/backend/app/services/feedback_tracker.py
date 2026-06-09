"""整改效果追踪服务 (v3.0 新增)

跟踪整改单下发后的效果:
1. 对比整改前后的差评率变化
2. 自动飞升/降级方案权重
3. 生成 FeedbackRecord
4. 更新厨师画像

运行方式: Celery Beat 定时任务每天执行一次
"""
from datetime import date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Review, Diagnosis, Dish, FeedbackRecord,
    FeedbackStatus, Sentiment,
)


class FeedbackTracker:
    """整改效果追踪器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def track_all_active_diagnoses(self) -> dict:
        """追踪所有已下发但未验证效果的诊断"""
        from datetime import datetime

        # 查找最近 30 天内已下发的诊断（还没有 FeedbackRecord 的）
        thirty_days_ago = datetime.now() - timedelta(days=30)

        result = await self.db.execute(
            select(Diagnosis).where(
                Diagnosis.created_at >= thirty_days_ago,
                Diagnosis.status == "completed",
                Diagnosis.decision_id.isnot(None),
            )
        )
        diagnoses = result.scalars().all()

        stats = {"tracked": 0, "promoted": 0, "demoted": 0, "skipped": 0}
        for diag in diagnoses:
            try:
                result = await self._track_one(diag)
                stats["tracked"] += 1
                if result.get("auto_promoted"):
                    stats["promoted"] += 1
                if result.get("auto_demoted"):
                    stats["demoted"] += 1
            except Exception as e:
                print(f"[FeedbackTracker] {diag.decision_id} 追踪失败: {e}")
                stats["skipped"] += 1

        await self.db.flush()
        return stats

    async def _track_one(self, diag: Diagnosis) -> dict:
        """追踪单个诊断的整改效果"""
        if not diag.decision_id or not diag.dish_id:
            return {"tracked": False}

        # 检查是否已有反馈记录
        existing = await self.db.execute(
            select(FeedbackRecord).where(
                FeedbackRecord.decision_id == diag.decision_id,
            )
        )
        if existing.scalar_one_or_none():
            return {"tracked": False, "reason": "already_tracked"}

        # 计算整改前 7 天差评率
        pre_start = (diag.created_at - timedelta(days=7)) if diag.created_at else datetime.now() - timedelta(days=7)
        pre_end = diag.created_at or datetime.now()
        pre_neg_rate = await self._calc_negative_rate(diag.dish_id, pre_start, pre_end)

        # 如果整改时间不足 3 天，暂不评估
        now = datetime.now()
        if (now - (diag.created_at or now)).days < 3:
            return {"tracked": False, "reason": "too_early"}

        # 计算整改后 3/7/14 天差评率
        post_3d = await self._calc_negative_rate(
            diag.dish_id,
            diag.created_at or now,
            (diag.created_at or now) + timedelta(days=3),
        )
        post_7d = await self._calc_negative_rate(
            diag.dish_id,
            diag.created_at or now,
            (diag.created_at or now) + timedelta(days=7),
        )
        post_14d = await self._calc_negative_rate(
            diag.dish_id,
            diag.created_at or now,
            (diag.created_at or now) + timedelta(days=14),
        )

        # 改善百分比 (负值 = 差评率下降 = 改善)
        improvement_7d = post_7d - pre_neg_rate

        # 自动飞升/降级
        auto_promoted = False
        auto_demoted = False
        status = FeedbackStatus.EXECUTED

        if pre_neg_rate > 0 and improvement_7d < -0.1:
            # 差评率下降超过 10 个百分点 → 自动飞升金标
            auto_promoted = True
            status = FeedbackStatus.EFFECTIVE
            await self._auto_promote_to_gold(diag.decision_id)
        elif pre_neg_rate > 0 and improvement_7d > 0.05:
            # 差评率上升超过 5 个百分点 → 标记失效
            auto_demoted = True
            status = FeedbackStatus.INEFFECTIVE

        # 写入反馈记录
        record = FeedbackRecord(
            decision_id=diag.decision_id,
            dish_id=diag.dish_id,
            status=status,
            pre_negative_rate=round(pre_neg_rate, 3),
            post_negative_rate_3d=round(post_3d, 3),
            post_negative_rate_7d=round(post_7d, 3),
            post_negative_rate_14d=round(post_14d, 3),
            improvement_pct=round(improvement_7d, 3),
            auto_promoted=auto_promoted,
            auto_demoted=auto_demoted,
            executed_at=diag.created_at,
        )
        self.db.add(record)

        return {
            "tracked": True,
            "auto_promoted": auto_promoted,
            "auto_demoted": auto_demoted,
        }

    async def _calc_negative_rate(
        self, dish_id: int, start, end
    ) -> float:
        """计算指定时间段内某菜品的差评率"""
        total_result = await self.db.execute(
            select(func.count(Review.id)).where(
                Review.dish_id == dish_id,
                Review.reviewed_at >= start,
                Review.reviewed_at < end,
                Review.is_valid == True,
            )
        )
        total = total_result.scalar() or 0

        neg_result = await self.db.execute(
            select(func.count(Review.id)).where(
                Review.dish_id == dish_id,
                Review.reviewed_at >= start,
                Review.reviewed_at < end,
                Review.sentiment == Sentiment.NEGATIVE,
                Review.is_valid == True,
            )
        )
        neg = neg_result.scalar() or 0

        return neg / total if total > 0 else 0.0

    async def _auto_promote_to_gold(self, decision_id: str):
        """自动飞升金标 (调用 Agent 微服务)"""
        import httpx
        from app.config import settings

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{settings.AGENT_INTERNAL_URL}/agent/promote",
                    json={"decision_id": decision_id},
                )
                if resp.status_code == 200:
                    print(f"[FeedbackTracker] {decision_id} 自动飞升金标")
        except Exception as e:
            print(f"[FeedbackTracker] {decision_id} 自动飞升失败: {e}")


async def track_effectiveness(db: AsyncSession) -> dict:
    """便捷函数: 执行一次效果追踪"""
    from datetime import datetime
    tracker = FeedbackTracker(db)
    return await tracker.track_all_active_diagnoses()
