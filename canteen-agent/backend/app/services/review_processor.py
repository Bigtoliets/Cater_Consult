"""上传后自动处理：情感分析 + 菜品匹配（支持关键词权重配置）
在 Agent 管道之前做快速预处理，让数据导入后立即可在 Dashboard 看到。
"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Review, Dish, Sentiment, SystemConfig

POSITIVE_WORDS = [
    "好吃", "不错", "很好", "满意", "推荐", "棒", "赞", "香", "美味",
    "新鲜", "嫩", "入味", "正宗", "分量足", "划算", "干净", "热情",
    "喜欢", "爱", "绝了", "给力", "优秀", "完美", "超值", "惊喜",
    "挺好的", "还可以", "还行", "不错哦", "不错啊", "好吃啊",
]

NEGATIVE_WORDS = [
    "难吃", "差", "不好", "失望", "恶心", "咸", "太咸", "太淡", "没味道",
    "不新鲜", "凉", "冷", "硬", "太硬", "软", "太软", "烂", "糊",
    "少", "太少", "分量少", "贵", "太贵", "不值", "坑", "烂透了",
    "不干净", "脏", "头发", "虫子", "异物", "变质", "馊", "臭",
    "拉肚子", "肚子疼", "不舒服", "态度差", "慢", "太慢", "等太久",
    "糊了", "焦", "生", "没熟", "腥", "油腻", "太油", "不好吃",
]

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


def _analyze_sentiment(text: str) -> str:
    if not text:
        return Sentiment.NEUTRAL.value
    pos_score = sum(1 for w in POSITIVE_WORDS if w in text)
    neg_score = sum(1 for w in NEGATIVE_WORDS if w in text)
    if neg_score > pos_score:
        return Sentiment.NEGATIVE.value
    elif pos_score > neg_score:
        return Sentiment.POSITIVE.value
    return Sentiment.NEUTRAL.value


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


async def match_dish(db: AsyncSession, dish_name_raw: str, stall_name: str = "") -> int | None:
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
            review.dish_id = await match_dish(db, review.dish_name_raw, review.stall_name or "")
        processed += 1

    await db.flush()
    return {"processed": processed}


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
            "raw_text": r.raw_text or "",
            "sentiment": r.sentiment.value if r.sentiment else "neutral",
            "dimensions": r.dimensions or [],
            "severity": r.risk_level or 1,
            "summary": (r.raw_text or "")[:80],
        })

    return groups
