"""问答 turn 追踪与恢复（存储层）离线自测

    python tests/test_resume_store.py

不需要 Redis / Milvus / LLM：用一个内存假 Redis 顶替 redis.asyncio。
盯的是「写错就没法恢复」的那几条契约：

- turn_id / session_id 要进 Redis key，必须挡住非法格式与改 key 语义的输入
- checkpoint 必须原样往返（messages 里的 tool_calls / tool_call_id 是恢复的命根子）
- 脏 checkpoint 不能把接口打 500，只能当「没有这个 turn」
- 状态机：running → completed / failed / abandoned；resume 超限自动 abandoned
- 锁只删自己的、只续自己的；抢不到返回 None（上层回 409）
- 终态写记忆靠 memo 标记幂等（重复 resume 不再往 Milvus 存一遍）
- 追踪日志：单行 JSON、可解析、带 latency_ms，异常也记一笔再抛
"""
import asyncio
import json
import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.chat import turn_store as TS
from app.chat.trace import TRACE_LOGGER_NAME, trace, trace_span

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


class FakeRedis:
    """只实现 turn_store 用到的那几个命令（含两段 Lua 的等价语义）"""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        self.ttls[key] = ex
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                self.ttls.pop(key, None)
                removed += 1
        return removed

    async def exists(self, key):
        return 1 if key in self.data else 0

    async def ping(self):
        return True

    async def eval(self, script, numkeys, *args):
        key, token = args[0], args[1]
        if self.data.get(key) != token:
            return 0
        if "expire" in script:          # _RENEW_LOCK_LUA：只续自己的
            self.ttls[key] = int(args[2])
            return 1
        del self.data[key]              # _RELEASE_LOCK_LUA：只删自己的
        self.ttls.pop(key, None)
        return 1

    async def aclose(self):
        pass


def new_store():
    redis = FakeRedis()
    return TS.TurnStore(client=redis), redis


# ── [1] 输入校验 ────────────────────────────────────────────


async def test_validate():
    print("\n[1] turn_id / session_id 校验：挡住改 key 语义的输入")
    uid = uuid.uuid4()
    check("32 位 hex 被接受", TS.normalize_turn_id(uid.hex) == uid.hex)
    check("带连字符的 uuid 归一到同一个 key", TS.normalize_turn_id(str(uid)) == uid.hex)
    check("大写 uuid 也归一", TS.normalize_turn_id(str(uid).upper()) == uid.hex)
    for bad in ("default", "chat:turn:1", "../../etc/passwd", uid.hex + "z", "g" * 32, "", None):
        check(f"非法 turn_id 被拒: {bad!r}", TS.normalize_turn_id(bad) is None)

    check("正常会话 id 通过", TS.validate_session_id("user_1-ab") == "user_1-ab")
    for bad in ("a:b", "会话", "x" * 65, "", None):
        check(f"非法 session_id 被拒: {bad!r}", TS.validate_session_id(bad) is None)
    check("兜底 turn_id 是合法的 32 位 hex", TS.normalize_turn_id(TS.new_turn_id()) is not None)
    check("兜底 session_id 符合白名单", TS.validate_session_id(TS.fallback_session_id()) is not None)


# ── [2] checkpoint 往返 ─────────────────────────────────────


async def test_checkpoint_roundtrip():
    print("\n[2] checkpoint 往返：消息链与推理现场一个都不能丢")
    store, redis = new_store()
    turn_id = uuid.uuid4().hex
    state = TS.TurnState(turn_id=turn_id, session_id="s1", question="红烧肉为什么咸", max_iterations=5)
    state.messages = [
        {"type": "system", "content": "你是品控助手"},
        {
            "type": "ai",
            "content": "",
            "tool_calls": [{"name": "search_knowledge_base", "args": {"query": "红烧肉"}, "id": "call_1"}],
        },
    ]
    state.pending = ["call_1"]
    state.call_history = ["search_knowledge_base_9f3a"]
    state.steps = [{"action": "search_knowledge_base", "observation": "x" * 500, "timestamp": "t"}]
    await store.save(state)

    raw = raw_value = redis.data[TS.turn_key(turn_id)]
    payload = json.loads(raw)
    check("落盘是 JSON 且带问题原文", payload["question"] == "红烧肉为什么咸")
    check("checkpoint TTL = 24h", redis.ttls[TS.turn_key(turn_id)] == TS.TURN_TTL)

    loaded = await store.load(turn_id)
    check("load 用 32 位规范 id", loaded.turn_id == turn_id)
    check("messages 里的 tool_calls / id 完整",
          loaded.messages[1]["tool_calls"][0]["id"] == "call_1", f"实际: {loaded.messages[1]}")
    check("pending 原样带回（resume 靠它补齐）", loaded.pending == ["call_1"])
    check("call_history 原样带回（死循环检测靠它）", loaded.call_history == ["search_knowledge_base_9f3a"])
    check("steps 原样带回", loaded.steps[0]["action"] == "search_knowledge_base")

    check("load 不存在的 turn → None", await store.load(uuid.uuid4().hex) is None)
    check("load 非法 turn_id → None，不抛", await store.load("default") is None)


# ── [3] 脏数据 / 版本兼容 ───────────────────────────────────


async def test_dirty_checkpoint():
    print("\n[3] 脏 checkpoint 不能把接口打 500")
    store, redis = new_store()
    turn_id = uuid.uuid4().hex
    key = TS.turn_key(turn_id)

    redis.data[key] = "{not json"
    check("非 JSON → None", await store.load(turn_id) is None)
    redis.data[key] = json.dumps({"turn_id": turn_id, "session_id": "s", "status": "weird"})
    check("未知状态 → None", await store.load(turn_id) is None)
    redis.data[key] = json.dumps({"session_id": "s"})
    check("缺 turn_id → None", await store.load(turn_id) is None)

    redis.data[key] = json.dumps({
        "turn_id": turn_id, "session_id": "s", "question": "q", "future_field": {"v": 2},
    })
    loaded = await store.load(turn_id)
    check("未知字段忽略、缺字段取默认值",
          loaded.status == TS.STATUS_RUNNING and loaded.iteration == 0
          and loaded.max_iterations == 5 and loaded.pending == [],
          f"实际: {loaded}")


# ── [4] 状态机 ──────────────────────────────────────────────


async def test_state_machine():
    print("\n[4] 状态机：额度、终态、待补清单")
    state = TS.TurnState(turn_id=uuid.uuid4().hex, session_id="s", question="q")
    check("新建 = running 且可恢复", state.status == TS.STATUS_RUNNING and state.resumable)
    check("初始剩余额度 = max_iterations", state.remaining_iterations == 5)
    state.iteration = 2
    check("跑了两轮 → 剩 3 轮（resume 用剩余额度，不重头跑）", state.remaining_iterations == 3)

    check("resume 第 1 次放行", state.begin_resume() is True)
    state.begin_resume()
    state.begin_resume()
    check("resume 第 4 次被拒", state.begin_resume() is False)
    check("超限自动落 abandoned", state.status == TS.STATUS_ABANDONED)
    check("abandoned 不再可恢复", not state.resumable)

    done = TS.TurnState(turn_id=uuid.uuid4().hex, session_id="s", question="q", iteration=3)
    done.pending = ["call_9"]
    done.complete("  最终答案  ")
    check("完成：状态终态 + 答案去空白",
          done.status == TS.STATUS_COMPLETED and done.final_answer == "最终答案")
    check("完成时清空 pending", done.pending == [])

    bad = TS.TurnState(turn_id=uuid.uuid4().hex, session_id="s", question="q")
    bad.fail(RuntimeError("炸了" * 400))
    check("失败：状态 + 错误截断到 500 字",
          bad.status == TS.STATUS_FAILED and len(bad.error) == 500)
    check("失败后不可恢复", not bad.resumable)

    pend = TS.TurnState(turn_id=uuid.uuid4().hex, session_id="s", question="q", pending=["a", "b"])
    check("摘 pending 命中才返回 True", pend.resolve_pending("a") is True and pend.pending == ["b"])
    check("摘不存在的 call_id 返回 False", pend.resolve_pending("zzz") is False)


# ── [5] 只读视图 ────────────────────────────────────────────


async def test_summary():
    print("\n[5] 轨迹摘要：给前端/排障看，不泄露整条消息链")
    state = TS.TurnState(turn_id=uuid.uuid4().hex, session_id="s", question="q", iteration=1)
    state.messages = [{"type": "system", "content": "x" * 5000}]
    state.call_history = ["sig"]
    state.steps = [{"action": "lookup_sop", "observation": "y" * 400, "timestamp": "t"}]
    summary = state.summary()
    check("不带消息链原文", "messages" not in summary and "call_history" not in summary)
    check("观察文本被截断", len(summary["steps"][0]["observation"]) <= 241,
          f"实际长度: {len(summary['steps'][0]['observation'])}")
    check("带剩余额度（前端提示还能不能接着跑）", summary["remaining_iterations"] == 4)
    check("未完成时最终答案不下发（防半截答案被当成品）", summary["final_answer"] is None)
    state.complete("正式答案")
    check("完成后摘要里能看到最终答案", state.summary()["final_answer"] == "正式答案")


# ── [6] 执行权锁 ────────────────────────────────────────────


async def test_lock():
    print("\n[6] 执行权锁：抢不到就是 409，不能双跑")
    store, _ = new_store()
    turn_id = uuid.uuid4().hex
    token = await store.acquire_lock(turn_id)
    check("抢到锁返回 token", bool(token))
    check("第二个请求抢不到（上层回 409）", await store.acquire_lock(turn_id) is None)
    check("别人续租失败", await store.renew_lock(turn_id, "not-my-token") is False)
    check("自己续租成功", await store.renew_lock(turn_id, token) is True)

    await store.release_lock(turn_id, "not-my-token")
    check("别人释放不掉我的锁", await store.acquire_lock(turn_id) is None)
    await store.release_lock(turn_id, token)
    check("自己释放后可以重新抢", bool(await store.acquire_lock(turn_id)))
    check("非法 turn_id 抢锁直接失败（不落脏 key）", await store.acquire_lock("default") is None)

    check("探活可用（/agent/health 用）", await store.ping() is True)

    class _DeadRedis(FakeRedis):
        async def ping(self):
            raise RuntimeError("redis down")

    check("Redis 挂了探活返回 False，不抛", await TS.TurnStore(client=_DeadRedis()).ping() is False)


# ── [7] 终态幂等 ────────────────────────────────────────────


async def test_memo():
    print("\n[7] 终态写记忆的幂等标记")
    store, _ = new_store()
    turn_id = uuid.uuid4().hex
    check("首次 → True（该写）", await store.mark_memoized(turn_id) is True)
    check("重复 → False（跳过，不再存一遍 Milvus）", await store.mark_memoized(turn_id) is False)
    check("非法 id 不写标记", await store.mark_memoized("default") is False)


# ── [8] 追踪日志 ────────────────────────────────────────────


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def test_trace_log():
    print("\n[8] 追踪日志：单行 JSON，时间线靠 turn_id 串")
    logger = logging.getLogger(TRACE_LOGGER_NAME)
    cap = _Capture()
    logger.addHandler(cap)
    logger.setLevel(logging.INFO)
    try:
        trace("turn_created", turn_id="a" * 32, session_id="s1", question="红烧肉", error=None)
        payload = json.loads(cap.lines[-1])
        check("事件一行 JSON 可解析", payload["event"] == "turn_created" and payload["session_id"] == "s1")
        check("中文不转义（日志可直接读）", "红烧肉" in cap.lines[-1])
        check("带毫秒时间戳", "T" in payload["ts"] and "." in payload["ts"])
        check("None 字段不落盘", "error" not in payload)

        async with trace_span("tool_end", turn_id="a" * 32, action="lookup_sop"):
            await asyncio.sleep(0)
        payload = json.loads(cap.lines[-1])
        check("span 记成功 + 耗时", payload["ok"] is True and payload["latency_ms"] >= 0)

        try:
            async with trace_span("tool_end", action="boom"):
                raise RuntimeError("炸了")
        except RuntimeError:
            pass
        payload = json.loads(cap.lines[-1])
        check("span 记失败但不吞异常",
              payload["ok"] is False and "RuntimeError" in payload["error"])
    finally:
        logger.removeHandler(cap)


async def main():
    await test_validate()
    await test_checkpoint_roundtrip()
    await test_dirty_checkpoint()
    await test_state_machine()
    await test_summary()
    await test_lock()
    await test_memo()
    await test_trace_log()
    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
