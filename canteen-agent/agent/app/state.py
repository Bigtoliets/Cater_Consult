"""Agent 状态定义（TypedDict）—— 菜品级批量处理"""
from typing import TypedDict, List, Dict, Optional
import uuid


def new_decision_id() -> str:
    return f"DEC-{uuid.uuid4().hex[:12].upper()}"


class AgentState(TypedDict):
    dish_name: str
    dish_id: str
    reviews: List[Dict]
    keyword_summary: str
    keyword_weights: Dict[str, float]
    gold_context: str
    standard_context: str
    reranked_knowledge: str
    improvement_summary: str
    improvement_detail: str
    decision_id: str
    human_review_required: bool
