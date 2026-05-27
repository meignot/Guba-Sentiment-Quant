# -*- coding: utf-8 -*-
"""基于 100 目录历史 Top100 快照的简易回测工具。

用途：验证活跃度、排名、趋势、涨幅透支等因子与次日收益的关系。
注意：若没有每日完整评分历史，本脚本使用 Top100 字段构造轻量代理评分。
"""
import os
import re
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "100")
OUTPUT_FILE = os.path.join(BASE_DIR, "backtest_result.csv")
SUMMARY_FILE = os.path.join(BASE_DIR, "backtest_summary.md")


def normalize_code(code):
    """统一股票代码为6位字符串。"""
    m = re.search(r"\d+", str(code))
    return m.group(0).zfill(6) if m else ""


def load_daily_data():
    """读取每日最晚 Top100 快照，避免同一天盘中多快照重复计入。"""
    daily = {}
    for filename in sorted(os.listdir(DATA_DIR)):
        m = re.match(r"top100_(\d{8})(?:_(\d{6}))?\.csv", filename)
        if not m:
            continue
        date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
        time_label = m.group(2) or "235959"
        path = os.path.join(DATA_DIR, filename)
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str})
        df["代码"] = df["代码"].apply(normalize_code)
        df["日期"] = pd.to_datetime(df["日期"])
        daily.setdefault(date, []).append((time_label, df))

    rows = []
    for _, items in daily.items():
        items.sort(key=lambda x: x[0])
        rows.append(items[-1][1])

    if not rows:
        raise RuntimeError("100 目录下未找到 top100_*.csv 数据")

    df_all = pd.concat(rows, ignore_index=True)
    df_all["代码"] = df_all["代码"].apply(normalize_code)
    df_all["日期"] = pd.to_datetime(df_all["日期"])
    return df_all.sort_values(["日期", "排名"])


def build_proxy_scores(df_all):
    """为每个历史信号日构造代理评分，并拼接次日涨跌幅。"""
    records = []
    dates = sorted(df_all["日期"].unique())
    for i, date in enumerate(dates[:-1]):
        hist = df_all[df_all["日期"] <= date].copy()
        day = df_all[df_all["日期"] == date].copy()
        next_day = df_all[df_all["日期"] == dates[i + 1]][["代码", "涨跌幅", "收盘"]].rename(
            columns={"涨跌幅": "次日涨跌幅", "收盘": "次日收盘"}
        )

        stats = []
        for code, group in hist.groupby("代码"):
            group = group.sort_values("日期").reset_index(drop=True)
            n_days = len(group)
            up_ratio = (group["涨跌幅"] > 0).mean() * 100
            cum_gain = group["涨跌幅"].sum()
            
            pullbacks = 0
            rebounds = 0
            for j in range(len(group) - 1):
                if group.iloc[j]["涨跌幅"] < 0:
                    pullbacks += 1
                    if group.iloc[j+1]["涨跌幅"] > 0:
                        rebounds += 1
            
            pb_rate = (rebounds / pullbacks * 100) if pullbacks > 0 else np.nan
            
            stats.append({
                "代码": code,
                "出现天数": n_days,
                "上涨占比": up_ratio,
                "近似累涨": cum_gain,
                "历史回调反弹率": pb_rate
            })
            
        df_stats = pd.DataFrame(stats)
        merged = day.merge(df_stats, on="代码", how="left").merge(next_day, on="代码", how="left")
        merged = merged.dropna(subset=["次日涨跌幅"])
        if merged.empty:
            continue

        score = np.zeros(len(merged))
        
        # 1. Frequency
        score += np.where(merged["出现天数"] >= 8, 3, 
                 np.where(merged["出现天数"] >= 5, 2, 0))
        
        # 2. Pullback & Rebound
        is_pullback = merged["涨跌幅"] < 0
        high_rebound = merged["历史回调反弹率"] >= 55
        med_rebound = merged["历史回调反弹率"] >= 45
        score += np.where(is_pullback & high_rebound, 5,
                 np.where(is_pullback & med_rebound, 1, 0))
                 
        # 3. Momentum (momentum_score is 0)
        
        # 4. Rank
        score += np.where(merged["排名"] <= 20, 1, 0)
        
        # 5. Overbought Penalty
        score += np.where(merged["5日涨幅"] >= 15, -6, 0)
        score += np.where(merged["近似累涨"] >= 30, -2, 0)
        
        # 6. Crash Protection
        score += np.where(merged["涨跌幅"] <= -6, -3, 0)

        merged["代理评分"] = score
        merged["信号日期"] = date
        records.append(merged)

    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def summarize(backtest_df):
    """生成 TopN 与评分分层统计。"""
    bt = backtest_df.copy()
    bt["命中"] = bt["次日涨跌幅"] > 0

    topn_parts = []
    for n in [5, 10, 20, 30]:
        picks = bt.sort_values(["信号日期", "代理评分", "排名"], ascending=[True, False, True]).groupby("信号日期").head(n)
        topn_parts.append({
            "组合": f"每日Top{n}",
            "样本数": len(picks),
            "胜率": round(picks["命中"].mean() * 100, 2),
            "平均次日收益": round(picks["次日涨跌幅"].mean(), 3),
            "中位数次日收益": round(picks["次日涨跌幅"].median(), 3),
            "最大单票亏损": round(picks["次日涨跌幅"].min(), 3),
        })

    summary = pd.DataFrame(topn_parts)
    score_bucket = bt.groupby(
        pd.cut(bt["代理评分"], bins=[-99, 3, 5, 7, 99], labels=["<=3", "4-5", "6-7", ">=8"]),
        observed=False,
    ).agg(
        样本数=("代码", "count"),
        胜率=("命中", lambda x: round(x.mean() * 100, 2) if len(x) else np.nan),
        平均次日收益=("次日涨跌幅", lambda x: round(x.mean(), 3) if len(x) else np.nan),
    ).reset_index().rename(columns={"代理评分": "评分分层"})
    return summary, score_bucket


def main():
    df_all = load_daily_data()
    backtest_df = build_proxy_scores(df_all)
    if backtest_df.empty:
        print("样本不足，无法回测。")
        return

    backtest_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    summary, bucket = summarize(backtest_df)

    md = "# Top100 活跃股代理评分回测报告\n\n"
    md += "## 每日按代理评分选股表现\n\n" + summary.to_markdown(index=False) + "\n\n"
    md += "## 评分分层表现\n\n" + bucket.to_markdown(index=False) + "\n\n"
    md += "> 说明：该回测使用历史 Top100 字段构造代理评分，用于验证因子方向；正式交易前仍需结合真实盘中评分、滑点和手续费。\n"
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"回测明细已保存: {OUTPUT_FILE}")
    print(f"回测摘要已保存: {SUMMARY_FILE}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
