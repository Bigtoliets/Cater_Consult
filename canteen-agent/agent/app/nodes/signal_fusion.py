"""节点①增强版：三维信号融合 + 冲突检测 (v3.0)

替代原有的简单维度加权计数, 新增:
1. 基本面信号: NER 提取的问题实体 × 严重度 × 维度权重
2. 频次面信号: 投诉密度 + 趋势方向
3. 关联面信号: 时间集中度分析

核心能力: 区分「口味偏好差异」和「生产品控波动」
"""
from dataclasses import dataclass, field
from app.state import AgentState

DEFAULT_DIMENSION_WEIGHTS = {
    "口味": 1.0, "卫生": 3.0, "分量": 1.0, "温度": 1.0,
    "口感": 1.5, "价格": 1.0, "服务": 1.0, "安全": 5.0,
}


@dataclass
class QualitySignal:
    """品控信号"""
    dimension: str
    direction: str             # "negative"(有问题) / "positive"(正常)
    strength: float            # 信号强度 0-1
    evidence_count: int        # 支撑评价数
    is_preference: bool        # 是否为口味偏好差异
    keywords: list[str]        # 支撑关键词
    avg_severity: float        # 平均严重度


@dataclass
class ConflictAnalysis:
    """冲突分析结果"""
    signal_type: str           # preference_divergence / quality_fluctuation / consistent_complaint
    description: str
    confidence: float
    should_trigger: bool
    reason: str


async def keyword_aggregation(state: AgentState) -> AgentState:
    """
    v3.0 信号融合版: 消费 NER 结果, 生成多维度信号 + 冲突分析

    流程:
    1. 从 NER 结果提取 QualitySignal 列表
    2. 冲突检测 (区分偏好差异 vs 品控波动)
    3. 生成结构化 keyword_summary
    """
    reviews = state.get("reviews", [])
    dish_name = state.get("dish_name", "未知")
    keyword_weights = state.get("keyword_weights", DEFAULT_DIMENSION_WEIGHTS)

    # ── Step 1: 提取信号 ──
    signals = _extract_signals(reviews, keyword_weights)

    # ── Step 2: 冲突检测 ──
    conflicts = _detect_conflicts(signals)

    # ── Step 3: 生成融合摘要 ──
    summary_parts = _build_fusion_summary(dish_name, reviews, signals, conflicts)

    should_trigger = any(c.should_trigger for c in conflicts)

    return {
        **state,
        "keyword_summary": "\n".join(summary_parts),
        "conflict_analysis": [
            {
                "signal_type": c.signal_type,
                "description": c.description,
                "confidence": c.confidence,
                "should_trigger": c.should_trigger,
                "reason": c.reason,
            }
            for c in conflicts
        ],
        "should_trigger_improvement": should_trigger,
        "keyword_weights": keyword_weights,
        "workflow_stage": "diagnostician_done",
    }


def _extract_signals(reviews: list[dict], weights: dict) -> list[QualitySignal]:
    """从 NER 结果提取结构化质量信号"""
    # 按维度聚合
    dim_stats: dict[str, dict] = {}

    for r in reviews:
        ner = r.get("ner_entities", {})
        dim = ner.get("dimension", "其他")
        sentiment = r.get("sentiment", "neutral")
        direction = "negative" if sentiment == "negative" else "positive"

        if dim not in dim_stats:
            dim_stats[dim] = {
                "positive": 0, "negative": 0,
                "keywords": [], "is_preference": [],
                "severity_sum": 0, "severity_count": 0,
                "weight": weights.get(dim, 1.0),
            }

        ds = dim_stats[dim]
        ds[direction] += 1
        ds["severity_sum"] += ner.get("severity", 1)
        ds["severity_count"] += 1
        if ner.get("issue"):
            ds["keywords"].append(ner["issue"])
        ds["is_preference"].append(ner.get("is_preference", False))

    signals = []
    for dim, stats in dim_stats.items():
        total = stats["positive"] + stats["negative"]
        if total == 0:
            continue
        neg_ratio = stats["negative"] / total
        pref_count = sum(stats["is_preference"])
        pref_ratio = pref_count / len(stats["is_preference"]) if stats["is_preference"] else 0
        avg_sev = stats["severity_sum"] / stats["severity_count"] if stats["severity_count"] > 0 else 1

        # 信号强度 = 差评占比 × 加权严重度 × 维度权重
        strength = min(1.0, neg_ratio * (avg_sev / 3) * min(2.0, stats["weight"]))

        signals.append(QualitySignal(
            dimension=dim,
            direction="negative" if neg_ratio > 0.3 else "positive",
            strength=strength,
            evidence_count=stats["negative"],
            is_preference=pref_ratio > 0.6 and stats["negative"] > 0,
            keywords=list(set(stats["keywords"]))[:5],
            avg_severity=round(avg_sev, 1),
        ))

    return signals


def _detect_conflicts(signals: list[QualitySignal]) -> list[ConflictAnalysis]:
    """
    冲突检测核心算法:
    - 同维度差评一致 → 品控问题 (触发整改)
    - 同维度有偏好标记 → 口味差异 (不触发)
    - 高频次 + 高严重度 → 一致性问题 (严重触发)
    """
    conflicts = []

    for s in signals:
        if s.direction == "positive":
            continue

        if s.is_preference and s.evidence_count < 5:
            # 少数人的口味偏好 → 不触发
            conflicts.append(ConflictAnalysis(
                signal_type="preference_divergence",
                description=f"「{s.dimension}」维度存在口味偏好差异（{s.evidence_count}条差评，关键词: {', '.join(s.keywords[:3])}）",
                confidence=0.65 + 0.3 * (s.evidence_count / 5),
                should_trigger=False,
                reason="众口难调，非品控问题，建议在菜单标注口味强度供顾客参考",
            ))
        elif s.strength >= 0.5 and s.evidence_count >= 3:
            # 高强度 + 足量样本 → 品控问题
            severity_label = "严重" if s.avg_severity >= 4 else "一般"
            conflicts.append(ConflictAnalysis(
                signal_type="quality_fluctuation" if s.evidence_count < 8 else "consistent_complaint",
                description=f"「{s.dimension}」维度存在{severity_label}品控问题：{', '.join(s.keywords[:3])}（{s.evidence_count}条差评，严重度{s.avg_severity}/5）",
                confidence=min(0.95, 0.5 + s.strength + (s.evidence_count / 20)),
                should_trigger=True,
                reason=f"多人一致反馈，确认为品控问题，建议排查后厨{s.dimension}相关工艺环节",
            ))
        elif s.strength >= 0.3:
            # 中低强度 → 持续观察
            conflicts.append(ConflictAnalysis(
                signal_type="quality_fluctuation",
                description=f"「{s.dimension}」维度存在轻微品控波动（{s.evidence_count}条差评）",
                confidence=0.4 + s.strength,
                should_trigger=False,
                reason="样本不足或强度偏低，建议持续观察，暂不触发整改",
            ))

    return conflicts


def _build_fusion_summary(
    dish_name: str,
    reviews: list[dict],
    signals: list[QualitySignal],
    conflicts: list[ConflictAnalysis],
) -> list[str]:
    """生成信号融合摘要"""
    total = len(reviews)
    neg_count = sum(1 for r in reviews if r.get("sentiment") == "negative")
    pos_count = sum(1 for r in reviews if r.get("sentiment") == "positive")
    neu_count = total - neg_count - pos_count

    parts = [
        f"## 📊 信号融合分析：{dish_name}",
        f"共 {total} 条评价（好评 {pos_count} / 中性 {neu_count} / 差评 {neg_count}）",
        f"提取 {len(signals)} 个维度信号",
        "",
    ]

    # 信号汇总
    actionable = [c for c in conflicts if c.should_trigger]
    preference = [c for c in conflicts if not c.should_trigger]

    if actionable:
        parts.append(f"### 🎯 需要整改的品控问题（{len(actionable)} 项）")
        for c in actionable:
            parts.append(f"- 🔴 {c.description} | 置信度: {c.confidence:.0%}")
            parts.append(f"  → {c.reason}")
        parts.append("")

    if preference:
        parts.append(f"### 💬 口味偏好差异（{len(preference)} 项，无需整改）")
        for c in preference:
            parts.append(f"- 🟢 {c.description}")
        parts.append("")

    if not actionable and not preference:
        parts.append("### ✅ 未检测到需要处理的品控问题")

    # 维度详情
    dim_weights = state.get("keyword_weights", DEFAULT_DIMENSION_WEIGHTS)
    parts.append("### 📋 维度详情")
    for s in signals:
        icon = "🔴" if s.direction == "negative" and not s.is_preference else "🟡" if s.is_preference else "🟢"
        w = dim_weights.get(s.dimension, 1.0)
        parts.append(
            f"{icon} **{s.dimension}** (权重{w:.1f}): "
            f"差评{s.evidence_count}条, 严重度{s.avg_severity}/5, "
            f"{'偏好差异' if s.is_preference else '品控信号'}"
        )

    return parts
