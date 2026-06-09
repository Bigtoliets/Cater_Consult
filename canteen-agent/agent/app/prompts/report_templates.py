"""报告范式模板库 (v3.0 新增)

三种报告范式:
- daily_brief: 每日品控日报
- dish_diagnosis: 单品诊断报告
- weekly_review: 周度品控总结
"""
from datetime import date

# ============================================================
# 日报模板
# ============================================================
DAILY_BRIEF_PROMPT = """你是食堂品控总监。请根据以下数据生成一份专业的每日品控日报。

日期：{date}
总评价数：{total_reviews}
好评率：{positive_rate:.0%} | 中性率：{neutral_rate:.0%} | 差评率：{negative_rate:.0%}

🏆 零差评 TOP3：
{top_good}

⚠️ 红牌预警 TOP3：
{top_bad}

📝 AI 诊断摘要：
{ai_summaries}

请按以下结构输出：

# 📊 {date} 食堂品控日报

## 一、市场总览
[用2-3句话总结今天的品控全局，含与昨天的环比变化（如有）]

## 二、亮点菜品
[分析零差评TOP3的成功经验，提炼可复用的做法]

## 三、重点异常
[分析红牌预警TOP3的根本原因，引用具体差评内容]

## 四、食安事件
[如有食安事件，详细说明时间/菜品/内容/处理状态；如无需注明"今日无食安事件"]

## 五、昨日整改跟踪
[昨日下发的整改单执行情况追踪]

## 六、行动建议
[3-5条具体的后厨管理建议，按优先级排序]
"""

# ============================================================
# 单品诊断模板
# ============================================================
DISH_DIAGNOSIS_PROMPT = """你是菜品品控专家。请为以下菜品生成专业的品控诊断报告。

菜品：{dish_name}
分类：{category}
成本：¥{unit_cost} | 售价：¥{price}

当日评价：{total_reviews} 条 | 差评率：{negative_rate:.0%}

━━━ 📊 信号融合分析 ━━━
{signal_fusion_summary}

━━━ 🔍 冲突检测 ━━━
{conflict_analysis}

━━━ 🗣️ 评价样本 ━━━
{review_samples}

━━━ 📚 历史经验 ━━━
{experience_context}

━━━ 📈 置信度 ━━━
综合置信度：{confidence_score:.0%} | 决策：{confidence_label}

请按以下结构输出：

# 🔍 {dish_name} 品控诊断报告

## 一、问题定位
[明确指出根本原因，引用具体证据]

## 二、历史对比
[与历史同期的品控表现对比分析]

## 三、冲突分析
[区分口味偏好差异和真实品控问题，说明判断依据]

## 四、整改方案
[引用具体SOP条目，给出可量化执行的整改步骤]

## 五、效果预估
[基于相似历史案例，预估整改后的改善幅度和验证周期]
"""

# ============================================================
# 周报模板
# ============================================================
WEEKLY_REVIEW_PROMPT = """你是食堂品控总监。请根据以下数据生成第{week_num}周品控周报。

统计周期：{start_date} ~ {end_date}
总评价数：{total_reviews} | 周好评率：{positive_rate:.0%}

📈 日度差评率趋势：
{daily_trend}

🔝 高发问题排行：
{top_issues}

✅ 本周成功改善案例：
{improvement_cases}

❌ 持续问题菜品：
{persistent_issues}

请按以下结构输出：

# 📈 第{week_num}周品控周报

## 一、周度趋势总览
[分析本周品控走势，与上周对比]

## 二、高发问题深度分析
[对TOP3问题做根因分析，关联到具体档口/厨师/工艺环节]

## 三、改善案例复盘
[分析本周成功改善的案例，提炼方法论]

## 四、持续问题预警
[标注本周仍未解决的问题，给出强化建议]

## 五、SOP更新建议
[基于本周新发现，建议新增或修订的SOP条目]

## 六、下周重点关注
[预测下周可能的风险点，给出预防措施]
"""


# ============================================================
# 辅助函数
# ============================================================
def format_report_date(d: date | None = None) -> str:
    if d is None:
        d = date.today()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekdays[d.weekday()]
    return f"{d.strftime('%Y年%m月%d日')} 星期{wd}"


def format_daily_brief_params(
    d: date,
    total: int, pos_rate: float, neu_rate: float, neg_rate: float,
    top_good: list, top_bad: list, ai_summaries: str,
) -> dict:
    return {
        "date": format_report_date(d),
        "total_reviews": total,
        "positive_rate": pos_rate,
        "neutral_rate": neu_rate,
        "negative_rate": neg_rate,
        "top_good": _format_top_list(top_good, "好评"),
        "top_bad": _format_top_list(top_bad, "差评"),
        "ai_summaries": ai_summaries or "暂无",
    }


def _format_top_list(items: list, label: str) -> str:
    if not items:
        return f"暂无{label}数据"
    lines = []
    for i, item in enumerate(items[:3]):
        did = item.get("dish_id", "?")
        dname = item.get("dish_name", f"菜品#{did}")
        cnt = item.get("count", 0)
        lines.append(f"{i+1}. {dname} - {cnt}条")
    return "\n".join(lines)
