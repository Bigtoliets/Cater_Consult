"""幻觉检测与防护系统 (v4.0)

多层防护:
1. 输出格式校验 (OutputValidatorTool)
2. 事实核查 (FactCheckTool)
3. 数字参数验证
4. 来源引用检查
5. 矛盾检测
6. 绝对化表述检测
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HallucinationReport:
    """幻觉检测报告"""
    has_hallucination: bool = False
    risk_level: str = "low"     # low / medium / high / critical
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)
    suggested_fixes: list[str] = field(default_factory=list)


class HallucinationDetector:
    """幻觉检测器 — 规则 + 启发式方法"""

    # 高风险幻觉模式
    ABSOLUTE_PATTERNS = [
        r'(绝对|一定|肯定|保证|绝不|永远|从来|完全)',
    ]
    NUMBER_PATTERN = re.compile(r'\d+\s*(分钟|小时|克|g|毫升|ml|°C|摄氏度|元|¥|%)')
    UNCERTAIN_MARKERS = [
        r'据我所知', r'根据我的经验', r'一般来说', r'通常情况下',
        r'大多数', r'通常', r'往往', r'经常',
    ]

    def __init__(self, known_sop: dict[str, str] = None):
        """
        Args:
            known_sop: 已知SOP参数映射 {"菜品:参数": "标准值"}
                       如 {"红烧肉:盐量": "5g", "红烧肉:压制时间": "20分钟"}
        """
        self.known_sop = known_sop or {}

    def check(self, text: str, context: dict = None) -> HallucinationReport:
        """
        对LLM输出做全面的幻觉检测

        Args:
            text: LLM生成的文本
            context: 上下文信息 (含known_facts, dish_name等)

        Returns:
            HallucinationReport
        """
        report = HallucinationReport()

        # 1. 绝对化表述检测
        for pattern in self.ABSOLUTE_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                report.warnings.append(f"包含绝对化表述: {', '.join(matches[:3])}")
                report.suggested_fixes.append("将绝对化表述改为概率性表述，如'建议'/'通常'/'一般情况'")

        # 2. 模糊表述检测
        for pattern in self.UNCERTAIN_MARKERS:
            if re.search(pattern, text):
                report.warnings.append(f"使用模糊表述'{re.search(pattern, text).group(0)}'，建议引用具体来源")
                report.suggested_fixes.append("将模糊表述替换为知识库引用，如'根据SOP xxxx 记录...'")

        # 3. 数字参数验证
        numbers = self.NUMBER_PATTERN.findall(text)
        if numbers and not self._has_source_citation(text):
            report.unverified_claims.extend(
                f"未验证的数字参数: {n}" for n in numbers[:5]
            )
            report.warnings.append(f"包含 {len(numbers)} 个未验证来源的数字参数")
            report.suggested_fixes.append("为每个数字参数标注来源或标记'建议人工核实'")

        # 4. SOP 一致性检查
        if self.known_sop:
            for key, expected in self.known_sop.items():
                if key.split(":")[0] in text:
                    # 提取文本中的对应数值
                    actual = self._extract_param(text, key.split(":")[1])
                    if actual and actual != expected:
                        report.issues.append(
                            f"SOP矛盾: {key} 应为'{expected}'，但输出为'{actual}'"
                        )
                        report.has_hallucination = True
                        report.risk_level = "high"
                        report.suggested_fixes.append(f"将{key}调整为标准值'{expected}'")

        # 5. 来源引用检查
        if not self._has_source_citation(text) and len(text) > 100:
            report.warnings.append("长文本未标注信息来源")
            report.suggested_fixes.append("添加来源标注，如 (来源: SOP-红烧肉) 或 (来源: 🏅金标)")

        # 6. 内部矛盾检测
        contradictions = self._detect_contradictions(text)
        if contradictions:
            report.issues.extend(contradictions)
            report.has_hallucination = True
            report.risk_level = "medium"

        # 综合风险评级
        if report.issues:
            report.risk_level = "high" if len(report.issues) > 2 else "medium"
        if any("SOP矛盾" in i for i in report.issues):
            report.risk_level = "critical"

        return report

    def _has_source_citation(self, text: str) -> bool:
        """检查是否包含来源引用"""
        patterns = [
            r'\(来源[：:].*?\)', r'\(SOP[^)]*\)', r'\(🏅[^)]*\)',
            r'\(📋[^)]*\)', r'根据.*?记录', r'引用.*?条目',
        ]
        return any(re.search(p, text) for p in patterns)

    def _extract_param(self, text: str, param_type: str) -> Optional[str]:
        """从文本中提取参数值"""
        patterns = {
            "盐量": r'盐\s*量?\s*[:：=]?\s*(\d+\s*g)',
            "压制时间": r'(?:压制|炖煮|高压锅)\s*[:：=]?\s*(\d+\s*分钟)',
            "温度": r'温度\s*[:：=≥]?\s*(\d+\s*°?C)',
        }
        if param_type in patterns:
            match = re.search(patterns[param_type], text)
            return match.group(1) if match else None
        return None

    def _detect_contradictions(self, text: str) -> list[str]:
        """检测文本内部矛盾"""
        contradictions = []

        # 简单矛盾: "应该增加" 和 "应该减少" 同时出现
        opposite_pairs = [
            (r'增[加多]', r'减[少小]', "增减矛盾"),
            (r'提[升高]', r'降[低下]', "升降矛盾"),
            (r'加[大多]', r'减小', "加减矛盾"),
        ]
        for pos_pat, neg_pat, label in opposite_pairs:
            has_pos = bool(re.search(pos_pat, text))
            has_neg = bool(re.search(neg_pat, text))
            if has_pos and has_neg:
                # 检查是否针对同一对象
                if self._same_subject(text, pos_pat, neg_pat):
                    contradictions.append(f"内部{label}: 同时出现增加和减少的建议")

        return contradictions

    def _same_subject(self, text: str, pat1: str, pat2: str) -> bool:
        """简化: 检查两个模式是否出现在同一段落"""
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            if re.search(pat1, para) and re.search(pat2, para):
                return True
        return False


# 全局单例
_detector: Optional[HallucinationDetector] = None


def get_detector() -> HallucinationDetector:
    global _detector
    if _detector is None:
        _detector = HallucinationDetector(known_sop={
            "红烧肉:盐量": "5g",
            "红烧肉:压制时间": "20分钟",
            "红烧肉:温度": "75°C",
            "麻婆豆腐:盐量": "3g",
            "麻婆豆腐:温度": "75°C",
        })
    return _detector
