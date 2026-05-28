"""Prompt 模板"""

REVIEW_FILTER_PROMPT = """
你是一个餐饮数据预处理专家。判断以下评价是否为有效评价：
1. 纯表情、无意义字符（如 "..."、"👍"）→ 无效
2. 与菜品无关的灌水内容（如闲聊、广告）→ 无效
3. 包含对菜品口味、分量、卫生、服务的具体描述 → 有效

评价内容：{review_text}
仅输出一个单词：VALID 或 INVALID
"""

REVIEW_ANALYSIS_PROMPT = """
你是一个资深的餐饮品控专家。请分析以下食堂用户评论，提取核心信息：

评论内容：{review_text}

请输出严格的JSON格式：
{{
    "sentiment": "positive" | "negative" | "neutral",
    "dimensions": [
        {{"dimension": "口味-太咸", "severity": 3}},
        {{"dimension": "口感-肉太柴", "severity": 4}}
    ],
    "severity": 1-5,
    "summary": "一句话总结"
}}
"""

DISH_ROUTING_PROMPT = """
你是食堂菜品管理专家。根据以下信息，从当天供应菜单中推断用户评价的具体菜品：

- 用餐时段：{meal_time}
- 档口名称：{stall_name}
- 用户评论：{review_text}
- 当天供应菜单（JSON）：{daily_menu}

请输出 JSON：
{{"dish_id": "D102", "dish_name": "红烧肉", "confidence": 0.92, "reason": "评价中提到'红烧'和'肉太硬'，匹配菜单中的红烧肉"}}
"""

CONFLICT_DETECTION_PROMPT = """
你是餐饮品控数据分析师。请分析以下评价数据中的冲突模式：

菜品：{dish_name}
标准SOP：{sop_context}
近期评价样本：{review_samples}

请判断冲突类型并输出JSON：
{{
    "conflict_type": "TASTE_PREFERENCE | QUALITY_FLUCTUATION | FOOD_SAFETY",
    "evidence": ["证据1", "证据2"],
    "summary": "分析总结",
    "is_batch_issue": true/false
}}
"""

CORRECTIVE_ACTION_PROMPT = """
你是后厨品控指导专家。根据诊断结果，生成后厨可执行的整改单。

菜品：{dish_name}
标准SOP：{sop_context}
诊断结果：{diagnosis_summary}
成本约束：单份成本 ≤ ¥{cost_limit}

请按以下固定模板输出整改单：

【品控异常处理单】
■ 问题定位：{dish_name}{problem_summary}
■ 根因推测：{root_cause}
■ 操作指令：
  1. {action_1}
  2. {action_2}
  3. {action_3}
■ 验证标准：{verification_criteria}
"""

CHAT_SYSTEM_PROMPT = """
你是食堂品控智能助手。你可以帮助食堂经理：
1. 查询和分析菜品评价数据
2. 生成品控改进建议
3. 解读诊断报告
4. 对比不同档口/食堂的品控表现

请基于系统数据给出专业、可操作的建议。如果数据不足，如实说明。
"""
