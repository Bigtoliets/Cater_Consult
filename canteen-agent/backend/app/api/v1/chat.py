"""智能问答 API — 后端直接查双库 RAG"""
import json
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from app.agent.utils.llm import get_llm
from app.agent.utils.milvus_client import search_with_score
from app.agent.prompts.templates import CHAT_SYSTEM_PROMPT

router = APIRouter()


@router.post("/query")
async def chat_query(question: str = Query(..., description="用户问题")):
    """SSE 流式对话 — 后端直接查双库 RAG，无需经 Agent 微服务"""

    async def event_stream():
        try:
            # ── 双库检索历史经验 ──
            gold_results = await search_with_score("gold_collection", question, k=2)
            standard_results = await search_with_score("standard_collection", question, k=2)

            experience_context = ""
            if gold_results:
                experience_context += "\n【🏅 金标经验（管理层认证）】\n"
                for r in gold_results:
                    experience_context += f"[GOLD] [相似度 {r['score']:.2f}] {r['content'][:400]}\n"
            if standard_results:
                experience_context += "\n【📋 普通经验（仅供参考）】\n"
                for r in standard_results:
                    experience_context += f"[STANDARD] [相似度 {r['score']:.2f}] {r['content'][:400]}\n"

            system_prompt = CHAT_SYSTEM_PROMPT
            if experience_context:
                system_prompt += f"\n\n当前查询到的历史经验：{experience_context}"

            llm = get_llm()
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
            "最近红烧肉的客诉情况怎么样？",
            "上周有哪些菜品收到了集中差评？",
            "肉质发硬有什么金标整改经验？",
            "对比一下两个食堂的满意度趋势",
            "本周食品安全相关投诉汇总",
            "哪道菜的复发性差评最多？",
        ]
    }
