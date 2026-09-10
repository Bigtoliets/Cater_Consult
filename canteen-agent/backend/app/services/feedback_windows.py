"""整改效果观察窗的纯逻辑 —— 不依赖 DB / ORM，便于离线单测

一条诊断下发生效后，要看 3 / 7 / 14 天的差评率变化。这里只做三件事：
1. 把「整改起点 + 当前时间」换算成各观察窗（窗口右端不能超过 now，否则是在拿未来算分）
2. 标出哪些窗口已经「满窗」（不满窗的窗口不能用来下结论）
3. 按阈值给出处置建议：飞升金标 / 标记失效 / 继续观察
"""
from datetime import datetime, timedelta

# 观察窗（天）
WINDOWS_DAYS = (3, 7, 14)
# 只有满这个天数的窗口才能用于飞升/降级判定
MIN_DAYS_FOR_VERDICT = 7
# 差评率下降超过 10 个百分点 → 方案有效，自动飞升金标
PROMOTE_DELTA = -0.10
# 差评率上升超过 5 个百分点 → 方案失效
DEMOTE_DELTA = 0.05


def tracking_windows(executed_at: datetime, now: datetime) -> dict[int, dict]:
    """算出 3/7/14 天观察窗：{天数: {"start", "end", "full", "elapsed_days"}}

    end 会被 now 截断 —— 否则「整改后 14 天差评率」在整改第 3 天就会用半截数据算出来，
    数字看着像结论，实际只是噪声。
    """
    windows: dict[int, dict] = {}
    for days in WINDOWS_DAYS:
        expected_end = executed_at + timedelta(days=days)
        windows[days] = {
            "start": executed_at,
            "end": min(expected_end, now),
            "full": now >= expected_end,
            "elapsed_days": max(0.0, (now - executed_at).total_seconds() / 86400),
        }
    return windows


def evaluate(pre_negative_rate: float, post_negative_rate_7d: float, windows: dict[int, dict]) -> dict:
    """给出处置建议

    返回 {"verdict": "too_early" | "no_baseline" | "effective" | "ineffective" | "inconclusive",
          "auto_promoted": bool, "auto_demoted": bool, "improvement": float}

    - 整改前没有差评基线（pre=0）：无从判断效果，不飞升也不降级
    - 7 天窗口没满：不给结论（too_early）
    """
    improvement = round(post_negative_rate_7d - pre_negative_rate, 4)
    result = {
        "verdict": "inconclusive",
        "auto_promoted": False,
        "auto_demoted": False,
        "improvement": improvement,
    }

    if not (windows.get(MIN_DAYS_FOR_VERDICT) or {}).get("full"):
        return {**result, "verdict": "too_early"}
    if pre_negative_rate <= 0:
        return {**result, "verdict": "no_baseline"}

    if improvement <= PROMOTE_DELTA:
        return {**result, "verdict": "effective", "auto_promoted": True}
    if improvement >= DEMOTE_DELTA:
        return {**result, "verdict": "ineffective", "auto_demoted": True}
    return result
