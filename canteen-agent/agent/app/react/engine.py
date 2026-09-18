"""ReAct 循环引擎 (v5.0)

原生 Function Calling 驱动的 Think → Act → Observe 循环：
- 放弃脆弱的正则解析，改用 LLM 原生工具调用（bind_tools）
- 工具执行带硬超时 + 异常隔离，失败转为可读的 Observation
- 死循环检测：相同工具 + 相同参数重复调用会被拦截
- 兜底合成升级为 LLM 聚合，而非字符串拼接
"""
import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)

from app.chat.trace import trace, trace_span
from app.chat.turn_store import TurnState, TurnStore, new_turn_id
from app.utils.llm import get_llm
from app.tools.base import ToolRegistry, get_tool_registry
from app.prompts.react_prompts import REACT_FC_SYSTEM_PROMPT
from app.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

TOOL_TIMEOUT = 20.0  # 单工具硬超时（秒）


@dataclass
class ReActStep:
    """一个 ReAct 步骤的记录"""
    thought: str         # LLM 在工具调用前的思考（function calling 下可能为空）
    action: str          # 工具名
    action_input: dict   # 工具参数
    observation: str     # 工具返回结果
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ReActResult:
    """ReAct 循环的最终结果"""
    answer: str
    steps: list[ReActStep]
    total_iterations: int
    tools_called: list[str]
    confidence: float
    sources: list[str]


class TurnProtocolError(RuntimeError):
    """checkpoint 的消息链已经违反 OpenAI 消息协议，无法继续恢复

    例：pending 里的 tool_call 在消息链里找不到声明（AI 声明的调用必须有对应 tool 消息）。
    上层收到它应当把 turn 落 failed/abandoned 并告诉前端重新提问。
    """


def _to_lc_message(message: dict):
    """记忆层的 {role, content} → LangChain 消息（未知 role 按 user 处理）"""
    role = str(message.get("role") or "user")
    content = str(message.get("content") or "")
    if role == "assistant":
        return AIMessage(content=content)
    if role == "system":
        return SystemMessage(content=content)
    return HumanMessage(content=content)


class ReActEngine:
    """ReAct 循环引擎"""

    MAX_ITERATIONS = 5

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        memory: Optional[MemoryManager] = None,
        max_iterations: int = 5,
        min_confidence: float = 0.5,
    ):
        self.registry = tool_registry or get_tool_registry()
        self.memory = memory
        self.max_iterations = max_iterations
        self.min_confidence = min_confidence

    async def run(self, question: str, session_id: str = "") -> ReActResult:
        """执行 ReAct 循环（不落 checkpoint 的精简入口；调试与旧调用方用）

        线上 /agent/chat 走 run_turn：每步落 Redis checkpoint，断线后能接着跑。
        两条路径共用同一套推理逻辑，所以这里只是 run_turn 的薄包装。
        """
        result, _ = await self.run_turn(question, session_id)
        return result

    async def run_turn(
        self,
        question: str,
        session_id: str = "",
        *,
        turn_id: str | None = None,
        state: TurnState | None = None,
        store: TurnStore | None = None,
    ) -> tuple[ReActResult, TurnState]:
        """执行或恢复一次问答，返回 (推理结果, turn 状态)

        Args:
            turn_id: 新 turn 的 id（前端生成 / 服务端兜底）；恢复时以 state 为准
            state:   传入 = 从 checkpoint 恢复（调用方负责校验、拿锁、计 resume 次数）
            store:   checkpoint 存储；None = 不落盘，只出结构化追踪日志
        """
        llm = get_llm(temperature=0.3)
        # 原生 Function Calling：把工具 schema 绑定到 LLM
        llm_with_tools = llm.bind_tools(self._build_tools_schema())

        resuming = state is not None
        if state is None:
            state = await self._new_turn(question, session_id, turn_id, store)
        else:
            question = state.question or question
        messages = messages_from_dict(state.messages)

        try:
            return await self._drive_turn(
                state, messages, question, llm, llm_with_tools, store, resuming
            )
        except TurnProtocolError:
            raise
        except Exception as exc:  # noqa: BLE001 — 记录现场后照常向上抛
            # 崩在推理中途：状态保持 running（每个写入点的消息链都是合法的），
            # 记下原因并落盘 —— 前端拿 turn_id 就能接着跑，不用重头问
            state.error = f"{type(exc).__name__}: {exc}"[:500]
            await self._checkpoint(store, state, messages, "turn_error", error=state.error)
            raise

    async def _drive_turn(
        self,
        state: TurnState,
        messages: list,
        question: str,
        llm,
        llm_with_tools,
        store: TurnStore | None,
        resuming: bool,
    ) -> tuple[ReActResult, TurnState]:
        """ReAct 推理主循环：恢复补齐 pending → 逐轮 Think / Act / Observe → 终态收尾"""
        if resuming:
            # 上次崩在工具执行中间 → 先补齐 AI 已声明的调用，消息链才合法
            await self._replay_pending(state, messages, store)

        trace(
            "turn_resume" if resuming else "turn_start",
            turn_id=state.turn_id,
            session_id=state.session_id,
            iteration=state.iteration,
            pending=len(state.pending),
            resume_count=state.resume_count,
        )

        final_answer = ""
        final_confidence = 0.5

        while state.iteration < state.max_iterations:
            round_no = state.iteration + 1
            async with trace_span(
                "llm_call",
                turn_id=state.turn_id,
                session_id=state.session_id,
                iteration=round_no,
            ):
                response = await llm_with_tools.ainvoke(messages)
            # 只在拿到响应后 +1：崩在 LLM 调用里时这一轮不算数，恢复会重发
            state.iteration = round_no

            # 无工具调用 → 视为最终答案
            if not response.tool_calls:
                final_answer = (response.content or "").strip()
                final_confidence = self._estimate_confidence(self._steps_of(state))
                break

            # 先把含 tool_calls 的 AIMessage 入栈（只需一次）
            messages.append(response)
            state.pending.extend(
                tc.get("id", "") for tc in response.tool_calls if tc.get("id")
            )
            # WAL 写入点 ②：AI 声明了哪些调用先落盘，工具还没跑也要能查出来
            await self._checkpoint(
                store, state, messages, "llm_tool_calls", calls=len(response.tool_calls)
            )

            for tool_call in response.tool_calls:
                await self._run_tool_call(
                    state, messages, tool_call, store, thought=response.content or ""
                )

        steps = self._steps_of(state)
        # 达到最大迭代但无最终答案 → LLM 兜底合成
        if not final_answer:
            final_answer = await self._synthesize_final_answer(steps, question, llm)
            final_confidence = max(0.2, self._estimate_confidence(steps))

        state.complete(final_answer)
        await self._checkpoint(store, state, messages, "turn_completed", answer_chars=len(final_answer))
        await self._store_episode(state, question, final_answer, final_confidence, store)

        result = ReActResult(
            answer=final_answer,
            steps=steps,
            total_iterations=state.iteration,
            tools_called=list(state.tools_called),
            confidence=final_confidence,
            sources=list(dict.fromkeys(state.sources)),
        )
        trace(
            "turn_finished",
            turn_id=state.turn_id,
            iteration=state.iteration,
            tools=len(state.tools_called),
            confidence=final_confidence,
            status=state.status,
        )
        return result, state

    # ── turn 现场：checkpoint / 恢复 ─────────────────────────

    async def _new_turn(
        self,
        question: str,
        session_id: str,
        turn_id: str | None,
        store: TurnStore | None,
    ) -> TurnState:
        """WAL 写入点 ①：turn 创建 + 初始消息链（记忆上下文作为快照一并存下）

        记忆检索只在起始做一次。恢复时不再重新检索：历史上下文已经在
        messages 快照里，而进程内的 MemoryManager 重启后本来就是空的。

        消息链 = System(REACT 提示词) + [长期记忆摘要] + 压缩块/关键事实/最近对话 + 当前问题。
        短期记忆里的当前问题会被去掉再统一追加，避免同一个问题出现两次。
        """
        memory_context = ""
        if self.memory and session_id:
            memory_context = await self.memory.retrieve_relevant(question, session_id, k=2)

        history: list[dict] = []
        if self.memory:
            history = self.memory.build_context(REACT_FC_SYSTEM_PROMPT)
            if (
                history
                and history[-1].get("role") == "user"
                and history[-1].get("content") == question
            ):
                history = history[:-1]

        messages = [_to_lc_message(m) for m in history] or [
            SystemMessage(content=REACT_FC_SYSTEM_PROMPT)
        ]
        if memory_context:
            messages.insert(1, SystemMessage(content=f"## 历史相关对话摘要\n{memory_context}"))
        messages.append(HumanMessage(content=question))

        state = TurnState(
            turn_id=turn_id or new_turn_id(),
            session_id=session_id or "default",
            question=question,
            max_iterations=self.max_iterations,
            messages=messages_to_dict(messages),
        )
        await self._checkpoint(store, state, messages, "turn_created")
        return state

    async def _replay_pending(
        self,
        state: TurnState,
        messages: list,
        store: TurnStore | None,
    ) -> None:
        """恢复时补齐 pending：AI 声明过、但 tool 消息还没写回的调用，按原顺序重放

        这是协议硬约束：AI 消息里声明的每个 tool_call 都必须有对应的 tool 消息，
        否则下一次调用 LLM 直接 400。工具全是只读的，重放安全。
        """
        if not state.pending:
            return
        declared: dict[str, tuple[dict, str]] = {}
        for message in messages:
            for tool_call in getattr(message, "tool_calls", None) or []:
                call_id = tool_call.get("id", "")
                if call_id:
                    declared[call_id] = (tool_call, getattr(message, "content", "") or "")

        for call_id in list(state.pending):
            entry = declared.get(call_id)
            if entry is None:
                # 声明都不在消息链里了，补不出合法结构 → 交给上层放弃这个 turn
                raise TurnProtocolError(
                    f"pending 中的 tool_call {call_id} 在消息链里找不到声明，checkpoint 不可恢复"
                )
            tool_call, thought = entry
            await self._run_tool_call(state, messages, tool_call, store, thought=thought)

    async def _run_tool_call(
        self,
        state: TurnState,
        messages: list,
        tool_call: dict,
        store: TurnStore | None,
        thought: str = "",
    ) -> None:
        """执行一个 tool_call：死循环检测 → 超时/异常隔离 → 追加 tool 消息 → 落 checkpoint"""
        call_id = tool_call.get("id", "") or ""
        action_name = tool_call.get("name", "")
        action_input = tool_call.get("args", {}) or {}

        # 死循环检测：相同工具 + 相同参数重复 ≥3 次 → 拦截并提示
        if self._check_repetition(state.call_history, action_name, action_input):
            messages.append(ToolMessage(
                content="你已用相同参数反复调用该工具且未获得新信息，请调整查询策略、换用其他工具，或直接基于已有信息给出答案。",
                tool_call_id=call_id,
            ))
            state.resolve_pending(call_id)
            await self._checkpoint(
                store, state, messages, "tool_blocked",
                action=action_name, tool_call_id=call_id,
            )
            return

        # Act：执行工具（带超时 + 异常隔离）
        async with trace_span(
            "tool_end",
            turn_id=state.turn_id,
            session_id=state.session_id,
            iteration=state.iteration,
            action=action_name,
            tool_call_id=call_id,
        ):
            observation, source = await self._execute_tool_safely(action_name, action_input)

        # WAL 写入点 ③：每个工具执行完立刻覆盖写，崩溃最多重放「正在跑的这一个」
        messages.append(ToolMessage(content=observation, tool_call_id=call_id))
        if source:
            state.sources.append(source)
        state.tools_called.append(action_name)
        state.steps.append({
            "thought": (thought or "")[:500],
            "action": action_name,
            "action_input": action_input,
            "observation": observation[:800],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        state.resolve_pending(call_id)
        await self._checkpoint(
            store, state, messages, "tool_end",
            action=action_name, tool_call_id=call_id, source=source,
        )

    async def _checkpoint(
        self,
        store: TurnStore | None,
        state: TurnState,
        messages: list,
        event: str,
        **fields,
    ) -> None:
        """把消息链 + 推理现场写进 Redis；落盘失败只丢可恢复性，不让这次问答失败"""
        state.messages = messages_to_dict(messages)
        if store is not None:
            try:
                await store.save(state)
            except Exception as exc:  # noqa: BLE001 — checkpoint 是尽力而为
                trace(
                    "checkpoint_failed",
                    turn_id=state.turn_id,
                    event=event,
                    error=f"{type(exc).__name__}: {exc}"[:200],
                )
                return
        trace(
            event,
            turn_id=state.turn_id,
            session_id=state.session_id,
            iteration=state.iteration,
            status=state.status,
            **fields,
        )

    async def _store_episode(
        self,
        state: TurnState,
        question: str,
        answer: str,
        confidence: float,
        store: TurnStore | None,
    ) -> None:
        """终态写向量记忆；同一个 turn 被重复 resume 时靠 memo 标记幂等"""
        if not (self.memory and state.session_id and answer):
            return
        if store is not None:
            try:
                if not await store.mark_memoized(state.turn_id):
                    trace("memory_skipped", turn_id=state.turn_id, reason="already_memoized")
                    return
            except Exception as exc:  # noqa: BLE001 — 去重标记不可用时照常写，不阻断交付
                trace("memory_dedupe_failed", turn_id=state.turn_id, error=str(exc)[:200])
        try:
            await self.memory.store_episode(
                session_id=state.session_id,
                question=question,
                answer=answer,
                metadata={
                    "steps": len(state.steps),
                    "tools": state.tools_called,
                    "confidence": confidence,
                    "turn_id": state.turn_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            trace("memory_store_failed", turn_id=state.turn_id, error=str(exc)[:200])

    @staticmethod
    def _steps_of(state: TurnState) -> list[ReActStep]:
        """checkpoint 里的步骤字典 → ReActStep（置信度评估与对外结果都用它）"""
        return [
            ReActStep(
                thought=str(s.get("thought") or ""),
                action=str(s.get("action") or ""),
                action_input=s.get("action_input") or {},
                observation=str(s.get("observation") or ""),
                timestamp=str(s.get("timestamp") or ""),
            )
            for s in state.steps
            if isinstance(s, dict)
        ]

    # ── 工具 schema ──────────────────────────────────────────

    def _build_tools_schema(self) -> list[dict]:
        """把注册的工具转成 OpenAI function calling schema"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.registry.get_all()
        ]

    # ── 工具执行（超时 + 异常隔离）────────────────────────────

    async def _execute_tool_safely(
        self,
        action_name: str,
        action_input: dict,
        timeout: float = TOOL_TIMEOUT,
    ) -> tuple[str, str]:
        """执行工具：硬超时 + 异常隔离，失败转为可读的错误 Observation"""
        try:
            result = await asyncio.wait_for(
                self.registry.execute_tool(action_name, **action_input),
                timeout=timeout,
            )
            return result.format_for_llm(), result.source
        except asyncio.TimeoutError:
            logger.warning(f"[ReAct] 工具 {action_name} 超时({timeout}s)")
            return (
                f"工具 [{action_name}] 调用超时（{timeout}s），请缩小查询范围或换用其他工具。",
                "system_error",
            )
        except Exception as e:
            logger.error(f"[ReAct] 工具 {action_name} 异常: {e}", exc_info=True)
            return (
                f"工具 [{action_name}] 执行失败：{e}。请检查参数或换用其他工具。",
                "system_error",
            )

    # ── 死循环检测 ───────────────────────────────────────────

    def _check_repetition(self, call_history: list[str], action_name: str, action_input: dict) -> bool:
        """死循环检测：相同工具 + 相同参数重复 ≥3 次则拦截"""
        sig = (
            f"{action_name}_"
            f"{hashlib.md5(json.dumps(action_input, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"
        )
        call_history.append(sig)
        return call_history.count(sig) >= 3

    # ── 兜底合成 ─────────────────────────────────────────────

    async def _synthesize_final_answer(
        self,
        steps: list[ReActStep],
        question: str,
        llm,
    ) -> str:
        """兜底合成：优先用 LLM 聚合观察结果，失败再降级为字符串拼接"""
        if not steps:
            return "抱歉，无法获取足够信息完成分析，请检查系统状态或提供更多信息。"

        observation_text = "\n".join(
            f"步骤{i + 1} [{s.action}]: {s.observation}" for i, s in enumerate(steps)
        )
        synthesize_prompt = [
            SystemMessage(content=(
                "你是严谨的总结助手。因推理轮数达上限，请结合以下观察结果尽力回答用户问题，"
                "信息不完整时明确说明缺失部分。"
            )),
            HumanMessage(content=f"用户问题：{question}\n\n已执行步骤与观察：\n{observation_text}"),
        ]
        try:
            res = await llm.ainvoke(synthesize_prompt)
            return (res.content or "").strip() + "\n\n*(本回答由多步观察自动聚合生成，建议复核)*"
        except Exception:
            # 二级兜底：字符串拼接
            parts = [
                f"[步骤{i + 1}] {s.action}: {s.observation[:200]}" for i, s in enumerate(steps)
            ]
            return "\n".join(parts) + "\n\n⚠️ 以上为自动合成的分析摘要，建议人工复核。"

    # ── 置信度 ───────────────────────────────────────────────

    def _estimate_confidence(self, steps: list[ReActStep]) -> float:
        """基于步骤质量估算置信度（工具调用越多不再线性加分）"""
        if not steps:
            return 0.3
        has_fact_check = any(s.action == "check_fact" for s in steps)
        has_kb = any(s.action in ("search_knowledge_base", "lookup_sop") for s in steps)
        base = 0.3
        if has_kb:
            base += 0.2
        if has_fact_check:
            base += 0.2
        return min(0.95, base)
