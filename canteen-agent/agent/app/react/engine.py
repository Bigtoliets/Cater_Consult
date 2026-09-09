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

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

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
        """执行 ReAct 循环

        Args:
            question: 用户问题
            session_id: 会话ID (用于记忆管理)

        Returns:
            ReActResult
        """
        llm = get_llm(temperature=0.3)
        # 原生 Function Calling：把工具 schema 绑定到 LLM
        llm_with_tools = llm.bind_tools(self._build_tools_schema())

        # 检索历史记忆
        memory_context = ""
        if self.memory and session_id:
            memory_context = await self.memory.retrieve_relevant(question, session_id, k=2)

        messages = [SystemMessage(content=REACT_FC_SYSTEM_PROMPT)]
        if memory_context:
            messages.append(SystemMessage(content=f"## 历史相关对话摘要\n{memory_context}"))
        messages.append(HumanMessage(content=question))

        steps: list[ReActStep] = []
        tools_called: list[str] = []
        sources: list[str] = []
        call_history: list[str] = []
        final_answer = ""
        final_confidence = 0.5

        for _ in range(self.max_iterations):
            response = await llm_with_tools.ainvoke(messages)

            # 无工具调用 → 视为最终答案
            if not response.tool_calls:
                final_answer = (response.content or "").strip()
                final_confidence = self._estimate_confidence(steps)
                break

            # 先把含 tool_calls 的 AIMessage 入栈（只需一次）
            messages.append(response)

            for tool_call in response.tool_calls:
                action_name = tool_call.get("name", "")
                action_input = tool_call.get("args", {}) or {}

                # 死循环检测：相同工具 + 相同参数重复 ≥3 次 → 拦截并提示
                if self._check_repetition(call_history, action_name, action_input):
                    messages.append(ToolMessage(
                        content="你已用相同参数反复调用该工具且未获得新信息，请调整查询策略、换用其他工具，或直接基于已有信息给出答案。",
                        tool_call_id=tool_call.get("id", ""),
                    ))
                    continue

                # Act：执行工具（带超时 + 异常隔离）
                observation, source = await self._execute_tool_safely(action_name, action_input)
                sources.append(source)
                tools_called.append(action_name)

                steps.append(ReActStep(
                    thought=(response.content or "")[:500],
                    action=action_name,
                    action_input=action_input,
                    observation=observation[:800],
                ))
                messages.append(ToolMessage(
                    content=observation,
                    tool_call_id=tool_call.get("id", ""),
                ))

        # 达到最大迭代但无最终答案 → LLM 兜底合成
        if not final_answer:
            final_answer = await self._synthesize_final_answer(steps, question, llm)
            final_confidence = max(0.2, self._estimate_confidence(steps))

        # 存储到长期记忆
        if self.memory and session_id and final_answer:
            await self.memory.store_episode(
                session_id=session_id,
                question=question,
                answer=final_answer,
                metadata={
                    "steps": len(steps),
                    "tools": tools_called,
                    "confidence": final_confidence,
                },
            )

        return ReActResult(
            answer=final_answer,
            steps=steps,
            total_iterations=len(steps),
            tools_called=tools_called,
            confidence=final_confidence,
            sources=list(set(sources)),
        )

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
