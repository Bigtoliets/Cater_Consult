"""上传后自动处理：情感分析 + 菜品匹配（支持关键词权重配置）
在 Agent 管道之前做快速预处理，让数据导入后立即可在 Dashboard 看到。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Review, Dish, Sentiment, SystemConfig

logger = logging.getLogger(__name__)

# 情感词典（带权重）：value 为权重，权重越高代表情感越强
POSITIVE_WORDS = {
    # 强好评
    "美味": 3, "绝了": 3, "完美": 3,
    # 明确好评
    "好吃": 2, "很好": 2, "满意": 2, "推荐": 2, "棒": 2, "赞": 2,
    "入味": 2, "正宗": 2, "分量足": 2, "划算": 2, "干净": 2, "热情": 2,
    "给力": 2, "优秀": 2, "超值": 2, "惊喜": 2, "好吃啊": 2,
    # 轻微好评
    "不错": 1, "香": 1, "新鲜": 1, "嫩": 1, "喜欢": 1, "爱": 1,
    "挺好的": 1, "还可以": 1, "还行": 1, "不错哦": 1, "不错啊": 1,
}

NEGATIVE_WORDS = {
    # 严重 / 安全 / 异物（高权重）
    "难吃": 3, "恶心": 3, "变质": 3, "馊": 3, "臭": 3,
    "拉肚子": 3, "肚子疼": 3, "头发": 3, "虫子": 3, "异物": 3,
    "烂透了": 3, "不好吃": 3, "生": 3, "没熟": 3,
    # 明确负面（中权重）
    "失望": 2, "咸": 2, "太咸": 2, "太淡": 2, "没味道": 2, "不新鲜": 2,
    "太硬": 2, "太软": 2, "烂": 2, "糊": 2, "太少": 2, "分量少": 2,
    "贵": 2, "太贵": 2, "不值": 2, "坑": 2, "不干净": 2, "脏": 2,
    "不舒服": 2, "态度差": 2, "太慢": 2, "等太久": 2, "糊了": 2,
    "焦": 2, "腥": 2, "油腻": 2, "太油": 2,
    # 轻微负面（低权重）
    "差": 1, "不好": 1, "凉": 1, "冷": 1, "硬": 1, "软": 1, "少": 1, "慢": 1,
}

DIMENSION_KEYWORDS = {
    "口味": ["咸", "淡", "甜", "辣", "酸", "苦", "没味道", "太咸", "太淡", "太辣", "不好吃", "难吃", "腥", "油腻", "糊"],
    "卫生": ["脏", "不干净", "头发", "虫子", "异物", "苍蝇", "蟑螂", "不卫生", "变质", "馊", "臭", "发霉"],
    "分量": ["少", "太少", "分量少", "不够吃", "吃不饱", "量少", "太少了", "少了"],
    "温度": ["凉", "冷", "不热", "温", "凉了", "冷了", "冰"],
    "口感": ["硬", "太硬", "软", "太软", "烂", "糊", "焦", "生", "没熟", "老了", "柴"],
    "价格": ["贵", "太贵", "不值", "坑", "不划算", "涨价", "贵了"],
    "服务": ["态度差", "慢", "太慢", "等太久", "不热情", "凶", "不耐烦"],
    "安全": ["拉肚子", "肚子疼", "不舒服", "中毒", "过敏", "腹泻", "呕吐"],
}

DEFAULT_DIMENSION_WEIGHTS = {
    "口味": 1.0, "卫生": 3.0, "分量": 1.0, "温度": 1.0,
    "口感": 1.5, "价格": 1.0, "服务": 1.0, "安全": 5.0,
}


async def get_keyword_weights(db: AsyncSession) -> dict:
    """从 SystemConfig 加载关键词权重（与默认值合并）"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key == "keyword_weights")
    )
    config = result.scalar_one_or_none()
    if config and config.config_value:
        merged = {**DEFAULT_DIMENSION_WEIGHTS, **config.config_value}
        return merged
    return dict(DEFAULT_DIMENSION_WEIGHTS)


NEGATION_WORDS = ("不是", "没有", "并不", "不太", "不怎么", "不", "没")


def _is_negated(text: str, start: int) -> bool:
    """判断情感词前面（≤3 字窗口）是否紧跟否定词"""
    prefix = text[max(0, start - 3):start]
    return any(nw in prefix for nw in NEGATION_WORDS)


def _analyze_sentiment(text: str) -> str:
    """情感分析：带权重的关键词匹配 + 否定翻转 + 平局偏负面

    相比旧版（纯计数）：
    1. 词按权重累加，而非每个词记 1 分
    2. 否定词（不/没/不是...）出现在情感词前 3 字内 → 极性翻转
    3. 正负打平时，只要存在负面词就判负面（业务上优先抓问题）
    """
    if not text:
        return Sentiment.NEUTRAL.value

    pos_score = 0
    neg_score = 0

    # 正面词：命中加分，被否定则反转到负面（如「不是很好」→ 负面）
    for word, weight in POSITIVE_WORDS.items():
        idx = text.find(word)
        if idx == -1:
            continue
        if _is_negated(text, idx):
            neg_score += weight
        else:
            pos_score += weight

    # 负面词：命中加分，被否定则反转到正面（如「不难吃」→ 正面）
    for word, weight in NEGATIVE_WORDS.items():
        idx = text.find(word)
        if idx == -1:
            continue
        if _is_negated(text, idx):
            pos_score += weight
        else:
            neg_score += weight

    if neg_score > pos_score:
        return Sentiment.NEGATIVE.value
    if pos_score > neg_score:
        return Sentiment.POSITIVE.value
    # 平局：有负面词就偏负面（抓问题优先），否则中性
    return Sentiment.NEGATIVE.value if neg_score > 0 else Sentiment.NEUTRAL.value


def _extract_dimensions(text: str) -> list:
    if not text:
        return []
    dimensions = []
    for dim, keywords in DIMENSION_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                dimensions.append({"dimension": dim, "keyword": kw})
                break
    return dimensions


def _calc_risk_level(sentiment: str, dimensions: list, text: str) -> int:
    risk = 1
    if sentiment == Sentiment.NEGATIVE.value:
        risk = 2
    for d in dimensions:
        if d["dimension"] in ("安全", "卫生"):
            risk = max(risk, 5)
        elif d["dimension"] in ("口感", "口味"):
            risk = max(risk, 3)
    emergency_words = ["中毒", "过敏", "拉肚子", "腹泻", "呕吐", "医院", "投诉", "举报"]
    if any(w in text for w in emergency_words):
        risk = 5
    return risk


async def match_dish(db: AsyncSession, dish_name_raw: str) -> int | None:
    if not dish_name_raw:
        return None
    result = await db.execute(
        select(Dish.id).where(Dish.name == dish_name_raw.strip())
    )
    dish_id = result.scalar_one_or_none()
    if dish_id:
        return dish_id
    result = await db.execute(select(Dish.id, Dish.name))
    all_dishes = result.all()
    name_clean = dish_name_raw.strip().replace(" ", "")
    for did, dname in all_dishes:
        dname_clean = dname.replace(" ", "")
        if name_clean in dname_clean or dname_clean in name_clean:
            return did
    return None


async def process_new_reviews(db: AsyncSession, review_ids: list[int]) -> dict:
    if not review_ids:
        return {"processed": 0}

    result = await db.execute(
        select(Review).where(Review.id.in_(review_ids))
    )
    reviews = result.scalars().all()

    processed = 0
    critical_reviews = []  # v3.0: 收集高风险评价用于告警

    for review in reviews:
        text = review.raw_text or ""
        sentiment = _analyze_sentiment(text)
        review.sentiment = Sentiment(sentiment)
        if sentiment == Sentiment.NEGATIVE.value:
            review.dimensions = _extract_dimensions(text)
        else:
            review.dimensions = []
        review.risk_level = _calc_risk_level(sentiment, review.dimensions or [], text)
        if review.dish_name_raw:
            review.dish_id = await match_dish(db, review.dish_name_raw)
        # 前置节点只做召回：词典标签是"候选提示"，不是结论。
        # Agent 深度加工后会回写精判结果并把 label_source 覆盖为 'llm'。
        review.label_source = "dict"
        processed += 1

        # 收集高风险评价
        if review.risk_level >= 5:
            critical_reviews.append(review)

    await db.flush()

    # v3.0: 高风险评价即时推送告警
    if critical_reviews:
        await _alert_critical_reviews(critical_reviews, db)

    return {"processed": processed}


async def _alert_critical_reviews(reviews: list, db: AsyncSession | None = None):
    """v3.0: 对食安级别评价即时推送告警

    传 db 才会走 SystemConfig.push_rules 的自定义路由；不传就永远是默认通道。
    """
    try:
        from app.push.dispatcher import get_dispatcher
        from app.push.base import Alert, AlertLevel

        dispatcher = get_dispatcher()
        for r in reviews:
            await dispatcher.dispatch(Alert(
                level=AlertLevel.CRITICAL,
                title=f"🚨 食安告警：{r.dish_name_raw or '未知菜品'}",
                content=f"**风险等级**：{r.risk_level}/5\n"
                        f"**评价内容**：{r.raw_text[:200]}\n"
                        f"**评价来源**：{r.source or '未知'}",
                dish_name=r.dish_name_raw,
            ), db=db)
    except Exception as e:  # noqa: BLE001 — 推送失败不影响主链路
        logger.warning(f"[Alert] 推送失败: {e}")


async def get_dish_review_groups(db: AsyncSession, review_ids: list[int]) -> dict[str, list]:
    """按 dish_id 聚合评价，返回 {dish_key: [reviews]}，供 Agent 批量分析"""
    result = await db.execute(
        select(Review).where(Review.id.in_(review_ids))
    )
    reviews = result.scalars().all()

    groups: dict = {}
    for r in reviews:
        key = str(r.dish_id) if r.dish_id else f"raw:{r.dish_name_raw or '未知'}"
        if key not in groups:
            groups[key] = {
                "dish_id": str(r.dish_id) if r.dish_id else "UNKNOWN",
                "dish_name": r.dish_name_raw or "未知菜品",
                "reviews": [],
            }
        groups[key]["reviews"].append({
            "review_id": r.id,  # Agent 精判后按此回写标签
            "raw_text": r.raw_text or "",
            "sentiment": r.sentiment.value if r.sentiment else "neutral",
            "dimensions": r.dimensions or [],
            "severity": r.risk_level or 1,
            "summary": (r.raw_text or "")[:80],
        })

    return groups
