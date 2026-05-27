# -*- coding: utf-8 -*-
"""
获取近10个交易日每天成交量前100名的股票，并输出到指定目录。
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import io
import glob

# Windows GBK终端兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(BASE_DIR, "100")
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# 往前推30天，以确保能拿到10个交易日
start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
end_date = datetime.now().strftime("%Y%m%d")
today_str = datetime.now().strftime("%Y-%m-%d")
target_days = 10

print("=" * 60)
print(f"开始抓取近 {target_days} 个交易日的成交量前100名股票")
print(f"输出目录: {output_dir}")
print("=" * 60)

# 禁用requests代理以防止网络问题
import requests
import re
_original_get = requests.get
def _no_proxy_get(url, **kwargs):
    kwargs['proxies'] = {'http': None, 'https': None}
    return _original_get(url, **kwargs)
requests.get = _no_proxy_get

# Step 1: 建立候选池
print("\n[Step 1] 获取全市场代码并使用腾讯接口建立高活跃候选池...")
df_codes = ak.stock_info_a_code_name()
df_codes['code'] = df_codes['code'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)

def normalize_stock_code(code):
    m = re.search(r"\d+", str(code))
    return m.group(0).zfill(6) if m else ""

def to_tencent_code(c):
    if c.startswith('6') or c.startswith('5'):
        return f'sh{c}'
    return f'sz{c}'

def normalize_volume_to_shares(code, vol):
    # 科创板688xxx、北交所8xxxxx/4xxxxx，返回的成交量已经是“股”
    # 沪深主板60xxxx/00xxxx、创业板30xxxx，返回的成交量是“手”，需乘以100转为“股”
    if code.startswith('688') or code.startswith('8') or code.startswith('4'):
        return vol
    return vol * 100

df_codes['tencent'] = df_codes['code'].apply(to_tencent_code)
codes_list = df_codes['tencent'].tolist()

all_spot = []
batch_size = 400
for i in range(0, len(codes_list), batch_size):
    batch = codes_list[i:i+batch_size]
    url = f"http://qt.gtimg.cn/q={','.join(batch)}"
    try:
        r = requests.get(url, timeout=15)
        for line in r.text.split(';'):
            line = line.strip()
            if not line or 'v_' not in line:
                continue
            m = re.search(r'v_(\w+)="(.*)"', line)
            if not m:
                continue
            f = m.group(2).split('~')
            if len(f) < 45:
                continue
            try:
                turnover = float(f[37]) * 10000 if f[37] else 0  # 腾讯接口f[37]是成交额(万元)，转为元
                vol = int(f[6]) if f[6] else 0
                price = float(f[3]) if f[3] else 0.0
                change_pct = float(f[32]) if f[32] else 0.0
                code = normalize_stock_code(f[2])
                if turnover > 0:
                    all_spot.append({
                        'tencent': m.group(1),
                        '代码': code,
                        '名称': f[1],
                        '成交量': normalize_volume_to_shares(code, vol),
                        '成交额': turnover,
                        '收盘': price,
                        '涨跌幅': change_pct
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"  批次请求失败: {e}")
    time.sleep(0.15)

df_spot = pd.DataFrame(all_spot)
if df_spot.empty:
    print("未能获取实时数据，请检查网络。")
    sys.exit(1)

# 取今天成交额最大的前1000名作为候选池
candidate_pool_size = 1000
df_spot = df_spot.sort_values(by="成交额", ascending=False).head(candidate_pool_size)
candidates = df_spot['tencent'].tolist() # 使用带sh/sz的代码，以便调用腾讯K线
name_map = dict(zip(df_spot['代码'], df_spot['名称']))

# 建立代码映射以在合并时查找实时数据
spot_dict = df_spot.set_index('代码').to_dict(orient='index')

print(f"  成功建立 {len(candidates)} 只高活跃股票的候选池。")

# Step 2: 获取候选池的历史K线
print("\n[Step 2] 获取候选池股票的近期历史K线 (使用多线程加速)...")
all_klines = []
fail_count = 0
t0 = time.time()

from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_single_stock(symbol):
    try:
        df_h = ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start_date, end_date=end_date, adjust="qfq")
        code = normalize_stock_code(symbol[2:])
        has_today = False
        local_klines = []
        if df_h is not None and not df_h.empty:
            for _, row in df_h.iterrows():
                row_date = str(row['date'])
                if row_date == today_str:
                    has_today = True
                close_val = float(row['close'])
                vol_raw = float(row['amount'])
                vol_shares = normalize_volume_to_shares(code, vol_raw)
                local_klines.append({
                    '代码': code,
                    '日期': row_date,
                    '收盘': close_val,
                    '涨跌幅': 0.0, # 稍后统一计算
                    '成交量': int(vol_shares),
                    '成交额': vol_shares * close_val
                })
            return symbol, local_klines, has_today
        else:
            return symbol, [], False
    except Exception:
        return symbol, [], False

with ThreadPoolExecutor(max_workers=30) as executor:
    futures = {executor.submit(fetch_single_stock, sym): sym for sym in candidates}
    for idx, future in enumerate(as_completed(futures)):
        sym, local_klines, has_today = future.result()
        code = sym[2:]
        if local_klines:
            all_klines.extend(local_klines)
        else:
            fail_count += 1
            
        # 如果K线数据里没有今天的最新数据，且实时数据有该股票，我们手动把今天的实时数据作为最后一行拼进去
        if not has_today and code in spot_dict:
            spot_row = spot_dict[code]
            all_klines.append({
                '代码': code,
                '日期': today_str,
                '收盘': spot_row['收盘'],
                '涨跌幅': spot_row['涨跌幅'],
                '成交量': spot_row['成交量'],
                '成交额': spot_row['成交额']
            })
            
        if (idx + 1) % 100 == 0:
            print(f"  进度: {idx+1}/{len(candidates)} 只股票，已获取 {len(all_klines)} 条记录, 失败 {fail_count} 只, 耗时 {time.time()-t0:.1f} 秒")

print(f"  完成! 成功获取 {len(all_klines)} 条记录, 失败 {fail_count} 只 (总耗时 {time.time()-t0:.1f} 秒)")

df_all = pd.DataFrame(all_klines)
if not df_all.empty and '代码' in df_all.columns:
    df_all['代码'] = df_all['代码'].apply(normalize_stock_code)

if df_all.empty:
    print("未获取到历史数据。")
    sys.exit(1)

# Step 2.5: 计算历史K线的涨跌幅、3日涨幅、5日涨幅
print("\n[Step 2.5] 计算历史K线各项涨跌幅...")
df_all = df_all.sort_values(by=['代码', '日期'])
df_all['涨跌幅'] = df_all.groupby('代码')['收盘'].pct_change() * 100
df_all['涨跌幅'] = df_all['涨跌幅'].fillna(0.0).round(2)
df_all['3日涨幅'] = df_all.groupby('代码')['收盘'].pct_change(periods=3) * 100
df_all['3日涨幅'] = df_all['3日涨幅'].fillna(0.0).round(2)
df_all['5日涨幅'] = df_all.groupby('代码')['收盘'].pct_change(periods=5) * 100
df_all['5日涨幅'] = df_all['5日涨幅'].fillna(0.0).round(2)

# Step 3: 按日期切片并提取Top 100
print("\n[Step 3] 计算每日Top 100并保存...")

# 提取所有的交易日并排序
trade_dates = sorted(df_all['日期'].unique(), reverse=True)

# 取最近的10个交易日
recent_10_dates = trade_dates[:target_days]
print(f"  识别到最近的 {len(recent_10_dates)} 个交易日: {recent_10_dates[::-1]}")

# 找出这10天内所有出现在Top 100的独特股票代码，用于批量获取所属板块，减少请求次数
unique_top_codes = set()
for d in recent_10_dates:
    day_df = df_all[df_all['日期'] == d]
    top100_codes = day_df.sort_values(by='成交额', ascending=False).head(100)['代码'].tolist()
    unique_top_codes.update(top100_codes)

unique_top_codes = sorted(list(unique_top_codes))
print(f"  这 {len(recent_10_dates)} 天内共出现 {len(unique_top_codes)} 只不同的 Top 100 股票，正在获取它们的所属板块...")

industry_map = {}
def fetch_industry(code):
    fmt_code = str(code).zfill(6)
    try:
        df_profile = ak.stock_profile_cninfo(symbol=fmt_code)
        if df_profile is not None and not df_profile.empty and '所属行业' in df_profile.columns:
            ind = df_profile['所属行业'].values[0]
            # 清理行业名称，使其更精简（例如“计算机、通信和其他电子设备制造业” -> “电子设备制造”）
            if ind == "计算机、通信和其他电子设备制造业":
                ind = "电子设备制造"
            elif ind.endswith("制造业"):
                ind = ind[:-3]
            return fmt_code, ind
        return fmt_code, "未知"
    except Exception:
        return fmt_code, "未知"

# 使用线程池并发获取行业数据，避免被单线程延迟拖累
from concurrent.futures import ThreadPoolExecutor, as_completed
t_ind_start = time.time()
with ThreadPoolExecutor(max_workers=20) as ex:
    futures = {ex.submit(fetch_industry, c): c for c in unique_top_codes}
    for idx, future in enumerate(as_completed(futures)):
        c, ind = future.result()
        industry_map[c] = ind
        if (idx + 1) % 50 == 0:
            print(f"    已获取 {idx+1}/{len(unique_top_codes)} 只股票的所属板块... (耗时 {time.time()-t_ind_start:.1f} 秒)")

print(f"  板块数据获取完毕，共耗时 {time.time()-t_ind_start:.1f} 秒")

for d in recent_10_dates:
    day_df = df_all[df_all['日期'] == d].copy()
    
    # 按照成交额排序，取前100 (真实的大资金排名)
    top100 = day_df.sort_values(by='成交额', ascending=False).head(100).copy()
    
    # 添加名称、排名、所属板块
    top100['代码'] = top100['代码'].apply(normalize_stock_code)
    top100['名称'] = top100['代码'].map(name_map)
    top100['排名'] = range(1, len(top100) + 1)
    top100['所属板块'] = top100['代码'].apply(lambda x: industry_map.get(str(x).zfill(6), "未知"))
    
    # 调整列顺序
    cols = ['排名', '代码', '名称', '日期', '收盘', '涨跌幅', '3日涨幅', '5日涨幅', '成交量', '成交额', '所属板块']
    top100 = top100[[c for c in cols if c in top100.columns]]
    
    # 保存文件
    clean_date = d.replace("-", "")
    
    # === 新增: 时间戳与清理防重逻辑 ===
    if d == today_str:
        # 取消清理逻辑，保留日内的所有切片用于 pullback_analysis 的多时段分析
        time_suffix = datetime.now().strftime("_%H%M%S")
        filename = os.path.join(output_dir, f"top100_{clean_date}{time_suffix}.csv")
    else:
        filename = os.path.join(output_dir, f"top100_{clean_date}.csv")
    
    # 防止乱码用 utf-8-sig
    top100.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"  已生成: {filename} (包含 {len(top100)} 只股票)")

print(f"\n✅ 任务完成！所有文件已成功保存到 {output_dir}")
