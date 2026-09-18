"""问答 turn 的追踪与恢复（checkpoint / 并发锁 / 结构化日志）

设计结论（2026-09 grill）见 turn_store 模块 docstring；对外只暴露这些名字，
调用方（main.py / engine.py）不要直接摸 Redis key 拼接。
"""
from app.chat.turn_store import (
    MAX_RESUME,
    STATUS_ABANDONED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    TurnState,
    TurnStore,
    fallback_session_id,
    get_turn_store,
    new_turn_id,
    normalize_turn_id,
    validate_session_id,
)

__all__ = [
    "MAX_RESUME",
    "STATUS_ABANDONED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_RUNNING",
    "TurnState",
    "TurnStore",
    "fallback_session_id",
    "get_turn_store",
    "new_turn_id",
    "normalize_turn_id",
    "validate_session_id",
]
