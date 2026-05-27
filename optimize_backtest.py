# -*- coding: utf-8 -*-
"""
Strategy Refined Grid Search Optimization
"""
import os
import re
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "100")

def normalize_code(code):
    m = re.search(r"\d+", str(code))
    return m.group(0).zfill(6) if m else ""

def load_daily_data():
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

    df_all = pd.concat(rows, ignore_index=True)
    df_all["代码"] = df_all["代码"].apply(normalize_code)
    df_all["日期"] = pd.to_datetime(df_all["日期"])
    return df_all.sort_values(["日期", "排名"])

def build_dataset(df_all):
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
                "历史回调数": pullbacks,
                "历史回调反弹率": pb_rate
            })
            
        df_stats = pd.DataFrame(stats)
        merged = day.merge(df_stats, on="代码", how="left").merge(next_day, on="代码", how="left")
        merged = merged.dropna(subset=["次日涨跌幅"])
        if merged.empty:
            continue
        merged["信号日期"] = date
        records.append(merged)
        
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()

def evaluate_score(df_dataset, params):
    df = df_dataset.copy()
    score = np.zeros(len(df))
    
    # 1. Frequency
    score += np.where(df["出现天数"] >= params['freq_high_days'], params['freq_high_score'], 
             np.where(df["出现天数"] >= params['freq_med_days'], params['freq_med_score'], 0))
    
    # 2. Pullback & Rebound
    is_pullback = df["涨跌幅"] < 0
    high_rebound = df["历史回调反弹率"] >= params['rebound_high_pct']
    med_rebound = df["历史回调反弹率"] >= params['rebound_med_pct']
    score += np.where(is_pullback & high_rebound, params['rebound_high_score'],
             np.where(is_pullback & med_rebound, params['rebound_med_score'], 0))
             
    # 3. Momentum (can be negative to penalize chasing high momentum)
    is_momentum = df["涨跌幅"] > 0
    score += np.where(is_momentum, params['momentum_score'], 0)
    
    # 4. Rank
    score += np.where(df["排名"] <= params['rank_top'], params['rank_score'], 0)
    
    # 5. Overbought Penalty
    score += np.where(df["5日涨幅"] >= params['overbought_5d_pct'], params['overbought_5d_penalty'], 0)
    score += np.where(df["近似累涨"] >= params['overbought_cum_pct'], params['overbought_cum_penalty'], 0)
    
    # 6. Technical Crash protection
    score += np.where(df["涨跌幅"] <= params['crash_pct'], params['crash_penalty'], 0)
    
    df["代理评分"] = score
    df["命中"] = df["次日涨跌幅"] > 0
    
    # Calculate performance for Top 5 and Top 10
    top5 = df.sort_values(["信号日期", "代理评分", "排名"], ascending=[True, False, True]).groupby("信号日期").head(5)
    top10 = df.sort_values(["信号日期", "代理评分", "排名"], ascending=[True, False, True]).groupby("信号日期").head(10)
    
    top5_win = top5["命中"].mean() * 100
    top5_ret = top5["次日涨跌幅"].mean()
    top10_win = top10["命中"].mean() * 100
    top10_ret = top10["次日涨跌幅"].mean()
    
    # Tier analysis
    bucket = df.groupby(
        pd.cut(df["代理评分"], bins=[-99, 3, 5, 7, 99], labels=["<=3", "4-5", "6-7", ">=8"]),
        observed=False
    )
    
    tier_stats = {}
    for name, grp in bucket:
        if len(grp) > 20: # Make sure we have a reasonable sample size
            tier_stats[name] = {
                'count': len(grp),
                'win_rate': grp["命中"].mean() * 100,
                'return': grp["次日涨跌幅"].mean()
            }
        else:
            tier_stats[name] = {'count': len(grp), 'win_rate': np.nan, 'return': np.nan}
            
    return {
        'top5_win': top5_win, 'top5_ret': top5_ret,
        'top10_win': top10_win, 'top10_ret': top10_ret,
        'tier_stats': tier_stats
    }

def main():
    df_all = load_daily_data()
    dataset = build_dataset(df_all)
    if dataset.empty:
        print("Dataset is empty.")
        return
        
    print(f"Dataset loaded with {len(dataset)} rows.")
    
    best_score = -99.0
    best_params = None
    best_result = None
    
    # Standard baseline parameters
    baseline_params = {
        'freq_high_days': 8, 'freq_high_score': 3,
        'freq_med_days': 5, 'freq_med_score': 2,
        'rebound_high_pct': 55, 'rebound_high_score': 5,
        'rebound_med_pct': 45, 'rebound_med_score': 1,
        'momentum_score': 0,
        'rank_top': 20, 'rank_score': 1,
        'overbought_5d_pct': 15, 'overbought_5d_penalty': -5,
        'overbought_cum_pct': 30, 'overbought_cum_penalty': -2,
        'crash_pct': -6, 'crash_penalty': -3
    }
    
    import itertools
    
    search_space = {
        'overbought_5d_pct': [12, 15, 18],
        'overbought_5d_penalty': [-4, -5, -6],
        'rebound_high_pct': [50, 55, 60],
        'rebound_high_score': [4, 5, 6],
        'momentum_score': [-2, -1, 0],
        'rank_score': [-1, 0, 1],
        'crash_pct': [-5, -6, -7]
    }
    
    keys, values = zip(*search_space.items())
    permutations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    print(f"Searching {len(permutations)} parameter combinations...")
    
    for idx, p_update in enumerate(permutations):
        params = baseline_params.copy()
        params.update(p_update)
        
        res = evaluate_score(dataset, params)
        
        # Objective function: We want a high win rate (>53% and ideally >55%) and high return.
        # Let's define a composite metric: Score = Top5_win_rate * 0.4 + Top10_win_rate * 0.3 + Top5_ret * 20 + Top10_ret * 10
        metric = res['top5_win'] * 0.4 + res['top10_win'] * 0.3 + res['top5_ret'] * 20.0 + res['top10_ret'] * 10.0
        
        # Check if the >=8 tier exists and is valid
        t_stats = res['tier_stats']
        if '>=8' in t_stats and not pd.isna(t_stats['>=8']['win_rate']) and t_stats['>=8']['count'] >= 10:
            if metric > best_score:
                best_score = metric
                best_params = params
                best_result = res
                
    print("\n" + "="*50)
    print("BEST PARAMETERS FOUND:")
    for k, v in best_params.items():
        print(f"  {k}: {v}")
    print("\nBEST PERFORMANCE:")
    print(f"  Top 5 Win Rate: {best_result['top5_win']:.2f}% | Avg Return: {best_result['top5_ret']:.4f}%")
    print(f"  Top 10 Win Rate: {best_result['top10_win']:.2f}% | Avg Return: {best_result['top10_ret']:.4f}%")
    print("\nTIER STATS:")
    for name, stat in best_result['tier_stats'].items():
        print(f"  Tier {name:4}: Count={stat['count']:3} | Win Rate={stat['win_rate']:.2f}% | Avg Return={stat['return']:.4f}%")

if __name__ == "__main__":
    main()
