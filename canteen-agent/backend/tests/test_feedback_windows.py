"""整改效果观察窗离线自测（不依赖 DB / Redis / 网络）

    python backend/tests/test_feedback_windows.py

盯的是自进化闭环的判定逻辑 —— 之前这里有两个真 bug：
1. 观察窗右端不截断，整改第 3 天就在用「整改后 14 天差评率」下结论；
2. 未满窗也能飞升/降级，把噪声当结论。
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.feedback_windows import (  # noqa: E402
    DEMOTE_DELTA,
    MIN_DAYS_FOR_VERDICT,
    PROMOTE_DELTA,
    evaluate,
    tracking_windows,
)

PASSED, FAILED = [], []


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  → {detail}" if detail and not condition else ""))


def test_windows():
    print("\n[1] 观察窗：右端必须截断在 now，满了才算满")
    executed = datetime(2026, 9, 1, 12, 0, 0)

    windows = tracking_windows(executed, executed + timedelta(days=3, hours=2))
    check("3 天窗口已满", windows[3]["full"] is True)
    check("7 天窗口不满", windows[7]["full"] is False)
    check("不满窗时 end 被 now 截断",
          windows[7]["end"] == executed + timedelta(days=3, hours=2),
          f"实际: {windows[7]['end']}")
    check("满窗时 end 就是到期时刻",
          windows[3]["end"] == executed + timedelta(days=3))

    windows = tracking_windows(executed, executed + timedelta(days=20))
    check("20 天后三个窗口都满",
          all(windows[d]["full"] for d in (3, 7, 14)))
    check("到期日之后 end 不再延后",
          windows[14]["end"] == executed + timedelta(days=14),
          f"实际: {windows[14]['end']}")
    check("elapsed_days 用于观测",
          round(windows[7]["elapsed_days"]) == 20, f"实际: {windows[7]['elapsed_days']}")


def test_evaluate():
    print("\n[2] 判定：满窗 + 有基线 才给结论")
    executed = datetime(2026, 9, 1, 12, 0, 0)
    full = tracking_windows(executed, executed + timedelta(days=10))
    early = tracking_windows(executed, executed + timedelta(days=2))

    r = evaluate(pre_negative_rate=0.30, post_negative_rate_7d=0.10, windows=early)
    check("不满 7 天 → too_early，且不飞升不降级",
          r["verdict"] == "too_early" and not r["auto_promoted"] and not r["auto_demoted"],
          f"实际: {r}")

    r = evaluate(pre_negative_rate=0.0, post_negative_rate_7d=0.05, windows=full)
    check("整改前没有差评基线 → 不给结论",
          r["verdict"] == "no_baseline", f"实际: {r}")

    r = evaluate(pre_negative_rate=0.30, post_negative_rate_7d=0.18, windows=full)
    check("差评率降 12pt → 有效，自动飞升",
          r["verdict"] == "effective" and r["auto_promoted"] is True, f"实际: {r}")
    check("改善幅度按 7 天窗口算",
          abs(r["improvement"] - (0.18 - 0.30)) < 1e-9, f"实际: {r['improvement']}")

    r = evaluate(pre_negative_rate=0.20, post_negative_rate_7d=0.10, windows=full)
    check("降 10pt 正好卡在阈值上 → 飞升",
          r["auto_promoted"] is True and abs(PROMOTE_DELTA + 0.10) < 1e-9, f"实际: {r}")

    r = evaluate(pre_negative_rate=0.10, post_negative_rate_7d=0.18, windows=full)
    check("差评率涨 8pt → 标记失效",
          r["verdict"] == "ineffective" and r["auto_demoted"] is True, f"实际: {r}")

    r = evaluate(pre_negative_rate=0.10, post_negative_rate_7d=0.12, windows=full)
    check("涨 2pt（低于 5pt 阈值）→ 不下结论",
          r["verdict"] == "inconclusive"
          and not r["auto_promoted"] and not r["auto_demoted"], f"实际: {r}")

    r = evaluate(pre_negative_rate=0.10, post_negative_rate_7d=0.10, windows=full)
    check("原地踏步 → 不下结论", r["verdict"] == "inconclusive", f"实际: {r}")
    check("判定窗口取 7 天", MIN_DAYS_FOR_VERDICT == 7)
    check("降级阈值是 5 个百分点", abs(DEMOTE_DELTA - 0.05) < 1e-9)


def main():
    test_windows()
    test_evaluate()
    print(f"\n{'=' * 46}\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
