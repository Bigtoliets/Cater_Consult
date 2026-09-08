"""Celery 消费者 —— 从 Redis 队列逐个消费分片 → 调 Agent → 聚合 → 最后一片合并写库"""
import asyncio
import time
import httpx
from celery.utils.log import get_task_logger

from app.tasks.celery_app import celery_app
from app.tasks.redis_queue import (
    pop_dish,
    delete_queue,
    store_chunk_result,
    get_chunk_results,
    cleanup_dish_chunks,
)
from app.config import settings

logger = get_task_logger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # 秒


async def _analyze_one(chunk: dict) -> dict:
    """分析单个分片（persist=False，分片结果不单独沉淀，等合并后再写）"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{settings.AGENT_INTERNAL_URL}/agent/analyze_dish",
            json={
                "dish_name": chunk["dish_name"],
                "dish_id": chunk["dish_id"],
                "reviews": chunk["reviews"],
                "keyword_weights": chunk.get("keyword_weights", {}),
                "persist": False,
            },
        )
        if resp.status_code != 200:
            raise Exception(f"Agent 返回 {resp.status_code}: {resp.text[:200]}")
        return resp.json()


async def _merge_one(dish_name: str, dish_id: str, chunk_results: list[dict]) -> dict:
    """调用 Agent 把该菜品的全部分片结果合并成一份最终诊断"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{settings.AGENT_INTERNAL_URL}/agent/merge_dish",
            json={
                "dish_name": dish_name,
                "dish_id": dish_id,
                "chunks": [
                    {
                        "improvement_summary": r.get("improvement_summary", ""),
                        "improvement_detail": r.get("improvement_detail", ""),
                        "human_review_required": r.get("human_review_required", False),
                    }
                    for r in chunk_results
                ],
            },
        )
        if resp.status_code != 200:
            raise Exception(f"Agent merge 返回 {resp.status_code}: {resp.text[:200]}")
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
    """消费分片 → 调 Agent 分析 → Redis 聚合 → 最后一片合并 → 回写 Diagnosis"""
    logger.info(f"[批次 {batch_id}] 开始消费")

    total = 0
    success = 0
    failed = 0

    while True:
        chunk = asyncio.run(pop_dish(batch_id))
        if chunk is None:
            break

        total += 1
        dish_id = chunk.get("dish_id", "UNKNOWN")
        dish_name = chunk.get("dish_name", "未知")
        chunk_index = chunk.get("chunk_index", 0)
        total_chunks = chunk.get("total_chunks", 1)
        logger.info(f"[批次 {batch_id}] #{total} 处理: {dish_name} 分片 {chunk_index + 1}/{total_chunks}")

        result = None
        retries = 0
        last_error = None
        while retries < MAX_RETRIES:
            try:
                result = asyncio.run(_analyze_one(chunk))
                success += 1
                break
            except Exception as e:
                retries += 1
                last_error = str(e)
                logger.warning(f"[批次 {batch_id}] {dish_name} 分片 {chunk_index + 1} 重试 {retries}/{MAX_RETRIES}: {last_error}")
                if retries < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        if result is None:
            failed += 1
            logger.error(
                f"[批次 {batch_id}] {dish_name} 分片 {chunk_index + 1} 已重试 {MAX_RETRIES} 次，降级跳过。"
                f"最后错误: {last_error}"
            )
            # 有分片失败 → 该菜品凑不齐 total_chunks，清理残留 key，避免泄漏
            asyncio.run(cleanup_dish_chunks(batch_id, dish_id))
            continue

        # 聚合分片结果，返回已完成分片数
        done_count = asyncio.run(store_chunk_result(batch_id, dish_id, chunk_index, result))
        logger.info(f"[批次 {batch_id}] {dish_name} 分片完成 {done_count}/{total_chunks}")

        # 最后一片 → 合并写库
        if done_count >= total_chunks:
            try:
                chunk_results = asyncio.run(get_chunk_results(batch_id, dish_id))
                merged = asyncio.run(_merge_one(dish_name, dish_id, chunk_results))
                _write_diagnosis_sync(chunk, merged)
                logger.info(f"[批次 {batch_id}] {dish_name} 合并完成, decision_id={merged.get('decision_id')}")
            except Exception as e:
                failed += 1
                logger.error(f"[批次 {batch_id}] {dish_name} 合并失败: {e}")
            finally:
                asyncio.run(cleanup_dish_chunks(batch_id, dish_id))

    asyncio.run(delete_queue(batch_id))
    stats = {"total": total, "success": success, "failed": failed}
    logger.info(f"[批次 {batch_id}] 完成: {stats}")
    return stats
