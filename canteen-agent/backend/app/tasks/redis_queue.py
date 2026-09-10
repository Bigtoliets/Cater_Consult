"""Redis Stream 生产侧（backend → agent）

这里只负责「把菜品分片推进 Stream」。消费、分片聚合、ACK/重投、合并锁
全部由 agent 侧负责（agent/app/queue.py），两边共用同一套 key 契约：

    STREAM_KEY   agent:dish:stream
    payload      {batch_id, dish_id, dish_name, chunk_index, total_chunks,
                  reviews[{review_id, raw_text, sentiment, dimensions, severity, summary}],
                  keyword_weights}

消费侧 key（由 agent 维护，此处只登记契约，避免两边各写一份实现后漂移）：
    agent:dish:chunks:{batch_id}:{dish_id}   分片结果聚合
    agent:dish:done:{batch_id}:{dish_id}     分片完成计数
    agent:dish:merge:{batch_id}:{dish_id}    合并锁
    agent:dish:merged:{batch_id}:{dish_id}   幂等标记
"""
import json
import uuid

import redis.asyncio as aioredis

from app.config import settings

STREAM_KEY = "agent:dish:stream"
# 单个分片的评论条数：80 条一批，既能让 LLM NER 的上下文可控，
# 又能让多个消费者并行分片（消费者数 × 分片数决定并行度）
CHUNK_SIZE = 80


def chunk_reviews(reviews: list, chunk_size: int = CHUNK_SIZE) -> list[list]:
    """把评论列表按 chunk_size 切片"""
    return [reviews[i:i + chunk_size] for i in range(0, len(reviews), chunk_size)]


async def get_redis():
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def push_dish_chunks(
    dish_groups: list[dict], chunk_size: int = CHUNK_SIZE
) -> str:
    """把菜品分组按 chunk_size 分片后 XADD 到 Redis Stream，返回 batch_id

    - 入队顺序按菜品最高风险等级降序：食安类问题先出队、先分析（消费组内 FIFO）
    - 整批走一条事务 pipeline：避免「发了一半就抛错」，留下永远凑不齐
      total_chunks 的孤儿分片（那些分片会被消费掉，但永远不会触发菜品级合并）
    """
    batch_id = uuid.uuid4().hex[:12]
    ordered = sorted(
        dish_groups,
        key=lambda g: max(
            (rv.get("severity", 1) for rv in g.get("reviews", [])), default=1
        ),
        reverse=True,
    )

    r = await get_redis()
    try:
        pipe = r.pipeline()
        for group in ordered:
            chunks = chunk_reviews(group.get("reviews", []), chunk_size)
            total_chunks = len(chunks)
            for idx, chunk in enumerate(chunks):
                payload = {
                    "batch_id": batch_id,
                    "dish_id": group.get("dish_id", "UNKNOWN"),
                    "dish_name": group.get("dish_name", "未知菜品"),
                    "chunk_index": idx,
                    "total_chunks": total_chunks,
                    "reviews": chunk,
                    "keyword_weights": group.get("keyword_weights", {}),
                }
                pipe.xadd(STREAM_KEY, {"data": json.dumps(payload, ensure_ascii=False)})
        await pipe.execute()
    finally:
        await r.close()

    return batch_id
