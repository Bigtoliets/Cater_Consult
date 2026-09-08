"""Redis 消息队列工具 —— 菜品分析任务的分片推送 / 消费 / 结果聚合"""
import json
import uuid

import redis.asyncio as aioredis

from app.config import settings
from app.services.review_processor import chunk_reviews

REDIS = settings.REDIS_URL
QUEUE_PREFIX = "agent:dish:queue"
CHUNK_KEY = "agent:dish:chunks:{batch_id}:{dish_id}"
CHUNK_DONE_KEY = "agent:dish:done:{batch_id}:{dish_id}"


async def get_redis():
    return aioredis.from_url(REDIS, decode_responses=True)


async def push_dish_batch(dish_groups: list[dict], chunk_size: int = 80) -> str:
    """将菜品分组按 chunk_size 分片后推入 Redis 队列，返回 batch_id"""
    batch_id = uuid.uuid4().hex[:12]
    r = await get_redis()
    pipe = r.pipeline()
    for group in dish_groups:
        reviews = group.get("reviews", [])
        chunks = chunk_reviews(reviews, chunk_size)
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
            pipe.rpush(f"{QUEUE_PREFIX}:{batch_id}", json.dumps(payload, ensure_ascii=False))
    await pipe.execute()
    await r.close()
    return batch_id


async def pop_dish(batch_id: str) -> dict | None:
    """从队列头部弹出一个分片"""
    r = await get_redis()
    raw = await r.lpop(f"{QUEUE_PREFIX}:{batch_id}")
    await r.close()
    if raw:
        return json.loads(raw)
    return None


async def store_chunk_result(batch_id: str, dish_id: str, chunk_index: int, result: dict) -> int:
    """存储一个分片结果，返回该菜品已完成的分片数（Redis INCR 原子递增）"""
    r = await get_redis()
    pipe = r.pipeline()
    pipe.rpush(
        CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id),
        json.dumps({"chunk_index": chunk_index, "result": result}, ensure_ascii=False),
    )
    pipe.incr(CHUNK_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id))
    results = await pipe.execute()
    await r.close()
    return results[1]


async def get_chunk_results(batch_id: str, dish_id: str) -> list[dict]:
    """按 chunk_index 顺序取回某菜品的全部分片结果"""
    r = await get_redis()
    raw = await r.lrange(CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id), 0, -1)
    await r.close()
    items = [json.loads(x) for x in raw]
    items.sort(key=lambda x: x["chunk_index"])
    return [x["result"] for x in items]


async def cleanup_dish_chunks(batch_id: str, dish_id: str):
    """清理某菜品的分片聚合临时 key"""
    r = await get_redis()
    pipe = r.pipeline()
    pipe.delete(CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id))
    pipe.delete(CHUNK_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id))
    await pipe.execute()
    await r.close()


async def queue_length(batch_id: str) -> int:
    r = await get_redis()
    length = await r.llen(f"{QUEUE_PREFIX}:{batch_id}")
    await r.close()
    return length


async def delete_queue(batch_id: str):
    r = await get_redis()
    await r.delete(f"{QUEUE_PREFIX}:{batch_id}")
    await r.close()
