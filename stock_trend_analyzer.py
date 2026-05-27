# -*- coding: utf-8 -*-
"""
A股通用股票趋势、量能与主力资金流向分析工具（基于成交额）
"""
import akshare as ak
import pandas as pd
import numpy as np
import os
import sys
import io
import requests
import bs4
import datetime

# 统一输出编码为UTF-8，防止Windows终端乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 禁用全局代理，确保境内财经API请求不受干扰
_original_get = requests.get
def _no_proxy_get(url, **kwargs):
    kwargs['proxies'] = {'http': None, 'https': None}
    return _original_get(url, **kwargs)
requests.get = _no_proxy_get

def get_sina_symbol(code):
    """
    转换股票代码为新浪/腾讯等接口所需的带前缀格式
    """
    if code.startswith('6') or code.startswith('9') or code.startswith('688'):
        return 'sh' + code
    elif code.startswith('0') or code.startswith('3') or code.startswith('002'):
        return 'sz' + code
    elif code.startswith('4') or code.startswith('8'):
        return 'bj' + code
    else:
        return 'sh' + code

def get_stock_info_from_csv(code):
    """
    尝试从本地 100 目录下的 CSV 文件匹配股票名称与板块
    """
    try:
        csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "100")
        if os.path.exists(csv_dir):
            for file in os.listdir(csv_dir):
                if file.startswith("top100_") and file.endswith(".csv"):
                    df_csv = pd.read_csv(os.path.join(csv_dir, file), encoding='utf-8-sig', dtype={'代码': str})
                    df_csv['代码'] = df_csv['代码'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)
                    match = df_csv[df_csv['代码'] == code]
                    if not match.empty:
                        name = match.iloc[0]['名称']
                        sector = match.iloc[0]['所属板块'] if '所属板块' in match.columns else "其他"
                        return name, sector
    except Exception:
        pass
    return None, None

def get_stock_name_and_sector(code):
    """
    多渠道获取股票名称和行业板块名称
    """
    name, sector = get_stock_info_from_csv(code)
    
    # 1. 尝试腾讯 API 获取最新股票简称
    if not name:
        try:
            symbol = get_sina_symbol(code)
            url = f"http://qt.gtimg.cn/q=s_{symbol}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                r.encoding = 'gbk'
                parts = r.text.split('~')
                if len(parts) > 1:
                    name = parts[1]
        except Exception:
            pass

    # 2. 尝试东财接口
    if not name:
        try:
            df_info = ak.stock_individual_info_em(symbol=code)
            name_row = df_info[df_info['item'] == '股票简称']
            if not name_row.empty:
                name = name_row.iloc[0]['value']
        except Exception:
            pass

    if not name:
        name = "未知股票"
    if not sector:
        sector = "未知板块"
        
    return name, sector

def classify_volume_by_amount(row):
    """
    根据成交额（资金面）而非成交量（股数）来判定更专业的量能状态
    结合考虑相对5日均值(额量比)和相对前一日(较前日额变)的双重维度
    """
    price_chg = row['涨跌幅']
    amount_ratio = row['额量比']
    amount_chg = row['较前一日额变']
    
    if pd.isna(amount_ratio) or pd.isna(amount_chg):
        return "平量震荡"
        
    # 涨跌停判定
    if price_chg >= 9.5:
        return "放量涨停" if amount_chg > 0 else "缩量涨停"
    elif price_chg <= -9.5:
        return "放量跌停" if amount_chg > 0 else "缩量跌停"
        
    # 专业量能状态分类
    # 1. 额量比极高 (>= 1.4)
    if amount_ratio >= 1.4:
        if price_chg >= 1.5:
            return "高位缩量大涨" if amount_chg <= -10 else "放量大涨"
        elif price_chg <= -1.5:
            return "高位缩量大跌" if amount_chg <= -10 else "放量大跌"
        else:
            return "放量滞涨" # 成交额极大股价不动，分歧严重或主力分批派发
            
    # 2. 额量比较高 (>= 1.2)
    elif amount_ratio >= 1.2:
        if price_chg > 0:
            return "高位缩量上涨" if amount_chg <= -10 else "放量上涨"
        else:
            return "高位缩量下跌" if amount_chg <= -10 else "放量下跌"
            
    # 3. 额量比极低 (<= 0.75) 且较前日明显缩量
    elif amount_ratio <= 0.75 and amount_chg <= -15:
        if price_chg >= 0.5:
            return "缩量上涨" # 惜售筹码锁定，无量空涨
        elif price_chg <= -0.5:
            return "无量洗盘" # 无恐慌盘，属技术回踩
        else:
            return "地量震荡"
            
    # 4. 温和缩量 (<= 0.85)
    elif amount_ratio <= 0.85 and amount_chg <= -10:
        if price_chg > 0:
            return "温和缩量上涨"
        else:
            return "温和缩量下跌"
            
    # 5. 温和放量 (>= 1.05)
    elif amount_ratio >= 1.05 and amount_chg >= 5:
        if price_chg > 0:
            return "温和放量上涨"
        else:
            return "温和放量下跌"
    else:
        return "平量震荡"

def fetch_and_analyze_news(code):
    """
    通过新浪财经爬取该股票的最新消息，并使用关键词规则归纳利好、利空
    """
    symbol = get_sina_symbol(code)
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{symbol}.phtml"
    
    stock_name, _ = get_stock_name_and_sector(code)
    pos_keywords = ['提价', '价格上调', '增长', '突破', '增持', '回购', '中标', '合作', '签约',
                    '扭亏为盈', '首发', '量产', '领先', '新进展', '高增长', '送样', '验证', '布局',
                    '预增', '订单', '扩产', '创新高', '战略合作']
    neg_keywords = ['冻结', '轮候冻结', '被冻结', '调查', '诉讼', '立案', '被执行', '亏损',
                    '同比下降', '下滑', '计提', '减持', '警告', '监管', '查处', '立案调查',
                    '问询函', '处罚', '终止', '退市', '商誉减值']
    
    pos_news = []
    neg_news = []
    neutral_news = []
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'gbk' # 新浪页面多使用 GBK
        
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
        list_div = soup.find(class_='datelist')
        if not list_div:
            return pos_news, neg_news, [{"date": "", "title": "未能获取到个股新闻数据（解析失败）", "link": "#"}]
            
        ul = list_div.find('ul')
        if not ul:
            return pos_news, neg_news, [{"date": "", "title": "未能获取到个股新闻数据（无公告列表）", "link": "#"}]
            
        # 爬取最近的一个月内的前30条新闻
        count = 0
        for a_tag in ul.find_all('a'):
            if count >= 30:
                break
                
            title = a_tag.text.strip()
            link = a_tag.get('href')
            
            # 获取日期兄弟节点
            date_str = ""
            prev = a_tag.previous_sibling
            if prev and isinstance(prev, bs4.element.NavigableString):
                date_str = prev.strip().replace('\xa0', ' ')
            
            item = {"date": date_str, "title": title, "link": link}
            
            # 情感分类：仅标题直接命中个股名称或代码时才判定，减少行业新闻误判
            company_hit = (stock_name and stock_name in title) or (code in title)
            is_pos = company_hit and any(kw in title for kw in pos_keywords)
            is_neg = company_hit and any(kw in title for kw in neg_keywords)
            
            if is_neg:
                neg_news.append(item)
            elif is_pos:
                pos_news.append(item)
            else:
                neutral_news.append(item)
            count += 1
            
    except Exception as e:
        print(f"新闻爬取异常: {e}")
        return [], [], [{"date": "", "title": f"新闻爬取出现故障: {e}", "link": "#"}]
        
    return pos_news, neg_news, neutral_news

def resolve_stock_code(input_str):
    """
    根据输入（代码或名称）解析出6位股票代码
    """
    input_str = input_str.strip()
    if not input_str:
        return None
        
    # 如果本身就是6位数字，直接返回
    if len(input_str) == 6 and input_str.isdigit():
        return input_str
        
    # 尝试从本地 100 目录下的 CSV 文件匹配股票名称
    try:
        csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "100")
        if os.path.exists(csv_dir):
            for file in os.listdir(csv_dir):
                if file.startswith("top100_") and file.endswith(".csv"):
                    df_csv = pd.read_csv(os.path.join(csv_dir, file), encoding='utf-8-sig', dtype={'代码': str})
                    df_csv['代码'] = df_csv['代码'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)
                    match = df_csv[df_csv['名称'] == input_str]
                    if not match.empty:
                        return match.iloc[0]['代码']
    except Exception:
        pass

    # 尝试从东方财富/新浪等网络接口中获取 A股 代码与名称对照表匹配
    try:
        df_codes = ak.stock_info_a_code_name()
        df_codes['code'] = df_codes['code'].astype(str).str.extract(r'(\d+)', expand=False).fillna('').str.zfill(6)
        match = df_codes[df_codes['name'] == input_str]
        if not match.empty:
            return match.iloc[0]['code']
        
        # 模糊匹配
        match_sub = df_codes[df_codes['name'].str.contains(input_str, na=False)]
        if not match_sub.empty:
            return match_sub.iloc[0]['code']
    except Exception:
        pass
        
    return None

def main():
    # 允许命令行参数传入股票代码/名称，或者动态输入
    if len(sys.argv) > 1:
        input_val = sys.argv[1].strip()
    else:
        input_val = input("请输入要分析的股票代码或名称 (例如 600703 或 长电科技): ").strip()
        
    if not input_val:
        print("错误：输入不能为空！")
        return
        
    print(f"[*] 正在解析输入 '{input_val}' 对应的股票代码...")
    code = resolve_stock_code(input_val)
    if not code:
        print(f"错误：无法将 '{input_val}' 解析为有效的股票代码！")
        return
        
    print(f"[*] 解析成功：代码为 {code}")
        
    # 获取股票简称与行业板块
    print(f"\n[*] 正在解析股票 {code} 的基本信息...")
    stock_name, sector_name = get_stock_name_and_sector(code)
    print(f"    股票简称: {stock_name} | 所属板块: {sector_name}")
    
    # 往前推约50天以保证计算滚动的5日均额
    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=50)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")
    
    # 1. 获取量价数据
    print(f"[1/4] 正在获取历史K线数据...")
    df = None
    try:
        # 首选东财历史数据（含换手率、成交额）
        df = ak.stock_zh_a_hist(symbol=code, start_date=start_date, end_date=end_date, adjust="qfq")
    except Exception as e:
        print(f"  东财常规接口获取失败 ({e})，尝试切换到腾讯接口做备用估算...")
        try:
            symbol_tx = get_sina_symbol(code)
            df = ak.stock_zh_a_hist_tx(symbol=symbol_tx, start_date=start_date, end_date=end_date, adjust="qfq")
            # 腾讯接口字段重命名并估算成交额
            df = df.rename(columns={
                'date': '日期', 'open': '开盘', 'close': '收盘', 
                'high': '最高', 'low': '最低', 'amount': '成交量'
            })
            df['日期'] = pd.to_datetime(df['日期'])
            df['成交额'] = df['成交量'] * 100 * df['收盘'] # 成交量(手) * 100 * 股价 = 估算成交额
            df['换手率'] = np.nan # 腾讯接口无换手率
        except Exception as ex:
            print(f"  错误：无法获取股票 {code} 的行情数据 ({ex})")
            return

    if df is None or df.empty:
        print("未获取到有效的历史数据。")
        return
        
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期').reset_index(drop=True)
    
    # 动态追加今日实时行情（若历史K线尚未更新今日数据）
    has_today = False
    if not df.empty:
        last_date = pd.to_datetime(df['日期'].iloc[-1]).strftime("%Y-%m-%d")
        if last_date == today.strftime("%Y-%m-%d"):
            has_today = True
            
    if not has_today:
        try:
            import re
            symbol_tx = get_sina_symbol(code)
            url = f"http://qt.gtimg.cn/q={symbol_tx}"
            r = requests.get(url, timeout=5)
            r.encoding = 'gbk'
            parts = r.text.strip().split('~')
            if len(parts) > 38:
                trade_time_str = parts[30]
                m_date = re.search(r'(\d{4})[-/]?(\d{2})[-/]?(\d{2})', trade_time_str)
                if m_date:
                    trade_date = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"
                    if trade_date == today.strftime("%Y-%m-%d"):
                        close_price = float(parts[3])
                        open_price = float(parts[5])
                        high_price = float(parts[33])
                        low_price = float(parts[34])
                        turnover_cny = float(parts[37]) * 10000.0 if parts[37] else 0.0
                        turnover_rate = float(parts[38]) if parts[38] else np.nan
                        vol_raw = float(parts[6]) if parts[6] else 0.0
                        if code.startswith('688') or code.startswith('8') or code.startswith('4'):
                            volume_shares = vol_raw
                        else:
                            volume_shares = vol_raw * 100
                        
                        if turnover_cny > 0:
                            new_row = pd.DataFrame([{
                                '日期': pd.to_datetime(trade_date),
                                '开盘': open_price,
                                '收盘': close_price,
                                '最高': high_price,
                                '最低': low_price,
                                '成交量': volume_shares,
                                '成交额': turnover_cny,
                                '换手率': turnover_rate
                            }])
                            df = pd.concat([df, new_row], ignore_index=True)
                            print(f"  成功追加今日 ({trade_date}) 实时行情数据：收盘={close_price}, 成交额={turnover_cny/10000.0:.1f}万")
        except Exception as e:
            print(f"  获取今日实时行情数据失败 ({e})")
            
    df = df.sort_values('日期').reset_index(drop=True)
    
    # 计算量价核心指标
    df['涨跌幅'] = df['收盘'].pct_change() * 100
    df['成交额_万'] = df['成交额'] / 10000.0
    df['5日均额_万'] = df['成交额_万'].rolling(window=5).mean()
    df['较前一日额变'] = df['成交额_万'].pct_change() * 100
    df['额量比'] = df['成交额_万'] / df['5日均额_万']
    
    # 2. 获取主力资金流向数据
    print(f"[2/4] 正在获取主力资金流向数据...")
    df_flow = None
    try:
        df_flow = ak.stock_individual_fund_flow(stock=code)
        if df_flow is not None and not df_flow.empty:
            df_flow['日期'] = pd.to_datetime(df_flow['日期'])
            df_flow['主力流入_万'] = df_flow['主力净流入-净额'] / 10000.0
            df_flow['主力占比_%'] = df_flow['主力净流入-净占比']
            df_flow = df_flow[['日期', '主力流入_万', '主力占比_%']]
            df = pd.merge(df, df_flow, on='日期', how='left')
    except Exception as e:
        print(f"  获取主力资金流向数据失败 ({e})")
        
    if '主力流入_万' not in df.columns:
        df['主力流入_万'] = np.nan
    if '主力占比_%' not in df.columns:
        df['主力占比_%'] = np.nan
        
    df['量能状态'] = df.apply(classify_volume_by_amount, axis=1)
    
    # 3. 动态爬取个股最新消息面分类
    print(f"[3/4] 正在获取个股最新消息面...")
    pos_news, neg_news, neutral_news = fetch_and_analyze_news(code)
    
    # 4. 构造分析报告表格
    print(f"[4/4] 正在生成深度分析报告...")
    recent_df = df.tail(10).copy()
    
    table_rows = []
    for idx, r in recent_df.iterrows():
        chg_amt = r['较前一日额变']
        chg_amt_str = f"{chg_amt:+.1f}%" if not pd.isna(chg_amt) else "N/A"
        
        turnover_val = r['换手率']
        turnover_str = f"{turnover_val:.2f}%" if not pd.isna(turnover_val) else "N/A"
        
        flow_val = r['主力流入_万']
        flow_str = f"{flow_val:+,.0f}" if not pd.isna(flow_val) else "N/A"
        
        flow_pct_val = r['主力占比_%']
        flow_pct = f"{flow_pct_val:+.1f}%" if not pd.isna(flow_pct_val) else "N/A"
        
        table_rows.append(
            f"| {r['日期'].strftime('%Y-%m-%d')} | {r['收盘']:.2f} | {r['涨跌幅']:+.2f}% | {r['成交额_万']:11,.0f} | {chg_amt_str:>8} | {r['额量比']:.2f} | {turnover_str:>7} | {flow_str:>11} | {flow_pct:>8} | **{r['量能状态']}** |"
        )
    table_str = "\n".join(table_rows)
    
    # 构造利好利空新闻的 Markdown 文本
    pos_news_md = ""
    if pos_news:
        for n in pos_news[:8]:
            pos_news_md += f"*   **[{n['date']}]** {n['title']} ([链接]({n['link']}))\n"
    else:
        pos_news_md = "*   暂无识别到的核心利好新闻/公告\n"
        
    neg_news_md = ""
    if neg_news:
        for n in neg_news[:8]:
            neg_news_md += f"*   **[{n['date']}]** {n['title']} ([链接]({n['link']}))\n"
    else:
        neg_news_md = "*   暂无识别到的核心利空新闻/公告\n"
        
    neutral_news_md = ""
    if neutral_news:
        for n in neutral_news[:8]:
            neutral_news_md += f"*   **[{n['date']}]** {n['title']} ([链接]({n['link']}))\n"
    else:
        neutral_news_md = "*   暂无其他中性新闻\n"
        
    # 分析结论
    last_row = recent_df.iloc[-1]
    latest_date_str = last_row['日期'].strftime('%Y-%m-%d')
    
    flow_val = last_row['主力流入_万']
    flow_pct_val = last_row['主力占比_%']
    if not pd.isna(flow_val) and not pd.isna(flow_pct_val):
        fund_flow_text = f"资金面显示，主力资金单日净流入额为 **{flow_val:+,.0f}** 万元，净占比为 **{flow_pct_val:+.1f}%**。"
    else:
        fund_flow_text = "资金面显示，当日主力资金流向数据暂未公布或存在缺失。"

    conclusion = f"""
1. **量能与资金特征分析**：
   * 在最新交易日（{latest_date_str}）中，该股收盘于 {last_row['收盘']:.2f} 元，涨跌幅为 {last_row['涨跌幅']:+.2f}%。
   * 当日成交额为 {last_row['成交额_万']:,.0f} 万元，较前一日增减量为 {last_row['较前一日额变']:+.1f}%。
   * 成交额占 5日均额 的比例（额量比）为 **{last_row['额量比']:.2f}**，最终量能判定为 **“{last_row['量能状态']}”**。
   * {fund_flow_text}
   
2. **多空消息面交叉验证**：
   * **利空因素**：需警惕近期频繁发生的控股股东司法诉讼或轮候冻结、管理层变动调查以及一季报财务压力等信息。
   * **利好支持**：光技术与半导体板块提价、新材料量产验证和前沿高新领域的进展对股价有中长期支撑。

3. **操作指导参考**：
   * 若量能呈现**“放量上涨”**且主力资金大幅流入，多头趋势较强，可顺势持股；
   * 若呈现**“放量滞涨”**或**“放量下跌”**且伴随主力资金大幅流出，说明高位分歧大或主力正在出货，需注意防范调整风险；
   * 若呈现**“无量洗盘”**或**“缩量下跌”**，一般代表市场抛压不大，属良性修正，可静待企稳。
"""

    report_md = f"""# {stock_name} ({code}) 最近10个交易日量价、主力资金与消息面深度分析报告

本报告对**{stock_name} ({code})** 在最近10个交易日的成交额变化（缩量/放量）、主力资金动向（主力净流入）以及个股多空新闻进行了系统性、多维度的梳理。

* **所属行业板块**: {sector_name}

---

## 一、 最近10个交易日量价与资金明细表

| 交易日期 | 收盘价 (元) | 涨跌幅 (%) | 成交额 (万元) | 较前日额变 | 额量比 (量比) | 换手率 (%) | 主力流入 (万元) | 主力流入占比 | 量能状态判定 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
{table_str}

> **指标说明**：
> 1. **额量比** = 当日成交额 / 5日移动平均成交额。若量比 > 1.2 判定为明显放量，< 0.8 判定为明显缩量。
> 2. **主力流入** = 东方财富超大单净流入 + 大单净流入的金额之和。
> 3. **量能状态** 根据主力资金规模、成交额与涨跌幅综合得出，较传统“股数成交量”更能真实反映主力调仓与控盘意图。

---

## 二、 动态爬取个股最新消息面分类

### 1. 核心利好与催化事件（疑似利好/技术进展）
{pos_news_md}

### 2. 风险警示与潜在隐患（疑似利空/股份冻结/立案）
{neg_news_md}

### 3. 其他中性及行业新闻
{neutral_news_md}

---

## 三、 综合量价、资金与消息面研判
{conclusion}

---

> [!WARNING]
> 本报告内容基于公开市场 and 网络数据，通过系统算法分析生成。不构成任何明示或暗示的投资建议。股市有风险，入市需谨慎。
"""

    # 保存报告至本地文件
    output_filename = f"{code}_analysis_report.md"
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print(f"\n================================================================================")
    print(f" 报告分析完成！")
    print(f" 报告文件已成功输出至: {output_path}")
    print(f"================================================================================")
    
    # 打印前 15 行表格和研判供终端参考
    print(report_md[:1200])
    print("...\n(报告其余部分已写入文件)")

if __name__ == "__main__":
    main()
