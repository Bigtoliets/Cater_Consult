"""ReAct 循环引擎 (v4.0)

Think → Act → Observe → Think → Act → ... 循环
- 最大迭代轮数: 可配置 (默认5)
- 自适应终止: LLM 输出 FINAL_ANSWER 或置信度达标时停止
- 工具调用: 通过 ToolRegistry 执行，结果注入下一轮 Think

ReAct Prompt 结构:
  System: 工具列表 + 行为规范 + Few-shot示例
  User: 用户问题
  Assistant(Think): 分析当前状态，决定下一步 (工具调用 / 最终答案)
  Tool(Observe): 工具执行结果
  Assistant(Think): 基于观察调整策略...
  ...
  Assistant: FINAL_ANSWER
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.utils.llm import get_llm
from app.tools.base import ToolRegistry, ToolResult, get_tool_registry
from app.prompts.react_prompts import REACT_SYSTEM_PROMPT, REACT_FEW_SHOT
from app.memory.manager import MemoryManager


@dataclass
class ReActStep:
    """一个 ReAct 步骤的记录"""
    thought: str     # LLM 的思考
    action: str      # 工具名 或 FINAL_ANSWER
    action_input: dict  # 工具参数
    observation: str  # 工具返回结果
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
    ACTION_PATTERN = re.compile(
        r'ACTION:\s*(\w+)\s*\nACTION_INPUT:\s*(\{.*?\}|.+?)(?:\n|$)',
        re.DOTALL,
    )
    FINAL_PATTERN = re.compile(
        r'FINAL_ANSWER:\s*\n?(.*)',
        re.DOTALL,
    )

    def __init__(
        self,
        tool_registry: ToolRegistry = None,
        memory: MemoryManager = None,
        max_iterations: int = 5,
        min_confidence: float = 0.5,
    ):
        self.registry = tool_registry or get_tool_registry()
        self.memory = memory
        self.max_iterations = max_iterations
        self.min_confidence = min_confidence

    async def run(self, question: str, session_id: str = "") -> ReActResult:
        """
        执行 ReAct 循环

        Args:
            question: 用户问题
            session_id: 会话ID (用于记忆管理)

        Returns:
            ReActResult
        """
        llm = get_llm(temperature=0.3)

        # 构建初始消息
        tools_desc = self.registry.get_tool_descriptions()
        system_prompt = REACT_SYSTEM_PROMPT.format(
            tools=tools_desc,
            few_shot=REACT_FEW_SHOT,
        )

        # 检索历史记忆
        memory_context = ""
        if self.memory and session_id:
            memory_context = await self.memory.retrieve_relevant(question, session_id, k=2)

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if memory_context:
            messages.append({"role": "system", "content": f"## 历史相关对话摘要\n{memory_context}"})
        messages.append({"role": "user", "content": question})

        steps: list[ReActStep] = []
        tools_called: list[str] = []
        sources: list[str] = []
        final_answer = ""
        final_confidence = 0.5

        for iteration in range(self.max_iterations):
            # Think: LLM 分析当前状态
            response = await llm.ainvoke(messages)
            thought_text = response.content

            # 检查是否为最终答案
            final_match = self.FINAL_PATTERN.search(thought_text)
            if final_match:
                final_answer = final_match.group(1).strip()
                final_confidence = self._estimate_confidence(steps)
                break

            # 解析 Action
            action_match = self.ACTION_PATTERN.search(thought_text)
            if not action_match:
                # 无法解析 → 要求LLM按格式输出
                messages.append({"role": "assistant", "content": thought_text})
                messages.append({
                    "role": "user",
                    "content": "请按格式输出: THOUGHT: ... ACTION: tool_name ACTION_INPUT: {...}"
                               " 或 FINAL_ANSWER: ..."
                })
                continue

            action_name = action_match.group(1).strip()
            action_input_str = action_match.group(2).strip()

            # 解析 action_input
            try:
                action_input = json.loads(action_input_str)
            except json.JSONDecodeError:
                action_input = {"query": action_input_str}

            # Act: 执行工具
            result = await self.registry.execute_tool(action_name, **action_input)

            # Observe
            observation = result.format_for_llm()
            sources.append(result.source)

            step = ReActStep(
                thought=thought_text[:500],
                action=action_name,
                action_input=action_input,
                observation=observation[:800],
            )
            steps.append(step)
            tools_called.append(action_name)

            # 更新对话
            messages.append({"role": "assistant", "content": thought_text})
            messages.append({
                "role": "user",
                "content": f"OBSERVATION: {observation}\n\n请继续分析。如果需要更多信息请调用工具，如果已经足够请输出 FINAL_ANSWER。"
            })

            # 自适应终止: 事实核查通过 + 高置信度 → 可提前退出
            if action_name == "check_fact" and result.confidence >= 0.7:
                final_answer = self._synthesize_final_answer(steps)
                final_confidence = result.confidence
                break

        # 达到最大迭代但无最终答案 → 强制合成
        if not final_answer:
            final_answer = self._synthesize_final_answer(steps)
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

    def _estimate_confidence(self, steps: list[ReActStep]) -> float:
        """基于步骤质量估算置信度"""
        if not steps:
            return 0.3
        # 工具调用次数越多 + 有事实核查 = 越高
        base = min(0.9, 0.3 + 0.15 * len(steps))
        has_fact_check = any(s.action == "check_fact" for s in steps)
        has_kb = any(s.action in ("search_knowledge_base", "lookup_sop") for s in steps)
        if has_fact_check:
            base += 0.1
        if has_kb:
            base += 0.1
        return min(0.95, base)

    def _synthesize_final_answer(self, steps: list[ReActStep]) -> str:
        """从步骤中合成最终答案（兜底）"""
        if not steps:
            return "抱歉，我无法完成这个分析。请提供更多信息或稍后重试。"

        parts = []
        for i, step in enumerate(steps):
            parts.append(f"[步骤{i+1}] 调用 {step.action}: {step.observation[:200]}")

        return "\n".join(parts) + "\n\n⚠️ 以上为自动合成的分析摘要，建议人工复核。"
