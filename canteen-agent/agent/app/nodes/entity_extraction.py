"""节点 0：LLM-based 实体识别与事件分类 (v3.0 新增)

从顾客评价中提取:
- dish: 被评价菜品名
- issue: 具体问题描述
- process: 涉及的后厨工艺环节
- event_type: 事件分类
- severity: 严重度 1-5
- is_preference: 是否为口味偏好差异

降级策略: LLM 不可用时回退到关键词词典匹配
"""

import json
import re
from app.state import AgentState
from app.utils.llm import get_llm

NER_SYSTEM_PROMPT = """你是后厨品控NER专家。从顾客评价中提取结构化信息。

对每条评价输出一个JSON对象 (不要数组, 每条评价独立分析):
{
  "dish": "被评价的菜品名",
  "issue": "顾客反映的具体问题 (如'太咸''有头发''分量少''肉太硬')",
  "process": "涉及的后厨工艺环节 (火候/调味/刀工/食材/卫生/服务/价格/分量/温度/其他)",
  "event_type": "事件分类 (taste_complaint/safety_incident/service_issue/portion_complaint/price_complaint/other)",
  "severity": 严重度1-5 (1=轻微偏好差异, 3=明显品控问题, 5=安全风险),
  "is_preference": true/false (是否为口味偏好差异, 非品控波动)
}

判断is_preference的关键依据:
- 主观偏好词("我觉得""我不喜欢""吃不惯") → true
- 客观标准问题("没熟""有异物""变质""拉肚子") → false
- 同菜品矛盾评价(有人咸有人淡) → 偏true

只输出JSON, 不要任何解释."""

# 规则降级词典
FALLBACK_DIMENSIONS = {
    "口味": ["咸", "淡", "甜", "辣", "酸", "苦", "没味道", "太咸", "太淡", "太辣", "不好吃", "难吃", "腥", "油腻", "糊"],
    "卫生": ["脏", "不干净", "头发", "虫子", "异物", "苍蝇", "蟑螂", "不卫生", "变质", "馊", "臭", "发霉"],
    "分量": ["少", "太少", "分量少", "不够吃", "吃不饱", "量少"],
    "温度": ["凉", "冷", "不热", "温", "凉了", "冷了"],
    "口感": ["硬", "太硬", "软", "太软", "烂", "糊", "焦", "生", "没熟", "老了", "柴"],
    "价格": ["贵", "太贵", "不值", "坑", "不划算", "涨价"],
    "服务": ["态度差", "慢", "太慢", "等太久", "不热情", "凶", "不耐烦"],
    "安全": ["拉肚子", "肚子疼", "不舒服", "中毒", "过敏", "腹泻", "呕吐"],
}

PREFERENCE_KEYWORDS = ["我觉得", "我不喜欢", "吃不惯", "不合口味", "不习惯", "我个人", "对我来说"]
SAFETY_KEYWORDS = ["中毒", "过敏", "拉肚子", "腹泻", "呕吐", "异物", "头发", "虫子", "变质", "医院"]


async def entity_extraction(state: AgentState) -> AgentState:
    """NER 实体提取节点 — 对每条评价做结构化信息提取"""
    reviews = state.get("reviews", [])
    if not reviews:
        return {**state, "ner_results": []}

    # 批量处理：每 15 条一批送给 LLM
    batch_size = 15
    all_ner = []

    for i in range(0, len(reviews), batch_size):
        batch = reviews[i:i + batch_size]
        # 编号后送给 LLM
        numbered = "\n\n".join(
            f"[{idx}] {r.get('raw_text', r.get('summary', ''))[:200]}"
            for idx, r in enumerate(batch)
        )

        try:
            llm = get_llm()
            response = await llm.ainvoke([
                {"role": "system", "content": NER_SYSTEM_PROMPT},
                {"role": "user", "content": f"请逐一分析以下评价，每条输出一个JSON对象，用换行分隔:\n\n{numbered}"},
            ])
            parsed = _parse_ner_response(response.content, len(batch))
            all_ner.extend(parsed)
        except Exception as e:
            print(f"[NER] LLM 调用失败, 降级到规则提取: {e}")
            for r in batch:
                all_ner.append(_fallback_ner(r))

    # 将 NER 结果附加到 reviews
    enriched_reviews = []
    for idx, review in enumerate(reviews):
        ner = all_ner[idx] if idx < len(all_ner) else _fallback_ner(review)
        # NER 维度合并到现有 dimensions
        dims = list(review.get("dimensions", []))
        if ner.get("dimension") and ner.get("dimension") != "其他":
            dims.append({
                "dimension": ner["dimension"],
                "keyword": ner.get("issue", ""),
            })
        enriched_reviews.append({
            **review,
            "ner_entities": ner,
            "dimensions": dims,
        })

    return {
        **state,
        "reviews": enriched_reviews,
        "ner_results": all_ner,
        "workflow_stage": "classifier_done",
    }


def _parse_ner_response(text: str, expected_count: int) -> list[dict]:
    """从 LLM 响应中提取 JSON 对象列表"""
    results = []

    # 按行尝试解析每个 JSON 对象
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            results.append(_normalize_ner(obj))
        except json.JSONDecodeError:
            continue

    # 如果逐行解析数量不够, 尝试整个文本作为数组
    if len(results) < expected_count:
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                arr = json.loads(match.group(0))
                if isinstance(arr, list):
                    results = [_normalize_ner(item) for item in arr]
            except json.JSONDecodeError:
                pass

    # 补齐不足的数量
    while len(results) < expected_count:
        results.append(_fallback_ner({"raw_text": ""}))

    return results[:expected_count]


def _normalize_ner(raw: dict) -> dict:
    """标准化 NER 输出字段"""
    return {
        "dish": raw.get("dish", ""),
        "issue": raw.get("issue", ""),
        "process": raw.get("process", "其他"),
        "dimension": _map_process_to_dimension(raw.get("process", "")),
        "event_type": raw.get("event_type", "other"),
        "severity": max(1, min(5, raw.get("severity", 1))),
        "is_preference": raw.get("is_preference", False),
    }


def _map_process_to_dimension(process: str) -> str:
    mapping = {
        "火候": "口感", "调味": "口味", "刀工": "口感",
        "食材": "卫生", "卫生": "卫生", "服务": "服务",
        "价格": "价格", "分量": "分量", "温度": "温度",
    }
    return mapping.get(process, "其他")


def _fallback_ner(review: dict) -> dict:
    """规则降级 NER — 使用关键词词典"""
    text = review.get("raw_text", review.get("summary", ""))

    dimension = "其他"
    issue = ""
    process = "其他"
    event_type = "other"
    severity = 1
    is_preference = False

    # 维度匹配
    for dim, keywords in FALLBACK_DIMENSIONS.items():
        for kw in keywords:
            if kw in text:
                dimension = dim
                issue = kw
                break
        if dimension != "其他":
            break

    # 工艺映射
    process_map = {"口味": "调味", "卫生": "食材", "口感": "火候", "温度": "火候", "分量": "分量", "价格": "价格", "服务": "服务", "安全": "食材"}
    process = process_map.get(dimension, "其他")

    # 事件类型
    if dimension == "安全":
        event_type = "safety_incident"
    elif dimension in ("口味", "口感", "温度"):
        event_type = "taste_complaint"
    elif dimension == "分量":
        event_type = "portion_complaint"
    elif dimension == "价格":
        event_type = "price_complaint"
    elif dimension == "服务":
        event_type = "service_issue"

    # 严重度
    if dimension == "安全":
        severity = 5
    elif dimension in ("卫生", "口感"):
        severity = 3
    elif dimension == "口味":
        severity = 2

    # 安全关键词检查
    if any(kw in text for kw in SAFETY_KEYWORDS):
        severity = 5
        dimension = "安全"

    # 偏好判断
    is_preference = any(kw in text for kw in PREFERENCE_KEYWORDS)

    return {
        "dish": review.get("dish_name", ""),
        "issue": issue,
        "process": process,
        "dimension": dimension,
        "event_type": event_type,
        "severity": severity,
        "is_preference": is_preference,
    }
