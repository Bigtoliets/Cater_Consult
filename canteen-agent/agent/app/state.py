"""Agent 状态定义（TypedDict）—— v3.0 扩展版"""
from typing import TypedDict, List, Dict, Optional, Any
import uuid


def new_decision_id() -> str:
    return f"DEC-{uuid.uuid4().hex[:12].upper()}"


class AgentState(TypedDict, total=False):
    # === 输入字段 ===
    dish_name: str
    dish_id: str
    reviews: List[Dict]
    keyword_weights: Dict[str, float]

    # === NER 提取结果 (v3.0 新增) ===
    ner_results: List[Dict]

    # === 信号融合 (v3.0 新增) ===
    keyword_summary: str
    conflict_analysis: List[Dict]        # 冲突分析结果列表
    should_trigger_improvement: bool     # 是否触发整改

    # === 知识检索 ===
    gold_context: str
    standard_context: str
    reranked_knowledge: str
    multi_kb_results: Dict[str, Any]     # v3.0: 五库检索结果

    # === 置信度评估 (v3.0 新增) ===
    confidence_score: float              # 综合置信度 0-1
    confidence_action: str               # auto_publish / publish_with_review / escalate
    confidence_factors: Dict[str, float] # 各因子得分

    # === 输出字段 ===
    improvement_summary: str
    improvement_detail: str
    decision_id: str
    human_review_required: bool

    # === Supervisor 路由 (v3.0 新增) ===
    workflow_stage: str                  # classifier / diagnostician / retriever / prescriber / reporter / escalate / done
