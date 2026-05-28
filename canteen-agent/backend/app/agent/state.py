"""Agent 状态定义（TypedDict）"""
from typing import TypedDict, List, Dict, Optional


class AgentState(TypedDict):
    raw_reviews: List[Dict]
    filtered_reviews: List[Dict]
    dish_info: Dict
    risk_level: int
    knowledge_context: str
    conflict_analysis: Dict
    confidence: float
    corrective_action: Optional[str]
    human_review_required: bool
