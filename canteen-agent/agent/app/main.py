"""Agent 微服务入口 v4.0 — ReAct引擎 + 工具系统 + 记忆管理 + 幻觉防护"""
import json
import asyncio
import re
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.workflow import agent_workflow
from app.state import AgentState, new_decision_id
from app.utils.llm import get_llm
from app.utils.milvus_client import write_to_standard
from app.utils.hallucination import get_detector, HallucinationDetector
from app.tools import register_all_tools, get_tool_registry
from app.react.engine import ReActEngine
from app.memory.manager import get_or_create_memory
from app.prompts.templates import CHAT_SYSTEM_PROMPT
from app.prompts.react_prompts import CHAT_SYSTEM_PROMPT_V4, REACT_FEW_SHOT

app = FastAPI(title="Canteen Agent Engine", version="4.1.0")

# ── 启动时注册所有工具 ──
@app.on_event("startup")
async def startup():
    register_all_tools()
    print(f"[Agent v4.0] 已启动，{len(get_tool_registry().get_all())} 个工具可用")


class DishAnalyzeInput(BaseModel):
    dish_name: str
    dish_id: str
    reviews: List[Dict]
    keyword_weights: Optional[Dict[str, float]] = None
    persist: bool = True  # 分片分析时传 False，等合并后再统一沉淀


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
    """v4.0: 流水线分析 + 幻觉检测 + 自动事实核查"""
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

        # ── v4.0: 幻觉检测 ──
        detector = get_detector()
        h_report = detector.check(
            detail + summary,
            context={"dish_name": input_data.dish_name},
        )
        if h_report.has_hallucination:
            # 附加幻觉警告到输出
            warning = f"\n\n⚠️ **幻觉检测警告** (风险: {h_report.risk_level}):\n"
            warning += "\n".join(f"- {i}" for i in h_report.issues[:3])
            detail += warning
            print(f"[Hallucination] {input_data.dish_name}: {h_report.risk_level} - {len(h_report.issues)} issues")

        decision_id = ""
        if detail and input_data.persist:
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
            human_review_required=result.get("human_review_required", False) or h_report.has_hallucination,
        )
    except Exception as e:
        print(f"[analyze_dish] 异常: {e}")
        return DishAnalyzeResult(
            dish_name=input_data.dish_name,
            dish_id=input_data.dish_id,
            decision_id=None,
            improvement_summary=None,
            improvement_detail=None,
            human_review_required=True,
        )


class MergeInput(BaseModel):
    dish_name: str
    dish_id: str
    chunks: List[Dict]  # [{improvement_summary, improvement_detail, human_review_required}]


MERGE_SYSTEM_PROMPT = """你是后厨品控指导专家。以下是对同一菜品「{dish_name}」的多个分片分析结果（每个分片分析了部分顾客评价）。请把它们合并成一份最终整改单。

要求：
1. 去重：相同或重复的整改建议合并为一条
2. 归纳：把零散的分片摘要归纳成一句核心问题
3. 完整：覆盖所有分片中提到的重要问题
4. 严格按以下格式输出，不要展开废话：

【一句话摘要】
[一句话概括核心问题和根本原因，30字以内]

【改进建议】
1. [具体可执行步骤]
2. [具体可执行步骤]
3. [具体可执行步骤]
"""


def _parse_summary_detail(full_text: str) -> tuple[str, str]:
    """从 LLM 输出解析 【一句话摘要】 和 【改进建议】"""
    summary = ""
    detail = ""
    m = re.search(r'【一句话摘要】\s*\n?(.*?)(?:\n【改进建议】|\Z)', full_text, re.DOTALL)
    if m:
        summary = m.group(1).strip()
        detail_start = full_text.find("【改进建议】")
        detail = full_text[detail_start:].strip() if detail_start != -1 else full_text
    else:
        lines = full_text.strip().split("\n")
        summary = lines[0].replace("【一句话摘要】", "").strip() if lines else full_text[:50]
        detail = full_text
    return summary, detail


@app.post("/agent/merge_dish")
async def merge_dish(input_data: MergeInput):
    """把同一菜品的多个分片分析结果合并成一份最终整改单（并沉淀到 Milvus）"""
    chunks = input_data.chunks or []
    if not chunks:
        return {
            "dish_name": input_data.dish_name,
            "dish_id": input_data.dish_id,
            "decision_id": None,
            "improvement_summary": None,
            "improvement_detail": None,
            "human_review_required": False,
        }

    # 单分片：直接透传，不额外调 LLM
    if len(chunks) == 1:
        summary = chunks[0].get("improvement_summary", "")
        detail = chunks[0].get("improvement_detail", "")
        human_review = bool(chunks[0].get("human_review_required", False))
    else:
        chunk_text = "\n\n".join(
            f"### 分片 {i}\n摘要：{c.get('improvement_summary', '')}\n建议：{c.get('improvement_detail', '')}"
            for i, c in enumerate(chunks, 1)
        )
        prompt = MERGE_SYSTEM_PROMPT.format(dish_name=input_data.dish_name) + f"\n\n{chunk_text}"
        llm = get_llm()
        result = await llm.ainvoke(prompt)
        summary, detail = _parse_summary_detail(result.content)
        human_review = any(bool(c.get("human_review_required", False)) for c in chunks)

    # 幻觉检测
    detector = get_detector()
    h_report = detector.check(detail + summary, context={"dish_name": input_data.dish_name})
    if h_report.has_hallucination:
        warning = f"\n\n⚠️ **幻觉检测警告** (风险: {h_report.risk_level}):\n"
        warning += "\n".join(f"- {i}" for i in h_report.issues[:3])
        detail += warning

    # 生成 decision_id + 沉淀到 Milvus
    decision_id = ""
    if detail:
        decision_id = new_decision_id()
        content_to_store = f"【菜品：{input_data.dish_name}】{summary}\n\n{detail}"
        asyncio.create_task(
            write_to_standard(decision_id, input_data.dish_name, content_to_store)
        )

    return {
        "dish_name": input_data.dish_name,
        "dish_id": input_data.dish_id,
        "decision_id": decision_id or None,
        "improvement_summary": summary or None,
        "improvement_detail": detail or None,
        "human_review_required": human_review or h_report.has_hallucination,
    }


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
    """v4.0: ReAct 引擎驱动 — Think→Act→Observe 循环 + 记忆管理 + 幻觉防护"""
    from fastapi.responses import StreamingResponse

    async def event_stream():
        try:
            # ── 创建会话记忆 ──
            session_id = "default"
            memory = get_or_create_memory(session_id)
            memory.add_message("user", input_data.question)

            # ── 初始化 ReAct 引擎 ──
            registry = get_tool_registry()
            engine = ReActEngine(
                tool_registry=registry,
                memory=memory,
                max_iterations=5,
                min_confidence=0.5,
            )

            # 发送思考中状态
            yield f"data: {json.dumps({'status': 'thinking', 'content': '🔍 正在分析您的问题...'})}\n\n"

            # 执行 ReAct 循环
            result = await engine.run(input_data.question, session_id=session_id)

            # ── 幻觉检测 ──
            detector = get_detector()
            h_report = detector.check(result.answer, context={"question": input_data.question})

            # 构建最终输出
            final_content = result.answer

            # 附加元信息
            meta_parts = []
            if result.tools_called:
                meta_parts.append(f"🔧 调用了 {len(result.tools_called)} 个工具: {', '.join(result.tools_called)}")
            if result.sources:
                meta_parts.append(f"📚 来源: {', '.join(set(result.sources))}")
            meta_parts.append(f"📊 置信度: {result.confidence:.0%}")
            if h_report.has_hallucination:
                meta_parts.append(f"⚠️ 幻觉风险: {h_report.risk_level}")

            final_content += "\n\n---\n" + "\n".join(meta_parts)

            # 存储助手回复到记忆
            memory.add_message("assistant", final_content)

            # 流式输出最终答案 (分块模拟流式)
            chunk_size = 50
            for i in range(0, len(final_content), chunk_size):
                chunk = final_content[i:i + chunk_size]
                yield f"data: {json.dumps({'content': chunk})}\n\n"
                await asyncio.sleep(0.01)  # 模拟流式延迟

            yield f"data: {json.dumps({'done': True, 'confidence': result.confidence, 'tools': result.tools_called})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agent/chat_react")
async def agent_chat_react(input_data: ChatInput):
    """ReAct 模式对话 (非流式, 返回完整结果含步骤)"""
    session_id = "default"
    memory = get_or_create_memory(session_id)
    memory.add_message("user", input_data.question)

    registry = get_tool_registry()
    engine = ReActEngine(
        tool_registry=registry,
        memory=memory,
        max_iterations=5,
        min_confidence=0.5,
    )

    result = await engine.run(input_data.question, session_id=session_id)

    # 幻觉检测
    detector = get_detector()
    h_report = detector.check(result.answer, context={"question": input_data.question})

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
            {
                "thought": s.thought[:200],
                "action": s.action,
                "observation": s.observation[:300],
            }
            for s in result.steps
        ],
    }


@app.get("/agent/health")
async def health_check():
    return {"status": "ok"}
