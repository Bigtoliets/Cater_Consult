"""Agent 微服务入口 —— ReAct 问答 + 调试端点

分析链路的线上入口是 app.consumer（Redis Stream 消费），本服务只保留这些端点：

    POST /agent/chat        智能问答（SSE，backend /api/v1/chat/query 透传）
    POST /agent/chat_react  同上的非流式版本（调试用，返回完整推理步骤）
    POST /agent/merge_dish  菜品级 Supervisor-Worker 调试入口
    POST /agent/promote     经验飞升金标（backend 调用）
    GET  /agent/health
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Dict, List

from fastapi import FastAPI
from pydantic import BaseModel

from app.memory.manager import get_or_create_memory
from app.pipeline import run_dish_analysis
from app.react.engine import ReActEngine
from app.tools import get_tool_registry, register_all_tools
from app.utils.hallucination import get_detector

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时注册全部工具（供 ReAct 引擎调用）"""
    register_all_tools()
    logger.info(f"[Agent] 已启动，{len(get_tool_registry().get_all())} 个工具可用")
    yield


app = FastAPI(title="Canteen Agent Engine", version="4.1.0", lifespan=lifespan)


class ChatInput(BaseModel):
    question: str


class MergeInput(BaseModel):
    dish_name: str
    dish_id: str
    chunks: List[Dict]  # 分片级产物：[{facts, reviews, keyword_weights}]


class PromoteInput(BaseModel):
    decision_id: str
    modified_content: str | None = None


def _build_engine() -> ReActEngine:
    return ReActEngine(
        tool_registry=get_tool_registry(),
        memory=get_or_create_memory("default"),
        max_iterations=5,
        min_confidence=0.5,
    )


@app.post("/agent/merge_dish")
async def merge_dish(input_data: MergeInput):
    """菜品级深度加工（Supervisor-Worker）—— 手动调试用

    线上链路由 app.consumer 直接调用 pipeline.run_dish_analysis。
    """
    return await run_dish_analysis(
        input_data.dish_name,
        input_data.dish_id,
        input_data.chunks or [],
        persist=True,
    )


@app.post("/agent/promote")
async def agent_promote(input_data: PromoteInput):
    """飞升金标：从 standard_collection 迁移到 gold_collection"""
    from app.utils.milvus_client import promote_to_gold

    return await promote_to_gold(input_data.decision_id, input_data.modified_content)


@app.post("/agent/chat")
async def agent_chat(input_data: ChatInput):
    """ReAct 引擎驱动：Think→Act→Observe 循环 + 记忆 + 幻觉防护（SSE 流式）"""
    from fastapi.responses import StreamingResponse

    async def event_stream():
        try:
            memory = get_or_create_memory("default")
            memory.add_message("user", input_data.question)
            engine = _build_engine()

            yield f"data: {json.dumps({'status': 'thinking', 'content': '🔍 正在分析您的问题...'})}\n\n"

            result = await engine.run(input_data.question, session_id="default")
            h_report = get_detector().check(
                result.answer, context={"question": input_data.question}
            )

            final_content = result.answer
            meta_parts = []
            if result.tools_called:
                meta_parts.append(
                    f"🔧 调用了 {len(result.tools_called)} 个工具: {', '.join(result.tools_called)}"
                )
            if result.sources:
                meta_parts.append(f"📚 来源: {', '.join(set(result.sources))}")
            meta_parts.append(f"📊 置信度: {result.confidence:.0%}")
            if h_report.has_hallucination:
                meta_parts.append(f"⚠️ 幻觉风险: {h_report.risk_level}")
            final_content += "\n\n---\n" + "\n".join(meta_parts)

            memory.add_message("assistant", final_content)

            # 分块输出，前端拿到的是 SSE data 帧
            for i in range(0, len(final_content), 50):
                yield f"data: {json.dumps({'content': final_content[i:i + 50]})}\n\n"
                await asyncio.sleep(0.01)

            yield f"data: {json.dumps({'done': True, 'confidence': result.confidence, 'tools': result.tools_called})}\n\n"

        except Exception as e:  # noqa: BLE001 — 流里出错也要给前端一个可读的结束帧
            logger.exception("[Agent] /agent/chat 异常")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agent/chat_react")
async def agent_chat_react(input_data: ChatInput):
    """ReAct 问答的非流式版本（返回完整推理步骤，调试用）"""
    memory = get_or_create_memory("default")
    memory.add_message("user", input_data.question)

    result = await _build_engine().run(input_data.question, session_id="default")
    h_report = get_detector().check(result.answer, context={"question": input_data.question})
    memory.add_message("assistant", result.answer)

    return {
        "answer": result.answer,
        "confidence": result.confidence,
        "iterations": result.total_iterations,
        "tools_called": result.tools_called,
        "sources": result.sources,
        "hallucination_risk": h_report.risk_level,
        "hallucination_issues": h_report.issues[:5],
        "steps": [
            {"thought": s.thought[:200], "action": s.action, "observation": s.observation[:300]}
            for s in result.steps
        ],
    }


@app.get("/agent/health")
async def health_check():
    return {"status": "ok"}
