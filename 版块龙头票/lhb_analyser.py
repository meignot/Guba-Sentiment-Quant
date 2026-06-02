# -*- coding: utf-8 -*-
"""
龙虎榜席位资金追踪工具
支持输入个股代码/名称，自动拉取近期上榜日期及详细席位资金（机构、外资、主要营业部）。
"""

import os
import sys
import io
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# Windows GBK终端兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 禁用全局代理
_original_get = requests.get
def _no_proxy_get(url, **kwargs):
    kwargs['proxies'] = {'http': None, 'https': None}
    headers = kwargs.get('headers', {})
    if not headers:
        headers = {}
    else:
        headers = headers.copy()
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    if 'Referer' not in headers:
        headers['Referer'] = 'https://quote.eastmoney.com/'
    kwargs['headers'] = headers
    return _original_get(url, **kwargs)
requests.get = _no_proxy_get

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "版块龙头票")

def resolve_stock_code(input_str):
    """根据输入（代码或名称）解析出6位股票代码，并获取简称"""
    input_str = input_str.strip()
    if not input_str:
        return None, None
        
    # 如果本身就是6位数字，尝试获取名称
    if len(input_str) == 6 and input_str.isdigit():
        code = input_str
        # 尝试从本地 100 目录匹配简称
        try:
            csv_dir = os.path.join(BASE_DIR, "100")
            if os.path.exists(csv_dir):
                for file in os.listdir(csv_dir):
                    if file.startswith("top100_") and file.endswith(".csv"):
                        df_csv = pd.read_csv(os.path.join(csv_dir, file), encoding='utf-8-sig', dtype={'代码': str})
                        df_csv['代码'] = df_csv['代码'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)
                        match = df_csv[df_csv['代码'] == code]
                        if not match.empty:
                            return code, match.iloc[0]['名称']
        except Exception:
            pass
            
        # 尝试用腾讯接口获取简称
        try:
            prefix = 'sh' if code.startswith('6') or code.startswith('688') else 'sz'
            url = f"http://qt.gtimg.cn/q=s_{prefix}{code}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                r.encoding = 'gbk'
                parts = r.text.split('~')
                if len(parts) > 1:
                    return code, parts[1]
        except Exception:
            pass
            
        return code, "未知简称"

    # 尝试从本地 100 目录下的 CSV 文件匹配股票名称
    try:
        csv_dir = os.path.join(BASE_DIR, "100")
        if os.path.exists(csv_dir):
            for file in os.listdir(csv_dir):
                if file.startswith("top100_") and file.endswith(".csv"):
                    df_csv = pd.read_csv(os.path.join(csv_dir, file), encoding='utf-8-sig', dtype={'代码': str})
                    df_csv['代码'] = df_csv['代码'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)
                    match = df_csv[df_csv['名称'] == input_str]
                    if not match.empty:
                        return match.iloc[0]['代码'], input_str
    except Exception:
        pass

    # 尝试从东方财富 A股代码名称对照表匹配
    try:
        import akshare as ak
        df_codes = ak.stock_info_a_code_name()
        df_codes['code'] = df_codes['code'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)
        match = df_codes[df_codes['name'] == input_str]
        if not match.empty:
            return match.iloc[0]['code'], input_str
        
        # 模糊匹配
        match_sub = df_codes[df_codes['name'].str.contains(input_str, na=False)]
        if not match_sub.empty:
            return match_sub.iloc[0]['code'], match_sub.iloc[0]['name']
    except Exception:
        pass
        
    return None, None

def analyze_lhb(code, name, target_date_str=None):
    import akshare as ak
    
    print(f"[*] 正在拉取 {name} ({code}) 的龙虎榜上榜历史日期...")
    try:
        df_dates = ak.stock_lhb_stock_detail_date_em(symbol=code)
    except Exception as e:
        print(f"[-] 获取龙虎榜日期失败: {e}")
        return
        
    if df_dates is None or df_dates.empty:
        print(f"[-] {name} ({code}) 近期未上过龙虎榜！")
        return
        
    # 第一列是索引，第二列是代码，第三列是日期
    # print(df_dates.head())
    dates_list = df_dates.iloc[:, 2].tolist()
    
    print(f"[+] 该股近期上榜次数：{len(dates_list)} 次")
    print(f"    最近 5 次上榜日期: {[d.strftime('%Y-%m-%d') for d in dates_list[:5]]}")
    
    if target_date_str:
        # 匹配指定的日期
        # 清理格式
        target_date = pd.to_datetime(target_date_str).date()
        if target_date in dates_list:
            selected_date = target_date
        else:
            print(f"[-] 指定的日期 {target_date_str} 该股未登上龙虎榜。")
            print(f"    将分析最近一次上榜日期: {dates_list[0]}")
            selected_date = dates_list[0]
    else:
        selected_date = dates_list[0]
        
    date_formatted = selected_date.strftime("%Y%m%d")
    date_display = selected_date.strftime("%Y-%m-%d")
    print(f"\n[*] 正在抓取 {date_display} 的龙虎榜席位明细资金...")
    
    try:
        df_detail = ak.stock_lhb_stock_detail_em(symbol=code, date=date_formatted)
    except Exception as e:
        print(f"[-] 抓取龙虎榜席位明细失败: {e}")
        return
        
    if df_detail is None or df_detail.empty:
        print(f"[-] 未能获取 {date_display} 的席位明细数据。")
        return
        
    # 解析明细数据
    # 营业部名称在第1列，买入额在第2列，卖出额在第4列，净额在第6列，上榜原因在第7列
    # 建立清洗后的DataFrame
    parsed_seats = []
    
    # 记录上榜原因 (所有行都一样)
    reason = df_detail.iloc[0, 7] if len(df_detail.columns) > 7 else "未知原因"
    
    for idx, row in df_detail.iterrows():
        seat_name = str(row.iloc[1])
        buy_amt = float(row.iloc[2]) if not pd.isna(row.iloc[2]) else 0.0
        sell_amt = float(row.iloc[4]) if not pd.isna(row.iloc[4]) else 0.0
        net_amt = float(row.iloc[6]) if not pd.isna(row.iloc[6]) else 0.0
        
        # 判断席位类型
        seat_type = '普通营业部'
        
        # 机构席位判定 (中文或Unicode points)
        seat_points = [ord(c) for c in seat_name]
        is_inst = "机构专用" in seat_name or [26426, 26500, 19987, 29992] == seat_points
        
        # 外资席位判定 (深股通/沪股通)
        is_connect = any(kw in seat_name for kw in ["深股通", "沪股通", "深港通", "沪港通", "深股通专用", "沪股通专用"]) or \
                     [28145, 32929, 36890, 19987, 29992] == seat_points or \
                     [37098, 32929, 36890, 19987, 29992] == seat_points
                     
        if is_inst:
            seat_type = '机构专用'
        elif is_connect:
            seat_type = '陆股通专用 (北向外资)'
            
        parsed_seats.append({
            '席位名称': seat_name,
            '席位类型': seat_type,
            '买入额_万': buy_amt / 10000.0,
            '卖出额_万': sell_amt / 10000.0,
            '净额_万': net_amt / 10000.0
        })
        
    df_seats = pd.DataFrame(parsed_seats)
    
    # 去重处理：东财API中买入前五和卖出前五包含重复席位，且整行数据完全相同，直接求和会导致翻倍。
    df_seats = df_seats.drop_duplicates(subset=['席位名称']).reset_index(drop=True)
    
    # 统计分类汇总
    # 1. 机构席位汇总
    inst_df = df_seats[df_seats['席位类型'] == '机构专用']
    inst_buy = inst_df['买入额_万'].sum()
    inst_sell = inst_df['卖出额_万'].sum()
    inst_net = inst_df['净额_万'].sum()
    inst_count = len(inst_df)
    
    # 2. 外资陆股通汇总
    conn_df = df_seats[df_seats['席位类型'] == '陆股通专用 (北向外资)']
    conn_buy = conn_df['买入额_万'].sum()
    conn_sell = conn_df['卖出额_万'].sum()
    conn_net = conn_df['净额_万'].sum()
    conn_count = len(conn_df)
    
    # 3. 游资席位汇总 (买入前三/卖出前三)
    yyb_df = df_seats[df_seats['席位类型'] == '普通营业部']
    
    # 4. 整体买入榜和卖出榜
    top_buyers = df_seats.sort_values(by='买入额_万', ascending=False).head(5)
    top_sellers = df_seats.sort_values(by='卖出额_万', ascending=False).head(5)
    
    # 打印控制台输出
    print("=" * 70)
    print(f" 📊 {name} ({code}) 龙虎榜席位资金深度追踪报告")
    print(f" 📅 上榜日期: {date_display} | 上榜原因: {reason}")
    print("=" * 70)
    
    print("\n[一] 核心机构与外资席位汇总:")
    print("-" * 50)
    print(f" 🏦 机构专用席位 (共 {inst_count} 家):")
    print(f"    ▶ 累计买入：{inst_buy:.2f} 万元")
    print(f"    ▶ 累计卖出：{inst_sell:.2f} 万元")
    print(f"    ▶ 净流入量：{inst_net:+.2f} 万元 " + ("(🔥主力抢筹)" if inst_net > 0 else "(💨主力减仓)" if inst_net < 0 else ""))
    
    print(f"\n 🌐 陆股通专用席位 (外资/北向，共 {conn_count} 家):")
    print(f"    ▶ 累计买入：{conn_buy:.2f} 万元")
    print(f"    ▶ 累计卖出：{conn_sell:.2f} 万元")
    print(f"    ▶ 净流入量：{conn_net:+.2f} 万元")
    print("-" * 50)
    
    print("\n[二] 买入金额最大的前 5 家席位明细:")
    print(top_buyers[['席位名称', '席位类型', '买入额_万', '卖出额_万', '净额_万']].to_string(index=False))
    
    print("\n[三] 卖出金额最大的前 5 家席位明细:")
    print(top_sellers[['席位名称', '席位类型', '买入额_万', '卖出额_万', '净额_万']].to_string(index=False))
    
    # 生成报告 Markdown 文本
    report_title = f"{name}_{code}_LHB席位分析_{date_formatted}"
    report_path = os.path.join(OUTPUT_DIR, f"{report_title}.md")
    
    inst_status = "机构净买入" if inst_net > 0 else "机构净卖出"
    conn_status = "外资净买入" if conn_net > 0 else "外资净卖出"
    
    top_buyers_rows = []
    for idx, r in top_buyers.iterrows():
        top_buyers_rows.append(f"| {r['席位名称']} | {r['席位类型']} | {r['买入额_万']:.2f} | {r['卖出额_万']:.2f} | {r['净额_万']:+.2f} |")
    top_buyers_str = "\n".join(top_buyers_rows)
    
    top_sellers_rows = []
    for idx, r in top_sellers.iterrows():
        top_sellers_rows.append(f"| {r['席位名称']} | {r['席位类型']} | {r['买入额_万']:.2f} | {r['卖出额_万']:.2f} | {r['净额_万']:+.2f} |")
    top_sellers_str = "\n".join(top_sellers_rows)

    report_md = f"""# {name} ({code}) 龙虎榜席位资金深度分析报告

本报告针对 **{name} ({code})** 在 **{date_display}** 登上龙虎榜的席位交易数据进行分类汇总，重点追踪**机构专用席位**及**外资（陆股通专用）**的买卖方向和规模，从而评判多空资金的力量博弈。

*   **分析日期**：{datetime.now().strftime("%Y-%m-%d")}
*   **龙虎榜日期**：{date_display}
*   **上榜原因**：{reason}

---

## 一、 核心席位主力资金分布

| 席位类型 | 上榜席位数 | 累计买入 (万元) | 累计卖出 (万元) | 净买入 (万元) | 资金态度判定 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **机构专用** | {inst_count} | {inst_buy:.2f} | {inst_sell:.2f} | {inst_net:+.2f} | **{inst_status}** |
| **陆股通专用 (北向外资)** | {conn_count} | {conn_buy:.2f} | {conn_sell:.2f} | {conn_net:+.2f} | **{conn_status}** |

> **主力研判**：
> 1. 机构专用席位累计买卖轧差后为 **{inst_net:+.2f}** 万元，表明机构态度为**{"积极流入抢筹" if inst_net > 0 else "逢高派发出货"}**。
> 2. 北向外资席位累计净买入额为 **{conn_net:+.2f}** 万元。

---

## 二、 龙虎榜交易额前 5 买入席位明细

| 席位/营业部名称 | 席位类型 | 买入金额 (万) | 卖出金额 (万) | 净额 (万) |
| :--- | :---: | :---: | :---: | :---: |
{top_buyers_str}

---

## 三、 龙虎榜交易额前 5 卖出席位明细

| 席位/营业部名称 | 席位类型 | 买入金额 (万) | 卖出金额 (万) | 净额 (万) |
| :--- | :---: | :---: | :---: | :---: |
{top_sellers_str}

---

## 四、 核心席位特征与席位风格分析

1.  **机构动作评估**：
    在 {date_display}，有 **{inst_count}** 家机构专用席位在买入/卖出方向上榜。总体来说，机构资金净买入达 **{inst_net:.2f}** 万元，表明公募基金/社保等长线主力在当前节点**{"偏向于做多" if inst_net > 0 else "偏向于止盈/割肉"}**。
2.  **外资（陆股通）动向**：
    深股通/沪股通席位在当日呈现 **{conn_net:+.2f}** 万元净额，说明外资在题材热度下的态度是 **{"增仓跟进" if conn_net > 0 else "顺势减磅"}**。
3.  **活跃游资席位分析**：
    - 在前五买入席位中，出现了以普通营业部为代表的游资主力，需密切关注其后续炒作的可持续性或是否为“一日游”资金。

---

> [!WARNING]
> 龙虎榜席位数据为盘后数据公布，反映当天已发生的资金动向。游资、外资和机构席位买卖金额不构成明细的未来股价趋势保证，请谨慎对待。
"""
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print(f"\n================================================================================")
    print(f" 席位资金分析完成！")
    print(f" 报告文件已写入: {report_path}")
    print(f"================================================================================")

def main():
    if len(sys.argv) > 1:
        input_val = sys.argv[1].strip()
    else:
        input_val = input("请输入要分析的股票代码或简称 (例如 002579 或 中京电子): ").strip()
        
    if not input_val:
        print("错误：输入不能为空！")
        return
        
    print(f"[*] 正在解析股票代码: '{input_val}'...")
    code, name = resolve_stock_code(input_val)
    if not code:
        print(f"错误：无法将 '{input_val}' 解析为有效的股票代码！")
        return
        
    print(f"[+] 解析成功: {name} ({code})")
    
    # 提取龙虎榜并分析
    target_date = sys.argv[2].strip() if len(sys.argv) > 2 else None
    analyze_lhb(code, name, target_date)

if __name__ == '__main__':
    main()
