"""Supervisor 路由 / 护栏离线自测

用桩替换 LLM 与各业务节点，只测决策逻辑本身，不需要 Redis / Milvus / LLM：

    python tests/test_supervisor_routing.py

覆盖的契约：
- LLM 可用 / 不可用 / 乱输出 / 一段文本里多个 JSON，四种情况都能走完
- 依赖顺序：跳步的委派会被驳回并回退到确定性链路
- 两段式审核：结论预审（audit）+ 整改单终审（report_audit），终审对象是要交付的文本
- 打回只打回「真的能改」的 prescriber；分析结论不过不再打回（确定性节点重跑同结果）
- 必须经过 reporter 且 reporter 表态（report_ok）才允许 FINISH
- 轮数上限强制收口，总步数有界
"""
import asyncio
import os
import sys
import types

# 让 app 包可导入（本文件在 tests/ 下）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，输出里的 ✅/❌ 会直接抛 UnicodeEncodeError 把测试挂掉
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 桩掉重依赖 ──────────────────────────────────────────────
def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_REPLY = {"text": ""}


class _FakeLLM:
    async def ainvoke(self, *a, **k):
        if isinstance(_REPLY["text"], Exception):
            raise _REPLY["text"]
        return types.SimpleNamespace(content=_REPLY["text"])


_stub("langchain_openai", ChatOpenAI=object, OpenAIEmbeddings=object)
_stub("app.utils.llm", get_llm=lambda *a, **k: _FakeLLM())
_stub("app.nodes.entity_extraction", entity_extraction=None)
_stub("app.nodes.signal_fusion", keyword_aggregation=None, DEFAULT_DIMENSION_WEIGHTS={})
_stub("app.nodes.llm_fusion", llm_fusion=None)
_stub("app.nodes.confidence", confidence_evaluation=None)
_stub("app.utils.multi_kb_retriever", multi_kb_search=None, format_kb_context=None)
_stub("app.utils.milvus_client", write_to_standard=None)

from app.agents import supervisor as S  # noqa: E402

PASSED, FAILED = [], []

# 直线链路：facts 未预填时走完一轮（含两段审核）的完整轨迹
LINEAR = [
    "extractor", "analyst", "auditor", "retriever",
    "prescriber", "auditor", "reporter", "FINISH",
]


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


def apply_worker(state, name, audit_passes=True, report_audit_passes=True):
    """模拟 Worker 执行后写入黑板的效果（写入键与真实节点保持一致）"""
    if name == "extractor":
        state["facts"] = {"dimension_stats": {"口味": {"count": 3}}}
    elif name == "analyst":
        state["analysis"] = {
            "summary": "分析结论",
            "conflicts": [{"dimension": "口味", "should_trigger": True, "reason": "多人一致反馈"}],
        }
    elif name == "auditor":
        if (state.get("improvement_detail") or "").strip():
            state["report_audit"] = {           # 第二段：终审整改单
                "passed": report_audit_passes,
                "scope": "report",
                "score": 1.0 if report_audit_passes else 0.4,
                "issues": [] if report_audit_passes else ["整改单只列出 1 条步骤"],
                "revision": state.get("improvement_revision") or 0,
            }
            state["review_notes"] = [] if report_audit_passes else ["整改单只列出 1 条步骤"]
        else:
            state["audit"] = {                  # 第一段：预审分析结论
                "passed": audit_passes,
                "scope": "analysis",
                "score": 1.0 if audit_passes else 0.4,
                "issues": [] if audit_passes else ["结论缺少证据"],
            }
            state["review_notes"] = [] if audit_passes else ["结论缺少证据"]
    elif name == "retriever":
        state["reranked_knowledge"] = "（知识库结果）"
        state["retrieved"] = True
        state["retrieval_ok"] = True
    elif name == "prescriber":
        state["improvement_detail"] = "【改进建议】\n1. 复检\n2. 复称"
        state["confidence_score"] = 0.72
        state["improvement_revision"] = (state.get("improvement_revision") or 0) + 1
    elif name == "reporter":
        state["report_ok"] = bool((state.get("improvement_detail") or "").strip())


async def drive(initial, audit_passes=True, report_audit_passes=True, limit=30):
    """驱动 supervisor 循环，返回 (路由轨迹, 最终状态)"""
    state = dict(initial)
    trace = []
    for _ in range(limit):
        upd = await S.supervisor_node(state)
        state = {**state, **upd}          # 模拟 langgraph 无 reducer 的浅合并
        nxt = upd["next_worker"]
        trace.append(nxt)
        if nxt == S.ROUTE_FINISH:
            break
        apply_worker(state, nxt, audit_passes, report_audit_passes)
    return trace, state


async def main():
    print("\n[1] LLM 不可用 → 降级 rule_fallback 直线链路")
    _REPLY["text"] = RuntimeError("llm down")
    trace, state = await drive({})
    check("直线走完全流程后 FINISH", trace == LINEAR, f"实际: {trace}")
    check("质检报告已产出", state.get("report_ok") is True)

    print("\n[2] LLM 乱输出 → 同样降级，不抛异常")
    _REPLY["text"] = "我觉得应该先分析一下（没有 JSON）"
    trace, _ = await drive({})
    check("乱输出被兜底接住并走完", trace[-1] == "FINISH", f"实际: {trace}")

    print("\n[3] LLM 想跳过流程直接 FINISH → 被护栏拉回确定性链路")
    _REPLY["text"] = '{"next": "FINISH", "instruction": "", "reason": "我懒"}'
    trace, _ = await drive({})
    check("不许空手结束，先补结构化事实", trace[0] == "extractor", f"实际: {trace}")
    check("最终仍然产出了报告", trace[-2:] == ["reporter", "FINISH"], f"实际: {trace}")

    print("\n[4] LLM 给出非法路由名 + 输出里混了多个 JSON")
    _REPLY["text"] = '{"next": "superman", "reason": "瞎写"}\n{"next": "analyst"}'
    trace, _ = await drive({})
    check("非法目标回退到 extractor", trace[0] == "extractor", f"实际: {trace}")

    print("\n[5] 分析结论预审不通过 → 不再打回（重跑同结果），带人工复核标记走完")
    _REPLY["text"] = RuntimeError("llm down")
    trace, state = await drive({}, audit_passes=False)
    check("确定性的 analyst 只跑一次", trace.count("analyst") == 1, f"实际: {trace}")
    check("extractor 不参与无效重做", trace.count("extractor") == 1, f"实际: {trace}")
    check("仍走完并标记人工复核",
          trace[-1] == "FINISH" and state.get("human_review_required") is True,
          f"trace={trace} human_review={state.get('human_review_required')}")

    print("\n[6] 整改单终审不通过 → 打回 prescriber 重写，预算用尽后收口")
    _REPLY["text"] = RuntimeError("llm down")
    trace, state = await drive({}, report_audit_passes=False)
    check("prescriber 最多被调 2 次（初版 + 1 次重写）",
          trace.count("prescriber") == S.MAX_WORKER_ATTEMPTS, f"实际: {trace}")
    check("重写后重新送审（终审跑 2 次）", trace.count("auditor") == 3, f"实际: {trace}")
    check("预算用尽仍带人工复核收口",
          trace[-1] == "FINISH" and state.get("human_review_required") is True,
          f"trace={trace}")
    check("总步数不超过护栏上限", len(trace) <= S.MAX_STEPS, f"实际: {len(trace)}")

    print("\n[7] 轮数上限 → 强制收口，不会无限转")
    _REPLY["text"] = '{"next": "analyst", "instruction": "", "reason": "死循环诱惑"}'
    trace, _ = await drive({"max_steps": 3})
    check("轮数到顶后收口且总步数有界",
          trace[-1] == "FINISH" and len(trace) <= 3 + 2, f"实际: {trace}")
    check("LLM 反复要同一个 Worker 也撞得到次数上限",
          trace.count("analyst") <= S.MAX_WORKER_ATTEMPTS, f"analyst={trace.count('analyst')}")

    print("\n[8] 跳步：分析结论还没预审就想开整改单 → 被驳回")
    _REPLY["text"] = '{"next": "extractor", "instruction": "", "reason": "先提取"}'
    state = {}
    upd = await S.supervisor_node(state)
    state = {**state, **upd}
    apply_worker(state, "extractor")
    _REPLY["text"] = '{"next": "analyst", "instruction": "", "reason": "分析"}'
    upd = await S.supervisor_node(state)
    state = {**state, **upd}
    apply_worker(state, "analyst")
    _REPLY["text"] = '{"next": "prescriber", "instruction": "直接出方案", "reason": "想省一步"}'
    upd = await S.supervisor_node(state)
    check("prescriber 前置未满足 → 被改判 auditor",
          upd["next_worker"] == "auditor", f"实际: {upd['next_worker']}")
    check("被改写时原指令不再透传", "prescriber" not in (upd.get("instructions") or {}))

    print("\n[9] 简单客诉可跳过 retriever（LLM 动态决策生效）")
    _REPLY["text"] = '{"next": "auditor", "instruction": "", "reason": "先审结论"}'
    upd = await S.supervisor_node(state)
    state = {**state, **upd}
    apply_worker(state, "auditor")
    _REPLY["text"] = '{"next": "prescriber", "instruction": "简单客诉，不必查库", "reason": "直接出方案"}'
    upd = await S.supervisor_node(state)
    check("retriever 被跳过", upd["next_worker"] == "prescriber", f"实际: {upd['next_worker']}")
    check("定向指令被记录",
          (upd.get("instructions") or {}).get("prescriber") == "简单客诉，不必查库")

    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
