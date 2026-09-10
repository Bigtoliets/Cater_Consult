"""Agent 分析管线 —— 两级

分片级（固定线路）: 单个分片 → 结构化事实 facts。不查库、不出整改方案。
菜品级（Supervisor-Worker 动态编排）: 全部分片事实 → 最终诊断报告。

consumer.py 与 main.py 的 HTTP 调试端点共用本层，保证两条入口行为一致。
"""
import asyncio
import logging

from app.state import AgentState, new_decision_id
from app.utils.hallucination import get_detector

logger = logging.getLogger(__name__)


def _log_persist_failure(task: asyncio.Task) -> None:
    """create_task 是 fire-and-forget，异常不接住会静默丢掉（"Task exception was never retrieved"）"""
    try:
        task.result()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[Pipeline] 经验沉淀写 Milvus 失败: {e}", exc_info=True)


def build_initial_state(
    dish_name: str,
    dish_id: str,
    reviews: list[dict],
    keyword_weights: dict | None = None,
) -> AgentState:
    """组装工作流初始状态（只含输入 + 空黑板，键由各节点自己写）"""
    return {
        "dish_name": dish_name,
        "dish_id": dish_id,
        "reviews": reviews,
        "keyword_weights": keyword_weights or {},
        "improvement_summary": "",
        "improvement_detail": "",
        "human_review_required": False,
        "steps": 0,
    }


# ── 分片级：固定线路 ────────────────────────────────────────────────

async def process_chunk(payload: dict) -> dict:
    """分片级分析（固定线路）：提取专家单独跑，产出结构化事实

    这一步刻意不查知识库、不生成整改方案 —— 那些是菜品级深度加工的事，
    放在分片级会按分片数放大开销，而且跨分片的对比本来就做不了。
    """
    from app.agents.extractor import extractor_node

    state = build_initial_state(
        dish_name=payload.get("dish_name", "未知菜品"),
        dish_id=payload.get("dish_id", "UNKNOWN"),
        reviews=payload.get("reviews", []),
        keyword_weights=payload.get("keyword_weights", {}),
    )
    updated = await extractor_node(state)

    return {
        "facts": updated.get("facts", {}),
        # 分片内部的评论（含 NER 结果与 review_id）留给菜品级复用，避免二次提取
        "reviews": updated.get("reviews", []),
        "keyword_weights": state.get("keyword_weights", {}),
    }


# ── 菜品级：跨分片归并 + Supervisor-Worker 深度加工 ─────────────────

def merge_facts(facts_list: list[dict]) -> dict:
    """跨分片归并结构化事实（提取专家的归并职责）

    同一个问题在不同分片里的表述要合并计数，而不是并列出多份。
    """
    merged: dict[str, dict] = {}
    safety_flags: list[dict] = []
    total_reviews = 0
    negative_count = 0

    for facts in facts_list:
        if not facts:
            continue
        total_reviews += facts.get("review_count", 0)
        negative_count += facts.get("negative_count", 0)
        safety_flags.extend(facts.get("safety_flags") or [])

        for dim, stat in (facts.get("dimension_stats") or {}).items():
            target = merged.setdefault(dim, {
                "count": 0, "severity_sum": 0.0, "keywords": [],
                "evidence": [], "is_preference": 0,
                "weight": stat.get("weight", 1.0),
            })
            count = stat.get("count", 0)
            target["count"] += count
            target["severity_sum"] += stat.get("avg_severity", 1.0) * count
            target["keywords"].extend(stat.get("keywords") or [])
            target["evidence"].extend(stat.get("evidence") or [])
            target["is_preference"] += stat.get("is_preference", 0)

    for stat in merged.values():
        stat["avg_severity"] = round(stat["severity_sum"] / (stat["count"] or 1), 2)
        stat["keywords"] = list(dict.fromkeys(stat["keywords"]))[:8]
        del stat["severity_sum"]

    return {
        "dimension_stats": merged,
        "safety_flags": safety_flags,
        "review_count": total_reviews,
        "negative_count": negative_count,
    }


def collect_review_labels(reviews: list[dict]) -> list[dict]:
    """汇总 Agent 精判的逐条评论标签，供 backend 回写（覆盖词典粗判）"""
    labels = []
    for review in reviews:
        review_id = review.get("review_id")
        if review_id is None:
            continue
        ner = review.get("ner_entities") or {}
        labels.append({
            "review_id": review_id,
            "sentiment": review.get("sentiment"),
            "dimensions": review.get("dimensions") or [],
            "risk_level": ner.get("severity"),
            "dimension_detail": [{
                "dimension": ner.get("dimension", "其他"),
                "severity": ner.get("severity", 1),
                "issue": ner.get("issue", ""),
                "is_preference": ner.get("is_preference", False),
            }] if ner else None,
        })
    return labels


def _build_task(dish_name: str, facts: dict) -> str:
    stats = facts.get("dimension_stats") or {}
    if not stats:
        return f"分析菜品「{dish_name}」的顾客评价，判断是否存在品控问题"
    top = sorted(stats.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:3]
    desc = "、".join(f"{dim}({s.get('count')}条,严重度{s.get('avg_severity')})" for dim, s in top)
    return (
        f"分析菜品「{dish_name}」的顾客评价：共 {facts.get('review_count', 0)} 条，"
        f"差评 {facts.get('negative_count', 0)} 条，主要问题维度 {desc}。"
        f"请定位根因并产出可执行的整改方案。"
    )


async def run_dish_analysis(
    dish_name: str,
    dish_id: str,
    chunk_results: list[dict],
    persist: bool = True,
) -> dict:
    """菜品级深度加工：跨分片归并 → Supervisor-Worker 编排 → 最终诊断

    返回字段：
    - 交付物：improvement_summary / improvement_detail / decision_id / report_ok
    - 判定：human_review_required（拒发、终审没过、食安等都会置 True）
    - 回写用：review_labels（逐条精判标签）、confidence_score / confidence_action、
      conflict_type、diagnosis_trace（冲突分析 + 两段审核结论 + 调用轨迹）

    落库闸门：只有 reporter 明确产出报告（report_ok）才写向量库，
    空壳报告绝不会被当成经验沉淀进去。
    """
    from app.workflow import RECURSION_LIMIT, supervisor_workflow

    if not chunk_results:
        return {
            "dish_name": dish_name, "dish_id": dish_id, "decision_id": None,
            "improvement_summary": None, "improvement_detail": None,
            "human_review_required": False, "review_labels": [],
            "confidence_score": 0.0, "confidence_action": "",
            "report_ok": False, "conflict_type": None, "diagnosis_trace": {},
        }

    reviews = [r for chunk in chunk_results for r in (chunk.get("reviews") or [])]
    facts = merge_facts([chunk.get("facts") or {} for chunk in chunk_results])
    weights = (chunk_results[0].get("keyword_weights") or {})

    state = build_initial_state(dish_name, dish_id, reviews, weights)
    # facts 在这里预填：分片级已经付过一次 NER 的钱，菜品级不必再抽一遍。
    # 副作用是开心路径上 extractor 会被 Supervisor 的前置条件跳过，它只在事实缺失时兜底。
    state["facts"] = facts
    state["task"] = _build_task(dish_name, facts)

    # 显式给递归上限：MAX_STEPS 轮 Supervisor + 等量 Worker 节点，
    # 用默认 25 容易在上限附近抛 GraphRecursionError（那条异常没有任何兜底）
    result = await supervisor_workflow.ainvoke(state, config={"recursion_limit": RECURSION_LIMIT})

    summary = result.get("improvement_summary") or ""
    detail = result.get("improvement_detail") or ""
    report_ok = bool(result.get("report_ok"))
    audit = result.get("audit") or {}
    report_audit = result.get("report_audit") or {}
    analysis = result.get("analysis") or {}
    conflicts = analysis.get("conflicts") or []
    actionable = [c for c in conflicts if c.get("should_trigger")]

    # 交付判定：只有 reporter 明确产出过报告、且整改单过了终审，才算「AI 已分析」；
    # 其余情况（拒发 / 终审没过 / 重写预算耗尽）一律标人工复核。
    human_review = bool(result.get("human_review_required", False))
    if not report_ok or not report_audit.get("passed"):
        human_review = True

    # 幻觉检测（最终报告兜底；终审之外的最后一层网）
    if detail:
        detector = get_detector()
        h_report = detector.check(detail + summary, context={"dish_name": dish_name})
        if h_report.has_hallucination:
            warning = f"\n\n⚠️ **幻觉检测警告** (风险: {h_report.risk_level}):\n"
            warning += "\n".join(f"- {i}" for i in h_report.issues[:3])
            detail += warning
            human_review = True

    decision_id = ""
    if detail and report_ok and persist:
        from app.utils.milvus_client import write_to_standard

        decision_id = new_decision_id()
        content_to_store = f"【菜品：{dish_name}】{summary}\n\n{detail}"
        task = asyncio.create_task(write_to_standard(decision_id, dish_name, content_to_store))
        task.add_done_callback(_log_persist_failure)

    return {
        "dish_name": dish_name,
        "dish_id": dish_id,
        "decision_id": decision_id or None,
        "improvement_summary": summary or None,
        "improvement_detail": detail or None,
        "human_review_required": human_review,
        "review_labels": collect_review_labels(reviews),
        # 以下字段供 consumer 回写 backend（置信度 / 诊断轨迹），不再有中间层把它们吞掉
        "confidence_score": result.get("confidence_score") or 0.0,
        "confidence_action": result.get("confidence_action") or "",
        "report_ok": report_ok,
        "conflict_type": actionable[0].get("signal_type") if actionable else None,
        "diagnosis_trace": {
            "agents_used": result.get("agents_used") or [],
            "conflicts": conflicts,
            "audit": audit,
            "report_audit": report_audit,
            "attempts": result.get("attempts") or {},
            "retrieval_ok": result.get("retrieval_ok"),
        },
    }
