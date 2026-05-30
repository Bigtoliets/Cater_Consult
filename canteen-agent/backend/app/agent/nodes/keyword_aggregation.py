"""节点①：关键词聚合 —— 按菜品汇总所有评价的关键词"""
from app.state import AgentState

DEFAULT_DIMENSION_WEIGHTS = {
    "口味": 1.0, "卫生": 3.0, "分量": 1.0, "温度": 1.0,
    "口感": 1.5, "价格": 1.0, "服务": 1.0, "安全": 5.0,
}


async def keyword_aggregation(state: AgentState) -> AgentState:
    reviews = state.get("reviews", [])
    keyword_weights = state.get("keyword_weights", DEFAULT_DIMENSION_WEIGHTS)

    dimension_stats: dict = {}
    total_pos = 0
    total_neg = 0
    total_neu = 0
    all_keywords = []

    for r in reviews:
        sentiment = r.get("sentiment", "neutral")
        if sentiment == "positive":
            total_pos += 1
        elif sentiment == "negative":
            total_neg += 1
        else:
            total_neu += 1

        for dim in r.get("dimensions", []):
            dim_name = dim.get("dimension", "其他")
            keyword = dim.get("keyword", "")
            weight = keyword_weights.get(dim_name, 1.0)
            if dim_name not in dimension_stats:
                dimension_stats[dim_name] = {"count": 0, "keywords": [], "weight": weight}
            dimension_stats[dim_name]["count"] += 1
            if keyword and keyword not in dimension_stats[dim_name]["keywords"]:
                dimension_stats[dim_name]["keywords"].append(keyword)
            all_keywords.append(f"[{dim_name}]{keyword}")

    sorted_dims = sorted(dimension_stats.items(), key=lambda x: x[1]["weight"] * x[1]["count"], reverse=True)

    parts = [
        f"菜品「{state.get('dish_name', '未知')}」共 {len(reviews)} 条评价",
        f"好评 {total_pos} / 中性 {total_neu} / 差评 {total_neg}",
        "",
        "投诉维度分布（权重×频次排序）：",
    ]
    for dim_name, stats in sorted_dims:
        parts.append(f"  - {dim_name}(权重{stats['weight']})：{stats['count']}次，关键词：{', '.join(stats['keywords'][:5])}")

    return {
        **state,
        "keyword_summary": "\n".join(parts),
        "keyword_weights": keyword_weights,
    }
