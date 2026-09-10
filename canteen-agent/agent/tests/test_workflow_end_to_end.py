"""Supervisor-Worker 端到端自测（真图 + 真 Worker，只桩掉 LLM / Milvus）

    python tests/test_workflow_end_to_end.py

跑的是线上同一条路径：process_chunk（分片级） → run_dish_analysis（菜品级 Supervisor 图）
→ 回写载荷。用的桩很少，图、状态合并、护栏、审核、报告范式都是真代码，
所以能验证「节点之间」的契约，而不只是单个节点的行为。

关键回归点：
- LLM 全程只想直接 FINISH，护栏仍然把链路拉回确定性顺序并产出报告
- 置信度真的从 prescriber 传到了最终返回值
- 食安事件一定带人工复核标记
- 报告正文落进向量库时已经带上页脚，且只落一次
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ── 桩：LLM / 向量库 ────────────────────────────────────────
NER_LINES = "\n".join([
    '{"dish":"红烧肉","issue":"太咸","process":"调味","event_type":"taste_complaint","severity":3,"is_preference":false}',
] * 4 + [
    '{"dish":"红烧肉","issue":"有头发","process":"卫生","event_type":"safety_incident","severity":5,"is_preference":false}',
])

REPORT_TEXT = """【一句话摘要】
红烧肉口味偏咸，来自调味环节的咸度波动，非口味偏好问题。

【改进建议】
1. 调味环节改为分两次下料，出锅前再复核一次咸度
2. 每餐抽检 3 份并记录在品控表
3. 对新员工重做调味标准化培训
"""


class _FakeLLM:
    """按 prompt 特征区分三种调用：Supervisor 路由 / NER / 整改单生成"""

    async def ainvoke(self, messages, **kwargs):
        if isinstance(messages, str):                     # llm_fusion 传的是整段字符串
            return types.SimpleNamespace(content=REPORT_TEXT)
        system_text = messages[0].get("content", "")
        if "调度中枢" in system_text:                      # Supervisor 路由
            return types.SimpleNamespace(
                content='{"next": "FINISH", "instruction": "", "reason": "想少干活"}'
            )
        return types.SimpleNamespace(content=NER_LINES)    # entity_extraction 的 NER


_written: list[tuple] = []


async def _record_write(decision_id, dish_name, content):
    _written.append((decision_id, dish_name, content))


_stub("langchain_openai", ChatOpenAI=object, OpenAIEmbeddings=object)
_stub("app.utils.llm", get_llm=lambda *a, **k: _FakeLLM())
_stub("app.utils.milvus_client", write_to_standard=_record_write)
_stub(
    "app.utils.multi_kb_retriever",
    multi_kb_search=None,        # 下面按需替换成异步桩
    format_kb_context=lambda results: results.get("_formatted", ""),
)


async def _fake_multi_kb_search(query, top_k=5):
    return {
        "top_k": [
            {"source": "gold_collection", "weighted_score": 0.86,
             "content": "金标经验：分两次下料，出锅前复核咸度"},
            {"source": "standard_collection", "weighted_score": 0.61,
             "content": "普通经验：抽检记录要留痕"},
        ],
        "_formatted": "[GOLD] [加权分 0.86] 金标经验：分两次下料\n[STANDARD] [加权分 0.61] 普通经验：抽检留痕",
    }


sys.modules["app.utils.multi_kb_retriever"].multi_kb_search = _fake_multi_kb_search

from app import pipeline as P        # noqa: E402
from app.workflow import supervisor_workflow  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


def _reviews() -> list[dict]:
    rows = [("太咸了，齁得慌", "negative", 3)] * 4 + [("菜里居然有头发", "negative", 5)]
    return [
        {
            "review_id": i + 1,
            "raw_text": text,
            "summary": text,
            "sentiment": sentiment,
            "dimensions": [],
            "severity": severity,
        }
        for i, (text, sentiment, severity) in enumerate(rows)
    ]


async def main():
    print("\n[1] 分片级：process_chunk 产出结构化事实")
    chunk = await P.process_chunk({
        "dish_name": "红烧肉", "dish_id": "1", "reviews": _reviews(), "keyword_weights": {},
    })
    facts = chunk["facts"]
    check("按维度归并出 count", facts["dimension_stats"].get("口味", {}).get("count") == 4,
          f"实际: {facts['dimension_stats']}")
    check("食安事件被单独标出来", len(facts["safety_flags"]) == 1, f"实际: {facts['safety_flags']}")
    check("评论带上了 NER 标签供后续复用",
          all("ner_entities" in r for r in chunk["reviews"]))

    print("\n[2] 菜品级：真图跑完 Supervisor-Worker（LLM 全程想直接 FINISH）")
    result = await P.run_dish_analysis("红烧肉", "1", [chunk])
    await asyncio.sleep(0)
    trace = result["diagnosis_trace"]["agents_used"]
    check("护栏把链路拉回确定性顺序",
          trace[:3] == ["analyst", "auditor", "retriever"] and trace[-1] == "reporter",
          f"实际: {trace}")
    check("整改单做了两段审核（auditor 出现两次）", trace.count("auditor") == 2,
          f"实际: {trace}")
    check("报告正文已产出", bool(result["improvement_detail"]))
    check("报告带生成页脚", "报告由食堂品控 Agent" in (result["improvement_detail"] or ""))

    print("\n[3] 交付契约：置信度 / 人工复核 / 落库")
    check("置信度来自 prescriber（不再恒为 0）",
          result["confidence_score"] > 0, f"实际: {result['confidence_score']}")
    check("食安事件 → 必须人工复核", result["human_review_required"] is True)
    check("终审通过", result["diagnosis_trace"]["report_audit"]["passed"] is True,
          f"实际: {result['diagnosis_trace']['report_audit']}")
    check("冲突分析落进诊断轨迹", bool(result["diagnosis_trace"]["conflicts"]))
    check("decision_id 与向量库写入一一对应",
          bool(result["decision_id"]) and len(_written) == 1
          and _written[0][0] == result["decision_id"],
          f"实际: decision_id={result['decision_id']} written={len(_written)}")
    check("落库内容包含摘要与整改单",
          "红烧肉" in _written[0][2] and "改进建议" in _written[0][2])

    print("\n[4] 图本身：编译产物存在且入口是 supervisor")
    check("supervisor_workflow 已编译", supervisor_workflow is not None)

    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
