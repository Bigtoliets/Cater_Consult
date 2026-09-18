"""问答链路的结构化追踪日志

每步一行 JSON，走 stdout（docker logs 可 grep），靠 turn_id 串成完整时间线：

    {"ts":"2026-09-18T10:20:31.512","event":"tool_end","turn_id":"...",
     "session_id":"...","iteration":2,"action":"search_knowledge_base",
     "tool_call_id":"call_abc","ok":true,"latency_ms":812.4}

为什么不起新组件：恢复只依赖 Redis checkpoint（见 turn_store），日志只承担
「可排查 / 可演示」，所以只往 stdout 写单行 JSON，不落文件、不进 MySQL。
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

TRACE_LOGGER_NAME = "agent.trace"

logger = logging.getLogger(TRACE_LOGGER_NAME)


def trace(event: str, **fields: Any) -> None:
    """记一条结构化事件（单行 JSON；ensure_ascii=False 保证中文可直接读）"""
    payload: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "event": event,
    }
    payload.update({k: v for k, v in fields.items() if v is not None})
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))


@asynccontextmanager
async def trace_span(event: str, **fields: Any) -> AsyncIterator[None]:
    """给一次外部调用（工具 / LLM）计时并记录成败；异常照常向上抛，不吞"""
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 —— 只做记录，拦截交给上层
        trace(
            event,
            **{**fields, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
               "latency_ms": _elapsed_ms(started)},
        )
        raise
    trace(event, **{**fields, "ok": True, "latency_ms": _elapsed_ms(started)})


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
