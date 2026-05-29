"""Agent 微服务入口（FastAPI）— 逐条独立流水线"""
import json
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.workflow import agent_workflow
from app.state import AgentState, new_decision_id
from app.config import agent_settings
from app.utils.llm import get_llm
from app.utils.milvus_client import get_milvus_store, write_to_standard
from app.prompts.templates import CHAT_SYSTEM_PROMPT

app = FastAPI(title="Canteen Agent Engine", version="3.0.0")


class ReviewInput(BaseModel):
    raw_reviews: List[Dict]


class ChatInput(BaseModel):
    question: str


class ReviewResult(BaseModel):
    decision_id: Optional[str] = None
    dish_name: str
    dish_id: str
    corrective_action: Optional[str] = None
    human_review_required: bool


@app.post("/agent/analyze")
async def analyze_reviews(input_data: ReviewInput) -> List[ReviewResult]:
    """逐条处理：每条评论独立走 cleansing→routing→rag→report"""
    results = []

    for review in input_data.raw_reviews:
        decision_id = ""  # 只有差评才分配

        initial_state: AgentState = {
            "review": review,
            "filtered_review": {},
            "dish_info": {},
            "risk_level": 1,
            "knowledge_context": "",
            "decision_id": decision_id,
            "corrective_action": None,
            "human_review_required": False,
        }

        try:
            result = await agent_workflow.ainvoke(initial_state)
            corrective_action = result.get("corrective_action")
            dish_info = result.get("dish_info", {})

            # 只对差评生成 decision_id + 入库
            if corrective_action:
                decision_id = new_decision_id()
                dish_name = dish_info.get("dish_name", "未知菜品")
                asyncio.create_task(
                    write_to_standard(decision_id, dish_name, corrective_action)
                )

            results.append(ReviewResult(
                decision_id=decision_id or None,
                dish_name=dish_info.get("dish_name", "未知菜品"),
                dish_id=str(dish_info.get("dish_id", "UNKNOWN")),
                corrective_action=corrective_action,
                human_review_required=result.get("human_review_required", False),
            ))
        except Exception:
            results.append(ReviewResult(
                decision_id=None,
                dish_name="处理失败",
                dish_id="UNKNOWN",
                corrective_action=None,
                human_review_required=True,
            ))

    return results


@app.post("/agent/chat")
async def agent_chat(input_data: ChatInput):
    """智能问答（SSE 流式 + 双库 RAG）"""
    from fastapi.responses import StreamingResponse
    from app.utils.milvus_client import search_with_score

    async def event_stream():
        try:
            gold_results = await search_with_score("gold_collection", input_data.question, k=2)
            standard_results = await search_with_score("standard_collection", input_data.question, k=2)

            experience_context = ""
            if gold_results:
                experience_context += "\n【🏅 金标经验】\n"
                for r in gold_results:
                    experience_context += f"[GOLD] {r['content'][:400]}\n"
            if standard_results:
                experience_context += "\n【📋 普通经验】\n"
                for r in standard_results:
                    experience_context += f"[STANDARD] {r['content'][:400]}\n"

            system_prompt = CHAT_SYSTEM_PROMPT
            if experience_context:
                system_prompt += f"\n\n当前查询到的历史经验：{experience_context}"

            llm = get_llm()
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
    return {"status": "ok"}
