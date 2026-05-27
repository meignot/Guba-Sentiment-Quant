# -*- coding: utf-8 -*-
"""
量化辅助选股系统 v7 — 含回测验证、代码标准化、市场环境过滤、评分明细、消息面降噪
基于100目录下10天的成交量TOP100数据
"""
from datetime import datetime as _dt
import pandas as pd
import numpy as np
import os, sys, io
import requests
import bs4
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
pd.set_option('display.max_rows', 200)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.width', 220)
pd.set_option('display.max_columns', 20)

# 禁用代理
_original_get = requests.get
def _no_proxy_get(url, **kwargs):
    kwargs['proxies'] = {'http': None, 'https': None}
    return _original_get(url, **kwargs)
requests.get = _no_proxy_get

# ====== P0 回测验证系统 ======
RECOMMENDATION_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recommendation_log.csv')

def fetch_today_change(code):
    """通过腾讯实时接口获取某只股票的当日涨跌幅"""
    try:
        c = str(code).zfill(6)
        prefix = 'sh' if c.startswith('6') else 'sz'
        r = requests.get(f'http://qt.gtimg.cn/q={prefix}{c}', timeout=3)
        r.encoding = 'gbk'
        parts = r.text.strip().split('~')
        if len(parts) > 32:
            return float(parts[32])  # 32 = 涨跌幅
    except:
        pass
    return np.nan

def run_backtest_check():
    """检查推荐日志中最近一次的推荐记录，并验证这些票今天的实际表现。"""
    if not os.path.exists(RECOMMENDATION_LOG):
        return
    try:
        df_log = pd.read_csv(RECOMMENDATION_LOG, encoding='utf-8-sig', dtype={'代码': str})
        if df_log.empty:
            return
        df_log['代码'] = df_log['代码'].astype(str).str.zfill(6)
        # 找出最近一次推荐的日期
        last_rec_date = df_log['推荐日期'].max()
        today_str = _dt.now().strftime('%Y-%m-%d')
        # 只有当推荐日期不是今天时才做验证（今天的推荐要明天才能验证）
        if last_rec_date == today_str:
            # 检查是否还有更早的记录
            older = df_log[df_log['推荐日期'] != today_str]
            if older.empty:
                return
            last_rec_date = older['推荐日期'].max()
        
        recs = df_log[df_log['推荐日期'] == last_rec_date].copy()
        if recs.empty:
            return
        
        print('\n' + '=' * 80)
        print(f'  📊 回测验证：{last_rec_date} 推荐的股票今日表现')
        print('=' * 80)
        
        results = []
        for _, row in recs.iterrows():
            code = row['代码']
            actual_chg = fetch_today_change(code)
            results.append({
                '代码': code,
                '名称': row['名称'],
                '类型': row['类型'],
                '推荐评分': row['综合评分'],
                '今日涨跌幅': actual_chg,
                '是否上涨': '✅' if actual_chg > 0 else ('❌' if actual_chg < 0 else '➖') if not np.isnan(actual_chg) else '?',
            })
        
        df_bt = pd.DataFrame(results)
        valid = df_bt[df_bt['今日涨跌幅'].notna()].copy()
        
        if not valid.empty:
            win_count = (valid['今日涨跌幅'] > 0).sum()
            total = len(valid)
            win_rate = win_count / total * 100
            avg_return = valid['今日涨跌幅'].mean()
            max_gain = valid['今日涨跌幅'].max()
            max_loss = valid['今日涨跌幅'].min()
            
            print(f'\n  推荐 {total} 只 | 上涨 {win_count} 只 | 胜率 {win_rate:.1f}%')
            print(f'  平均收益 {avg_return:+.2f}% | 最大盈利 {max_gain:+.2f}% | 最大亏损 {max_loss:+.2f}%')
            print(f'\n  明细:')
            print(df_bt[['代码', '名称', '类型', '推荐评分', '今日涨跌幅', '是否上涨']].to_string(index=False))
        else:
            print('  未能获取到实际涨跌数据，跳过验证。')
        print()
    except Exception as e:
        print(f'  回测验证出现异常: {e}\n')

# ====== 辅助函数: 主力资金流向 ======
def fetch_fund_flow_5d(code):
    """获取个股近5日主力资金累计净流入(万元)和最近1日净流入"""
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow(stock=str(code).zfill(6))
        if df is None or df.empty:
            return np.nan, np.nan
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        r5 = df.tail(5)
        total_5d = r5['主力净流入-净额'].sum() / 10000  # 万
        last_1d = df.iloc[-1]['主力净流入-净额'] / 10000
        return total_5d, last_1d
    except Exception:
        return np.nan, np.nan

# ====== 辅助函数: v4 宏观与概念数据 ======
def fetch_market_liquidity():
    """获取两市总成交额(亿)，判断是否缩量"""
    try:
        import akshare as ak
        sh = ak.stock_zh_index_daily_em(symbol='sh000001')
        sz = ak.stock_zh_index_daily_em(symbol='sz399001')
        vol_sh = sh.iloc[-1]['成交额'] / 1e8
        vol_sz = sz.iloc[-1]['成交额'] / 1e8
        return vol_sh + vol_sz
    except:
        return np.nan

def fetch_float_market_cap(code):
    """通过腾讯接口快速获取流通市值(亿)"""
    try:
        prefix = 'sh' if str(code).startswith('6') else 'sz'
        r = requests.get(f'http://qt.gtimg.cn/q={prefix}{code}', timeout=2)
        r.encoding = 'gbk'
        parts = r.text.strip().split('~')
        return float(parts[44])  # 44是流通市值
    except:
        return 0

def fetch_hot_concept_stocks():
    """获取今日排名前3的爆款细分概念及其成分股集合"""
    concept_stocks = set()
    hot_concept_names = []
    try:
        import akshare as ak
        df_concepts = ak.stock_board_concept_name_em()
        top_concepts = df_concepts.sort_values(by='涨跌幅', ascending=False).head(3)
        for _, row in top_concepts.iterrows():
            c_name = row['板块名称']
            hot_concept_names.append(c_name)
            cons = ak.stock_board_concept_cons_em(symbol=c_name)
            concept_stocks.update(cons['代码'].tolist())
    except:
        pass
    return concept_stocks, hot_concept_names

# ====== 辅助函数: 消息面利空扫描 ======
def normalize_stock_code(code):
    """统一股票代码为6位字符串，避免CSV读写导致前导0丢失。"""
    m = re.search(r"\d+", str(code))
    return m.group(0).zfill(6) if m else ""


def check_news_risk(code, stock_name=None):
    """扫描新浪财经最新新闻，仅在标题命中个股名称/代码时计算高危利空，减少行业新闻误判。"""
    neg_keywords = ['冻结', '轮候冻结', '被冻结', '立案', '调查', '被执行',
                    '折戟', '否决', '警告', '退市', '暂停上市', '留置',
                    '问询函', '处罚', '终止', '减持', '商誉减值']
    try:
        c = normalize_stock_code(code)
        prefix = 'sh' if c.startswith('6') else 'sz'
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{prefix}{c}.phtml"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        r = requests.get(url, headers=headers, timeout=8)
        r.encoding = 'gbk'
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
        list_div = soup.find(class_='datelist')
        if not list_div:
            return 0, []
        hits = []
        for a in list_div.find_all('a')[:20]:
            title = a.text.strip()
            
            # 清理股票名称前缀（如 XD, ST, *ST, XR 等），防止新闻标题因不带前缀而漏判
            clean_name = str(stock_name) if stock_name else ""
            clean_name = re.sub(r'^(?:XD|XR|DR|N|C|\*ST|ST)\s*', '', clean_name)
            
            company_hit = (clean_name and clean_name in title) or (c in title)
            if not company_hit:
                continue
            for kw in neg_keywords:
                if kw in title:
                    hits.append(title[:40])
                    break
        return len(hits), hits
    except Exception:
        return 0, []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(BASE_DIR, "100")

# ====== P0: 启动时自动验证上次推荐 ======
run_backtest_check()

# ====== Step 1: 读取所有CSV并合并 (v5 重构：多时段快照支持) ======
daily_dfs = {}

for f in sorted(os.listdir(data_dir)):
    if f.startswith("top100_") and f.endswith(".csv"):
        fp = os.path.join(data_dir, f)
        df = pd.read_csv(fp, encoding='utf-8-sig', dtype={'代码': str})
        if '代码' in df.columns:
            df['代码'] = df['代码'].apply(normalize_stock_code)
        
        # 提取日期和可能存在的时间戳
        m = re.match(r"top100_(\d{8})(?:_(\d{6}))?\.csv", f)
        if m:
            date_str = m.group(1)
            time_str = m.group(2) if m.group(2) else "235959" # 没带时间的默认为收盘
            dt_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            
            if dt_formatted not in daily_dfs:
                daily_dfs[dt_formatted] = []
            daily_dfs[dt_formatted].append((time_str, df))

all_baseline_dfs = []
today_intraday_dfs = []

available_dates = sorted(list(daily_dfs.keys()))
if not available_dates:
    print("未找到有效数据！")
    sys.exit(1)
    
last_trade_date_str = available_dates[-1]

for date_str, df_list in daily_dfs.items():
    # 按时间戳排序
    df_list.sort(key=lambda x: x[0])
    
    # 获取每日最晚的一份作为基础库，避免历史数据重复
    latest_time, latest_df = df_list[-1]
    all_baseline_dfs.append(latest_df)
    
    # 抽取今天所有的盘中切片，构建日内时间轴
    if date_str == last_trade_date_str:
        for t_str, d in df_list:
            today_intraday_dfs.append((t_str, d))

df_all = pd.concat(all_baseline_dfs, ignore_index=True)
df_all['代码'] = df_all['代码'].apply(normalize_stock_code)
df_all['日期'] = pd.to_datetime(df_all['日期'])
for idx, (t_str, snap_df) in enumerate(today_intraday_dfs):
    if '代码' in snap_df.columns:
        today_intraday_dfs[idx] = (t_str, snap_df.assign(代码=snap_df['代码'].apply(normalize_stock_code)))
trade_dates = sorted(df_all['日期'].unique())
print(f"共读取 {len(available_dates)} 天数据, 今天存在 {len(today_intraday_dfs)} 份日内时段快照")
print(f"总基础记录数: {len(df_all)}")

# 获取最新交易日和预测明日日期
last_trade_date = pd.to_datetime(trade_dates[-1])
last_date_label = f"{last_trade_date.month}/{last_trade_date.day}"

next_day = last_trade_date + pd.Timedelta(days=1)
if next_day.weekday() == 5:    # 周六
    next_day += pd.Timedelta(days=2)
elif next_day.weekday() == 6:  # 周日
    next_day += pd.Timedelta(days=1)
predict_date_label = f"{next_day.month}/{next_day.day}"

print("=" * 80)
print(f"       回调后上涨 & 连续上涨 股票筛选 — 预测明天({predict_date_label})上涨标的")
print("=" * 80)

# ====== Step 2: 构建每只股票的时间序列 ======
# 获取所有出现过的股票
stocks = df_all.groupby(['代码', '名称']).agg(
    出现天数=('日期', 'nunique'),
    平均排名=('排名', 'mean'),
    平均成交额=('成交额', 'mean'),
).reset_index()

print(f"\n10天内共出现 {len(stocks)} 只不同股票")

# 为每只股票构建完整的日涨跌序列
stock_series = {}
for code in df_all['代码'].unique():
    sdf = df_all[df_all['代码'] == code].sort_values('日期').copy()
    name = sdf['名称'].iloc[0]
    sector = sdf['所属板块'].iloc[0] if '所属板块' in sdf.columns else ''
    records = []
    for _, row in sdf.iterrows():
        records.append({
            '日期': row['日期'],
            '收盘': row['收盘'],
            '涨跌幅': row['涨跌幅'],
            '排名': row['排名'],
            '成交额': row['成交额'],
            '成交量': row['成交量'],
        })
    stock_series[code] = {'name': name, 'sector': sector, 'data': pd.DataFrame(records)}

# ====== Step 3: 识别"回调后第二天上涨"模式 ======
print("\n" + "=" * 80)
print("  一、回调后第二天上涨的股票 (跌→涨 模式)")
print("=" * 80)
print("  定义: 某天涨跌幅<0(回调), 紧接着下一个出现日涨跌幅>0(反弹上涨)")

pullback_rise_stats = []
for code, info in stock_series.items():
    df = info['data'].sort_values('日期').reset_index(drop=True)
    if len(df) < 2:
        continue
    
    pullback_rise_count = 0
    total_pullback = 0
    avg_bounce = []
    last_pattern = None  # 最近一次的模式
    
    for i in range(len(df) - 1):
        if df.iloc[i]['涨跌幅'] < 0:  # 当天回调
            total_pullback += 1
            if df.iloc[i+1]['涨跌幅'] > 0:  # 次日上涨
                pullback_rise_count += 1
                avg_bounce.append(df.iloc[i+1]['涨跌幅'])
    
    # 检查最后一天的状态
    last_row = df.iloc[-1]
    last_date = last_row['日期']
    last_change = last_row['涨跌幅']
    
    if total_pullback >= 1:
        pullback_rise_stats.append({
            '代码': code,
            '名称': info['name'],
            '板块': info['sector'],
            '出现天数': len(df),
            '回调次数': total_pullback,
            '回调后上涨次数': pullback_rise_count,
            '回调反弹率': round(pullback_rise_count / total_pullback * 100, 1) if total_pullback > 0 else 0,
            '平均反弹幅度': round(np.mean(avg_bounce), 2) if avg_bounce else 0,
            f'{last_date_label}涨跌幅': last_change,
            f'{last_date_label}是否回调': last_change < 0,
            f'{last_date_label}收盘': last_row['收盘'],
            f'{last_date_label}排名': last_row['排名'],
        })

df_pullback = pd.DataFrame(pullback_rise_stats)

# 筛选: 最新交易日是回调日 且 历史回调反弹率高
today_pullback = df_pullback[df_pullback[f'{last_date_label}是否回调'] == True].copy()
today_pullback = today_pullback.sort_values(['回调反弹率', '出现天数', '平均反弹幅度'], ascending=[False, False, False])

print(f"\n  {last_date_label}回调的股票中，历史回调后反弹概率排名:")
print(f"  (共 {len(today_pullback)} 只股票在{last_date_label}回调)")
if not today_pullback.empty:
    show_cols = ['代码', '名称', '板块', '出现天数', '回调次数', '回调后上涨次数', '回调反弹率', '平均反弹幅度', f'{last_date_label}涨跌幅']
    print(today_pullback[show_cols].head(30).to_string(index=False))

# ====== Step 4: 识别"连续上涨"模式 ======
print("\n\n" + "=" * 80)
print("  二、连续上涨的股票")
print("=" * 80)
print("  定义: 最近连续多天涨跌幅>0 的股票")

continuous_rise = []
for code, info in stock_series.items():
    df = info['data'].sort_values('日期').reset_index(drop=True)
    if len(df) < 2:
        continue
    
    # 从最后一天往前数连续上涨天数
    streak = 0
    for i in range(len(df) - 1, -1, -1):
        if df.iloc[i]['涨跌幅'] > 0:
            streak += 1
        else:
            break
    
    # 总上涨天数
    up_days = (df['涨跌幅'] > 0).sum()
    
    if streak >= 2:  # 至少连续2天上涨
        last_row = df.iloc[-1]
        continuous_rise.append({
            '代码': code,
            '名称': info['name'],
            '板块': info['sector'],
            '出现天数': len(df),
            '连续上涨天数': streak,
            '总上涨天数': up_days,
            '上涨占比': round(up_days / len(df) * 100, 1),
            '最近涨幅': last_row['涨跌幅'],
            f'{last_date_label}收盘': last_row['收盘'],
            f'{last_date_label}排名': last_row['排名'],
            '5日涨幅趋势': round(df['涨跌幅'].tail(5).sum() if len(df) >= 5 else df['涨跌幅'].sum(), 2),
        })

df_continuous = pd.DataFrame(continuous_rise)
if not df_continuous.empty:
    df_continuous = df_continuous.sort_values(['连续上涨天数', '上涨占比'], ascending=[False, False])
    print(f"\n  最近连续上涨≥2天的股票，共 {len(df_continuous)} 只:")
    show_cols = ['代码', '名称', '板块', '出现天数', '连续上涨天数', '总上涨天数', '上涨占比', '最近涨幅', '5日涨幅趋势']
    print(df_continuous[show_cols].head(30).to_string(index=False))

# ====== Step 5: 综合共识分析 (v2 - 含修正因子及板块温度) ======
print("\n\n" + "=" * 80)
print(f"  三、共识指标综合分析 — 明天({predict_date_label})上涨概率评估 (v2增强版)")
print("=" * 80)

# ================== 新增：计算前一日板块整体温度与资金动量 ==================
print("  [*] 正在并发拉取全市场活跃股资金流，计算真实板块温度(约10秒)...")
# 提取最新一天所有出现的股票表现
df_last_day = df_all[df_all['日期'] == last_trade_date].copy()
df_last_day['所属板块'] = df_last_day['所属板块'].fillna('未知')

# 并发获取资金流(1日)
last_codes = df_last_day['代码'].unique()
fund_flow_1d_map = {}

def get_1d_flow(c):
    try:
        import akshare as ak
        df_f = ak.stock_individual_fund_flow(stock=str(c).zfill(6))
        if df_f is not None and not df_f.empty:
            return c, df_f.iloc[-1]['主力净流入-净额'] / 10000
    except:
        pass
    return c, np.nan

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(get_1d_flow, c): c for c in last_codes}
    for future in as_completed(futures):
        c, flow = future.result()
        fund_flow_1d_map[c] = flow

df_last_day['主力净流入'] = df_last_day['代码'].map(fund_flow_1d_map)

# 计算板块统计数据
sector_stats = df_last_day.groupby('所属板块').agg(
    股票数量=('代码', 'count'),
    平均涨跌幅=('涨跌幅', 'mean'),
    涨跌标准差=('涨跌幅', 'std'),
    上涨家数=('涨跌幅', lambda x: (x > 0).sum()),
    板块净流入=('主力净流入', 'sum')
).reset_index()

# 过滤极小样本板块，避免波动过大
sector_stats = sector_stats[sector_stats['股票数量'] >= 3].copy()
sector_stats['板块胜率'] = (sector_stats['上涨家数'] / sector_stats['股票数量'] * 100).round(1)
sector_stats['涨跌标准差'] = sector_stats['涨跌标准差'].fillna(0)

# 构建方便查询的字典
sector_hotness = {}
for _, row in sector_stats.iterrows():
    sector_hotness[row['所属板块']] = {
        '平均涨跌幅': row['平均涨跌幅'],
        '板块胜率': row['板块胜率'],
        '分歧度': row['涨跌标准差'],
        '板块净流入': row['板块净流入']
    }
# ==================================================================

# 预计算: 获取TOP30候选的资金流和消息面 (仅对高分候选做耗时查询)
print("  [*] 正在获取主力资金流向与消息面数据 (约30秒)...")

# 对每只股票计算综合评分
all_codes = df_all['代码'].unique()
scoring = []

for code in all_codes:
    info = stock_series[code]
    df = info['data'].sort_values('日期').reset_index(drop=True)
    if len(df) < 3:
        continue
    
    last_row = df.iloc[-1]
    last_date = last_row['日期']
    sector = info['sector']

    
    score = 0
    score_breakdown = {
        '频率分': 0, '胜率分': 0, '回调分': 0, '动量分': 0, '排名分': 0,
        '趋势分': 0, '涨跌幅分': 0, '板块分': 0, '风险扣分': 0, '日内分': 0,
        '资金分': 0, '消息分': 0, '流动性分': 0, '概念分': 0, '市场环境分': 0
    }
    reasons = []
    risk_flags = []
    
    # 因子1: 出现频率 (出现天数越多 = 持续被资金关注)
    appear_days = len(df)
    if appear_days >= 8:
        score += 3
        score_breakdown['频率分'] += 3
        reasons.append(f"高频上榜{appear_days}天")
    elif appear_days >= 5:
        score += 2
        score_breakdown['频率分'] += 2
        reasons.append(f"中频上榜{appear_days}天")
    elif appear_days >= 3:
        score += 1
        score_breakdown['频率分'] += 1
    
    # 因子2: 上涨概率
    up_days = (df['涨跌幅'] > 0).sum()
    up_ratio = up_days / len(df) * 100
    if up_ratio >= 70:
        score += 3
        score_breakdown['胜率分'] += 3
        reasons.append(f"高胜率{up_ratio:.0f}%")
    elif up_ratio >= 50:
        score += 1
        score_breakdown['胜率分'] += 1
    
    # 因子3: 回调后反弹模式 (最新交易日回调 且 历史反弹率高)
    pb_row = df_pullback[df_pullback['代码'] == code]
    if not pb_row.empty:
        pb = pb_row.iloc[0]
        if pb[f'{last_date_label}是否回调'] and pb['回调反弹率'] >= 55:
            score += 5
            score_breakdown['回调分'] += 5
            reasons.append(f"回调反弹率{pb['回调反弹率']}%")
        elif pb[f'{last_date_label}是否回调'] and pb['回调反弹率'] >= 45:
            score += 1
            score_breakdown['回调分'] += 1
            reasons.append(f"回调中+反弹{pb['回调反弹率']}%")
    
    # 因子4: 连续上涨惯性 (v2修正: 加入动能衰减检测)
    cont_row = df_continuous[df_continuous['代码'] == code] if not df_continuous.empty else pd.DataFrame()
    if not cont_row.empty:
        streak = cont_row.iloc[0]['连续上涨天数']
        if streak >= 2:
            # v2新增: 检测动能衰减 (最后两天涨幅对比)
            if len(df) >= 2:
                chg_prev = df.iloc[-2]['涨跌幅']
                chg_last = df.iloc[-1]['涨跌幅']
                if chg_prev > 0 and chg_last > 0:
                    decay_rate = (1 - chg_last / chg_prev) * 100 if chg_prev != 0 else 0
                    if decay_rate >= 80:
                        # 动能严重衰减, 不加分反而扣分
                        score -= 2
                        score_breakdown['动量分'] -= 2
                        risk_flags.append(f"⚠动能衰减{decay_rate:.0f}%")
                    elif decay_rate >= 50:
                        # 动能中度衰减, 少加分
                        score += 1
                        score_breakdown['动量分'] += 1
                        reasons.append(f"连涨{streak}天(动能衰减)")
                    else:
                        # 动能健康
                        if streak >= 3:
                            score += 3
                            score_breakdown['动量分'] += 3
                        else:
                            score += 2
                            score_breakdown['动量分'] += 2
                        reasons.append(f"连涨{streak}天(动能强)")
                else:
                    if streak >= 3:
                        score += 3
                        score_breakdown['动量分'] += 3
                    else:
                        score += 2
                        score_breakdown['动量分'] += 2
                    reasons.append(f"连涨{streak}天")
            else:
                score += 2
                score_breakdown['动量分'] += 2
                reasons.append(f"连涨{streak}天")
                
    # 因子5: 最新交易日排名靠前 (资金集中度高)
    rank_last = last_row['排名']
    if rank_last <= 20:
        score += 1
        score_breakdown['排名分'] += 1
        reasons.append(f"排名TOP{int(rank_last)}")
    
    # 因子6: 近期趋势 (3日/5日涨幅)
    sdf_last = df_all[(df_all['代码'] == code) & (df_all['日期'] == last_date)]
    if not sdf_last.empty:
        r = sdf_last.iloc[0]
        if '3日涨幅' in r and r['3日涨幅'] > 0 and '5日涨幅' in r and r['5日涨幅'] > 0:
            score += 2
            score_breakdown['趋势分'] += 2
            reasons.append(f"3日+5日均涨")
        elif '3日涨幅' in r and r['3日涨幅'] > 0:
            score += 1
            score_breakdown['趋势分'] += 1
    
    # 因子7: 当日涨跌幅适中(非暴涨暴跌，可持续)
    last_chg = last_row['涨跌幅']
    if 0 < last_chg <= 5:
        score += 1
        score_breakdown['涨跌幅分'] += 1
        reasons.append(f"温和上涨{last_chg}%")
    elif -3 < last_chg < 0:
        score += 1  # 小幅回调也ok
        score_breakdown['涨跌幅分'] += 1
    
    # ========== 因子8: 板块热度、动量共振与分歧度分析 (v3升级版) ==========
    if sector in sector_hotness:
        sh = sector_hotness[sector]
        s_win_rate = sh['板块胜率']
        s_avg_chg = sh['平均涨跌幅']
        s_std = sh['分歧度']
        s_flow = sh['板块净流入']
        
        # 1. 诱多识别 (拉高出货): 表面胜率高/平均收红，但资金大幅跑路 (净流出超3000万)
        if s_win_rate >= 50 and s_avg_chg > 0 and s_flow < -3000:
            score -= 5
            score_breakdown['板块分'] -= 5
            risk_flags.append(f"⚠板块诱多(流出{abs(s_flow):.0f}万)")
            
        # 2. 板块真实风口: 胜率高，且资金为正向流入或流出极小
        elif s_win_rate >= 60 and s_avg_chg > 0 and s_flow > -1000:
            score += 3
            score_breakdown['板块分'] += 3
            reasons.append(f"板块风口(流{s_flow:.0f}万)")
            
        # 3. 退潮确认: 胜率低，平均收跌
        elif s_win_rate <= 30 and s_avg_chg < 0:
            score -= 3
            score_breakdown['板块分'] -= 3
            risk_flags.append(f"⚠板块退潮(胜率{s_win_rate:.0f}%)")
            
        # 4. 去弱留强 (高分歧期): 胜率在40-60%之间，且标准差极大
        elif 40 <= s_win_rate <= 60 and s_std >= 2.5:
            # 高分歧下，如果该股票今日没怎么涨(涨幅<2%)，或者动能不足，属于被淘汰的弱势股
            if last_chg < 2:
                score -= 2
                score_breakdown['板块分'] -= 2
                risk_flags.append(f"分歧期弱势股(跟风淘汰)")
            else:
                reasons.append(f"分歧期龙头(穿越)")
    
    # ========== v2新增惩罚因子 ==========
    
    # 惩罚因子A: 累计涨幅透支度 (基于CSV中可获取的5日涨幅数据)
    cum_gain_10d = df['涨跌幅'].sum()  # 10日窗口内累计涨跌幅之和(近似)
    if not sdf_last.empty:
        r = sdf_last.iloc[0]
        five_d_gain = r['5日涨幅'] if '5日涨幅' in r and pd.notna(r['5日涨幅']) else 0
    else:
        five_d_gain = 0
    
    if cum_gain_10d >= 30:
        score -= 2
        score_breakdown['风险扣分'] -= 2
        risk_flags.append(f"⚠10日涨{cum_gain_10d:.0f}%透支")
    
    # 惩罚因子A-2: 5日涨幅过快 (保持原阈值15%，经核验12%会误伤上涨股)
    if five_d_gain >= 15:
        score -= 6
        score_breakdown['风险扣分'] -= 6
        risk_flags.append(f"⚠5日涨{five_d_gain:.0f}%过快(扣6分)")
        
    # 通用崩盘保护
    if last_chg <= -6:
        score -= 3
        score_breakdown['风险扣分'] -= 3
        risk_flags.append(f"⚠单日跌幅过大({last_chg:.1f}%)")
    
    # 惩罚因子B: 连涨期间最后一天已转跌 (说明趋势可能已反转)
    if len(df) >= 3:
        if df.iloc[-3]['涨跌幅'] > 0 and df.iloc[-2]['涨跌幅'] > 0 and df.iloc[-1]['涨跌幅'] < 0:
            # 连涨后突然转跌
            if abs(last_chg) >= 3:
                score -= 2
                score_breakdown['风险扣分'] -= 2
                risk_flags.append(f"⚠连涨后大跌{last_chg:.1f}%")
            else:
                score -= 1
                score_breakdown['风险扣分'] -= 1
                risk_flags.append(f"连涨后转跌{last_chg:.1f}%")


    # ========== 因子9: 日内多时段快照对比 (v5新增) ==========
    if len(today_intraday_dfs) > 1:
        t_first, df_first = today_intraday_dfs[0]
        t_last, df_last = today_intraday_dfs[-1]
        
        rank_first_series = df_first.loc[df_first['代码'] == code, '排名']
        rank_last_series = df_last.loc[df_last['代码'] == code, '排名']
        
        r_first = rank_first_series.values[0] if not rank_first_series.empty else 999
        r_last = rank_last_series.values[0] if not rank_last_series.empty else 999
        
        # 1. 新晋异动 (早盘没上榜，下午杀入前50)
        if r_first > 100 and r_last <= 50:
            score += 2
            score_breakdown['日内分'] += 2
            reasons.append(f"🔥日内新晋抢筹")
            
        # 2. 排名飙升 (排名提升超过30名)
        elif r_first != 999 and r_last != 999 and (r_first - r_last) >= 30:
            score += 2
            score_breakdown['日内分'] += 2
            reasons.append(f"日内飙升{r_first - r_last}名")
            
        # 3. 冲高回落骗线 (早盘前30，下午掉出60)
        elif r_first <= 30 and r_last >= 60:
            score -= 2
            score_breakdown['日内分'] -= 2
            risk_flags.append(f"⚠日内冲高回落(坠{r_last - r_first}名)")

    scoring.append({
        '代码': normalize_stock_code(code),
        '名称': info['name'],
        '板块': info['sector'],
        '出现天数': appear_days,
        f'{last_date_label}涨跌幅': last_chg,
        f'{last_date_label}排名': int(rank_last),
        '上涨占比': round(up_ratio, 1),
        '10日累涨': round(cum_gain_10d, 1),
        **score_breakdown,
        '综合评分': score,
        '理由': ' | '.join(reasons),
        '风险标记': ' | '.join(risk_flags) if risk_flags else '',
    })

df_score = pd.DataFrame(scoring)
df_score = df_score.sort_values('综合评分', ascending=False)

# === v3/v4新增: 对TOP30候选做资金流、消息面、流动性及概念深度扫描 ===
top_codes = df_score.head(30)['代码'].tolist()
fund_flow_data = {}
news_risk_data = {}
float_cap_data = {}

print("  [*] 正在探测大盘流动性与爆款细分概念 (v4)...")
market_vol = fetch_market_liquidity()
is_shrinking = False
market_score_adj = 0
market_status = "未知"
if pd.notna(market_vol):
    if market_vol < 7000:
        is_shrinking = True
        market_score_adj = -2
        market_status = "弱势缩量"
        print(f"      [!] 大盘极度缩量至 {market_vol:.0f} 亿，所有候选降权！")
    elif market_vol < 8000:
        is_shrinking = True
        market_score_adj = -1
        market_status = "缩量震荡"
        print(f"      [!] 大盘缩量至 {market_vol:.0f} 亿，启动谨慎过滤！")
    elif market_vol >= 10000:
        market_score_adj = 1
        market_status = "放量强势"
        print(f"      [+] 大盘量能 {market_vol:.0f} 亿，流动性充裕。")
    else:
        market_status = "正常震荡"
        print(f"      [+] 大盘量能 {market_vol:.0f} 亿，环境中性。")
        
hot_concept_stocks, hot_concept_names = fetch_hot_concept_stocks()
if hot_concept_names:
    print(f"      [+] 今日爆款概念: {', '.join(hot_concept_names)}")

print("  [*] 正在查询TOP30候选的主力资金流、流通市值与消息面 (约30秒)...")
for c in top_codes:
    c_str = str(c).zfill(6)
    # 资金流
    flow_5d, flow_1d = fetch_fund_flow_5d(c_str)
    fund_flow_data[c] = (flow_5d, flow_1d)
    # 流通市值
    float_cap_data[c] = fetch_float_market_cap(c_str)

for c in top_codes:
    c_str = str(c).zfill(6)
    stock_name = df_score.loc[df_score['代码'] == normalize_stock_code(c), '名称'].iloc[0]
    hit_count, hit_titles = check_news_risk(c_str, stock_name)
    news_risk_data[c] = (hit_count, hit_titles)

# 应用资金流和消息面修正
for idx in df_score.index:
    code = df_score.at[idx, '代码']
    if code not in top_codes:
        continue
    
    reasons_extra = []
    risk_extra = []
    score_adj = 0
    
    # 市场环境过滤：弱市降低信号可信度，放量强势适度加分
    if market_score_adj != 0:
        score_adj += market_score_adj
        df_score.at[idx, '市场环境分'] += market_score_adj
        if market_score_adj > 0:
            reasons_extra.append(f"市场{market_status}")
        else:
            risk_extra.append(f"市场{market_status}")

    # 惩罚因子C: 5日主力资金累计方向
    flow_5d, flow_1d = fund_flow_data.get(code, (np.nan, np.nan))
    if not np.isnan(flow_5d):
        if flow_5d >= 50000:  # 5亿以上大幅净流入
            score_adj += 3
            df_score.at[idx, '资金分'] += 3
            reasons_extra.append(f"主力5日流入{flow_5d/10000:.1f}亿")
        elif flow_5d >= 10000:  # 1亿以上净流入
            score_adj += 1
            df_score.at[idx, '资金分'] += 1
            reasons_extra.append(f"主力5日流入{flow_5d/10000:.1f}亿")
        elif flow_5d <= -50000:  # 5亿以上大幅净流出
            score_adj -= 3
            df_score.at[idx, '资金分'] -= 3
            risk_extra.append(f"⚠主力5日出{abs(flow_5d)/10000:.1f}亿")
        elif flow_5d <= -10000:  # 1亿以上净流出
            score_adj -= 1
            df_score.at[idx, '资金分'] -= 1
            risk_extra.append(f"主力5日出{abs(flow_5d)/10000:.1f}亿")
    
    # 惩罚因子D: 消息面高危利空
    hit_count, hit_titles = news_risk_data.get(code, (0, []))
    if hit_count >= 3:
        score_adj -= 5
        df_score.at[idx, '消息分'] -= 5
        risk_extra.append(f"⚠重大利空{hit_count}条")
    elif hit_count >= 1:
        score_adj -= 2
        df_score.at[idx, '消息分'] -= 2
        risk_extra.append(f"利空{hit_count}条")
        
    # v4 惩罚因子E: 缩量行情下的大盘股流动性挤压
    float_cap = float_cap_data.get(code, 0)
    if is_shrinking and float_cap > 500:
        score_adj -= 3
        df_score.at[idx, '流动性分'] -= 3
        risk_extra.append(f"⚠缩量受限(流通{float_cap:.0f}亿)")
    elif float_cap > 1000:
        # 即便不极度缩量，千亿盘子也适当降权
        score_adj -= 1
        df_score.at[idx, '流动性分'] -= 1
        risk_extra.append(f"盘子太大(流通{float_cap:.0f}亿)")
        
    # v4 奖励因子F: 命中爆款概念
    if str(code).zfill(6) in hot_concept_stocks:
        score_adj += 3
        df_score.at[idx, '概念分'] += 3
        reasons_extra.append(f"🔥爆款概念成分股")
    
    df_score.at[idx, '综合评分'] += score_adj
    if reasons_extra:
        orig = df_score.at[idx, '理由']
        df_score.at[idx, '理由'] = orig + (' | ' if orig else '') + ' | '.join(reasons_extra)
    if risk_extra:
        orig = df_score.at[idx, '风险标记']
        df_score.at[idx, '风险标记'] = orig + (' | ' if orig else '') + ' | '.join(risk_extra)

# 重新排序
df_score = df_score.sort_values('综合评分', ascending=False)

# 最终推荐
print("\n  综合评分TOP30 (评分越高, 明天上涨概率越大):")
print("-" * 120)
show = df_score.head(30)
show_cols = ['代码', '名称', '板块', '出现天数', f'{last_date_label}涨跌幅', f'{last_date_label}排名',
             '上涨占比', '10日累涨', '频率分', '胜率分', '回调分', '动量分', '排名分', '趋势分',
             '板块分', '资金分', '消息分', '流动性分', '概念分', '市场环境分', '综合评分', '理由', '风险标记']
print(show[[c for c in show_cols if c in show.columns]].to_string(index=False))

# ====== Step 6: 最终筛选 ======
print("\n\n" + "=" * 80)
print(f"  四、★ 明天({predict_date_label})最可能上涨的股票 ★")
print("=" * 80)

# 分两类推荐
print(f"\n  【A类: 回调反弹型】 — {last_date_label}回调, 历史反弹率高, 明天反弹概率大")
print("-" * 120)
# 保持原筛选条件，经核验 -3% 跌幅过滤会错杀实际上涨股(特变电工+2.08%、同花顺+3.44%)
cat_a = df_score[(df_score[f'{last_date_label}涨跌幅'] < 0) & (df_score['综合评分'] >= 6)].copy()
cat_a = cat_a.sort_values('综合评分', ascending=False)
if not cat_a.empty:
    print(cat_a[['代码', '名称', '板块', '出现天数', f'{last_date_label}涨跌幅', '上涨占比', '10日累涨', '综合评分', '理由', '风险标记']].head(15).to_string(index=False))
else:
    print("  无符合条件的A类股票(降低阈值至5分)")
    cat_a = df_score[(df_score[f'{last_date_label}涨跌幅'] < 0) & (df_score['综合评分'] >= 5)].copy()
    cat_a = cat_a.sort_values('综合评分', ascending=False)
    if not cat_a.empty:
        print(cat_a[['代码', '名称', '板块', '出现天数', f'{last_date_label}涨跌幅', '上涨占比', '10日累涨', '综合评分', '理由', '风险标记']].head(15).to_string(index=False))

print(f"\n  【B类: 连续上涨型】 — 近期连续上涨, 趋势强劲, 惯性延续")
print("-" * 120)
cat_b = df_score[(df_score[f'{last_date_label}涨跌幅'] > 0) & (df_score['综合评分'] >= 7)].copy()
cat_b = cat_b.sort_values('综合评分', ascending=False)
if not cat_b.empty:
    print(cat_b[['代码', '名称', '板块', '出现天数', f'{last_date_label}涨跌幅', '上涨占比', '10日累涨', '综合评分', '理由', '风险标记']].head(15).to_string(index=False))
else:
    print("  无符合条件的B类股票(降低阈值至6分)")
    cat_b = df_score[(df_score[f'{last_date_label}涨跌幅'] > 0) & (df_score['综合评分'] >= 6)].copy()
    cat_b = cat_b.sort_values('综合评分', ascending=False)
    if not cat_b.empty:
        print(cat_b[['代码', '名称', '板块', '出现天数', f'{last_date_label}涨跌幅', '上涨占比', '10日累涨', '综合评分', '理由', '风险标记']].head(15).to_string(index=False))

# ====== 保存结果 ======
output_file = os.path.join(BASE_DIR, "pullback_analysis_result.csv")
df_score.to_csv(output_file, index=False, encoding='utf-8-sig')
print(f"\n\n完整评分结果已保存: {output_file}")

# ====== P0: 推荐日志持久化 ======
rec_date = last_trade_date.strftime('%Y-%m-%d')
rec_rows = []

if not cat_a.empty:
    for _, row in cat_a.head(10).iterrows():
        rec_rows.append({
            '推荐日期': rec_date,
            '代码': row['代码'],
            '名称': row['名称'],
            '板块': row['板块'],
            '类型': 'A-回调反弹',
            '综合评分': row['综合评分'],
            f'当日涨跌幅': row[f'{last_date_label}涨跌幅'],
        })

if not cat_b.empty:
    for _, row in cat_b.head(10).iterrows():
        rec_rows.append({
            '推荐日期': rec_date,
            '代码': row['代码'],
            '名称': row['名称'],
            '板块': row['板块'],
            '类型': 'B-趋势延续',
            '综合评分': row['综合评分'],
            f'当日涨跌幅': row[f'{last_date_label}涨跌幅'],
        })

if rec_rows:
    df_rec = pd.DataFrame(rec_rows)
    # 追加模式：如果文件已存在则不写表头
    write_header = not os.path.exists(RECOMMENDATION_LOG)
    # 先移除该日期的旧记录（防止同一天多次运行导致重复）
    if os.path.exists(RECOMMENDATION_LOG):
        df_existing = pd.read_csv(RECOMMENDATION_LOG, encoding='utf-8-sig', dtype={'代码': str})
        df_existing = df_existing[df_existing['推荐日期'] != rec_date]
        df_combined = pd.concat([df_existing, df_rec], ignore_index=True)
        df_combined.to_csv(RECOMMENDATION_LOG, index=False, encoding='utf-8-sig')
    else:
        df_rec.to_csv(RECOMMENDATION_LOG, index=False, encoding='utf-8-sig')
    print(f"📝 已将 {len(rec_rows)} 条推荐记录写入日志: {RECOMMENDATION_LOG}")

print("\n✅ 分析完成! (v7 - 含回测验证/代码标准化/市场环境过滤/评分明细/消息面降噪)")
