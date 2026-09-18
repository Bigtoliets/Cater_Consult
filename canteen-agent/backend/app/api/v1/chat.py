"""智能问答 API（SSE 流式）—— 透传 Agent 微服务，双库 RAG 检索

问答 turn 的追踪与断点恢复都在 agent 侧（agent/app/chat/turn_store.py），
backend 只做三件事：透传 SSE、转发 turn 状态查询、别自作主张改字段。
"""
import json
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import settings

router = APIRouter()


class ChatQuery(BaseModel):
    question: str
    session_id: str | None = None   # 前端生成的会话 id（记忆隔离）
    turn_id: str | None = None      # 前端生成的 turn id（断线恢复用）


def _error_frame(message: str) -> str:
    """错误也包成 data 帧：前端只认一种 SSE 协议，不用同时处理 HTTP 错误码"""
    return f"data: {json.dumps({'type': 'error', 'error': message}, ensure_ascii=False)}\n\n"


async def _relay_agent_stream(url: str, payload: dict | None = None, params: dict | None = None):
    """把 agent 的 SSE 帧原样转发给前端"""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", url, json=payload, params=params) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:200]
                    yield _error_frame(f"Agent 返回 {resp.status_code}: {body}")
                    return
                async for line in resp.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
    except httpx.ConnectError:
        yield _error_frame("Agent 微服务未启动，请先启动 Agent (端口 8001)")
    except Exception as exc:  # noqa: BLE001 — 流里出错也要给前端一个可读的结束帧
        yield _error_frame(str(exc))


@router.post("/query")
async def chat_query(payload: ChatQuery):
    """透传 SSE 流到 Agent 微服务 /agent/chat

    改成 JSON body 是为了带上 session_id / turn_id（前端生成）；
    只传 question 的老调用方也能用，缺省由 agent 兜底生成。
    """
    return StreamingResponse(
        _relay_agent_stream(
            f"{settings.AGENT_INTERNAL_URL}/agent/chat",
            payload=payload.model_dump(exclude_none=True),
        ),
        media_type="text/event-stream",
    )


@router.post("/resume/{turn_id}")
async def chat_resume(turn_id: str, session_id: str | None = None):
    """透传恢复流：接着一个没跑完的 turn 继续（409 已有恢复在跑 / 410 不能恢复）"""
    params = {"session_id": session_id} if session_id else None
    return StreamingResponse(
        _relay_agent_stream(
            f"{settings.AGENT_INTERNAL_URL}/agent/chat/resume/{turn_id}", params=params
        ),
        media_type="text/event-stream",
    )


@router.get("/turns/{turn_id}")
async def chat_turn_status(turn_id: str, session_id: str | None = None):
    """只读轨迹：前端刷新后先探这里，决定「接着跑」还是「重新问」"""
    params = {"session_id": session_id} if session_id else None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.AGENT_INTERNAL_URL}/agent/chat/turns/{turn_id}", params=params
            )
    except httpx.ConnectError:
        return JSONResponse({"error": "Agent 微服务未启动"}, status_code=503)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=502)
    try:
        return JSONResponse(resp.json(), status_code=resp.status_code)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "Agent 返回了非 JSON 响应"}, status_code=502)


@router.get("/presets")
async def get_presets():
    return {
        "presets": [
            "今天哪些菜品差评最多？分析一下原因",
            "上次红烧肉的整改方案有效果吗？",
            "最近一周卫生问题的趋势怎么样？",
            "昨天收到的客诉中包含哪些安全风险？",
            "为什么将上次红烧肉的方案设为金标？",
        ]
    }
