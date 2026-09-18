"""问答 turn 的 checkpoint / resume 离线自测（不需要 Redis / LLM / Milvus）

    python tests/test_resume_engine.py

用假 LLM + 假工具注册表 + 内存 Redis 真跑 ReActEngine.run_turn，盯的是：

- WAL 三个写入点：turn 创建 / AI 声明工具 / 每个工具执行完，各写一次
- 批量工具是「跑完一个写一个」，崩了能看到「跑到一半」的中间态
- 崩在工具执行中（KeyboardInterrupt 模拟进程被杀）→ 恢复先补 pending，
  消息链满足「ai 声明的每个 tool_call 都有对应 tool 消息」才继续
- 恢复用剩余额度，不重头跑
- call_history 跟着 checkpoint 走：跨恢复的死循环拦截依然生效
- pending 找不到声明 → TurnProtocolError，宁可失败也不发非法消息链给 LLM
- 追踪日志按 turn_id 打全：turn_created → llm_tool_calls → tool_end → turn_completed
- 终态写记忆有幂等标记，重复收尾不会往 Milvus 存第二遍
"""
import asyncio
import json
import logging
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import (  # noqa: E402
    AIMessage,
    HumanMessage,
    SystemMessage,
    messages_to_dict,
)


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


# 引擎会调用 app.utils.llm.get_llm()，这里换成脚本化假 LLM；
# 工具包的真实 __init__ 会去连 Milvus，所以连 app.tools / app.tools.base 一起桩掉
_LLM = {"instance": None}
_stub("app.utils.llm", get_llm=lambda *a, **k: _LLM["instance"], get_embeddings=lambda *a, **k: None)
_stub("app.tools", get_tool_registry=lambda: None, register_all_tools=lambda: None)
_stub("app.tools.base", ToolRegistry=object, get_tool_registry=lambda: None)

from app.chat.trace import TRACE_LOGGER_NAME  # noqa: E402
from app.chat.turn_store import TurnState, TurnStore  # noqa: E402
from app.react.engine import ReActEngine, TurnProtocolError  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


# ── 假件 ────────────────────────────────────────────────────


class _FakeRedis:
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
        for key in keys:
            self.data.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.data else 0

    async def ping(self):
        return True

    async def eval(self, script, numkeys, *args):
        key, token = args[0], args[1]
        if self.data.get(key) != token:
            return 0
        if "expire" in script:
            self.ttls[key] = int(args[2])
            return 1
        del self.data[key]
        return 1

    async def aclose(self):
        pass


class _Store(TurnStore):
    """带快照记录的 TurnStore：每次 save 都把当时的 checkpoint 抄一份，方便断言中间态"""

    def __init__(self):
        self.redis = _FakeRedis()
        super().__init__(client=self.redis)
        self.snapshots: list[dict] = []

    async def save(self, state):
        result = await super().save(state)
        self.snapshots.append(json.loads(state.to_json()))
        return result


class _Tool:
    def __init__(self, name):
        self.name = name
        self.description = "测试工具"
        self.parameters = {"type": "object", "properties": {}}


class _ToolResult:
    def __init__(self, text, source="test_kb"):
        self.text, self.source = text, source

    def format_for_llm(self):
        return self.text


class _Registry:
    def __init__(self, names=("kb_search",), handler=None):
        self._tools = [_Tool(n) for n in names]
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    def get_all(self):
        return self._tools

    async def execute_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.handler is not None:
            return await self.handler(name, kwargs)
        return _ToolResult(f"{name} 的观察结果")


class _ScriptedLLM:
    """脚本化 LLM：每次 ainvoke 弹一条响应；脚本项可以是异常（模拟 LLM 调用失败）"""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def bind_tools(self, schema):
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages_to_dict(messages))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class _Memory:
    def __init__(self):
        self.episodes: list[dict] = []
        self.history: list[dict] = []      # 短期记忆（main 会往里 add_message）
        self.memory_context = ""           # 长期记忆（Milvus 摘要）

    async def retrieve_relevant(self, query, session_id, k=2):
        return self.memory_context

    async def store_episode(self, **kwargs):
        self.episodes.append(kwargs)

    def add_message(self, role, content, metadata=None):
        self.history.append({"role": role, "content": content})

    def build_context(self, system_prompt, current_question=None):
        messages = [{"role": "system", "content": system_prompt}, *self.history]
        if current_question:
            messages.append({"role": "user", "content": current_question})
        return messages


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def tool_call_response(*calls, thought=""):
    """calls: (call_id, tool_name, args)"""
    return AIMessage(content=thought, tool_calls=[
        {"name": name, "args": args, "id": call_id, "type": "tool_call"}
        for call_id, name, args in calls
    ])


def make_engine(registry, llm, memory=None, max_iterations=5):
    _LLM["instance"] = llm
    return ReActEngine(
        tool_registry=registry, memory=memory, max_iterations=max_iterations, min_confidence=0.5
    )


def _tool_count(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("type") == "tool")


def _last_tool_text(messages: list[dict]) -> str:
    tool_msgs = [m for m in messages if m.get("type") == "tool"]
    return str(tool_msgs[-1]["data"].get("content") or "") if tool_msgs else ""


def _chain_valid(messages: list[dict]) -> bool:
    """ai 消息声明了几个 tool_call，就得有对应数量的 tool 消息把 id 对上"""
    pending: list[str] = []
    for message in messages:
        if message.get("type") == "ai":
            pending = [tc.get("id", "") for tc in message["data"].get("tool_calls") or []]
        elif message.get("type") == "tool":
            call_id = message["data"].get("tool_call_id")
            if call_id in pending:
                pending.remove(call_id)
    return not pending


# ── [1] 正常链路 ────────────────────────────────────────────


async def test_happy_path():
    print("\n[1] WAL 三个写入点：创建 / 声明工具 / 工具完成 / 终态")
    store = _Store()
    registry = _Registry(("kb_search",))
    llm = _ScriptedLLM([
        tool_call_response(("call_1", "kb_search", {"q": "红烧肉"})),
        AIMessage(content="最终答案"),
    ])
    engine = make_engine(registry, llm)

    result, state = await engine.run_turn("红烧肉为什么咸", "s1", turn_id="a" * 32, store=store)

    check("答案回传", result.answer == "最终答案", f"实际: {result.answer}")
    check("工具调用被记录", result.tools_called == ["kb_search"])
    check("写入点齐全 = 创建 + 声明 + 工具 + 完成 共 4 次",
          len(store.snapshots) == 4, f"实际: {len(store.snapshots)}")
    check("checkpoint 终态 completed", store.snapshots[-1]["status"] == "completed")
    check("final_answer 落在 checkpoint（刷新页面能直接补全）",
          store.snapshots[-1]["final_answer"] == "最终答案")
    check("pending 清空", store.snapshots[-1]["pending"] == [])
    check("消息链合法：声明的 tool_call 都有 tool 消息",
          _chain_valid(store.snapshots[-1]["messages"]))
    check("checkpoint TTL = 24h", store.redis.ttls[f"chat:turn:{'a' * 32}"] == 24 * 3600)
    check("iteration 记的是 LLM 轮数", state.iteration == 2, f"实际: {state.iteration}")


# ── [2] 崩在工具执行中 → 恢复 ───────────────────────────────


async def test_crash_mid_tool_then_resume():
    print("\n[2] 崩在工具执行中：恢复先补 pending，消息链依旧合法")
    store = _Store()
    crash = {"armed": True}

    async def handler(name, kwargs):
        if crash["armed"]:
            crash["armed"] = False
            raise KeyboardInterrupt("模拟进程被杀")  # BaseException：模拟真崩，不是业务异常
        return _ToolResult("红烧肉 SOP：盐 5g")

    registry = _Registry(("kb_search",), handler=handler)
    llm = _ScriptedLLM([
        tool_call_response(("call_1", "kb_search", {"q": "红烧肉"})),
        AIMessage(content="不会跑到这里"),
    ])
    engine = make_engine(registry, llm)

    crashed = False
    try:
        await engine.run_turn("红烧肉为什么咸", "s1", turn_id="b" * 32, store=store)
    except KeyboardInterrupt:
        crashed = True
    check("第一次真的崩在工具执行中", crashed)

    saved = json.loads(store.redis.data[f"chat:turn:{'b' * 32}"])
    check("崩溃现场停在「已声明、未执行完」",
          saved["pending"] == ["call_1"] and saved["steps"] == [], f"实际: {saved['pending']}")
    check("此刻消息链还不完整（所以恢复必须先补齐）", not _chain_valid(saved["messages"]))
    check("崩在工具里时这一轮 LLM 调用已计入额度", saved["iteration"] == 1)

    # 进程重启：上层（main）加载 checkpoint、计一次 resume、再交给引擎
    resumed = await store.load("b" * 32)
    check("resume 申请放行", resumed.begin_resume() is True)
    await store.save(resumed)

    llm.script = [AIMessage(content="恢复后的答案")]
    result, state = await engine.run_turn("", resumed.session_id, state=resumed, store=store)

    check("恢复后给出答案", result.answer == "恢复后的答案")
    check("重放发生在下一轮 LLM 之前（LLM 看到最后一条是 tool 消息）",
          llm.calls[-1][-1]["type"] == "tool", f"实际: {llm.calls[-1][-1]['type']}")
    final = json.loads(store.redis.data[f"chat:turn:{'b' * 32}"])
    check("工具结果进了消息链且链合法",
          _tool_count(final["messages"]) == 1 and _chain_valid(final["messages"]))
    check("resume_count 记到 checkpoint", final["resume_count"] == 1)
    check("崩溃那次 + 重放那次 = 工具被执行两次（只读，重放安全）",
          len(registry.calls) == 2, f"实际: {len(registry.calls)}")


# ── [3] 批量工具逐条落盘 ────────────────────────────────────


async def test_per_tool_checkpoint():
    print("\n[3] 批量工具调用：跑完一个写一个，中间态可见")
    store = _Store()
    registry = _Registry(("kb_search", "sop_lookup"))
    llm = _ScriptedLLM([
        tool_call_response(
            ("c1", "kb_search", {"q": "a"}),
            ("c2", "sop_lookup", {"q": "b"}),
        ),
        AIMessage(content="答案"),
    ])
    engine = make_engine(registry, llm)
    await engine.run_turn("q", "s1", turn_id="c" * 32, store=store)

    check("写入次数 = 创建 + 声明 + 两个工具 + 完成 = 5",
          len(store.snapshots) == 5, f"实际: {len(store.snapshots)}")
    mid = store.snapshots[2]
    check("第一个工具跑完就落盘（不是等整批）",
          len(mid["steps"]) == 1 and mid["pending"] == ["c2"], f"实际: {mid['pending']}")
    check("另一个未完成调用已在 pending 里", mid["pending"] == ["c2"])
    final = store.snapshots[-1]
    check("最终两个工具都进了消息链", _tool_count(final["messages"]) == 2)
    check("最终链合法且 pending 清空", _chain_valid(final["messages"]) and final["pending"] == [])


# ── [4] 剩余额度 ────────────────────────────────────────────


async def test_remaining_budget():
    print("\n[4] 恢复用剩余额度：不重头跑")
    store = _Store()
    registry = _Registry(("kb_search",))
    llm = _ScriptedLLM([AIMessage(content="答案")])
    engine = make_engine(registry, llm, max_iterations=5)
    state = TurnState(
        turn_id="d" * 32, session_id="s1", question="q", max_iterations=5, iteration=4,
        messages=messages_to_dict([SystemMessage(content="sys"), HumanMessage(content="q")]),
    )

    result, done = await engine.run_turn("", "s1", state=state, store=store)

    check("只剩 1 轮额度 → 只调 1 次 LLM", len(llm.calls) == 1, f"实际: {len(llm.calls)}")
    check("iteration 到顶 5/5", done.iteration == 5)
    check("剩余额度归零", done.remaining_iterations == 0)
    check("额度用尽也能交付（没走兜底合成）", result.answer == "答案")


# ── [5] 死循环检测跨恢复 ────────────────────────────────────


async def test_repetition_across_resume():
    print("\n[5] call_history 跟着 checkpoint 走：跨恢复的重复调用仍被拦")
    store = _Store()
    registry = _Registry(("kb_search",))
    engine = make_engine(registry, _ScriptedLLM([AIMessage(content="答案")]))

    history: list[str] = []
    engine._check_repetition(history, "kb_search", {"q": "a"})
    engine._check_repetition(history, "kb_search", {"q": "a"})
    state = TurnState(
        turn_id="e" * 32, session_id="s1", question="q", max_iterations=5,
        call_history=history,
        pending=["c1"],
        messages=messages_to_dict([
            SystemMessage(content="sys"),
            HumanMessage(content="q"),
            AIMessage(content="", tool_calls=[
                {"name": "kb_search", "args": {"q": "a"}, "id": "c1", "type": "tool_call"},
            ]),
        ]),
    )

    _, done = await engine.run_turn("", "s1", state=state, store=store)

    check("第三次相同调用被拦，工具没执行", registry.calls == [], f"实际: {registry.calls}")
    check("拦截提示进了消息链（LLM 看得到）", "反复调用" in _last_tool_text(store.snapshots[-1]["messages"]))
    check("pending 已清空（链依然合法）", done.pending == [] and _chain_valid(store.snapshots[-1]["messages"]))


# ── [6] 不可恢复的 checkpoint ───────────────────────────────


async def test_unrecoverable_pending():
    print("\n[6] pending 找不到声明 → 拒绝恢复，不发非法消息链给 LLM")
    store = _Store()
    registry = _Registry(("kb_search",))
    llm = _ScriptedLLM([])
    engine = make_engine(registry, llm)
    state = TurnState(
        turn_id="f" * 32, session_id="s1", question="q",
        messages=messages_to_dict([SystemMessage(content="sys"), HumanMessage(content="q")]),
        pending=["ghost"],
    )

    raised = None
    try:
        await engine.run_turn("", "s1", state=state, store=store)
    except TurnProtocolError as exc:
        raised = exc

    check("抛 TurnProtocolError（上层落 abandoned）", raised is not None)
    check("没有浪费一次 LLM 调用", llm.calls == [])


# ── [7] 记忆幂等 + 追踪日志 ─────────────────────────────────


async def test_memory_idempotent_and_trace():
    print("\n[7] 终态记忆幂等 + 追踪事件齐全")
    store = _Store()
    memory = _Memory()
    registry = _Registry(("kb_search",))
    llm = _ScriptedLLM([
        tool_call_response(("c1", "kb_search", {"q": "x"})),
        AIMessage(content="答案"),
    ])
    engine = make_engine(registry, llm, memory=memory)

    logger = logging.getLogger(TRACE_LOGGER_NAME)
    cap = _Capture()
    logger.addHandler(cap)
    logger.setLevel(logging.INFO)
    try:
        await engine.run_turn("q", "s1", turn_id="1" * 32, store=store)
        check("终态写了一次向量记忆", len(memory.episodes) == 1)

        state = await store.load("1" * 32)
        await engine._store_episode(state, "q", "答案", 0.8, store)
        check("重复收尾被 memo 标记挡住（不往 Milvus 存第二遍）", len(memory.episodes) == 1)
    finally:
        logger.removeHandler(cap)

    events = [json.loads(line)["event"] for line in cap.lines]
    expected = {"turn_start", "turn_created", "llm_call", "llm_tool_calls",
                "tool_end", "turn_completed", "turn_finished"}
    check("事件按顺序打全", expected <= set(events), f"实际: {events}")
    check("工具事件带耗时与结果标记",
          any(json.loads(line)["event"] == "tool_end"
              and json.loads(line)["ok"] is True
              and json.loads(line)["latency_ms"] >= 0 for line in cap.lines))


async def test_error_keeps_turn_resumable():
    print("\n[8] 推理中途失败：状态留在 running，错误原因落盘，仍可继续")
    store = _Store()
    registry = _Registry(("kb_search",))
    llm = _ScriptedLLM([RuntimeError("LLM 超时")])
    engine = make_engine(registry, llm)
    state = TurnState(
        turn_id="9" * 32, session_id="s1", question="q",
        messages=messages_to_dict([SystemMessage(content="sys"), HumanMessage(content="q")]),
    )

    raised = None
    try:
        await engine.run_turn("", "s1", state=state, store=store)
    except RuntimeError as exc:
        raised = exc
    check("异常照常上抛（SSE 才能给出错误帧）", raised is not None)

    saved = json.loads(store.redis.data[f"chat:turn:{'9' * 32}"])
    check("状态保持 running（不是 failed）", saved["status"] == "running")
    check("失败原因写进 checkpoint 供排查", "LLM 超时" in (saved["error"] or ""))
    check("失败的 LLM 轮次不占额度", saved["iteration"] == 0)

    llm.script = [AIMessage(content="补跑成功")]
    resumed = await store.load("9" * 32)
    check("失败后仍可申请恢复", resumed.begin_resume() is True)
    result, done = await engine.run_turn("", "s1", state=resumed, store=store)
    check("接着跑能出答案", result.answer == "补跑成功" and done.status == "completed")


async def test_memory_history_in_messages():
    print("\n[9] 短期/长期记忆进消息链：多轮上下文不丢，当前问题不重复")
    store = _Store()
    registry = _Registry(("kb_search",))
    llm = _ScriptedLLM([AIMessage(content="答案")])
    memory = _Memory()
    memory.memory_context = "上次聊过：红烧肉盐量偏高"
    # 模拟 main 的写入顺序：上一轮问答 + 本轮问题都已经在短期记忆里
    memory.add_message("user", "红烧肉为什么咸？")
    memory.add_message("assistant", "上一轮答案：调味环节盐量波动")
    memory.add_message("user", "那怎么改？")

    engine = make_engine(registry, llm, memory=memory)
    await engine.run_turn("那怎么改？", "s1", turn_id="7" * 32, store=store)

    first_call = llm.calls[0]
    roles = [m["type"] for m in first_call]
    texts = [str(m["data"].get("content") or "") for m in first_call]

    check("历史里的上一轮问答进了消息链", any("上一轮答案" in t for t in texts), f"实际: {texts}")
    check("当前问题只出现一次（不会被拼两遍）",
          sum(1 for t in texts if t == "那怎么改？") == 1, f"实际: {texts}")
    check("system 提示词在最前", roles[0] == "system")
    check("长期记忆摘要紧跟 system", roles[1] == "system" and "盐量偏高" in texts[1])
    check("最后一条是当前问题", roles[-1] == "human" and texts[-1] == "那怎么改？")
    check("对话历史顺序保持 user → ai", roles[2:] == ["human", "ai", "human"], f"实际: {roles}")


async def main():
    await test_happy_path()
    await test_crash_mid_tool_then_resume()
    await test_per_tool_checkpoint()
    await test_remaining_budget()
    await test_repetition_across_resume()
    await test_unrecoverable_pending()
    await test_memory_idempotent_and_trace()
    await test_error_keeps_turn_resumable()
    await test_memory_history_in_messages()
    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
