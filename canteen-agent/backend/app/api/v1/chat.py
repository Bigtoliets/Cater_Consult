"""智能问答 API（SSE 流式）—— 透传 Agent 微服务，双库 RAG 检索"""
import json
import httpx
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.config import settings

router = APIRouter()


@router.post("/query")
async def chat_query(question: str = Query(..., description="用户问题")):
    """透传 SSE 流到 Agent 微服务 /agent/chat"""

    async def event_stream():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{settings.AGENT_INTERNAL_URL}/agent/chat",
                    json={"question": question},
                ) as resp:
                    if resp.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Agent 返回 {resp.status_code}'})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if line:
                            yield f"{line}\n\n"
        except httpx.ConnectError:
            yield f"data: {json.dumps({'error': 'Agent 微服务未启动，请先启动 Agent (端口 8001)'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
