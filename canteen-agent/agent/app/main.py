"""Agent 微服务入口 —— ReAct 问答 + 调试端点

分析链路的线上入口是 app.consumer（Redis Stream 消费），本服务只保留这些端点：

    POST /agent/chat                智能问答（SSE，backend /api/v1/chat/query 透传）
    POST /agent/chat/resume/{id}    接着上次没跑完的 turn 继续（SSE）
    GET  /agent/chat/turns/{id}     只读轨迹/状态（排查 + 前端刷新后探测）
    POST /agent/chat_react          同上的非流式版本（调试用，返回完整推理步骤）
    POST /agent/merge_dish  菜品级 Supervisor-Worker 调试入口
    POST /agent/promote     经验飞升金标（backend 调用）
    GET  /agent/health
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.chat import (
    MAX_RESUME,
    STATUS_RUNNING,
    TurnState,
    fallback_session_id,
    get_turn_store,
    new_turn_id,
    normalize_turn_id,
    validate_session_id,
)
from app.chat.trace import trace
from app.memory.manager import get_or_create_memory
from app.pipeline import run_dish_analysis
from app.react.engine import ReActEngine, TurnProtocolError
from app.tools import get_tool_registry, register_all_tools
from app.utils.hallucination import get_detector

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时注册全部工具（供 ReAct 引擎调用）"""
    register_all_tools()
    logger.info(f"[Agent] 已启动，{len(get_tool_registry().get_all())} 个工具可用")
    try:
        yield
    finally:
        await get_turn_store().aclose()  # 退掉 checkpoint 的 Redis 长连接


app = FastAPI(title="Canteen Agent Engine", version="4.1.0", lifespan=lifespan)


class ChatInput(BaseModel):
    question: str
    session_id: str | None = None   # 前端生成的会话 id；缺省由服务端兜底
    turn_id: str | None = None      # 前端生成的 turn id；缺省由服务端兜底（前端拿不到 → 不可恢复）


class MergeInput(BaseModel):
    dish_name: str
    dish_id: str
    chunks: List[Dict]  # 分片级产物：[{facts, reviews, keyword_weights}]


class PromoteInput(BaseModel):
    decision_id: str
    modified_content: str | None = None


def _build_engine(session_id: str) -> ReActEngine:
    return ReActEngine(
        tool_registry=get_tool_registry(),
        memory=get_or_create_memory(session_id),
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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _safe_save(store, state: TurnState) -> None:
    """落 checkpoint：失败只记日志，不把异常抛回请求（丢的是可恢复性，不是这次问答）"""
    try:
        await store.save(state)
    except Exception as exc:  # noqa: BLE001
        trace("checkpoint_failed", turn_id=state.turn_id, event="safe_save", error=str(exc)[:200])


@asynccontextmanager
async def _hold_lock(store, turn_id: str, token: str):
    """持锁跑推理并按 10s 续租：单次推理（最长 5 轮 × 20s 工具超时）远超锁的 30s TTL"""
    stop = asyncio.Event()

    async def _renew_loop():
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                break
            try:
                if not await store.renew_lock(turn_id, token):
                    trace("lock_lost", turn_id=turn_id)
                    return
            except Exception as exc:  # noqa: BLE001
                trace("lock_renew_failed", turn_id=turn_id, error=str(exc)[:200])

    task = asyncio.create_task(_renew_loop())
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=2)
        except Exception:  # noqa: BLE001 — 续租任务收尾失败不影响放锁
            task.cancel()
        await store.release_lock(turn_id, token)


async def _final_frames(question: str, session_id: str, result) -> AsyncIterator[str]:
    """幻觉检测 + 元信息页脚 + 分块推 SSE（保持与历史行为一致，前端渲染不用改）"""
    memory = get_or_create_memory(session_id)
    h_report = get_detector().check(result.answer, context={"question": question})

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

    for i in range(0, len(final_content), 50):
        yield _sse({"content": final_content[i:i + 50]})
        await asyncio.sleep(0.01)
    yield _sse({"done": True, "confidence": result.confidence, "tools": result.tools_called})


@app.post("/agent/chat")
async def agent_chat(input_data: ChatInput):
    """ReAct 引擎驱动：Think→Act→Observe 循环 + 记忆 + 幻觉防护（SSE 流式）

    turn_id / session_id 由前端生成并随请求带上；缺省时服务端兜底生成
    （照样落 checkpoint、出追踪日志，只是前端拿不到 id，断了就没法恢复）。
    """
    from fastapi.responses import StreamingResponse

    store = get_turn_store()
    session_id = validate_session_id(input_data.session_id) or fallback_session_id()
    turn_id = normalize_turn_id(input_data.turn_id) or new_turn_id()

    if input_data.turn_id:
        # 同一个 turn_id 重复 POST（双击 / 客户端重试）→ 让它走 resume，别起第二条推理
        try:
            existing = await store.load(turn_id)
        except Exception:  # noqa: BLE001 — Redis 抖了就当没有旧 turn，照常跑
            existing = None
        if existing is not None:
            return JSONResponse(
                {"error": "该 turn_id 已存在，请改用 /agent/chat/resume/{turn_id}",
                 "status": existing.status},
                status_code=409,
            )

    async def event_stream():
        try:
            memory = get_or_create_memory(session_id)
            memory.add_message("user", input_data.question)
            engine = _build_engine(session_id)

            yield _sse({"type": "turn", "turn_id": turn_id, "session_id": session_id, "resumed": False})
            yield _sse({"status": "thinking", "content": "🔍 正在分析您的问题..."})

            result, _state = await engine.run_turn(
                input_data.question, session_id, turn_id=turn_id, store=store
            )
            async for frame in _final_frames(input_data.question, session_id, result):
                yield frame

        except Exception as e:  # noqa: BLE001 — 流里出错也要给前端一个可读的结束帧
            logger.exception("[Agent] /agent/chat 异常")
            trace("turn_error", turn_id=turn_id, error=str(e)[:300])
            yield _sse({"type": "error", "turn_id": turn_id, "error": str(e), "resumable": True})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agent/chat/resume/{turn_id}")
async def agent_chat_resume(turn_id: str, session_id: str | None = None):
    """接着没跑完的 turn 继续：先补 pending 的工具调用，再用剩余额度往下跑

    409 = 已有恢复在跑；410 = 不存在 / 已过期 / 已终态 / 恢复次数超限。
    """
    from fastapi.responses import StreamingResponse

    store = get_turn_store()
    tid = normalize_turn_id(turn_id)
    if tid is None:
        return JSONResponse({"error": "turn_id 必须是 32/36 位 uuid"}, status_code=400)

    try:
        state = await store.load(tid)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"checkpoint 存储不可用: {exc}"}, status_code=503)

    if state is None:
        return JSONResponse({"error": "turn 不存在或已过期（checkpoint 保留 24h）"}, status_code=410)
    normalized_session = validate_session_id(session_id)
    if normalized_session and normalized_session != state.session_id:
        # 回 404 而不是 403：不告诉调用方「这个 turn 存在，只是不属于你」
        return JSONResponse({"error": "turn 不存在"}, status_code=404)
    if not state.resumable:
        # 已终态 / 恢复次数用尽：直接 410，不用去抢锁
        if state.status == STATUS_RUNNING:
            state.abandon(f"resume 次数超过上限 {MAX_RESUME}")
            await _safe_save(store, state)
        return JSONResponse(
            {"error": f"turn 已是 {state.status}，不能恢复",
             "status": state.status, "final_answer": state.final_answer},
            status_code=410,
        )

    token = await store.acquire_lock(state.turn_id)
    if token is None:
        return JSONResponse({"error": "该 turn 正在恢复中，请稍后再试"}, status_code=409)

    if not state.begin_resume():
        await _safe_save(store, state)
        await store.release_lock(state.turn_id, token)
        return JSONResponse(
            {"error": "恢复次数超过上限，已放弃该 turn", "status": state.status}, status_code=410
        )
    await _safe_save(store, state)  # resume_count 先落盘：重复触发不会重复计数

    async def event_stream():
        try:
            engine = _build_engine(state.session_id)
            yield _sse({
                "type": "resume",
                "turn_id": state.turn_id,
                "resumed": True,
                "completed_steps": len(state.steps),
                "remaining_iterations": state.remaining_iterations,
            })
            yield _sse({"status": "thinking", "content": "♻️ 正在接着上次的进度继续..."})

            async with _hold_lock(store, state.turn_id, token):
                result, _state = await engine.run_turn(
                    "", state.session_id, state=state, store=store
                )
                async for frame in _final_frames(state.question, state.session_id, result):
                    yield frame

        except TurnProtocolError as exc:
            # 消息链补不成合法结构：放弃这个 turn，前端提示重新提问
            state.abandon(str(exc))
            await _safe_save(store, state)
            trace("turn_abandoned", turn_id=state.turn_id, error=str(exc)[:300])
            yield _sse({"type": "error", "turn_id": state.turn_id, "error": str(exc), "abandoned": True})

        except Exception as exc:  # noqa: BLE001 — 状态留在 running，还能再恢复
            logger.exception("[Agent] /agent/chat/resume 异常")
            yield _sse({"type": "error", "turn_id": state.turn_id, "error": str(exc), "resumable": True})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/agent/chat/turns/{turn_id}")
async def agent_turn_status(turn_id: str, session_id: str | None = None):
    """只读轨迹：前端刷新后先探这里，决定「接着跑」还是「重新问」"""
    store = get_turn_store()
    try:
        state = await store.load(turn_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"checkpoint 存储不可用: {exc}"}, status_code=503)
    if state is None:
        return JSONResponse({"error": "turn 不存在或已过期（checkpoint 保留 24h）"}, status_code=410)
    normalized_session = validate_session_id(session_id)
    if normalized_session and normalized_session != state.session_id:
        return JSONResponse({"error": "turn 不存在"}, status_code=404)
    return state.summary()


@app.post("/agent/chat_react")
async def agent_chat_react(input_data: ChatInput):
    """ReAct 问答的非流式版本（返回完整推理步骤，调试用）—— 同样落 checkpoint / 出追踪"""
    store = get_turn_store()
    session_id = validate_session_id(input_data.session_id) or fallback_session_id()
    turn_id = normalize_turn_id(input_data.turn_id) or new_turn_id()

    memory = get_or_create_memory(session_id)
    memory.add_message("user", input_data.question)

    result, state = await _build_engine(session_id).run_turn(
        input_data.question, session_id, turn_id=turn_id, store=store
    )
    h_report = get_detector().check(result.answer, context={"question": input_data.question})
    memory.add_message("assistant", result.answer)

    return {
        "turn_id": state.turn_id,
        "session_id": session_id,
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
    """健康检查：顺带探一下 checkpoint 存储（问答的追踪与恢复都依赖它）"""
    checkpoint_ok = await get_turn_store().ping()
    return {"status": "ok", "checkpoint_store": "ok" if checkpoint_ok else "down"}
