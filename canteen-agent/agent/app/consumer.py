"""分析消费者 —— Redis Stream 分片消费 → 深度加工 → 回调 backend 写库

用独立进程启动，多开即多消费者并发（同一消费组，Redis 自动分发）：
    python -m app.consumer --consumer c1
    python -m app.consumer --consumer c2

可靠性设计：
- 处理失败不 ACK → 留 PEL → XAUTOCLAIM 重投；投递次数超上限 → 死信流 agent:dish:dead
  （否则一条坏消息会无限重投，每次重投都要重跑一遍 LLM）
- 合并用带 token 的 SETNX 锁 + 幂等标记：重复投递下只出一份诊断报告，且失败后仍可重试
"""
import argparse
import asyncio
import logging
import os

import httpx

from app.config import agent_settings
from app.pipeline import process_chunk, run_dish_analysis
from app import queue as q

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # 秒
# 同一条消息最多投递多少次（含重投）。超了就进死信队列，不再无限重投烧 LLM
MAX_DELIVERIES = 4


async def _with_retry(payload: dict) -> dict:
    """分片级分析带本地重试，避免瞬时 LLM/网络抖动触发整条消息重投"""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return await process_chunk(payload)
        except Exception as e:
            last_err = e
            logger.warning(f"分片分析重试 {attempt + 1}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError(f"分片分析重试耗尽: {last_err}")


async def _callback_backend(payload: dict, merged: dict):
    """把最终诊断回写 backend（写 diagnoses 表 + 回写评论精判标签 + 推告警）"""
    # 没有可交付报告时（reporter 拒发），仍然回写一条诊断：这样「分析失败」会以
    # 「需人工复核」的形式出现在看板上，而不是无声消失。摘要用固定文案占位，
    # 避免落库一条看起来像空数据的记录。
    has_report = bool(merged.get("improvement_detail"))
    summary = merged.get("improvement_summary") or ""
    if not has_report:
        summary = "AI 分析未产出可交付报告（需人工复核）"

    body = {
        "batch_id": payload.get("batch_id"),
        "dish_id": payload.get("dish_id"),
        "dish_name": payload.get("dish_name"),
        "decision_id": merged.get("decision_id"),
        "summary": summary,
        "corrective_action": merged.get("improvement_detail") or "",
        # 置信度由菜品级 prescriber 产出。分片级不评估置信度，
        # 早期这里读的是分片结果里的 confidence_score，因此恒为 0。
        "confidence": float(merged.get("confidence_score") or 0.0),
        "human_review_required": merged.get("human_review_required", False),
        "conflict_type": merged.get("conflict_type"),
        # 诊断轨迹（冲突分析 / 两段审核结论 / 调用轨迹）落库，复盘时才说得清为什么这么判
        "conflict_analysis": merged.get("diagnosis_trace") or {},
        # Agent 精判的逐条标签，backend 据此覆盖词典粗判
        "reviews": merged.get("review_labels") or [],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{agent_settings.BACKEND_INTERNAL_URL}/api/v1/internal/diagnosis",
            json=body,
        )
        resp.raise_for_status()


async def _try_finalize(payload: dict):
    """全部分片到齐 → 抢占执行权 → 深度加工 → 回调写库

    幂等 + 可重试：
    - 已完成（幂等标记）直接返回，重复投递不会再出一份报告
    - 抢不到锁说明别的消费者正在处理，跳过
    - 处理失败放锁并抛出，等消息重投后重试
    """
    batch_id = payload.get("batch_id", "")
    dish_id = payload.get("dish_id", "UNKNOWN")
    dish_name = payload.get("dish_name", "未知菜品")

    if await q.is_dish_finalized(batch_id, dish_id):
        return
    lock_token = await q.acquire_merge_lock(batch_id, dish_id)
    if not lock_token:
        return

    try:
        chunk_results = await q.get_chunk_results(batch_id, dish_id)
        merged = await run_dish_analysis(dish_name, dish_id, chunk_results)
        await _callback_backend(payload, merged)
        await q.mark_dish_finalized(batch_id, dish_id)
        logger.info(f"{dish_name} 深度加工完成 decision_id={merged.get('decision_id')}")
    except Exception:
        await q.release_merge_lock(batch_id, dish_id, lock_token)
        raise
    else:
        await q.cleanup_dish_chunks(batch_id, dish_id)
        await q.release_merge_lock(batch_id, dish_id, lock_token)


async def process_one(payload: dict):
    """处理单个分片：分析（带重试）→ 聚合 → 最后一片触发菜品级深度加工"""
    batch_id = payload.get("batch_id", "")
    dish_id = payload.get("dish_id", "UNKNOWN")
    dish_name = payload.get("dish_name", "未知菜品")
    chunk_index = payload.get("chunk_index", 0)
    total_chunks = payload.get("total_chunks", 1)

    result = await _with_retry(payload)

    # 聚合分片结果（INCR 原子，多消费者安全）
    done = await q.store_chunk_result(batch_id, dish_id, chunk_index, result)
    logger.info(f"{dish_name} 分片 {chunk_index + 1}/{total_chunks} 完成 {done}/{total_chunks}")

    if done >= total_chunks:
        await _try_finalize(payload)


async def handle_message(msg_id: str, payload: dict, sem: asyncio.Semaphore):
    """处理一条消息：成功才 ACK，失败留 PEL 等待重投"""
    async with sem:
        deliveries = await q.bump_delivery(msg_id)
        if deliveries > MAX_DELIVERIES:
            # 毒消息/持续故障：无限重投只会每次重跑一遍 LLM，得不偿失
            await q.move_to_dead(msg_id, payload, f"投递 {deliveries} 次仍未成功")
            logger.error(
                f"消息 {msg_id} 投递 {deliveries} 次仍失败，已进死信队列 "
                f"（菜品 {payload.get('dish_name')}）"
            )
            return
        try:
            await process_one(payload)
        except Exception as e:
            logger.error(
                f"处理分片失败（不 ACK，等待重投 {deliveries}/{MAX_DELIVERIES}）: {e}",
                exc_info=True,
            )
            return
    await q.ack_chunk(msg_id)


async def run_consumer(consumer_name: str):
    """消费者主循环：消费新消息 + 回收超时 pending"""
    await q.ensure_consumer_group()
    concurrency = agent_settings.CONSUMER_CONCURRENCY
    logger.info(f"[Consumer] {consumer_name} 启动，并发 {concurrency}，Redis: {agent_settings.REDIS_HOST}")

    sem = asyncio.Semaphore(concurrency)
    while True:
        try:
            # 1. 消费新消息（阻塞 5s）
            messages = await q.read_new(consumer_name, count=concurrency, block=5000)
            # 2. 无新消息时回收超时未确认的（失败重投）
            if not messages:
                messages = await q.claim_pending(
                    consumer_name, min_idle_ms=30000, count=concurrency
                )
            if messages:
                await asyncio.gather(
                    *(handle_message(mid, payload, sem) for mid, payload in messages)
                )
        except Exception as e:
            logger.error(f"[Consumer] 循环异常: {e}", exc_info=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canteen Agent 分析消费者")
    parser.add_argument(
        "--consumer", default=f"consumer-{os.getpid()}",
        help="消费者名（同一消费组内需唯一）",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_consumer(args.consumer))
