"""Celery 消费者 —— 从 Redis 队列逐个消费菜品分析任务（重试 + 降级）"""
import asyncio
import time
import httpx
from celery.utils.log import get_task_logger

from app.tasks.celery_app import celery_app
from app.tasks.redis_queue import pop_dish, delete_queue
from app.config import settings

logger = get_task_logger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # 秒


async def _analyze_one(group: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{settings.AGENT_INTERNAL_URL}/agent/analyze_dish",
            json={
                "dish_name": group["dish_name"],
                "dish_id": group["dish_id"],
                "reviews": group["reviews"],
                "keyword_weights": group.get("keyword_weights", {}),
            },
        )
        if resp.status_code != 200:
            raise Exception(f"Agent 返回 {resp.status_code}: {resp.text[:200]}")
        return resp.json()


def _write_diagnosis_sync(group: dict, agent_result: dict):
    from app.models.base import SyncSessionLocal
    from app.models.models import Diagnosis, DiagnosisStatus

    with SyncSessionLocal() as session:
        dish_id = int(group["dish_id"]) if group["dish_id"].isdigit() else None
        diag = Diagnosis(
            dish_id=dish_id,
            dish_name=group.get("dish_name", "") or "",
            status=DiagnosisStatus.COMPLETED,
            decision_id=agent_result.get("decision_id"),
            summary=agent_result.get("improvement_summary", "") or "",
            corrective_action=agent_result.get("improvement_detail", "") or "",
            human_review_required=agent_result.get("human_review_required", False),
            confidence=agent_result.get("confidence_score", 0.8),
        )
        session.add(diag)
        session.commit()

        # v3.0: 需人工复核时推送告警
        if diag.human_review_required:
            _push_review_alert(
                group.get("dish_name", ""),
                dish_id,
                diag.decision_id,
                diag.summary,
                diag.confidence,
            )


def _push_review_alert(
    dish_name: str,
    dish_id: int | None,
    decision_id: str | None,
    summary: str,
    confidence: float,
):
    """v3.0: 需要人工复核的诊断结果推送告警"""
    try:
        from app.push.dispatcher import get_dispatcher
        from app.push.base import Alert, AlertLevel

        confidence_pct = f"{confidence:.0%}" if confidence else "N/A"
        dispatcher = get_dispatcher()
        import asyncio
        asyncio.run(dispatcher.dispatch(Alert(
            level=AlertLevel.WARNING,
            title=f"需人工复核：{dish_name}",
            content=f"**决策ID**：{decision_id or 'N/A'}\n"
                    f"**置信度**：{confidence_pct}\n"
                    f"**摘要**：{summary or '无'}\n\n"
                    f"请在 Dashboard 中查看详情并复核。",
            dish_name=dish_name,
            dish_id=dish_id,
            decision_id=decision_id,
        )))
    except Exception as e:
        print(f"[Alert] 复核告警推送失败: {e}")


@celery_app.task(
    name="app.tasks.consumer.process_dish_batch",
    bind=True,
    max_retries=0,
)
def process_dish_batch(self, batch_id: str):
    """从 Redis 队列逐个消费 → 调 Agent → 重试 → 降级 → 回写 Diagnosis"""
    logger.info(f"[批次 {batch_id}] 开始消费")

    total = 0
    success = 0
    failed = 0

    while True:
        group = asyncio.run(pop_dish(batch_id))
        if group is None:
            break

        total += 1
        dish_name = group.get("dish_name", "未知")
        logger.info(f"[批次 {batch_id}] #{total} 处理: {dish_name}")

        result = None
        retries = 0
        last_error = None

        while retries < MAX_RETRIES:
            try:
                result = asyncio.run(_analyze_one(group))
                success += 1
                logger.info(f"[批次 {batch_id}] {dish_name} 成功, decision_id={result.get('decision_id')}")
                _write_diagnosis_sync(group, result)
                break
            except Exception as e:
                retries += 1
                last_error = str(e)
                logger.warning(f"[批次 {batch_id}] {dish_name} 重试 {retries}/{MAX_RETRIES}: {last_error}")
                if retries < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        if result is None:
            failed += 1
            logger.error(
                f"[批次 {batch_id}] {dish_name} 已重试 {MAX_RETRIES} 次，降级跳过。"
                f"最后错误: {last_error}"
            )

    asyncio.run(delete_queue(batch_id))
    stats = {"total": total, "success": success, "failed": failed}
    logger.info(f"[批次 {batch_id}] 完成: {stats}")
    return stats
