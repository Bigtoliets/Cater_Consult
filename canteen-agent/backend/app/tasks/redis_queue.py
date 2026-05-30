"""Redis 消息队列工具 —— 菜品分析任务的推送 / 消费"""
import json
import uuid
import redis.asyncio as aioredis
from app.config import settings

REDIS = settings.REDIS_URL
QUEUE_PREFIX = "agent:dish:queue"


async def get_redis():
    return aioredis.from_url(REDIS, decode_responses=True)


async def push_dish_batch(dish_groups: list[dict]) -> str:
    """将菜品分组批量推入 Redis 队列，返回 batch_id"""
    batch_id = uuid.uuid4().hex[:12]
    r = await get_redis()
    pipe = r.pipeline()
    for group in dish_groups:
        payload = json.dumps(group, ensure_ascii=False)
        pipe.rpush(f"{QUEUE_PREFIX}:{batch_id}", payload)
    await pipe.execute()
    await r.close()
    return batch_id


async def pop_dish(batch_id: str) -> dict | None:
    """从队列头部弹出一个菜品"""
    r = await get_redis()
    raw = await r.lpop(f"{QUEUE_PREFIX}:{batch_id}")
    await r.close()
    if raw:
        return json.loads(raw)
    return None


async def push_retry(batch_id: str, group: dict):
    """失败重试：推回队列头部"""
    r = await get_redis()
    payload = json.dumps(group, ensure_ascii=False)
    await r.lpush(f"{QUEUE_PREFIX}:{batch_id}", payload)
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
