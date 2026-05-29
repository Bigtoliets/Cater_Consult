"""Agent 状态定义（TypedDict）"""
from typing import TypedDict, List, Dict, Optional
import uuid


def new_decision_id() -> str:
    return f"DEC-{uuid.uuid4().hex[:12].upper()}"


class AgentState(TypedDict):
    # === 原始数据（单条） ===
    review: Dict                       # 单条评价 {raw_text, stall_name, dish_name_raw, ...}
    filtered_review: Dict              # 清洗后的单条结构化结果

    # === 菜品消歧 ===
    dish_info: Dict                    # dish_id, dish_name, stall_name, match_confidence...

    # === 检索 ===
    risk_level: int
    knowledge_context: str             # 双库检索拼接结果（[GOLD] / [STANDARD] 标签）

    # === 输出 ===
    decision_id: str                   # 唯一决策ID，用于后续飞升
    corrective_action: Optional[str]
    human_review_required: bool
