"""审核员 Worker（C）—— 一致性校验，防大模型幻觉

两段式把关，不产出业务结论，只产出「通过 / 不通过 + 问题清单 + 得分」：

- 第一段（scope=analysis）：整改单还没生成，先审分析结论有没有事实支撑。
- 第二段（scope=report）  ：整改单生成后，审真正要交付的那份文本（improvement_detail）。
  这一段才是防幻觉的关键闸门 —— 终审不过会被 Supervisor 打回 prescriber 重写。

问题分两级：
- issues   阻断级，会导致打回重写 / 人工复核标记
- warnings 记录级，只进报告脚注与落库观测，不阻断

工具权限：check_fact、validate_output
"""
import re
from datetime import datetime

from app.state import AgentState
from app.utils.hallucination import HallucinationDetector, get_detector

# 每发现一个阻断级问题扣 0.3 分
PENALTY_PER_ISSUE = 0.3
# 终审：正文短于这个长度视为没写出来
MIN_REPORT_LEN = 40
# 终审：至少要有这么多条可执行步骤
MIN_REPORT_STEPS = 2
# 终审：绝对化表述超过这个数量才算问题（偶发一两处不算）
MAX_ABSOLUTE_HITS = 2

# 有序号（1. / 1、/ 一、）或项目符号（- / * / •）开头都算一条可执行步骤
STEP_PATTERN = re.compile(
    r"^\s*(?:\d+[.、)]|[一二三四五六七八九十]+[、.)]|[-*•])\s*\S+", re.MULTILINE
)


async def auditor_node(state: AgentState) -> dict:
    """只返回本 Worker 负责的键，不返回 {**state}（见 state.py 约定）

    审核对象由黑板决定：有整改单就终审整改单，没有就预审分析结论。
    """
    detail = (state.get("improvement_detail") or "").strip()
    if detail:
        return _audit_report(state, detail)
    return _audit_analysis(state)


# ── 第一段：analysis 预审 ──────────────────────────────────────────

def _audit_analysis(state: AgentState) -> dict:
    analysis = state.get("analysis") or {}
    facts = state.get("facts") or {}
    conclusion = analysis.get("summary") or state.get("keyword_summary", "")
    conflicts = analysis.get("conflicts") or state.get("conflict_analysis") or []
    actionable = [c for c in conflicts if c.get("should_trigger")]

    issues: list[str] = []
    warnings: list[str] = []

    # 1. 幻觉检测：结论里有没有凭空捏造的表述
    report, err = _hallucination(conclusion, state)
    if err:
        warnings.append(err)
    elif report is not None and report.has_hallucination:
        issues.extend(
            f"幻觉风险({report.risk_level}): {item}" for item in (report.issues or [])[:3]
        )
    if report is not None:
        warnings.extend(report.warnings[:3])

    # 2. 一致性：声称要整改的维度必须在结构化事实里找得到
    dim_stats = facts.get("dimension_stats") or {}
    for conflict in actionable:
        dim = _declared_dimension(conflict)
        if dim and dim not in dim_stats:
            issues.append(f"结论声称的维度「{dim}」在原始评价中找不到支撑")

    # 3. 有整改结论却没有证据样本
    if actionable and not dim_stats:
        issues.append("存在待整改结论，但缺少支撑证据")

    # 4. 有整改结论却没有根因
    if actionable and not any((c.get("reason") or "").strip() for c in actionable):
        issues.append("存在待整改结论，但未给出根因")

    # 5. 食安事件必须有人接住：事实里标了食安，结论却不触发整改
    safety_flags = facts.get("safety_flags") or []
    if safety_flags and not actionable:
        issues.append(
            f"存在 {len(safety_flags)} 条食安事件标记，但分析结论未触发任何整改，需人工确认"
        )

    return _result("analysis", issues, warnings)


# ── 第二段：report 终审 ────────────────────────────────────────────

def _audit_report(state: AgentState, detail: str) -> dict:
    issues: list[str] = []
    warnings: list[str] = []

    # 1. 幻觉检测 —— 对象是真正要交付给后厨的那份文本
    report, err = _hallucination(detail, state)
    if err:
        warnings.append(err)
    elif report is not None and report.has_hallucination:
        issues.extend(
            f"幻觉风险({report.risk_level}): {item}" for item in (report.issues or [])[:3]
        )
    if report is not None:
        warnings.extend(report.warnings[:5])

    # 2. 绝对化表述过量（绝对/保证/永远/完全…）—— 整改建议不该这么说
    absolute_hits = sum(
        len(re.findall(pattern, detail)) for pattern in HallucinationDetector.ABSOLUTE_PATTERNS
    )
    if absolute_hits >= MAX_ABSOLUTE_HITS:
        issues.append(
            f"整改单含 {absolute_hits} 处绝对化表述（绝对/保证/永远…），应改为建议性表述"
        )

    # 3. 形态：正文过短 / 缺少可执行步骤
    if len(detail) < MIN_REPORT_LEN:
        issues.append("整改单正文过短，未形成可交付内容")
    steps = STEP_PATTERN.findall(detail)
    if len(steps) < MIN_REPORT_STEPS:
        issues.append(
            f"整改单只列出 {len(steps)} 条步骤，至少需要 {MIN_REPORT_STEPS} 条可执行步骤"
        )

    # 4. 报告的结论维度要有事实支撑（防止重写时跑偏）
    dim_stats = (state.get("facts") or {}).get("dimension_stats") or {}
    analysis = state.get("analysis") or {}
    for conflict in [c for c in (analysis.get("conflicts") or []) if c.get("should_trigger")]:
        dim = _declared_dimension(conflict)
        if dim and dim not in dim_stats:
            issues.append(f"整改单依据的维度「{dim}」在原始评价中找不到支撑")

    # 记下审的是哪一版整改单：重写后 revision 变了，这份终审就自动过期
    return _result("report", issues, warnings, revision=state.get("improvement_revision") or 0)


# ── 公共小工具 ────────────────────────────────────────────────────

def _hallucination(text: str, state: AgentState):
    """幻觉检测。返回 (report, error)；检测器本身故障不阻断链路"""
    if not text:
        return None, None
    try:
        report = get_detector().check(text, context={"dish_name": state.get("dish_name", "")})
        return report, None
    except Exception as e:  # noqa: BLE001 — 工具故障不应阻断业务链路
        return None, f"幻觉检测不可用：{e}"


def _declared_dimension(conflict: dict) -> str:
    """取冲突对应的维度名：优先显式字段，其次从描述里的「」取"""
    dim = (conflict.get("dimension") or "").strip()
    if dim:
        return dim
    match = re.search(r"「(.+?)」", conflict.get("description", "") or "")
    return match.group(1).strip() if match else ""


def _result(
    scope: str, issues: list[str], warnings: list[str], revision: int | None = None
) -> dict:
    passed = not issues
    score = 1.0 if passed else max(0.0, round(1.0 - PENALTY_PER_ISSUE * len(issues), 2))
    payload = {
        "passed": passed,
        "score": score,
        "issues": issues,
        "warnings": warnings,
        "scope": scope,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    if revision is not None:
        payload["revision"] = revision
    key = "report_audit" if scope == "report" else "audit"
    return {key: payload, "review_notes": issues}
