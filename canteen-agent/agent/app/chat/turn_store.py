"""问答 turn 的 checkpoint 存储与并发锁（Redis 热存）

一次问答 = 一个 turn。ReAct 循环每推进一步就往同一个 key 覆盖写，
断线 / 进程重启后靠它把推理接上：

    chat:turn:{turn_id}        checkpoint（TTL 24h）
    chat:turn:{turn_id}:lock   执行权锁（SETNX + token，TTL 30s，持锁期间续租）
    chat:turn:{turn_id}:memo   终态写记忆 / 向量库的幂等标记

与 engine / main / 前端共享的约定：

1. 粒度：每个工具调用执行完覆盖写一次。崩溃时最多重放「正在跑的那一个」工具，
   而不是整轮。
2. messages 按 LangChain messages_to_dict 的形状存（ai 消息带 tool_calls、
   tool 消息带 tool_call_id），resume 时原样重建消息链。
3. pending 记「AI 已声明、tool 消息还没写回」的 call_id。resume 必须先补齐
   pending —— OpenAI 协议要求声明过的 tool_call 必须有对应 tool 消息。
4. call_history 是 engine 死循环检测的依据（工具名 + 参数签名），必须跟着
   checkpoint 走，否则 resume 之后重复调用检测归零。
5. 状态机：running → completed / failed / abandoned；resume 超过 MAX_RESUME
   次自动落 abandoned，不再接受恢复。

MySQL 不参与恢复链路：agent 不直连 MySQL，恢复只认这个 key。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime
from typing import Any

from app.config import agent_settings

logger = logging.getLogger(__name__)

TURN_KEY = "chat:turn:{turn_id}"
LOCK_KEY = "chat:turn:{turn_id}:lock"
MEMO_KEY = "chat:turn:{turn_id}:memo"

TURN_TTL = 24 * 3600   # checkpoint 保留 24h：覆盖「用户发现断了再回来点恢复」的窗口
LOCK_TTL = 30          # 执行权锁；跑着的 resume 会定期续租
MAX_RESUME = 3         # 超过就落 abandoned，别拿 LLM 配额无限重试

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_ABANDONED = "abandoned"
STATUSES = frozenset({STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_ABANDONED})

# turn_id 只能进 Redis key，必须挡住 ":"、"*"、空格等可以改 key 语义的字符
_TURN_ID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 只删 / 只续自己的锁：锁超时被第二个请求抢走后，第一个请求不至于误删别人的锁
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 对外校验 / 生成 ──────────────────────────────────────────


def normalize_turn_id(turn_id: str | None) -> str | None:
    """校验并规范化 turn_id（uuid 的 32/36 位形式）→ 32 位 hex；非法返回 None"""
    if not turn_id or not isinstance(turn_id, str):
        return None
    candidate = turn_id.strip()
    if not _TURN_ID_RE.match(candidate):
        return None
    try:
        return uuid.UUID(candidate).hex
    except ValueError:
        return None


def validate_session_id(session_id: str | None) -> str | None:
    """会话 id 白名单校验（字母数字下划线连字符，1~64 位）；非法返回 None"""
    if not session_id or not isinstance(session_id, str):
        return None
    candidate = session_id.strip()
    return candidate if _SESSION_ID_RE.match(candidate) else None


def new_turn_id() -> str:
    """服务端兜底生成的 turn_id：前端没传时用，追踪照样完整，只是不可恢复"""
    return uuid.uuid4().hex


def fallback_session_id() -> str:
    """前端没传 session_id 时的兜底会话（老调用方 / 调试端点）"""
    return f"anon-{uuid.uuid4().hex[:12]}"


def turn_key(turn_id: str) -> str:
    return TURN_KEY.format(turn_id=turn_id)


def lock_key(turn_id: str) -> str:
    return LOCK_KEY.format(turn_id=turn_id)


def memo_key(turn_id: str) -> str:
    return MEMO_KEY.format(turn_id=turn_id)


# ── 状态对象 ────────────────────────────────────────────────


@dataclass
class TurnState:
    """一个问答 turn 的完整可恢复状态（直接 JSON 序列化进 Redis）"""

    turn_id: str
    session_id: str
    question: str
    status: str = STATUS_RUNNING
    iteration: int = 0
    max_iterations: int = 5
    resume_count: int = 0
    messages: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    call_history: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    final_answer: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # ── 序列化 ──
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "TurnState":
        """反序列化：未知字段忽略、缺失字段取默认值；结构性损坏抛 ValueError"""
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("checkpoint 不是 JSON 对象")
        status = str(data.get("status") or STATUS_RUNNING)
        if status not in STATUSES:
            raise ValueError(f"未知状态: {status}")

        known = {f.name for f in dataclass_fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        payload["status"] = status
        if not payload.get("turn_id") or not payload.get("session_id"):
            raise ValueError("checkpoint 缺少 turn_id / session_id")
        payload["turn_id"] = str(payload["turn_id"])
        payload["session_id"] = str(payload["session_id"])
        payload["question"] = str(payload.get("question") or "")
        payload["iteration"] = _as_int(payload.get("iteration"), 0)
        payload["max_iterations"] = _as_int(payload.get("max_iterations"), 5)
        payload["resume_count"] = _as_int(payload.get("resume_count"), 0)
        for key in ("messages", "steps", "tools_called", "sources", "call_history", "pending"):
            payload[key] = _as_list(payload.get(key))
        payload["final_answer"] = _as_opt_str(payload.get("final_answer"))
        payload["error"] = _as_opt_str(payload.get("error"))
        payload["created_at"] = str(payload.get("created_at") or _now())
        payload["updated_at"] = str(payload.get("updated_at") or _now())
        return cls(**payload)

    # ── 只读视图（GET /agent/chat/turns/{turn_id}）──
    def summary(self, step_chars: int = 240) -> dict:
        """给前端/排障用的轨迹摘要：不含消息链原文，观察文本截断"""
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "question": self.question,
            "status": self.status,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "remaining_iterations": self.remaining_iterations,
            "resume_count": self.resume_count,
            "pending": list(self.pending),
            "tools_called": list(self.tools_called),
            "sources": list(self.sources),
            "steps": [
                {
                    "action": s.get("action"),
                    "observation": _truncate(s.get("observation"), step_chars),
                    "timestamp": s.get("timestamp"),
                }
                for s in self.steps
                if isinstance(s, dict)
            ],
            "message_count": len(self.messages),
            "final_answer": self.final_answer if self.status == STATUS_COMPLETED else None,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    # ── 状态机 ──
    @property
    def remaining_iterations(self) -> int:
        return max(0, self.max_iterations - self.iteration)

    @property
    def resumable(self) -> bool:
        return self.status == STATUS_RUNNING and self.resume_count < MAX_RESUME

    def touch(self) -> None:
        self.updated_at = _now()

    def begin_resume(self, max_resume: int = MAX_RESUME) -> bool:
        """申请恢复一次：非 running 或超限返回 False；超限顺带落 abandoned"""
        if self.status != STATUS_RUNNING:
            return False
        if self.resume_count >= max_resume:
            self.abandon(f"resume 次数超过上限 {max_resume}")
            return False
        self.resume_count += 1
        self.touch()
        return True

    def complete(self, answer: str) -> None:
        self.status = STATUS_COMPLETED
        self.final_answer = (answer or "").strip()
        self.pending = []
        self.touch()

    def fail(self, error: Any) -> None:
        self.status = STATUS_FAILED
        self.error = str(error)[:500]
        self.pending = []
        self.touch()

    def abandon(self, reason: str = "") -> None:
        self.status = STATUS_ABANDONED
        if reason:
            self.error = reason[:500]
        self.pending = []
        self.touch()

    def resolve_pending(self, tool_call_id: str) -> bool:
        """某个 tool_call 的 tool 消息已经写回 → 从待补清单里摘掉"""
        if tool_call_id and tool_call_id in self.pending:
            self.pending.remove(tool_call_id)
            self.touch()
            return True
        return False


# ── 存储 ────────────────────────────────────────────────────


class TurnStore:
    """Redis checkpoint 读写 + 执行权锁 + 终态幂等标记

    client 可注入（测试用内存假实现）；不注入时懒建一个长连接客户端并复用。
    """

    def __init__(self, client: Any = None, ttl: int = TURN_TTL, lock_ttl: int = LOCK_TTL):
        self._client = client
        self._ttl = ttl
        self._lock_ttl = lock_ttl

    async def _conn(self):
        if self._client is None:
            self._client = _new_client()
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if closer is None:
            return
        result = closer()
        if hasattr(result, "__await__"):
            await result

    async def ping(self) -> bool:
        """探活：健康检查用，Redis 不通不该把 /agent/health 打成 500"""
        try:
            r = await self._conn()
            return bool(await r.ping())
        except Exception:  # noqa: BLE001
            return False

    # ── checkpoint ──
    async def save(self, state: TurnState) -> TurnState:
        state.touch()
        r = await self._conn()
        await r.set(turn_key(state.turn_id), state.to_json(), ex=self._ttl)
        return state

    async def load(self, turn_id: str) -> TurnState | None:
        key_id = normalize_turn_id(turn_id)
        if key_id is None:
            return None
        r = await self._conn()
        raw = await r.get(turn_key(key_id))
        if not raw:
            return None
        try:
            return TurnState.from_json(raw)
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning(f"[TurnStore] checkpoint 损坏 turn_id={key_id}: {exc}")
            return None

    async def delete(self, turn_id: str) -> None:
        key_id = normalize_turn_id(turn_id)
        if key_id is None:
            return
        r = await self._conn()
        await r.delete(turn_key(key_id))

    # ── 执行权锁（抢不到 → 调用方返回 409）──
    async def acquire_lock(self, turn_id: str) -> str | None:
        key_id = normalize_turn_id(turn_id)
        if key_id is None:
            return None
        r = await self._conn()
        token = uuid.uuid4().hex
        ok = await r.set(lock_key(key_id), token, nx=True, ex=self._lock_ttl)
        return token if ok else None

    async def renew_lock(self, turn_id: str, token: str | None) -> bool:
        """续租：锁已经过期并被别人抢走时返回 False（调用方应停止写 checkpoint）"""
        key_id = normalize_turn_id(turn_id)
        if key_id is None or not token:
            return False
        r = await self._conn()
        res = await r.eval(_RENEW_LOCK_LUA, 1, lock_key(key_id), token, self._lock_ttl)
        return bool(res)

    async def release_lock(self, turn_id: str, token: str | None) -> None:
        key_id = normalize_turn_id(turn_id)
        if key_id is None or not token:
            return
        r = await self._conn()
        await r.eval(_RELEASE_LOCK_LUA, 1, lock_key(key_id), token)

    # ── 终态幂等（写记忆 / 向量库前先问一次）──
    async def mark_memoized(self, turn_id: str, ttl: int = TURN_TTL) -> bool:
        """第一次调用返回 True，重复调用返回 False（重复的 resume 不该再存一遍记忆）"""
        key_id = normalize_turn_id(turn_id)
        if key_id is None:
            return False
        r = await self._conn()
        ok = await r.set(memo_key(key_id), "1", nx=True, ex=ttl)
        return bool(ok)


def _new_client():
    """懒加载 redis：模块导入时不依赖 redis 包（离线单测也就能跑）"""
    try:
        import redis.asyncio as aioredis
    except ImportError as exc:  # pragma: no cover - 部署环境装了 redis
        raise RuntimeError("缺少 redis 依赖：pip install 'redis>=5.0'") from exc
    return aioredis.from_url(agent_settings.REDIS_URL, decode_responses=True)


_store: TurnStore | None = None


def get_turn_store() -> TurnStore:
    """进程内单例：复用一条 Redis 连接（每个工具都新建连接会很浪费）"""
    global _store
    if _store is None:
        _store = TurnStore()
    return _store


# ── 反序列化小工具 ──────────────────────────────────────────


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _truncate(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "…"
