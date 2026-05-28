"""智能问答 API —— 直接调用 Agent 工作流（已合并）"""
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from app.agent.utils.llm import get_llm
from app.agent.workflow import agent_workflow
from app.agent.state import AgentState
import json

router = APIRouter()


@router.post("/query")
async def chat_query(question: str = Query(..., description="用户问题")):
    """SSE 流式对话 —— 直接调用 OpenAI"""

    async def event_stream():
        try:
            llm = get_llm()
            system_prompt = (
                "你是食堂品控智能助手。你可以帮助食堂经理：\n"
                "1. 查询和分析菜品评价数据\n"
                "2. 生成品控改进建议\n"
                "3. 解读诊断报告\n"
                "4. 对比不同档口/食堂的品控表现\n"
                "请基于系统数据给出专业、可操作的建议。如果数据不足，如实说明。"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ]
            async for chunk in llm.astream(question):
                if hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'content': chunk.content})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/presets")
async def get_preset_questions():
    """预设快捷问询"""
    return {
        "presets": [
            "查询昨日客诉最多的档口",
            "生成上周三层食堂的综合改进报告",
            "为什么今天红烧肉评价这么差？",
            "本周食品安全相关投诉汇总",
            "对比一食堂和二食堂的满意度趋势",
            "哪道菜的复发性差评最多？",
        ]
    }
