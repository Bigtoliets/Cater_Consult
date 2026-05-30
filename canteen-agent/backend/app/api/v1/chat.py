"""智能问答 API（SSE 流式）—— 对接 Agent 双库 RAG 检索链路"""
import json
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.utils.llm import get_llm
from app.agent.prompts.templates import CHAT_SYSTEM_PROMPT

router = APIRouter()

GOLD_WEIGHT = 0.7
STANDARD_WEIGHT = 0.3


@router.post("/query")
async def chat_query(question: str = Query(..., description="用户问题")):
    from app.agent.utils.milvus_client import search_with_score

    async def event_stream():
        try:
            gold_results = await search_with_score("gold_collection", question, k=2)
            standard_results = await search_with_score("standard_collection", question, k=2)

            all_items = []
            for r in gold_results:
                all_items.append({"content": r["content"], "score": r["score"], "source": "GOLD", "w": r["score"] * GOLD_WEIGHT})
            for r in standard_results:
                all_items.append({"content": r["content"], "score": r["score"], "source": "STANDARD", "w": r["score"] * STANDARD_WEIGHT})
            all_items.sort(key=lambda x: x["w"], reverse=True)

            experience_context = ""
            if all_items:
                experience_context = "\n\n历史品控经验（已按权重重排序）：\n"
                for i, item in enumerate(all_items, 1):
                    tag = "🏅金标" if item["source"] == "GOLD" else "📋普通"
                    experience_context += f"\n{i}. [{tag}] [加权分{item['w']:.2f}]\n{item['content'][:500]}\n"

            system_prompt = CHAT_SYSTEM_PROMPT
            if experience_context:
                system_prompt += f"\n{experience_context}\n\n请在回答中引用相关历史经验时注明来源（金标/普通）。"

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
async def get_presets():
    return {
        "presets": [
            "今天哪些菜品差评最多？分析一下原因",
            "上次红烧肉的整改方案有效果吗？",
            "最近一周卫生问题的趋势怎么样？",
            "对比一下所有档口的差评率排名",
            "昨天收到的客诉中包含哪些安全风险？",
            "为什么将上次红烧肉的方案设为金标？",
        ]
    }
