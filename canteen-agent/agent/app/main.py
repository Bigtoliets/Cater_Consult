"""Agent 微服务入口（FastAPI）—— 菜品级批量处理 + 自进化闭环"""
import json
import asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.workflow import agent_workflow
from app.state import AgentState, new_decision_id
from app.utils.llm import get_llm
from app.utils.milvus_client import write_to_standard
from app.prompts.templates import CHAT_SYSTEM_PROMPT

app = FastAPI(title="Canteen Agent Engine", version="4.1.0")


class DishAnalyzeInput(BaseModel):
    dish_name: str
    dish_id: str
    reviews: List[Dict]
    keyword_weights: Optional[Dict[str, float]] = None


class DishAnalyzeResult(BaseModel):
    dish_name: str
    dish_id: str
    decision_id: Optional[str] = None
    improvement_summary: Optional[str] = None
    improvement_detail: Optional[str] = None
    human_review_required: bool


class ChatInput(BaseModel):
    question: str


@app.post("/agent/analyze_dish")
async def analyze_dish(input_data: DishAnalyzeInput) -> DishAnalyzeResult:
    initial_state: AgentState = {
        "dish_name": input_data.dish_name,
        "dish_id": input_data.dish_id,
        "reviews": input_data.reviews,
        "keyword_summary": "",
        "keyword_weights": input_data.keyword_weights or {},
        "gold_context": "",
        "standard_context": "",
        "reranked_knowledge": "",
        "improvement_summary": "",
        "improvement_detail": "",
        "decision_id": "",
        "human_review_required": False,
    }

    try:
        result = await agent_workflow.ainvoke(initial_state)
        summary = result.get("improvement_summary", "")
        detail = result.get("improvement_detail", "")

        decision_id = ""
        if detail:
            decision_id = new_decision_id()
            content_to_store = f"【菜品：{input_data.dish_name}】{summary}\n\n{detail}"
            asyncio.create_task(
                write_to_standard(decision_id, input_data.dish_name, content_to_store)
            )

        return DishAnalyzeResult(
            dish_name=input_data.dish_name,
            dish_id=input_data.dish_id,
            decision_id=decision_id or None,
            improvement_summary=summary or None,
            improvement_detail=detail or None,
            human_review_required=result.get("human_review_required", False),
        )
    except Exception:
        return DishAnalyzeResult(
            dish_name=input_data.dish_name,
            dish_id=input_data.dish_id,
            decision_id=None,
            improvement_summary=None,
            improvement_detail=None,
            human_review_required=True,
        )


class PromoteInput(BaseModel):
    decision_id: str
    modified_content: str | None = None


@app.post("/agent/promote")
async def agent_promote(input_data: PromoteInput):
    """飞升金标：从 standard_collection 迁移到 gold_collection"""
    from app.utils.milvus_client import promote_to_gold
    return await promote_to_gold(input_data.decision_id, input_data.modified_content)


@app.post("/agent/chat")
async def agent_chat(input_data: ChatInput):
    from fastapi.responses import StreamingResponse
    from app.utils.milvus_client import search_with_score

    GOLD_W = 0.7
    STD_W = 0.3

    async def event_stream():
        try:
            gold_results = await search_with_score("gold_collection", input_data.question, k=2)
            standard_results = await search_with_score("standard_collection", input_data.question, k=2)
            print(f"[Chat] 问题: {input_data.question[:50]} | gold={len(gold_results)} standard={len(standard_results)}")

            all_items = []
            for r in gold_results:
                all_items.append({"content": r["content"], "score": r["score"], "source": "GOLD", "w": r["score"] * GOLD_W})
            for r in standard_results:
                all_items.append({"content": r["content"], "score": r["score"], "source": "STANDARD", "w": r["score"] * STD_W})
            all_items.sort(key=lambda x: x["w"], reverse=True)

            experience_context = ""
            if all_items:
                experience_context += "\n历史经验（按权重重排序）：\n"
                for item in all_items:
                    tag = "🏅金标" if item["source"] == "GOLD" else "📋普通"
                    experience_context += f"[{tag}] [加权分{item['w']:.2f}] {item['content'][:400]}\n"

            system_prompt = CHAT_SYSTEM_PROMPT
            if experience_context:
                system_prompt += f"\n\n当前查询到的历史经验：{experience_context}"
            else:
                system_prompt += "\n\n⚠️ 当前向量库中暂无相关历史决策数据，请如实告知用户暂无记录，不要编造。"

            llm = get_llm()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_data.question},
            ]

            async for chunk in llm.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'content': chunk.content})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/agent/health")
async def health_check():
    return {"status": "ok"}
