"""记忆管理系统 (v4.0)

三层记忆架构:
1. **短期记忆 (Short-term)**: 滑动窗口 — 最近 N 轮对话 (默认20条消息)
2. **工作记忆 (Working)**: 当前分析上下文 — AgentState
3. **长期记忆 (Long-term)**: 向量存储的历史对话摘要 — 通过 Milvus 实现

记忆压缩策略:
- 滑动窗口: 保留最近 K 条完整消息，超出的压缩为摘要
- 关键点提取: 每 N 轮对话自动提取关键事实为 bullet points
- 触发条件: 总 token 估算超过阈值 (默认 3000 tokens) 时触发压缩
"""
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class Message:
    """单条消息"""
    role: str           # user / assistant / system / tool
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class CompressedMemory:
    """压缩后的记忆块"""
    summary: str              # 关键点摘要
    original_message_count: int
    compressed_at: float
    key_facts: list[str] = field(default_factory=list)


class MemoryManager:
    """三层记忆管理器"""

    # Token 估算 (中文约1.5字符/token)
    CHARS_PER_TOKEN = 1.5
    MAX_TOKENS = 3000           # 总上下文 token 上限
    WINDOW_SIZE = 20            # 滑动窗口大小 (消息条数)
    COMPRESS_EVERY_N = 10       # 每 N 轮对话触发一次压缩
    KEY_FACT_MAX = 8            # 关键事实最大保留数

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.short_term: deque[Message] = deque(maxlen=self.WINDOW_SIZE)
        self.compressed_blocks: list[CompressedMemory] = []
        self.key_facts: list[str] = []        # 全局关键事实
        self.message_count_since_compress = 0
        self.working_context: dict[str, Any] = {}  # 工作记忆

    # ── 短期记忆 ──────────────────────────────────

    def add_message(self, role: str, content: str, metadata: dict = None):
        """添加消息到短期记忆"""
        msg = Message(role=role, content=content, metadata=metadata or {})
        # 如果窗口满了，最旧的消息被挤出前先检查是否需要压缩
        if len(self.short_term) >= self.WINDOW_SIZE - 2:
            self._maybe_compress()

        self.short_term.append(msg)
        self.message_count_since_compress += 1

    def get_recent_messages(self, n: int = None) -> list[dict]:
        """获取最近 n 条消息"""
        msgs = list(self.short_term)
        if n:
            msgs = msgs[-n:]
        return [{"role": m.role, "content": m.content} for m in msgs]

    # ── 记忆压缩 ──────────────────────────────────

    def _maybe_compress(self):
        """检查是否需要压缩并执行"""
        # 条件1: 累计消息数达到阈值
        if self.message_count_since_compress < self.COMPRESS_EVERY_N:
            # 条件2: token 估算超限
            est_tokens = self._estimate_tokens()
            if est_tokens < self.MAX_TOKENS:
                return

        self._compress()

    def _compress(self):
        """执行压缩: 将窗口前一半消息压缩为摘要"""
        if len(self.short_term) < 6:
            return

        messages = list(self.short_term)
        # 取前一半消息进行压缩
        split_point = len(messages) // 2
        to_compress = messages[:split_point]

        # 提取关键事实
        new_facts = self._extract_key_facts(to_compress)
        for fact in new_facts:
            if fact not in self.key_facts:
                self.key_facts.append(fact)
        # 保持关键事实数量在限制内
        if len(self.key_facts) > self.KEY_FACT_MAX:
            self.key_facts = self.key_facts[-self.KEY_FACT_MAX:]

        # 生成摘要
        summary_parts = [f"[对话摘要 {len(self.compressed_blocks)+1}]"]
        user_msgs = [m for m in to_compress if m.role == "user"]
        assistant_msgs = [m for m in to_compress if m.role == "assistant"]

        if user_msgs:
            summary_parts.append(f"用户关注: {'; '.join(m.content[:80] for m in user_msgs[-3:])}")
        if assistant_msgs:
            summary_parts.append(f"回复要点: {'; '.join(m.content[:100] for m in assistant_msgs[-3:])}")

        compressed = CompressedMemory(
            summary="\n".join(summary_parts),
            original_message_count=len(to_compress),
            compressed_at=time.time(),
            key_facts=list(new_facts),
        )
        self.compressed_blocks.append(compressed)

        # 重建短期记忆: 只保留后半部分消息
        self.short_term = deque(messages[split_point:], maxlen=self.WINDOW_SIZE)
        self.message_count_since_compress = 0

    def _extract_key_facts(self, messages: list[Message]) -> list[str]:
        """
        从消息中提取关键事实 (规则提取, 不调用LLM以节省token)
        识别模式:
        - 菜品名 + 数值参数
        - 整改建议
        - 置信度声明
        """
        import re
        facts = []

        for msg in messages:
            if msg.role != "assistant":
                continue
            # 提取含数字参数的事实
            params = re.findall(r'(\S{2,10}\s*[:：=]\s*\d+\s*\S{0,5})', msg.content)
            for p in params[:3]:
                facts.append(p.strip())

            # 提取整改项
            improvements = re.findall(r'[1-9]\.\s*(.{10,60})', msg.content)
            for imp in improvements[:2]:
                facts.append(f"整改: {imp.strip()}")

        return list(set(facts))[:5]

    def _estimate_tokens(self) -> int:
        """估算当前上下文的总token数"""
        total_chars = sum(len(m.content) for m in self.short_term)
        for block in self.compressed_blocks:
            total_chars += len(block.summary)
        total_chars += sum(len(f) for f in self.key_facts)
        return int(total_chars / self.CHARS_PER_TOKEN)

    # ── 长期记忆 ──────────────────────────────────

    async def store_episode(
        self, session_id: str, question: str, answer: str, metadata: dict = None
    ):
        """存储完整对话片段到长期记忆 (写入 Milvus)"""
        # 生成摘要作为向量化内容
        summary = f"Q: {question[:200]}\nA: {answer[:400]}"
        try:
            from app.utils.milvus_client import write_to_standard
            import uuid
            ep_id = f"MEM-{uuid.uuid4().hex[:8].upper()}"
            await write_to_standard(ep_id, session_id[:50], summary)
        except Exception as e:
            print(f"[Memory] 长期记忆写入失败: {e}")

    async def retrieve_relevant(self, query: str, session_id: str, k: int = 3) -> str:
        """从长期记忆中检索相关历史对话"""
        try:
            from app.utils.milvus_client import search_with_score
            results = await search_with_score("standard_collection", query, k=k)
            if not results:
                return ""
            parts = ["## 历史相关记忆"]
            for i, r in enumerate(results[:k], 1):
                parts.append(f"[{i}] {r['content'][:300]}")
            return "\n".join(parts)
        except Exception:
            return ""

    # ── 完整上下文构建 ──────────────────────────────────

    def build_context(self, system_prompt: str, current_question: str) -> list[dict]:
        """构建完整的对话上下文 (含压缩块 + 关键事实 + 滑动窗口)"""
        messages = [{"role": "system", "content": system_prompt}]

        # 注入压缩记忆
        if self.compressed_blocks:
            compressed_text = "\n".join(
                f"### {block.summary}" for block in self.compressed_blocks[-3:]
            )
            messages.append({
                "role": "system",
                "content": f"## 历史对话摘要 (已压缩)\n{compressed_text}",
            })

        # 注入关键事实
        if self.key_facts:
            messages.append({
                "role": "system",
                "content": f"## 已确认的关键事实\n" + "\n".join(f"- {f}" for f in self.key_facts),
            })

        # 滑动窗口消息
        messages.extend(self.get_recent_messages())

        # 当前问题
        messages.append({"role": "user", "content": current_question})

        return messages

    # ── 工作记忆 ──────────────────────────────────

    def set_working(self, key: str, value: Any):
        """设置工作记忆"""
        self.working_context[key] = value

    def get_working(self, key: str, default: Any = None) -> Any:
        return self.working_context.get(key, default)


# ── 全局会话记忆池 ──
_session_memories: dict[str, MemoryManager] = {}


def get_or_create_memory(session_id: str) -> MemoryManager:
    """获取或创建会话记忆"""
    global _session_memories
    if session_id not in _session_memories:
        _session_memories[session_id] = MemoryManager(session_id=session_id)

    # 清理过期会话 (超过1小时未活动的)
    now = time.time()
    expired = [
        sid for sid, mem in _session_memories.items()
        if now - (mem.short_term[-1].timestamp if mem.short_term else now) > 3600
    ]
    for sid in expired:
        del _session_memories[sid]

    return _session_memories[session_id]
