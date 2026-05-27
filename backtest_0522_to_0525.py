# -*- coding: utf-8 -*-
"""
回测验证：2026-05-22 推荐 → 2026-05-25 实际表现
分析哪些推荐正确上涨、哪些下跌，并诊断失败原因。
"""
import os, sys, io, re
import pandas as pd
import numpy as np
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 禁用代理
_original_get = requests.get
def _no_proxy_get(url, **kwargs):
    kwargs['proxies'] = {'http': None, 'https': None}
    return _original_get(url, **kwargs)
requests.get = _no_proxy_get

def normalize_code(code):
    m = re.search(r"\d+", str(code))
    return m.group(0).zfill(6) if m else ""

# ====== 1. 加载 5/22 推荐记录 ======
rec_log = os.path.join(BASE_DIR, 'recommendation_log.csv')
df_rec = pd.read_csv(rec_log, encoding='utf-8-sig', dtype={'代码': str})
df_rec['代码'] = df_rec['代码'].apply(normalize_code)
recs_0522 = df_rec[df_rec['推荐日期'] == '2026-05-22'].copy()
print(f"5/22 推荐记录共 {len(recs_0522)} 条")
print(recs_0522[['代码', '名称', '类型', '综合评分', '当日涨跌幅']].to_string(index=False))

# ====== 2. 加载 5/25 实际数据 ======
data_dir = os.path.join(BASE_DIR, '100')
# 找 5/25 最晚的快照
files_0525 = sorted([f for f in os.listdir(data_dir) if f.startswith('top100_20260525')])
if files_0525:
    latest_0525 = os.path.join(data_dir, files_0525[-1])
    df_0525 = pd.read_csv(latest_0525, encoding='utf-8-sig', dtype={'代码': str})
    df_0525['代码'] = df_0525['代码'].apply(normalize_code)
    print(f"\n加载 5/25 数据: {files_0525[-1]} ({len(df_0525)} 条)")
else:
    print("找不到 5/25 数据!")
    sys.exit(1)

# 也加载 5/22 数据以获取 5/22 的收盘价
files_0522 = sorted([f for f in os.listdir(data_dir) if f.startswith('top100_20260522')])
if files_0522:
    latest_0522 = os.path.join(data_dir, files_0522[-1])
    df_0522 = pd.read_csv(latest_0522, encoding='utf-8-sig', dtype={'代码': str})
    df_0522['代码'] = df_0522['代码'].apply(normalize_code)

# ====== 3. 对于不在 Top100 中的推荐股票，用腾讯接口获取实时涨跌幅 ======
def fetch_realtime_change(code):
    """获取5/25的实际涨跌幅（通过腾讯接口）"""
    try:
        c = str(code).zfill(6)
        prefix = 'sh' if c.startswith('6') else 'sz'
        r = requests.get(f'http://qt.gtimg.cn/q={prefix}{c}', timeout=3)
        r.encoding = 'gbk'
        parts = r.text.strip().split('~')
        if len(parts) > 32:
            return float(parts[32])  # 涨跌幅
    except:
        pass
    return np.nan

# ====== 4. 合并推荐 vs 实际 ======
results = []
for _, rec in recs_0522.iterrows():
    code = rec['代码']
    name = rec['名称']
    rec_type = rec['类型']
    score = rec['综合评分']
    rec_day_chg = rec['当日涨跌幅']
    
    # 查找 5/25 实际涨跌幅
    row_0525 = df_0525[df_0525['代码'] == code]
    if not row_0525.empty:
        actual_chg = row_0525.iloc[0]['涨跌幅']
        actual_close = row_0525.iloc[0]['收盘']
        actual_rank = row_0525.iloc[0]['排名']
        actual_vol = row_0525.iloc[0]['成交额']
    else:
        # 不在 Top100 中，用腾讯接口获取
        actual_chg = fetch_realtime_change(code)
        actual_close = np.nan
        actual_rank = '>100'
        actual_vol = np.nan
    
    # 5/22 收盘价
    row_0522 = df_0522[df_0522['代码'] == code] if df_0522 is not None else pd.DataFrame()
    close_0522 = row_0522.iloc[0]['收盘'] if not row_0522.empty else np.nan
    rank_0522 = row_0522.iloc[0]['排名'] if not row_0522.empty else np.nan
    
    is_up = actual_chg > 0 if not np.isnan(actual_chg) else None
    
    results.append({
        '代码': code,
        '名称': name,
        '推荐类型': rec_type,
        '综合评分': score,
        '5/22涨跌幅': rec_day_chg,
        '5/22收盘价': close_0522,
        '5/22排名': rank_0522,
        '5/25涨跌幅': actual_chg,
        '5/25收盘价': actual_close,
        '5/25排名': actual_rank,
        '是否上涨': '✅' if is_up else ('❌' if is_up is False else '?'),
        '盈亏': f"+{actual_chg:.2f}%" if actual_chg > 0 else f"{actual_chg:.2f}%" if not np.isnan(actual_chg) else '?'
    })

df_result = pd.DataFrame(results)

# ====== 5. 输出汇总 ======
print("\n" + "=" * 100)
print("  📊 2026-05-22 推荐 → 2026-05-25 回测验证报告")
print("=" * 100)

# 分类统计
valid = df_result[df_result['是否上涨'] != '?']
win_count = (valid['是否上涨'] == '✅').sum()
lose_count = (valid['是否上涨'] == '❌').sum()
total = len(valid)
win_rate = win_count / total * 100 if total > 0 else 0
avg_return = valid['5/25涨跌幅'].mean()

print(f"\n  总推荐: {total} 只 | 上涨: {win_count} 只 | 下跌: {lose_count} 只")
print(f"  胜率: {win_rate:.1f}% | 平均收益: {avg_return:+.2f}%")

# A 类统计
cat_a = df_result[df_result['推荐类型'] == 'A-回调反弹']
cat_a_valid = cat_a[cat_a['是否上涨'] != '?']
a_win = (cat_a_valid['是否上涨'] == '✅').sum()
a_total = len(cat_a_valid)
a_avg = cat_a_valid['5/25涨跌幅'].mean() if a_total > 0 else 0
print(f"\n  【A类-回调反弹】 {a_total} 只 | 上涨 {a_win} 只 | 胜率 {a_win/a_total*100:.1f}% | 平均收益 {a_avg:+.2f}%")

# B 类统计
cat_b = df_result[df_result['推荐类型'] == 'B-趋势延续']
cat_b_valid = cat_b[cat_b['是否上涨'] != '?']
b_win = (cat_b_valid['是否上涨'] == '✅').sum()
b_total = len(cat_b_valid)
b_avg = cat_b_valid['5/25涨跌幅'].mean() if b_total > 0 else 0
print(f"  【B类-趋势延续】 {b_total} 只 | 上涨 {b_win} 只 | 胜率 {b_win/b_total*100:.1f}% | 平均收益 {b_avg:+.2f}%")

# 详细表
print("\n" + "-" * 100)
print("  详细推荐结果:")
print("-" * 100)

# 上涨的
print("\n  ✅ 正确上涨的股票:")
up_stocks = df_result[df_result['是否上涨'] == '✅'].sort_values('5/25涨跌幅', ascending=False)
if not up_stocks.empty:
    print(up_stocks[['代码', '名称', '推荐类型', '综合评分', '5/22涨跌幅', '5/25涨跌幅', '5/25排名']].to_string(index=False))

# 下跌的
print("\n  ❌ 错误下跌的股票:")
down_stocks = df_result[df_result['是否上涨'] == '❌'].sort_values('5/25涨跌幅', ascending=True)
if not down_stocks.empty:
    print(down_stocks[['代码', '名称', '推荐类型', '综合评分', '5/22涨跌幅', '5/25涨跌幅', '5/25排名']].to_string(index=False))

# ====== 6. 失败原因诊断 ======
print("\n\n" + "=" * 100)
print("  🔍 失败股票原因诊断")
print("=" * 100)

for _, row in down_stocks.iterrows():
    code = row['代码']
    name = row['名称']
    rec_type = row['推荐类型']
    chg_0522 = row['5/22涨跌幅']
    chg_0525 = row['5/25涨跌幅']
    score = row['综合评分']
    
    reasons = []
    
    # 诊断1: 5/22 已经跌幅很大，可能是趋势性下跌而非回调
    if rec_type == 'A-回调反弹' and chg_0522 < -3:
        reasons.append(f"回调幅度过大({chg_0522:.1f}%)，可能是趋势性下跌而非技术回调")
    
    # 诊断2: B 类推荐但已经涨幅透支
    if rec_type == 'B-趋势延续':
        # 检查 5/22 数据中的 5日涨幅
        r22 = df_0522[df_0522['代码'] == code]
        if not r22.empty:
            gain_5d = r22.iloc[0].get('5日涨幅', 0) or 0
            if gain_5d > 15:
                reasons.append(f"5日涨幅已达{gain_5d:.1f}%，涨幅透支严重")
            gain_3d = r22.iloc[0].get('3日涨幅', 0) or 0
            if gain_3d > 10:
                reasons.append(f"3日涨幅{gain_3d:.1f}%，短期冲高后回落风险大")
    
    # 诊断3: 5/25 排名大幅下降（资金撤离）
    rank_0522_val = row.get('5/22排名', np.nan)
    rank_0525_val = row.get('5/25排名', '>100')
    if str(rank_0525_val) == '>100':
        reasons.append("5/25 已跌出成交额前100，资金严重流出")
    elif not np.isnan(float(rank_0522_val)) and float(rank_0525_val) - float(rank_0522_val) > 20:
        reasons.append(f"排名从{int(rank_0522_val)}跌至{int(rank_0525_val)}，资金关注度大幅下降")
    
    # 诊断4: 周末效应（5/22 周四 → 5/25 周一，跨周末持仓风险）
    reasons.append("跨周末持仓，周末消息面不确定性增加")
    
    # 诊断5: 5/22 当天大涨后的获利回吐
    if chg_0522 > 5:
        reasons.append(f"5/22 当天大涨{chg_0522:.1f}%，次交易日获利回吐压力大")
    
    # 诊断6: 5/25 跌幅很大
    if chg_0525 < -5:
        reasons.append(f"5/25 跌幅达{chg_0525:.1f}%，可能遇到突发利空或板块整体回调")
    
    if not reasons:
        reasons.append("无明显可诊断的风险信号，可能受大盘/板块整体情绪影响")
    
    print(f"\n  {code} {name} [{rec_type}] 评分{score} → 5/25跌{chg_0525:.2f}%")
    for i, r in enumerate(reasons):
        print(f"    {i+1}. {r}")

# ====== 7. 策略修复建议 ======
print("\n\n" + "=" * 100)
print("  🔧 策略自我修复建议")
print("=" * 100)

# 分析失败模式
a_fails = down_stocks[down_stocks['推荐类型'] == 'A-回调反弹']
b_fails = down_stocks[down_stocks['推荐类型'] == 'B-趋势延续']

fixes = []

# 修复1: A 类大幅回调股票不应推荐
big_drop_a = a_fails[a_fails['5/22涨跌幅'] < -3]
if not big_drop_a.empty:
    fixes.append({
        '问题': f'A类回调反弹中，{len(big_drop_a)} 只在推荐日跌幅超过3%的股票表现不佳',
        '修复': '增加A类推荐的当日跌幅上限：当日跌幅 > -3% 时不予推荐（当前无此限制）',
        '影响': '排除伪回调（实质性下跌趋势），减少A类虚假信号',
        '代码位置': 'pullback_analysis.py Step 6 cat_a 筛选条件'
    })

# 修复2: B 类高涨幅透支
b_high_gain = []
for _, row in b_fails.iterrows():
    r22 = df_0522[df_0522['代码'] == row['代码']]
    if not r22.empty:
        g5 = r22.iloc[0].get('5日涨幅', 0) or 0
        if g5 > 10:
            b_high_gain.append(row['名称'])
if b_high_gain:
    fixes.append({
        '问题': f'B类趋势延续中，{", ".join(b_high_gain)} 等在推荐时5日涨幅已透支',
        '修复': '对B类推荐增加"5日涨幅 < 12%"的硬性过滤条件（当前阈值15%过宽松）',
        '影响': '降低追高买入风险，减少B类在短期冲顶时的虚假信号',
        '代码位置': 'pullback_analysis.py Step 6 cat_b 筛选条件 / 惩罚因子A'
    })

# 修复3: 周末过滤
fixes.append({
    '问题': '5/22(周四) → 5/25(周一)，跨周末持仓引入额外不确定性',
    '修复': '在周四/周五推荐时，增加"周末效应"降权因子（-1分），或提示风险',
    '影响': '降低周末消息面冲击导致的回测偏差',
    '代码位置': 'pullback_analysis.py 综合评分部分'
})

# 修复4: 高分但下跌的情况
high_score_fails = down_stocks[down_stocks['综合评分'] >= 10]
if not high_score_fails.empty:
    fixes.append({
        '问题': f'{len(high_score_fails)} 只评分≥10的高分股票仍然下跌，说明评分体系有盲区',
        '修复': '高分候选增加"成交量异常萎缩检测"因子——如果排名日成交额下降>20%，扣分',
        '影响': '识别高位放量后的缩量出货行为',
        '代码位置': 'pullback_analysis.py Step 5 综合评分'
    })

for i, fix in enumerate(fixes):
    print(f"\n  修复 #{i+1}:")
    print(f"    问题: {fix['问题']}")
    print(f"    修复: {fix['修复']}")
    print(f"    影响: {fix['影响']}")
    print(f"    位置: {fix['代码位置']}")

# 保存结果
output = os.path.join(BASE_DIR, 'backtest_0522_to_0525.csv')
df_result.to_csv(output, index=False, encoding='utf-8-sig')
print(f"\n\n📝 详细结果已保存: {output}")
print("✅ 回测分析完成!")
