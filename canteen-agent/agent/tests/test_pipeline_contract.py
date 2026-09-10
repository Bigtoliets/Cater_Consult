"""菜品级交付契约离线自测（不需要 Redis / Milvus / LLM）

    python tests/test_pipeline_contract.py

盯的是「报告到底能不能交付」这条线，都是之前真实踩过的坑：
- reporter 不能把空正文拼个页脚就当报告
- 审核员两段式：审的不是模板摘要，而是真正要交付的整改单
- 终审没过的整改单必须能被识别为「过期/未通过」，并落到人工复核
- 置信度必须从 prescriber 一路传到 backend 回调（曾经恒为 0）
- 回调必须带上诊断轨迹，否则前端/复盘无从解释「为什么这么判」
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


# ── 桩掉重依赖 ──────────────────────────────────────────────
_written: list[tuple] = []
_posted: list[tuple] = []


async def _record_write(decision_id, dish_name, content):
    _written.append((decision_id, dish_name, content))


class _FakeGraph:
    """替掉编译好的 LangGraph：直接返回预设的最终状态"""

    def __init__(self, result: dict):
        self.result = result
        self.calls: list[tuple] = []

    async def ainvoke(self, state, config=None):
        self.calls.append((state, config))
        return self.result


_stub("langchain_openai", ChatOpenAI=object, OpenAIEmbeddings=object)
_stub("app.utils.llm", get_llm=lambda *a, **k: None)
_stub("app.nodes.entity_extraction", entity_extraction=None)
_stub("app.nodes.signal_fusion", keyword_aggregation=None, DEFAULT_DIMENSION_WEIGHTS={})
_stub("app.nodes.llm_fusion", llm_fusion=None)
_stub("app.nodes.confidence", confidence_evaluation=None)
_stub("app.utils.multi_kb_retriever", multi_kb_search=None, format_kb_context=None)
_stub("app.utils.milvus_client", write_to_standard=_record_write)
_stub("app.workflow", supervisor_workflow=None, RECURSION_LIMIT=40)

_redis_mod = _stub("redis")
_stub("redis.asyncio", from_url=lambda *a, **k: None)
_redis_mod.asyncio = sys.modules["redis.asyncio"]

from app.agents.auditor import auditor_node          # noqa: E402
from app.agents.reporter import reporter_node        # noqa: E402
from app import pipeline as P                        # noqa: E402
import app.consumer as C                             # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


GOOD_REPORT = """【一句话摘要】
红烧肉口味偏咸，来自调味环节的盐量波动。

【改进建议】
1. 出餐前用电子秤复核每份的盐量，按标准 5g 执行
2. 高压锅上汽后压制满 20 分钟再出锅，避免收汁过度
3. 每餐抽检 3 份并记录在品控表 (来源: SOP-红烧肉)
"""


def _facts(dim: str = "口味") -> dict:
    return {
        "dimension_stats": {dim: {"count": 4, "avg_severity": 3.0}},
        "safety_flags": [],
        "review_count": 12,
        "negative_count": 4,
    }


def _analysis(dim: str = "口味") -> dict:
    return {
        "summary": "红烧肉口味偏咸，多人一致反馈",
        "conflicts": [{
            "dimension": dim, "signal_type": "quality_fluctuation",
            "should_trigger": True, "reason": "多人一致反馈",
        }],
    }


async def test_reporter():
    print("\n[1] reporter：空正文拒发，有正文只加一次页脚")
    out = await reporter_node({"dish_name": "红烧肉"})
    check("空正文 → report_ok=False 且不产出 improvement_detail",
          out.get("report_ok") is False and "improvement_detail" not in out, f"实际: {out}")
    check("空正文 → 标人工复核", out.get("human_review_required") is True)

    state = {
        "dish_name": "红烧肉",
        "improvement_detail": GOOD_REPORT,
        "confidence_score": 0.72,
        "confidence_action": "publish_with_review",
        "agents_used": ["analyst", "prescriber", "reporter"],
        "audit": {"passed": True, "score": 1.0},
        "report_audit": {"passed": True, "score": 0.9, "warnings": ["未标注来源的数字参数: 5g"]},
    }
    out = await reporter_node(state)
    detail = out.get("improvement_detail", "")
    check("有正文 → report_ok=True", out.get("report_ok") is True)
    check("页脚带置信度与两段审核结论",
          "72%" in detail and "结论预审" in detail and "整改单终审" in detail)
    check("审核员的记录级提示被带出来", "5g" in detail)

    again = await reporter_node({"dish_name": "红烧肉", "improvement_detail": detail})
    check("重跑不叠加页脚",
          again == {"report_ok": True}, f"实际: {again}")


async def test_auditor():
    print("\n[2] auditor：两段式审核，对象不同、互不覆盖")
    out = await auditor_node({"facts": _facts(), "analysis": _analysis()})
    check("第一段审结论 → 写 audit(scope=analysis)",
          out["audit"]["scope"] == "analysis", f"实际: {out}")
    check("结论有事实支撑 → 通过", out["audit"]["passed"] is True, f"实际: {out['audit']}")

    out = await auditor_node({
        "facts": _facts(),
        "analysis": _analysis(),
        "improvement_detail": GOOD_REPORT,
        "improvement_revision": 2,
    })
    check("第二段审整改单 → 写 report_audit(scope=report)",
          out["report_audit"]["scope"] == "report" and "audit" not in out, f"实际: {out}")
    check("终审记录版本号（重写后自动过期）",
          out["report_audit"]["revision"] == 2, f"实际: {out['report_audit']}")
    check("合规整改单 → 终审通过", out["report_audit"]["passed"] is True,
          f"实际: {out['report_audit']['issues']}")

    out = await auditor_node({
        "facts": _facts(),
        "analysis": _analysis(),
        "improvement_detail": "太咸了，改一下。",
        "improvement_revision": 1,
    })
    issues = out["report_audit"]["issues"]
    check("终审拦得住空壳整改单（过短 + 没有可执行步骤）",
          out["report_audit"]["passed"] is False and len(issues) >= 2, f"实际: {issues}")

    out = await auditor_node({
        "facts": _facts(),
        "analysis": _analysis(),
        "improvement_detail": GOOD_REPORT + "\n绝对不要再犯错，一定要保证完全达标。",
        "improvement_revision": 1,
    })
    check("终审拦得住满篇绝对化表述",
          any("绝对化表述" in i for i in out["report_audit"]["issues"]),
          f"实际: {out['report_audit']['issues']}")

    out = await auditor_node({
        "facts": {"dimension_stats": {}, "safety_flags": [{"issue": "有头发", "severity": 5}]},
        "analysis": {"summary": "整体正常", "conflicts": []},
    })
    check("食安事件没有触发整改 → 预审不通过",
          out["audit"]["passed"] is False and any("食安" in i for i in out["audit"]["issues"]),
          f"实际: {out['audit']['issues']}")


async def test_run_dish_analysis():
    print("\n[3] run_dish_analysis：交付判定 + 置信度 + 落库闸门")
    chunks = [{
        "facts": _facts(),
        "reviews": [{
            "review_id": 7, "raw_text": "太咸了", "sentiment": "negative",
            "ner_entities": {"dimension": "口味", "severity": 3, "issue": "太咸"},
        }],
        "keyword_weights": {},
    }]

    # 3.1 报告拒发 → 不落库、必须人工复核
    _written.clear()
    sys.modules["app.workflow"].supervisor_workflow = _FakeGraph({
        "report_ok": False,
        "human_review_required": True,
        "improvement_detail": None,
    })
    out = await P.run_dish_analysis("红烧肉", "1", chunks)
    await asyncio.sleep(0)
    check("拒发 → decision_id 为空", out["decision_id"] is None, f"实际: {out}")
    check("拒发 → 不写向量库", _written == [], f"实际: {_written}")
    check("拒发 → human_review_required=True", out["human_review_required"] is True)

    # 3.2 终审没过 → 仍然人工复核
    sys.modules["app.workflow"].supervisor_workflow = _FakeGraph({
        "report_ok": True,
        "improvement_detail": GOOD_REPORT,
        "improvement_summary": "红烧肉偏咸（非品控问题）",
        "confidence_score": 0.72,
        "confidence_action": "publish_with_review",
        "audit": {"passed": True, "scope": "analysis", "issues": []},
        "report_audit": {"passed": False, "scope": "report", "issues": ["缺少步骤"]},
    })
    out = await P.run_dish_analysis("红烧肉", "1", chunks)
    check("终审没过 → human_review_required=True", out["human_review_required"] is True)
    await asyncio.sleep(0)   # 让上面那次 fire-and-forget 落库任务跑完，避免串到下一段断言

    # 3.3 正常交付 → 落库 + 置信度与轨迹一路带回
    _written.clear()
    sys.modules["app.workflow"].supervisor_workflow = _FakeGraph({
        "report_ok": True,
        "improvement_detail": GOOD_REPORT,
        "improvement_summary": "红烧肉口味偏咸，来自调味环节",
        "confidence_score": 0.72,
        "confidence_action": "publish_with_review",
        "agents_used": ["analyst", "auditor", "prescriber", "auditor", "reporter"],
        "attempts": {"prescriber": 1},
        "retrieval_ok": False,
        "analysis": _analysis(),
        "audit": {"passed": True, "scope": "analysis", "issues": []},
        "report_audit": {"passed": True, "scope": "report", "issues": [], "score": 1.0},
    })
    out = await P.run_dish_analysis("红烧肉", "1", chunks)
    await asyncio.sleep(0)
    check("正常交付 → decision_id 落库",
          bool(out["decision_id"]) and len(_written) == 1
          and _written[0][0] == out["decision_id"],
          f"实际: decision_id={out['decision_id']} written={len(_written)}")
    check("置信度不再恒为 0", out["confidence_score"] == 0.72, f"实际: {out['confidence_score']}")
    check("只回收了 prescriber 自己算的置信度",
          out["human_review_required"] is False, f"实际: {out['human_review_required']}")
    trace = out["diagnosis_trace"]
    check("诊断轨迹带上冲突分析 / 两段审核 / 调用轨迹",
          trace["conflicts"] and trace["audit"]["scope"] == "analysis"
          and trace["report_audit"]["passed"] is True
          and trace["agents_used"][-1] == "reporter", f"实际: {trace}")
    check("conflict_type 取可整改结论的信号类型", out["conflict_type"] is not None)


async def test_callback():
    print("\n[4] consumer 回调：置信度与轨迹真的写进 body")
    merged = await P.run_dish_analysis("红烧肉", "1", [{
        "facts": _facts(),
        "reviews": [{
            "review_id": 7,
            "raw_text": "太咸了",
            "sentiment": "negative",
            # 既有形状就是「字典列表」，backend 的 RefinedReview.dimensions 必须能接住，
            # 声明成 list[str] 会让整条回调 422（诊断一份都落不了库）
            "dimensions": [{"dimension": "口味", "keyword": "太咸"}],
            "ner_entities": {"dimension": "口味", "severity": 3, "issue": "太咸"},
        }],
        "keyword_weights": {},
    }])

    class _Resp:
        def raise_for_status(self):
            pass

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            _posted.append((url, json))
            return _Resp()

    C.httpx = types.SimpleNamespace(AsyncClient=_Client)
    await C._callback_backend(
        {"batch_id": "b1", "dish_id": "1", "dish_name": "红烧肉"}, merged,
    )
    body = _posted[-1][1]
    check("回调带 prescriber 的置信度", body["confidence"] == 0.72, f"实际: {body['confidence']}")
    check("回调带诊断轨迹（不再是空）",
          bool(body["conflict_analysis"].get("agents_used")), f"实际: {body['conflict_analysis']}")
    check("回调带 conflict_type", body["conflict_type"] is not None, f"实际: {body}")
    check("回写的 dimensions 保持既有形状（字典列表，不是字符串列表）",
          body["reviews"][0]["dimensions"] == [{"dimension": "口味", "keyword": "太咸"}],
          f"实际: {body['reviews']}")


async def main():
    await test_reporter()
    await test_auditor()
    await test_run_dish_analysis()
    await test_callback()
    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
