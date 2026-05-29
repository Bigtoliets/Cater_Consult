"""每日菜品质量日报 API"""
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date

from app.models import get_db, Review, DailySummary, Sentiment

router = APIRouter()


def _generate_summary(total: int, pos: int, neu: int, neg: int,
                      top_good: list, top_bad: list) -> str:
    """根据统计数据实时生成 AI 摘要"""
    if total == 0:
        return "今日暂无评价数据。"

    pos_rate = pos / total * 100
    neg_rate = neg / total * 100

    lines = [
        f"今日共收到 {total} 条有效评价。",
        f"好评率 {pos_rate:.0f}%，差评率 {neg_rate:.0f}%。",
    ]

    if top_good:
        names = ", ".join(item["dish_name"] for item in top_good[:3])
        lines.append(f"零差评菜品 TOP：{names}。")

    if top_bad:
        names = ", ".join(item["dish_name"] for item in top_bad[:3])
        lines.append(f"⚠️ 红牌预警菜品：{names}，建议优先跟进整改。")

    if neg_rate > 10:
        lines.append("整体差评率偏高，请关注档口出品质量。")
    elif neg_rate < 3:
        lines.append("整体评价良好，继续保持。")

    return "".join(lines)


@router.get("/summary")
async def get_daily_summary(
    target_date: date = Query(None, description="查询日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """获取日报摘要：全局情绪指数、红黑榜、AI摘要"""
    if target_date is None:
        target_date = date.today()

    # 查询缓存的日报
    result = await db.execute(
        select(DailySummary).where(func.date(DailySummary.date) == target_date)
    )
    summary = result.scalar_one_or_none()

    if summary:
        return {
            "date": str(target_date),
            "total_reviews": summary.total_reviews,
            "positive_rate": summary.positive_rate,
            "neutral_rate": summary.neutral_rate,
            "negative_rate": summary.negative_rate,
            "top_good": summary.top_good,
            "top_bad": summary.top_bad,
            "radar_data": summary.radar_data,
            "ai_summary": summary.ai_summary,
            "cached": True,
        }

    # 实时计算
    reviews_query = select(Review).where(
        func.date(Review.reviewed_at) == target_date,
        Review.is_valid == True,
    )
    result = await db.execute(reviews_query)
    reviews = result.scalars().all()

    total = len(reviews)
    if total == 0:
        return {
            "date": str(target_date),
            "total_reviews": 0,
            "positive_rate": 0,
            "neutral_rate": 0,
            "negative_rate": 0,
            "top_good": [],
            "top_bad": [],
            "radar_data": [],
            "ai_summary": "今日暂无评价数据。",
            "cached": False,
        }

    pos = sum(1 for r in reviews if r.sentiment == Sentiment.POSITIVE)
    neu = sum(1 for r in reviews if r.sentiment == Sentiment.NEUTRAL)
    neg = sum(1 for r in reviews if r.sentiment == Sentiment.NEGATIVE)

    # 批量获取已匹配的菜品名称
    matched_dish_ids = list({r.dish_id for r in reviews if r.dish_id})
    dish_name_map = {}
    if matched_dish_ids:
        from app.models.models import Dish
        dish_result = await db.execute(
            select(Dish.id, Dish.name).where(Dish.id.in_(matched_dish_ids))
        )
        dish_name_map = {did: dname for did, dname in dish_result.all()}

    # 计算菜品维度统计（优先 dish_id，降级到 dish_name_raw）
    dish_neg_count: dict[str, dict] = {}   # key -> {count, dish_id, dish_name}
    dish_pos_count: dict[str, dict] = {}

    def _get_dish_key(r) -> str | None:
        """获取菜品分组键：dish_id > dish_name_raw > None"""
        if r.dish_id:
            return f"id:{r.dish_id}"
        if r.dish_name_raw and r.dish_name_raw.strip():
            return f"raw:{r.dish_name_raw.strip()}"
        return None

    def _get_dish_label(r) -> str:
        """获取菜品显示名"""
        if r.dish_id and r.dish_id in dish_name_map:
            return dish_name_map[r.dish_id]
        if r.dish_name_raw and r.dish_name_raw.strip():
            return r.dish_name_raw.strip()
        return "未知菜品"

    for r in reviews:
        key = _get_dish_key(r)
        if not key:
            continue
        if r.sentiment == Sentiment.NEGATIVE:
            if key not in dish_neg_count:
                dish_neg_count[key] = {"count": 0, "dish_id": r.dish_id, "dish_name": _get_dish_label(r)}
            dish_neg_count[key]["count"] += 1
        elif r.sentiment == Sentiment.POSITIVE:
            if key not in dish_pos_count:
                dish_pos_count[key] = {"count": 0, "dish_id": r.dish_id, "dish_name": _get_dish_label(r)}
            dish_pos_count[key]["count"] += 1

    top_bad = sorted(dish_neg_count.values(), key=lambda x: x["count"], reverse=True)[:3]
    top_good = sorted(dish_pos_count.values(), key=lambda x: x["count"], reverse=True)[:3]

    # 实时生成 AI 摘要
    ai_summary = _generate_summary(total, pos, neu, neg, top_good, top_bad)

    return {
        "date": str(target_date),
        "total_reviews": total,
        "positive_rate": round(pos / total, 2),
        "neutral_rate": round(neu / total, 2),
        "negative_rate": round(neg / total, 2),
        "top_good": top_good,
        "top_bad": top_bad,
        "radar_data": [],
        "ai_summary": ai_summary,
        "cached": False,
    }


@router.get("/radar")
async def get_complaint_radar(
    target_date: date = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取槽点雷达图数据"""
    if target_date is None:
        target_date = date.today()

    result = await db.execute(
        select(Review).where(
            func.date(Review.reviewed_at) == target_date,
            Review.is_valid == True,
            Review.sentiment == Sentiment.NEGATIVE,
        )
    )
    reviews = result.scalars().all()

    # 汇总吐槽维度
    dimension_count = {}
    for r in reviews:
        if r.dimensions:
            for dim in r.dimensions:
                key = dim.get("dimension", "其他")
                dimension_count[key] = dimension_count.get(key, 0) + 1

    total_dim = sum(dimension_count.values()) or 1
    radar_data = [
        {"name": k, "value": v, "rate": round(v / total_dim, 2)}
        for k, v in sorted(dimension_count.items(), key=lambda x: x[1], reverse=True)
    ]
    return {"date": str(target_date), "radar": radar_data}


@router.get("/summary-table")
async def get_summary_table(
    target_date: date = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    核心改进摘要表格：
      1. 查 diagnoses 表（已包含 Agent 流水线生成的 corrective_action）
      2. 按菜品聚合，LLM 融合已有的技术决策为一份主厨摘要
      3. 返回子决策列表，供前端展开 + 单条点赞
    返回: [{dish_name, negative_count, corrective_summary, decisions: [{decision_id, corrective_action}]}]
    """
    if target_date is None:
        target_date = date.today()

    from app.models.models import Diagnosis, Dish

    # 查当日有整改单的诊断记录
    result = await db.execute(
        select(Diagnosis).where(
            func.date(Diagnosis.created_at) == target_date,
            Diagnosis.corrective_action.isnot(None),
        )
    )
    diagnoses = result.scalars().all()

    if not diagnoses:
        return {"date": str(target_date), "table": []}

    # 批量取菜品名
    dish_ids = list({d.dish_id for d in diagnoses if d.dish_id})
    dish_name_map = {}
    if dish_ids:
        dish_result = await db.execute(
            select(Dish.id, Dish.name).where(Dish.id.in_(dish_ids))
        )
        dish_name_map = {did: dname for did, dname in dish_result.all()}

    # 按菜品分组
    groups: dict[str, dict] = {}
    for d in diagnoses:
        key = str(d.dish_id) if d.dish_id else "未知菜品"
        if key not in groups:
            groups[key] = {"decisions": [], "dish_id": d.dish_id}
        groups[key]["decisions"].append({
            "decision_id": d.decision_id,
            "corrective_action": d.corrective_action,
        })

    table = []

    for key, group in groups.items():
        dish_name = dish_name_map.get(group["dish_id"], "未知菜品") if group["dish_id"] else key
        decisions = group["decisions"]

        # 不调 LLM — 直接拼接已有决策预览，毫秒级响应
        if len(decisions) == 1:
            summary = decisions[0]["corrective_action"][:100]
        else:
            preview = decisions[0]["corrective_action"][:60]
            summary = f"共 {len(decisions)} 条整改决策。{preview}..."

        table.append({
            "dish_name": dish_name,
            "negative_count": len(decisions),
            "corrective_summary": summary,
            "decisions": decisions,
        })

    return {"date": str(target_date), "table": table}
