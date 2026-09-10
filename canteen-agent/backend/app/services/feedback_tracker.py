"""整改效果追踪服务

跟踪整改单下发后的效果：
1. 对比整改前后的差评率变化（3/7/14 天观察窗，窗口与判定逻辑在 feedback_windows.py）
2. 有效 → 自动飞升金标；无效 → 标记失效
3. 落一条 FeedbackRecord

运行方式：APScheduler 定时任务，每天一次（app/tasks/periodic_tasks.py）
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Diagnosis,
    DiagnosisStatus,
    FeedbackRecord,
    FeedbackStatus,
    Review,
    Sentiment,
)
from app.services.feedback_windows import MIN_DAYS_FOR_VERDICT, evaluate, tracking_windows

logger = logging.getLogger(__name__)

# 纳入追踪的诊断状态：completed=已出报告，dispatched=已下发后厨。
# 只认 completed 会把真正执行过的整改单漏掉 —— 而它们才是效果评估的对象。
TRACKED_STATUSES = (DiagnosisStatus.COMPLETED, DiagnosisStatus.DISPATCHED)

# 只回溯这么久以内的诊断
TRACK_WINDOW_DAYS = 30
# 整改前基线窗口
BASELINE_DAYS = 7


class FeedbackTracker:
    """整改效果追踪器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def track_all_active_diagnoses(self) -> dict:
        """追踪所有未验证效果的诊断，返回统计"""
        now = datetime.now()
        since = now - timedelta(days=TRACK_WINDOW_DAYS)

        result = await self.db.execute(
            select(Diagnosis).where(
                Diagnosis.created_at >= since,
                Diagnosis.status.in_(TRACKED_STATUSES),
                Diagnosis.decision_id.isnot(None),
            )
        )
        diagnoses = result.scalars().all()

        stats = {"tracked": 0, "promoted": 0, "demoted": 0, "too_early": 0, "skipped": 0}
        for diag in diagnoses:
            try:
                outcome = await self._track_one(diag, now)
            except Exception as e:  # noqa: BLE001 — 单条失败不该中断整批
                logger.warning(f"[FeedbackTracker] {diag.decision_id} 追踪失败: {e}")
                stats["skipped"] += 1
                continue

            reason = outcome.get("reason")
            if reason:
                stats[reason] = stats.get(reason, 0) + 1
            if outcome.get("tracked"):
                stats["tracked"] += 1
            if outcome.get("auto_promoted"):
                stats["promoted"] += 1
            if outcome.get("auto_demoted"):
                stats["demoted"] += 1

        await self.db.flush()
        return stats

    async def _track_one(self, diag: Diagnosis, now: datetime) -> dict:
        """追踪单个诊断的整改效果"""
        if not diag.decision_id or not diag.dish_id:
            return {"tracked": False, "reason": "skipped"}

        # 已有反馈记录 → 不重复追踪
        existing = await self.db.execute(
            select(FeedbackRecord).where(FeedbackRecord.decision_id == diag.decision_id)
        )
        if existing.scalar_one_or_none():
            return {"tracked": False}

        # 观察窗起点 = 诊断生成时刻（模型里没有 dispatched_at，这是当前能取到的最接近的起点）
        executed_at = diag.created_at or now
        windows = tracking_windows(executed_at, now)
        if not windows[MIN_DAYS_FOR_VERDICT]["full"]:
            return {"tracked": False, "reason": "too_early"}

        pre_rate = await self._calc_negative_rate(
            diag.dish_id, executed_at - timedelta(days=BASELINE_DAYS), executed_at
        )
        post_rates = {
            days: await self._calc_negative_rate(diag.dish_id, w["start"], w["end"])
            for days, w in windows.items()
        }

        verdict = evaluate(pre_rate, post_rates[MIN_DAYS_FOR_VERDICT], windows)
        status = FeedbackStatus.EXECUTED
        if verdict["auto_promoted"]:
            status = FeedbackStatus.EFFECTIVE
            await self._auto_promote_to_gold(diag.decision_id)
        elif verdict["auto_demoted"]:
            status = FeedbackStatus.INEFFECTIVE

        self.db.add(FeedbackRecord(
            decision_id=diag.decision_id,
            dish_id=diag.dish_id,
            status=status,
            pre_negative_rate=round(pre_rate, 3),
            post_negative_rate_3d=round(post_rates[3], 3),
            post_negative_rate_7d=round(post_rates[7], 3),
            post_negative_rate_14d=round(post_rates[14], 3),
            improvement_pct=verdict["improvement"],
            auto_promoted=verdict["auto_promoted"],
            auto_demoted=verdict["auto_demoted"],
            executed_at=executed_at,
        ))

        return {
            "tracked": True,
            "verdict": verdict["verdict"],
            "auto_promoted": verdict["auto_promoted"],
            "auto_demoted": verdict["auto_demoted"],
        }

    async def _calc_negative_rate(self, dish_id: int, start: datetime, end: datetime) -> float:
        """指定时间段内某菜品的差评率（无样本返回 0.0）

        sentiment 由 ORM 的 SAEnum 写入，存的是枚举名（'NEGATIVE'），
        所以必须用枚举成员比较，不要写成裸字符串。
        """
        conditions = (
            Review.dish_id == dish_id,
            Review.reviewed_at >= start,
            Review.reviewed_at < end,
            Review.is_valid.is_(True),
        )
        total = (await self.db.execute(
            select(func.count(Review.id)).where(*conditions)
        )).scalar() or 0
        if total == 0:
            return 0.0

        negative = (await self.db.execute(
            select(func.count(Review.id)).where(*conditions, Review.sentiment == Sentiment.NEGATIVE)
        )).scalar() or 0
        return negative / total

    async def _auto_promote_to_gold(self, decision_id: str):
        """自动飞升金标（调 Agent 微服务的 /agent/promote）"""
        import httpx

        from app.config import settings

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{settings.AGENT_INTERNAL_URL}/agent/promote",
                    json={"decision_id": decision_id},
                )
            if resp.status_code == 200:
                logger.info(f"[FeedbackTracker] {decision_id} 自动飞升金标成功")
            else:
                logger.warning(f"[FeedbackTracker] {decision_id} 自动飞升失败: HTTP {resp.status_code}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[FeedbackTracker] {decision_id} 自动飞升异常: {e}")
