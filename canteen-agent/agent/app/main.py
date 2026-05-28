"""Agent 微服务入口（FastAPI）"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import json

from app.workflow import agent_workflow
from app.state import AgentState
from app.config import agent_settings
from app.utils.llm import get_llm
from app.utils.milvus_client import get_milvus_store

app = FastAPI(title="Canteen Agent Engine", version="1.0.0")


class ReviewInput(BaseModel):
    raw_reviews: List[Dict]


class ChatInput(BaseModel):
    question: str


class AnalysisResponse(BaseModel):
    status: str
    dish_info: Dict
    risk_level: int
    confidence: float
    conflict_analysis: Dict
    corrective_action: Optional[str]
    human_review_required: bool


@app.post("/agent/analyze", response_model=AnalysisResponse)
async def analyze_reviews(input_data: ReviewInput):
    """分析评价 —— 运行完整 LangGraph 工作流"""
    initial_state: AgentState = {
        "raw_reviews": input_data.raw_reviews,
        "filtered_reviews": [],
        "dish_info": {},
        "risk_level": 1,
        "knowledge_context": "",
        "conflict_analysis": {},
        "confidence": 0.0,
        "corrective_action": None,
        "human_review_required": False,
    }

    try:
        result = await agent_workflow.ainvoke(initial_state)
        return AnalysisResponse(
            status="completed",
            dish_info=result.get("dish_info", {}),
            risk_level=result.get("risk_level", 1),
            confidence=result.get("confidence", 0.0),
            conflict_analysis=result.get("conflict_analysis", {}),
            corrective_action=result.get("corrective_action"),
            human_review_required=result.get("human_review_required", False),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 分析失败：{str(e)}")


@app.post("/agent/chat")
async def agent_chat(input_data: ChatInput):
    """智能问答（SSE 流式）"""
    from fastapi.responses import StreamingResponse

    async def event_stream():
        try:
            llm = get_llm()
            system_prompt = """你是食堂品控智能助手。根据已有知识和数据，回答食堂经理的问题。
请给出专业、可操作的建议。如果数据不足，如实说明。"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_data.question},
            ]

            async for chunk in llm.astream(input_data.question):
                if hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'content': chunk.content})}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/agent/health")
async def health_check():
    """Agent 健康检查"""
    # 检查 Milvus
    milvus_status = {"connected": False, "collections": 0}
    try:
        store = get_milvus_store("sop_collection")
        milvus_status = {"connected": True, "collections": 4}
    except Exception:
        pass

    # 检查 OpenAI API（LLM）
    openai_status = {"connected": False, "model": agent_settings.OPENAI_LLM_MODEL}
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{agent_settings.OPENAI_BASE_URL}/models",
                headers={"Authorization": f"Bearer {agent_settings.OPENAI_API_KEY}"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                openai_status = {
                    "connected": True,
                    "model": agent_settings.OPENAI_LLM_MODEL,
                }
    except Exception:
        pass

    return {
        "status": "ok",
        "milvus": milvus_status,
        "openai_llm": openai_status,
    }
