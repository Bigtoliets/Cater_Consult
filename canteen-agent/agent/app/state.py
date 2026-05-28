"""Agent 状态定义（TypedDict）"""
from typing import TypedDict, List, Dict, Optional


class AgentState(TypedDict):
    # === 原始数据 ===
    raw_reviews: List[Dict]            # 批量流入的原始评价
    filtered_reviews: List[Dict]       # 清洗后的有效评价

    # === 菜品消歧结果 ===
    dish_info: Dict                    # {"dish_id": "D102", "dish_name": "土豆肉丝",
                                       #  "chef_id": "C005", "stall_name": "二楼川湘档口",
                                       #  "meal_time": "lunch", "match_confidence": 0.92}

    # === 风险与知识 ===
    risk_level: int                    # 风险等级 1-5
    knowledge_context: str             # SOP标准 + 历史客诉 + 成本约束

    # === 分析与决策 ===
    conflict_analysis: Dict            # 冲突检测结构
    confidence: float                  # 系统综合置信度 0.0-1.0

    # === 输出 ===
    corrective_action: Optional[str]   # 最终生成的整改单文本
    human_review_required: bool        # 是否需要人工复核
