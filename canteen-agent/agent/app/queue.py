"""Redis Stream 消费侧客户端

与 backend/app/tasks/redis_queue.py（生产侧）共用同一套 Stream 契约，
两边改动必须同步：

    STREAM_KEY   agent:dish:stream
    GROUP_NAME   analysis-group
    payload      {batch_id, dish_id, dish_name, chunk_index, total_chunks,
                  reviews[{review_id, raw_text, sentiment, dimensions, severity, summary}],
                  keyword_weights}
    聚合 key      agent:dish:chunks:{batch_id}:{dish_id}
                 agent:dish:done:{batch_id}:{dish_id}
    投递计数      agent:dish:delivery:{msg_id}（超过次数上限 → 死信流 agent:dish:dead）
"""
import json
import uuid

import redis.asyncio as aioredis

from app.config import agent_settings

REDIS = agent_settings.REDIS_URL
STREAM_KEY = "agent:dish:stream"
GROUP_NAME = "analysis-group"
CHUNK_KEY = "agent:dish:chunks:{batch_id}:{dish_id}"
CHUNK_DONE_KEY = "agent:dish:done:{batch_id}:{dish_id}"
MERGE_LOCK_KEY = "agent:dish:merge:{batch_id}:{dish_id}"
MERGE_DONE_KEY = "agent:dish:merged:{batch_id}:{dish_id}"
DELIVERY_KEY = "agent:dish:delivery:{msg_id}"
DEAD_STREAM_KEY = "agent:dish:dead"
# 分片聚合 key 的兜底过期时间：正常批次合并后会被 cleanup 删掉，
# 但「凑不齐 total_chunks」的批次永远等不到那一步，没有 TTL 就会在 Redis 里堆成垃圾
CHUNK_TTL = 6 * 3600

# 只删自己的锁：值对得上才删。锁超时后被别人拿走时，这边释放不至于误删别人的锁。
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


async def get_redis():
    return aioredis.from_url(REDIS, decode_responses=True)


async def ensure_consumer_group():
    """创建消费组（幂等）"""
    r = await get_redis()
    try:
        await r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except Exception:
        pass  # 组已存在
    await r.close()


async def read_new(consumer_name: str, count: int = 1, block: int = 5000) -> list[tuple[str, dict]]:
    """消费组读新消息（block 毫秒），返回 [(msg_id, payload), ...]"""
    r = await get_redis()
    try:
        res = await r.xreadgroup(
            GROUP_NAME, consumer_name, {STREAM_KEY: ">"}, count=count, block=block
        )
    finally:
        await r.close()

    messages = []
    if res:
        for _, entries in res:
            for msg_id, fields in entries:
                messages.append((msg_id, json.loads(fields.get("data", "{}"))))
    return messages


async def ack_chunk(msg_id: str):
    """确认消息处理完成（从 PEL 移除）"""
    r = await get_redis()
    try:
        pipe = r.pipeline()
        pipe.xack(STREAM_KEY, GROUP_NAME, msg_id)
        pipe.delete(DELIVERY_KEY.format(msg_id=msg_id))
        await pipe.execute()
    finally:
        await r.close()


# ── 投递次数 / 死信队列 ────────────────────────────────────────────

async def bump_delivery(msg_id: str, ttl: int = 86400) -> int:
    """记一次投递，返回累计投递次数（用来把毒消息挡在无限重投之外）"""
    r = await get_redis()
    try:
        key = DELIVERY_KEY.format(msg_id=msg_id)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        results = await pipe.execute()
    finally:
        await r.close()
    return int(results[0])


async def move_to_dead(msg_id: str, payload: dict, reason: str):
    """投递次数耗尽 → 落死信流并 ACK，避免一条坏消息永久占着 PEL、每次重投都重跑 LLM"""
    r = await get_redis()
    try:
        pipe = r.pipeline()
        pipe.xadd(DEAD_STREAM_KEY, {
            "source_id": msg_id,
            "reason": reason,
            "data": json.dumps(payload, ensure_ascii=False),
        })
        pipe.xack(STREAM_KEY, GROUP_NAME, msg_id)
        pipe.delete(DELIVERY_KEY.format(msg_id=msg_id))
        await pipe.execute()
    finally:
        await r.close()


async def claim_pending(
    consumer_name: str, min_idle_ms: int = 30000, count: int = 5
) -> list[tuple[str, dict]]:
    """回收超时未确认的消息（失败重投），返回 [(msg_id, payload), ...]"""
    r = await get_redis()
    try:
        res = await r.xautoclaim(
            STREAM_KEY, GROUP_NAME, consumer_name,
            min_idle_time=min_idle_ms, start_id="0-0", count=count,
        )
    finally:
        await r.close()

    messages = []
    if res and len(res) >= 2:
        for msg_id, fields in res[1]:
            messages.append((msg_id, json.loads(fields.get("data", "{}"))))
    return messages


# ── 分片结果聚合 ────────────────────────────────────────────────────

async def store_chunk_result(batch_id: str, dish_id: str, chunk_index: int, result: dict) -> int:
    """存储分片分析结果，返回该菜品已完成的分片数（INCR 原子递增，多消费者安全）"""
    r = await get_redis()
    try:
        pipe = r.pipeline()
        pipe.rpush(
            CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id),
            json.dumps({"chunk_index": chunk_index, "result": result}, ensure_ascii=False),
        )
        pipe.incr(CHUNK_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id))
        pipe.expire(CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id), CHUNK_TTL)
        pipe.expire(CHUNK_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id), CHUNK_TTL)
        results = await pipe.execute()
    finally:
        await r.close()
    return results[1]


async def get_chunk_results(batch_id: str, dish_id: str) -> list[dict]:
    """按 chunk_index 顺序取回某菜品的全部分片结果"""
    r = await get_redis()
    try:
        raw = await r.lrange(CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id), 0, -1)
    finally:
        await r.close()
    items = [json.loads(x) for x in raw]
    items.sort(key=lambda x: x["chunk_index"])
    return [x["result"] for x in items]


async def acquire_merge_lock(batch_id: str, dish_id: str, ttl: int = 1800) -> str | None:
    """抢占「合并该菜品」的执行权（SETNX）

    分片被 XAUTOCLAIM 重投时 INCR 会被重复执行，没有这把锁会重复合并、重复写库。
    返回 token（抢到）或 None（没抢到）。
    TTL 取 30 分钟：一次菜品级深度加工要跑一串 LLM 调用，600s 可能中途过期被第二个消费者抢走。
    """
    r = await get_redis()
    token = uuid.uuid4().hex
    try:
        ok = await r.set(
            MERGE_LOCK_KEY.format(batch_id=batch_id, dish_id=dish_id), token, nx=True, ex=ttl
        )
        return token if ok else None
    finally:
        await r.close()


async def release_merge_lock(batch_id: str, dish_id: str, token: str | None):
    """放锁（只放自己那把）：合并失败/完成时调用，让重投后能重新尝试"""
    if not token:
        return
    r = await get_redis()
    try:
        await r.eval(
            _RELEASE_LOCK_LUA,
            1,
            MERGE_LOCK_KEY.format(batch_id=batch_id, dish_id=dish_id),
            token,
        )
    finally:
        await r.close()


async def is_dish_finalized(batch_id: str, dish_id: str) -> bool:
    """该菜品是否已合并写库（幂等标记，防止重投导致重复出诊断报告）"""
    r = await get_redis()
    try:
        return bool(await r.exists(MERGE_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id)))
    finally:
        await r.close()


async def mark_dish_finalized(batch_id: str, dish_id: str, ttl: int = 86400):
    """合并成功 → 打幂等标记（保留 24h，覆盖重投窗口）"""
    r = await get_redis()
    try:
        await r.set(
            MERGE_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id), "1", ex=ttl
        )
    finally:
        await r.close()


async def cleanup_dish_chunks(batch_id: str, dish_id: str):
    """清理分片聚合临时 key（保留幂等标记）"""
    r = await get_redis()
    try:
        pipe = r.pipeline()
        pipe.delete(CHUNK_KEY.format(batch_id=batch_id, dish_id=dish_id))
        pipe.delete(CHUNK_DONE_KEY.format(batch_id=batch_id, dish_id=dish_id))
        # 合并锁不在这里删：它有自己的 TTL，且必须由持锁人拿 token 释放
        await pipe.execute()
    finally:
        await r.close()
