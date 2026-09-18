"""Supervisor Agent — 决策中枢 (v4.1)

只做三件事：Planning（规划）、Delegation（委派）、Gatekeeping（把关）。
不提取、不分析、不查库、不写报告 —— 它的工具注册表是空的。

每轮读黑板（各 Worker 产物）决定下一步委派给谁，读审核意见决定放行还是打回。

护栏是加在本模块外面的「宪法」，Supervisor 无权绕过：
- 依赖顺序     每个 Worker 都有前置条件，不满足就回退到确定性链路（LLM 跳不了步）
- 两段式审核   analysis 预审 + report 终审；终审对象是真正要交付的整改单
- 打回预算     只有 prescriber 重写是「真的能改」的（分析节点是确定性的，重跑同结果）
- MAX_STEPS    总轮数上限，超限强制收口
- 不许空手结束 FINISH 前 reporter 必须表态（report_ok），拒发就标人工复核
- LLM 输出不可解析 → 降级 rule_fallback（确定性链路）
"""
import logging
from json import JSONDecodeError, JSONDecoder

from app.prompts.supervisor_prompts import (
    SUPERVISOR_SYSTEM_PROMPT,
    SUPERVISOR_USER_TEMPLATE,
)
from app.state import AgentState
from app.utils.llm import get_llm

logger = logging.getLogger(__name__)

# ── 路由常量 ──
ROUTE_EXTRACTOR = "extractor"
ROUTE_RETRIEVER = "retriever"
ROUTE_ANALYST = "analyst"
ROUTE_AUDITOR = "auditor"
ROUTE_PRESCRIBER = "prescriber"
ROUTE_REPORTER = "reporter"
ROUTE_FINISH = "FINISH"

WORKERS = (
    ROUTE_EXTRACTOR, ROUTE_RETRIEVER, ROUTE_ANALYST,
    ROUTE_AUDITOR, ROUTE_PRESCRIBER, ROUTE_REPORTER,
)

# ── 护栏（宪法）──
# 最坏路径 10 步：extractor → analyst → auditor → retriever → prescriber → auditor
# → prescriber(重写) → auditor → reporter → FINISH（facts 已由分片级预填时少一步），
# 再留 2 步余量，避免护栏把正常流程提前掐断。
MAX_STEPS = 12
MAX_WORKER_ATTEMPTS = 2
# 各 Worker 的调用额度上限（缺省用 MAX_WORKER_ATTEMPTS）。
# auditor 要跑两段（预审 + 终审），整改单重写后还要复审判一次，所以给它 3 次；
# 否则终审会把额度吃光，重写后的整改单只能「不审就发」。
WORKER_ATTEMPTS = {ROUTE_AUDITOR: 3}
# 终审不过时可以打回重写的 Worker。只放 prescriber：它调 LLM，换个指令真能改写；
# analyst 是确定性节点（signal_fusion），重跑必然得到同一份结论，
# 把它列成打回目标只会烧掉两轮 LLM 调用再放弃。
REPORT_REWORK_TARGETS = (ROUTE_PRESCRIBER,)


def _budget(worker: str) -> int:
    return WORKER_ATTEMPTS.get(worker, MAX_WORKER_ATTEMPTS)


def _decision(next_worker: str, instruction: str = "", reason: str = "") -> dict:
    return {"next": next_worker, "instruction": instruction, "reason": reason}


# ── 观测：把黑板翻译成 Supervisor 能读懂的进度表 ──

def _audit_text(audit: dict) -> str:
    if not audit:
        return "❌ 未做"
    if audit.get("passed"):
        return f"✅ 通过（得分 {audit.get('score')}）"
    return f"⚠️ 不通过（{len(audit.get('issues') or [])} 个问题）"


def _retrieval_text(state: AgentState) -> str:
    if not state.get("retrieved"):
        return "❌ 未做"
    return "✅ 已完成" if state.get("retrieval_ok", True) else "⚠️ 知识库不可用"


def _report_text(state: AgentState) -> str:
    if state.get("report_ok") is True:
        return "✅ 已完成"
    if state.get("report_ok") is False:
        return "❌ 拒发（无正文，需人工复核）"
    return "❌ 未做"


def _progress(state: AgentState) -> str:
    steps = state.get("steps", 0)
    max_steps = state.get("max_steps", MAX_STEPS)
    rows = [
        ("extractor 结构化事实", "✅ 已完成" if state.get("facts") else "❌ 未做"),
        ("analyst 分析结论", "✅ 已完成" if state.get("analysis") else "❌ 未做"),
        ("auditor 结论预审", _audit_text(state.get("audit") or {})),
        ("retriever 知识库依据", _retrieval_text(state)),
        ("prescriber 整改单", "✅ 已完成" if state.get("improvement_detail") else "❌ 未做"),
        ("auditor 整改单终审", _audit_text(state.get("report_audit") or {})),
        ("reporter 最终报告", _report_text(state)),
    ]
    head = f"轮数：{steps}/{max_steps}（每轮 = 一次 Supervisor 决策）"
    return head + "\n" + "\n".join(f"- {name}: {status}" for name, status in rows)


def _quota_text(state: AgentState) -> str:
    attempts = state.get("attempts") or {}
    return "，".join(f"{w} {attempts.get(w, 0)}/{_budget(w)}" for w in WORKERS)


# ── LLM 决策 ──

def _iter_json_objects(text: str):
    """逐个抠出文本里的 JSON 对象（贪婪正则在多对象/带示例时会把整段喂给 json.loads 失败）"""
    decoder = JSONDecoder()
    idx = 0
    while True:
        start = text.find("{", idx)
        if start == -1:
            return
        try:
            obj, end = decoder.raw_decode(text[start:])
        except JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):
            yield obj
        idx = start + max(end, 1)


def _parse_decision(text: str) -> dict | None:
    """从 LLM 输出里抠出决策 JSON，失败返回 None（交给兜底）"""
    if not text:
        return None
    for obj in _iter_json_objects(text):
        nxt = str(obj.get("next", "") or "").strip()
        if not nxt:
            continue
        return _decision(
            nxt,
            str(obj.get("instruction", "") or ""),
            str(obj.get("reason", "") or ""),
        )
    return None


async def _llm_decide(state: AgentState) -> dict | None:
    task = state.get("task") or (
        f"分析菜品「{state.get('dish_name', '未知菜品')}」的顾客评价，定位根因并产出整改方案"
    )
    notes = state.get("review_notes") or []
    prompt = SUPERVISOR_USER_TEMPLATE.format(
        task=task,
        progress=_progress(state),
        agents_used=" → ".join(state.get("agents_used") or []) or "（无）",
        attempts=_quota_text(state),
        review_notes="\n".join(f"- {n}" for n in notes) or "（无）",
    )
    try:
        llm = get_llm()
        resp = await llm.ainvoke([
            {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return _parse_decision(resp.content)
    except Exception as e:
        logger.warning(f"[Supervisor] LLM 路由失败，降级规则路由: {e}")
        return None


# ── 兜底：确定性链路（LLM 不可用 / 输出不可解析时）──

def rule_fallback(state: AgentState) -> dict:
    """确定性兜底路由 —— 与依赖顺序一致的直线链路

    顺序：facts → analysis → 预审 → 检索 → 整改单 → 终审 → 报告 → FINISH。
    「审核没通过」不再打回分析（重跑同结果），只打回 prescriber 重写整改单。
    """
    attempts = state.get("attempts") or {}
    notes = state.get("review_notes") or []
    report_audit = state.get("report_audit") or {}

    if not state.get("facts"):
        return _decision(ROUTE_EXTRACTOR, "", "兜底：尚无结构化事实")
    if not state.get("analysis"):
        return _decision(ROUTE_ANALYST, "", "兜底：尚无分析结论")
    if not state.get("audit"):
        return _decision(ROUTE_AUDITOR, "", "兜底：结论未经预审")
    if not state.get("retrieved"):
        return _decision(ROUTE_RETRIEVER, "", "兜底：结论缺少知识库依据")
    if not state.get("improvement_detail"):
        return _decision(ROUTE_PRESCRIBER, "", "兜底：尚无整改方案")
    if not _report_audit_fresh(state):
        # 既是「还没终审」，也是「重写后上一版终审已过期」
        return _decision(ROUTE_AUDITOR, "", "兜底：整改单未做终审（或重写后需再审）")

    if not report_audit.get("passed"):
        for target in REPORT_REWORK_TARGETS:
            if attempts.get(target, 0) < _budget(target):
                return _decision(
                    target,
                    "；".join(notes[:3]),
                    "兜底：整改单终审未通过，打回重写",
                )
        # 重写预算耗尽 → 带人工复核标记继续出报告，不再纠缠

    if "report_ok" not in state:
        return _decision(ROUTE_REPORTER, "", "兜底：最终报告未生成")
    return _decision(ROUTE_FINISH, "", "兜底：流程完成")


def _prerequisite_ok(worker: str, state: AgentState) -> bool:
    """依赖顺序：这个 Worker 现在真的有活可干吗？"""
    if worker == ROUTE_EXTRACTOR:
        return True
    if worker == ROUTE_ANALYST:
        return bool(state.get("facts"))
    if worker in (ROUTE_AUDITOR, ROUTE_RETRIEVER):
        return bool(state.get("analysis"))
    if worker == ROUTE_PRESCRIBER:
        # 先审后开方：分析结论在，且预审至少跑过（通不通过另说，不通过会带人工复核标记）
        return bool(state.get("analysis")) and bool(state.get("audit"))
    if worker == ROUTE_REPORTER:
        return bool((state.get("improvement_detail") or "").strip())
    return True


def _report_audit_fresh(state: AgentState) -> bool:
    """终审结论是否针对当前这一版整改单（重写后自动过期，必须重新送审）"""
    report_audit = state.get("report_audit") or {}
    if not report_audit:
        return False
    return report_audit.get("revision") == (state.get("improvement_revision") or 0)


def _terminate(state: AgentState) -> str:
    """收口：有正文就补报告，没正文就直接结束（由调用方标记人工复核）"""
    if "report_ok" in state:
        return ROUTE_FINISH
    if (state.get("improvement_detail") or "").strip():
        return ROUTE_REPORTER
    return ROUTE_FINISH


def _sanitize(next_worker: str, state: AgentState, _allow_fallback: bool = True) -> str:
    """护栏校验：非法路由、跳步、超限、空手结束都不放行"""
    attempts = state.get("attempts") or {}

    # 非法目标 → 回退到确定性路由
    if next_worker not in WORKERS and next_worker != ROUTE_FINISH:
        next_worker = rule_fallback(state)["next"]

    bad_order = next_worker in WORKERS and not _prerequisite_ok(next_worker, state)
    premature_finish = next_worker == ROUTE_FINISH and "report_ok" not in state
    over_budget = (
        next_worker in WORKERS and attempts.get(next_worker, 0) >= _budget(next_worker)
    )

    if bad_order or premature_finish or over_budget:
        if not _allow_fallback:
            return _terminate(state)
        fallback = rule_fallback(state)["next"]
        if fallback == next_worker:
            return _terminate(state)
        return _sanitize(fallback, state, _allow_fallback=False)

    return next_worker


async def supervisor_node(state: AgentState) -> dict:
    """决策节点：只返回增量，不返回 {**state}（见 state.py 的约定）"""
    steps = state.get("steps", 0)
    max_steps = state.get("max_steps", MAX_STEPS)
    # 调用轨迹
    used = list(state.get("agents_used") or [])
    # 各 Worker 已调用次数（护栏）
    attempts = dict(state.get("attempts") or {})

    # 护栏①：轮数超限 → 强制收口。注意这里刻意不过 _sanitize：它会把这句 FINISH
    # 当成「还没出报告就想跑」驳回，结果轮数护栏形同虚设。
    forced = steps >= max_steps
    if forced:
        decision = _decision(_terminate(state), "", f"轮数达到上限 {max_steps}，强制收口")
    else:
        decision = await _llm_decide(state)
        if decision is None:
            decision = rule_fallback(state)

    next_worker = decision["next"] if forced else _sanitize(decision["next"], state)
    # 目标被护栏改写时，原指令不再适用
    # decision：{"next": "analyst", "instruction": "重点看口味维度", "reason": "还没分析"}
    instruction = decision["instruction"] if next_worker == decision["next"] else ""

    updates: dict = {
        "next_worker": next_worker,
        "route_reason": decision.get("reason", ""),
        "steps": steps + 1,
    }

    if next_worker != ROUTE_FINISH:
        updates["agents_used"] = used + [next_worker]
        attempts[next_worker] = attempts.get(next_worker, 0) + 1
        updates["attempts"] = attempts
        if instruction:
            updates["instructions"] = {
                **(state.get("instructions") or {}), next_worker: instruction,
            }

    # 护栏②：审核没过 / 报告拒发 → 人工复核。只有在「没有重写机会了」时才落标记，
    # 避免一次可修复的终审打回就把整条链路打成人工复核。
    audit = state.get("audit") or {}
    report_audit = state.get("report_audit") or {}
    if audit and not audit.get("passed"):
        updates["human_review_required"] = True
    if report_audit and not report_audit.get("passed") and _report_audit_fresh(state):
        rework_left = any(
            attempts.get(t, 0) < _budget(t) for t in REPORT_REWORK_TARGETS
        )
        if not rework_left or "report_ok" in state:
            updates["human_review_required"] = True
    if state.get("report_ok") is False:
        updates["human_review_required"] = True
    if forced and next_worker == ROUTE_FINISH and "report_ok" not in state:
        # 轮数用尽且没产出报告 → 交人工
        updates["human_review_required"] = True

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"[Supervisor] step={steps + 1} → {next_worker} ({decision.get('reason', '')})"
        )
    return updates
