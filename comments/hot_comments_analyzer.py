# -*- coding: utf-8 -*-
"""
热门股票股吧评论抓取与情感/热度分析器
"""

import os
import sys
import io
import time
import random
import re
import math
import pandas as pd
import requests
from bs4 import BeautifulSoup
import akshare as ak
from datetime import datetime
from collections import Counter

# Windows GBK终端兼容，强制设置标准输出为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_OUTPUT_PATH = os.path.join(BASE_DIR, "hot_comments_summary.csv")
REPORT_OUTPUT_PATH = os.path.join(BASE_DIR, "hot_stocks_sentiment_report.md")

# 情感分析关键词字典
BULLISH_KEYWORDS = [
    "涨", "牛", "买", "好", "多", "突破", "强势", "主力流入", "加仓", 
    "主升浪", "抄底", "封板", "看多", "龙头", "起飞", "吸筹", "上攻", 
    "大牛", "稳了", "补仓", "满仓", "吃肉", "看好", "暴涨", "拉升"
]

BEARISH_KEYWORDS = [
    "跌", "熊", "卖", "垃圾", "割肉", "空", "出货", "跑路", "清仓", 
    "退潮", "跌停", "见顶", "亏损", "诱多", "做空", "砸盘", "破位", 
    "离场", "凉了", "减仓", "套牢", "崩盘", "暴跌", "看空", "骗局"
]

def analyze_sentiment(title):
    """
    基于情感词典对帖子标题进行情感打分和分类
    """
    score = 0
    # 匹配词汇并加减分
    for kw in BULLISH_KEYWORDS:
        if kw in title:
            score += 1
    for kw in BEARISH_KEYWORDS:
        if kw in title:
            score -= 1
            
    if score > 0:
        label = "看多/乐观"
    elif score < 0:
        label = "看空/悲观"
    else:
        label = "中立/理性"
    return score, label

def clean_and_parse_int(text_val):
    """
    解析并清理整数，如将 '1.2万' 转为 12000，或直接转为整数
    """
    text_val = text_val.strip()
    if not text_val:
        return 0
    try:
        if '万' in text_val:
            num_part = text_val.replace('万', '').strip()
            return int(float(num_part) * 10000)
        return int(text_val)
    except Exception:
        return 0

def fetch_guba_comments(stock_code, stock_name, rank):
    """
    抓取指定股票的东方财富股吧第一页评论列表(约80条)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://guba.eastmoney.com/',
    }
    
    url = f"https://guba.eastmoney.com/list,{stock_code}.html"
    print(f"  正在抓取 [{stock_name}({stock_code})] 股吧: {url} ...")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"    [警告] 状态码异常: {response.status_code}")
            return []
            
        # 使用 utf-8 解码东财股吧 HTML 页面
        html = response.content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, 'html.parser')
        
        rows = soup.find_all('tr', class_='listitem')
        if not rows:
            print(f"    [警告] 未解析到 tr.listitem 元素，可能是页面结构变动。")
            return []
            
        comments_data = []
        for row in rows:
            tds = row.find_all('td')
            if len(tds) < 5:
                continue
                
            # 1. 阅读量
            read_count = clean_and_parse_int(tds[0].text)
            # 2. 评论量
            reply_count = clean_and_parse_int(tds[1].text)
            
            # 3. 标题与链接
            title_td = tds[2]
            title_a = title_td.find('a', href=True)
            if not title_a:
                continue
            title_text = title_a.text.strip()
            href = title_a['href']
            if href.startswith('//'):
                full_url = f"https:{href}"
            elif href.startswith('/'):
                full_url = f"https://guba.eastmoney.com{href}"
            else:
                full_url = href
                
            # 4. 作者
            author_td = tds[3]
            author_a = author_td.find('a')
            author_name = author_a.text.strip() if author_a else author_td.text.strip()
            
            # 5. 时间
            time_text = tds[4].text.strip()
            
            # 进行情感打分
            sentiment_score, sentiment_label = analyze_sentiment(title_text)
            
            comments_data.append({
                'StockCode': stock_code,
                'StockName': stock_name,
                'PopularityRank': rank,
                'Title': title_text,
                'Link': full_url,
                'ReadCount': read_count,
                'ReplyCount': reply_count,
                'Author': author_name,
                'UpdateTime': time_text,
                'SentimentScore': sentiment_score,
                'SentimentLabel': sentiment_label
            })
            
        print(f"    成功解析出 {len(comments_data)} 条评论帖子记录。")
        return comments_data
        
    except Exception as e:
        print(f"    [错误] 抓取股吧失败: {e}")
        return []

def calculate_stock_heat(total_reads, total_replies):
    """
    根据阅读量和评论量计算热度指数 (0 - 100)
    """
    if total_reads == 0 and total_replies == 0:
        return 0.0
    # 对数计算使数据更平滑
    log_reads = math.log1p(total_reads)
    log_replies = math.log1p(total_replies)
    
    # 设定基准权重，阅读量比重20%，回复量比重80% (因为回复需要交互，更能代表真实讨论热度)
    # 假设最高单页阅读量20万(log=12.2)，最高单页评论数1000(log=6.9)
    reads_score = min(1.0, log_reads / 12.2) * 20.0
    replies_score = min(1.0, log_replies / 6.9) * 80.0
    
    heat_index = round(reads_score + replies_score, 1)
    return heat_index

def extract_hot_topics(all_comments):
    """
    从所有评论标题中提取热门话题关键词
    """
    TOPIC_KEYWORDS = {
        '韬定律': '华为韬定律', '韬': '华为韬定律',
        '华为': '华为/鸿蒙',
        '半导体': '半导体板块', '芯片': '半导体板块', '封测': '半导体板块', '封装': '半导体板块',
        'AI': 'AI/人工智能', '人工智能': 'AI/人工智能', '算力': 'AI/人工智能',
        '涨停': '涨停板', '封板': '涨停板', '打板': '涨停板',
        '减持': '股东减持', '解禁': '股东减持',
        '主力': '主力资金动向', '资金': '主力资金动向', '北向': '主力资金动向', '游资': '主力资金动向',
        '大跌': '暴跌恐慌', '暴跌': '暴跌恐慌', '杀跌': '暴跌恐慌', '跳水': '暴跌恐慌',
        '抄底': '抄底/逢低布局', '低吸': '抄底/逢低布局', '补仓': '抄底/逢低布局',
        '见顶': '见顶/出货信号', '出货': '见顶/出货信号', '高位': '见顶/出货信号', '套牢': '见顶/出货信号',
        '龙头': '龙头股讨论', '妖股': '龙头股讨论',
        '业绩': '基本面/业绩', '财报': '基本面/业绩', '利润': '基本面/业绩', '增长': '基本面/业绩',
        '利好': '利好消息', '政策': '利好消息',
        '利空': '利空消息',
        '割肉': '割肉/止损', '止损': '割肉/止损', '亏损': '割肉/止损',
        '满仓': '仓位策略', '加仓': '仓位策略', '减仓': '仓位策略', '清仓': '仓位策略',
        '突破': '技术面/突破', '均线': '技术面/突破', '趋势': '技术面/突破', '支撑': '技术面/突破',
        '光模块': '光模块/CPO', 'CPO': '光模块/CPO',
        '存储': '存储芯片', '内存': '存储芯片',
        '先进封装': '先进封装', '3D封装': '先进封装',
    }
    topic_counter = Counter()
    topic_examples = {}
    for c in all_comments:
        title = c['Title']
        matched_topics = set()
        for kw, topic in TOPIC_KEYWORDS.items():
            if kw in title:
                matched_topics.add(topic)
        for topic in matched_topics:
            topic_counter[topic] += 1
            if topic not in topic_examples or c['ReplyCount'] > topic_examples[topic]['ReplyCount']:
                topic_examples[topic] = c
    return topic_counter, topic_examples

def _fmt_title(title, max_len=40):
    t = title.replace('|', '\u4e28').replace('\n', ' ')
    return t[:max_len-1] + '...' if len(t) > max_len else t

def generate_report(stock_summaries, top_comments_all):
    """
    生成格式精美的 Markdown 分析报告 (增强版：含看涨/看跌分类及热门话题)
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    total_bullish = sum(s['BullishCount'] for s in stock_summaries)
    total_bearish = sum(s['BearishCount'] for s in stock_summaries)
    total_neutral = sum(s['NeutralCount'] for s in stock_summaries)
    total_comments = total_bullish + total_bearish + total_neutral
    
    bullish_pct = round((total_bullish / total_comments * 100), 1) if total_comments > 0 else 0.0
    bearish_pct = round((total_bearish / total_comments * 100), 1) if total_comments > 0 else 0.0
    neutral_pct = round((total_neutral / total_comments * 100), 1) if total_comments > 0 else 0.0
    
    market_sentiment = "中立偏乐观"
    if bullish_pct > bearish_pct + 10:
        market_sentiment = "乐观/多头情绪占优"
    elif bearish_pct > bullish_pct + 10:
        market_sentiment = "悲观/看空情绪占优"
    elif bullish_pct > 40:
        market_sentiment = "高度活跃/分歧较大"
        
    md = []
    md.append("# 热门股票社区评论深度舆情分析报告")
    md.append(f"\n> **报告生成时间**: {now_str}")
    md.append("> **数据源**: 东方财富个股人气榜 + 股吧讨论社区")
    md.append(f"> **分析样本**: 前 10 名热门个股的最新股吧讨论数据 (共计 {len(top_comments_all)} 条记录)")
    md.append(f"> **看涨评论**: {total_bullish} 条 ({bullish_pct}%) | **看跌评论**: {total_bearish} 条 ({bearish_pct}%) | **中立评论**: {total_neutral} 条 ({neutral_pct}%)")
    
    # === 一、市场整体舆情大盘 ===
    md.append("\n## 一、 市场整体舆情大盘")
    md.append("\n> [!NOTE]\n> 当前市场前10大热门股票在社区中呈现的情感分布如下，这代表了散户投资者的主要情绪走向：")
    
    bar_len = 30
    bullish_bar = "🔴" * int(round(bullish_pct / 100 * bar_len))
    neutral_bar = "⚪" * int(round(neutral_pct / 100 * bar_len))
    bearish_bar = "🟢" * int(round(bearish_pct / 100 * bar_len))
    
    md.append(f"\n- **看多比例 (Bullish)**: {bullish_pct}% ({total_bullish}条)")
    md.append(f"- **看空比例 (Bearish)**: {bearish_pct}% ({total_bearish}条)")
    md.append(f"- **中立比例 (Neutral)**: {neutral_pct}% ({total_neutral}条)")
    md.append(f"- **情绪能量条**: {bullish_bar}{neutral_bar}{bearish_bar}")
    md.append(f"- **市场核心情绪判定**: **{market_sentiment}**")
    
    # === 二、全市场热门话题 TOP 榜 ===
    md.append("\n## 二、 全市场讨论最多的热门话题")
    md.append("\n> [!TIP]\n> 通过自然语言关键词匹配提取散户讨论频次最高的话题，帮助判断当前市场注意力焦点：")
    
    topic_counter, topic_examples = extract_hot_topics(top_comments_all)
    top_topics = topic_counter.most_common(15)
    
    if top_topics:
        md.append("\n| 排名 | 热门话题 | 讨论次数 | 最热帖子 (点击跳转) | 阅读量 | 回复量 |")
        md.append("| :---: | :--- | :---: | :--- | :---: | :---: |")
        for rank, (topic, count) in enumerate(top_topics, 1):
            ex = topic_examples.get(topic)
            if ex:
                ex_title = _fmt_title(ex['Title'], 35)
                md.append(f"| {rank} | **{topic}** | {count} | [{ex_title}]({ex['Link']}) | {ex['ReadCount']} | {ex['ReplyCount']} |")
            else:
                md.append(f"| {rank} | **{topic}** | {count} | - | - | - |")
    
    # === 三、热门股票热度与情绪排行榜 ===
    md.append("\n## 三、 热门股票热度与情绪排行榜")
    md.append("\n| 人气排名 | 股票代码 | 股票名称 | 最新价 | 涨跌幅 | 社区热度指数 | 总阅读量 (页) | 总回复量 (页) | 乐观占比 | 悲观占比 | 核心舆情态度 |")
    md.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    
    for s in stock_summaries:
        md.append(f"| {s['Rank']} | {s['Code']} | {s['Name']} | {s['Price']} | {s['ChangePct']}% | **{s['HeatIndex']}** | {s['TotalReads']} | {s['TotalReplies']} | {s['BullishPct']}% | {s['BearishPct']}% | **{s['OverallSentiment']}** |")

    # === 四、看涨评论 TOP 20 ===
    md.append("\n## 四、 看涨 (Bullish) 评论 TOP 20")
    md.append("\n> [!IMPORTANT]\n> 以下是所有热门股票中**情绪最看涨、讨论最热烈**的评论汇总，按回复量排序：")
    
    bullish_comments = sorted(
        [c for c in top_comments_all if c['SentimentLabel'] == '看多/乐观'],
        key=lambda x: x['ReplyCount'], reverse=True
    )
    
    md.append("\n| 序号 | 股票 | 标题 (点击跳转详情) | 阅读量 | 回复量 | 作者 | 发布时间 | 看涨关键词 |")
    md.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
    
    for idx, c in enumerate(bullish_comments[:20]):
        matched = [kw for kw in BULLISH_KEYWORDS if kw in c['Title']]
        kw_str = ', '.join(matched[:3]) if matched else '-'
        title = _fmt_title(c['Title'], 35)
        md.append(f"| {idx+1} | {c['StockName']} | [{title}]({c['Link']}) | {c['ReadCount']} | {c['ReplyCount']} | {c['Author']} | {c['UpdateTime']} | {kw_str} |")
    
    # === 五、看跌评论 TOP 20 ===
    md.append("\n## 五、 看跌 (Bearish) 评论 TOP 20")
    md.append("\n> [!WARNING]\n> 以下是所有热门股票中**情绪最悲观、看空最明确**的评论汇总，按回复量排序：")
    
    bearish_comments = sorted(
        [c for c in top_comments_all if c['SentimentLabel'] == '看空/悲观'],
        key=lambda x: x['ReplyCount'], reverse=True
    )
    
    md.append("\n| 序号 | 股票 | 标题 (点击跳转详情) | 阅读量 | 回复量 | 作者 | 发布时间 | 看跌关键词 |")
    md.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
    
    for idx, c in enumerate(bearish_comments[:20]):
        matched = [kw for kw in BEARISH_KEYWORDS if kw in c['Title']]
        kw_str = ', '.join(matched[:3]) if matched else '-'
        title = _fmt_title(c['Title'], 35)
        md.append(f"| {idx+1} | {c['StockName']} | [{title}]({c['Link']}) | {c['ReadCount']} | {c['ReplyCount']} | {c['Author']} | {c['UpdateTime']} | {kw_str} |")

    # === 六、个股舆情深度穿透与走势研判 ===
    md.append("\n## 六、 个股舆情深度穿透与走势研判")
    
    for s in stock_summaries:
        code = s['Code']
        name = s['Name']
        
        md.append("\n---")
        md.append(f"\n### {name} ({code}) - 人气榜第 {s['Rank']}")
        md.append(f"\n- **基本指标**: 最新价 `{s['Price']}` | 今日涨跌 `{s['ChangePct']}%` | 社区热度指数 `{s['HeatIndex']}/100`")
        md.append(f"- **舆情倾向**: 乐观 `{s['BullishPct']}%` | 悲观 `{s['BearishPct']}%` | 中立 `{s['NeutralPct']}%` | 核心态度: **{s['OverallSentiment']}**")
        
        stock_comments = [c for c in top_comments_all if c['StockCode'] == code]
        stock_bullish = sorted([c for c in stock_comments if c['SentimentLabel'] == '看多/乐观'], key=lambda x: x['ReplyCount'], reverse=True)
        stock_bearish = sorted([c for c in stock_comments if c['SentimentLabel'] == '看空/悲观'], key=lambda x: x['ReplyCount'], reverse=True)
        stock_sorted = sorted(stock_comments, key=lambda x: x['ReplyCount'], reverse=True)
        
        md.append("\n#### 当前讨论最激烈的评论 (Top 5)")
        md.append("| 序号 | 标题 (点击跳转详情) | 阅读量 | 回复量 | 作者 | 发布时间 | 情感倾向 |")
        md.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
        for idx, c in enumerate(stock_sorted[:5]):
            title = _fmt_title(c['Title'], 38)
            md.append(f"| {idx+1} | [{title}]({c['Link']}) | {c['ReadCount']} | {c['ReplyCount']} | {c['Author']} | {c['UpdateTime']} | {c['SentimentLabel']} |")
        
        if stock_bullish:
            md.append("\n#### 看涨评论 (Top 3)")
            md.append("| 序号 | 标题 | 阅读量 | 回复量 | 看涨关键词 |")
            md.append("| :---: | :--- | :---: | :---: | :---: |")
            for idx, c in enumerate(stock_bullish[:3]):
                matched = [kw for kw in BULLISH_KEYWORDS if kw in c['Title']]
                kw_str = ', '.join(matched[:3]) if matched else '-'
                title = _fmt_title(c['Title'], 38)
                md.append(f"| {idx+1} | [{title}]({c['Link']}) | {c['ReadCount']} | {c['ReplyCount']} | {kw_str} |")
        
        if stock_bearish:
            md.append("\n#### 看跌评论 (Top 3)")
            md.append("| 序号 | 标题 | 阅读量 | 回复量 | 看跌关键词 |")
            md.append("| :---: | :--- | :---: | :---: | :---: |")
            for idx, c in enumerate(stock_bearish[:3]):
                matched = [kw for kw in BEARISH_KEYWORDS if kw in c['Title']]
                kw_str = ', '.join(matched[:3]) if matched else '-'
                title = _fmt_title(c['Title'], 38)
                md.append(f"| {idx+1} | [{title}]({c['Link']}) | {c['ReadCount']} | {c['ReplyCount']} | {kw_str} |")
            
        md.append("\n#### 散户情绪分析与未来走势预测")
        
        bp = s['BullishPct']
        bep = s['BearishPct']
        hi = s['HeatIndex']
        chg = s['ChangePct']
        
        if hi > 85 and bp > 40 and chg > 5:
            prediction = (
                f"**散户情绪判定**: 极度狂热追涨，乐观占比 {bp}%。\n"
                "**未来走势研判**: 散户看多情绪高度一致且股价大涨放量。历史规律表明，散户一致看多+放天量往往意味着**短期冲顶风险**加剧。"
                "主力可能借利好出货，建议逢高分批止盈，不宜盲目追涨。若次日高开低走则确认短期见顶。"
            )
        elif hi > 80 and bp > bep + 10 and bp <= 40:
            prediction = (
                f"**散户情绪判定**: 乐观情绪主导，看涨 {bp}% vs 看跌 {bep}%。\n"
                "**未来走势研判**: 散户整体偏乐观但尚未极度狂热，说明市场信心较强，趋势向好。"
                "短期内有望**延续上升趋势**，但需关注量能配合。若放量滞涨则需警惕。"
            )
        elif hi > 75 and bep > 35:
            prediction = (
                f"**散户情绪判定**: 恐慌抛售，看跌占比 {bep}%。\n"
                "**未来走势研判**: 股吧中充斥着割肉和看空言论，洗盘较为彻底。"
                "若股价已连续下跌，这通常是**阶段性底部信号**（恐慌盘杀出 = 底部标志），可关注企稳后的超跌反弹机会。"
            )
        elif abs(bp - bep) < 10 and hi > 70:
            prediction = (
                f"**散户情绪判定**: 多空激烈对峙，看涨 {bp}% vs 看跌 {bep}%。\n"
                "**未来走势研判**: 散户意见严重分裂，主力资金正在剧烈博弈。"
                "股价通常会**大幅震荡**，方向选择在即。建议等待放量突破或跌破关键位后再做方向性操作。"
            )
        elif bp > 25 and bp > bep:
            prediction = (
                f"**散户情绪判定**: 温和乐观，看涨 {bp}% > 看跌 {bep}%。\n"
                "**未来走势研判**: 散户关注度适中、情绪偏暖。这种'未完全狂热'状态往往最有利于**震荡上行**，"
                "主力可能正在悄悄拉升。短期趋势看好，可继续持股或轻仓逢低布局。"
            )
        else:
            prediction = (
                f"**散户情绪判定**: 态度中立观望，看涨 {bp}% / 看跌 {bep}%。\n"
                "**未来走势研判**: 市场关注度一般，股价可能受大盘或板块联动影响。"
                "短期内倾向于**横盘整理**，建议配合技术面（均线、成交量）进行高抛低吸。"
            )
            
        md.append(prediction)
        
    md.append("\n---")
    md.append("\n## 七、 免责声明")
    md.append("\n> [!CAUTION]\n> 本报告是基于社区公开评论数据进行的情感词匹配分析与情绪热度计算，代表散户心理与舆情热度，并不构成任何投资决策建议。股市有风险，投资需谨慎。")
    
    with open(REPORT_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    print(f"\n[成功] 已成功生成 Markdown 深度分析报告: {REPORT_OUTPUT_PATH}")

def main():
    print("=" * 60)
    print(" 热门股票股吧评论抓取与情感/走势分析器启动")
    print(f" 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Step 1: 从东财接口获取最新人气股排行榜 (含重试)
    print("\n[Step 1] 获取东方财富最新的个股人气榜...")
    df_hot = None
    for attempt in range(1, 6):
        try:
            df_hot = ak.stock_hot_rank_em()
            if df_hot is not None and not df_hot.empty:
                break
            print(f"  [重试 {attempt}/5] 返回数据为空，{attempt * 3}秒后重试...")
        except Exception as e:
            print(f"  [重试 {attempt}/5] 调用失败: {e}")
        time.sleep(attempt * 3)
    
    if df_hot is None or df_hot.empty:
        print("[错误] 多次重试后仍未能获取人气榜数据，程序退出。")
        return
        
    print(f"  成功获取到 {len(df_hot)} 只人气股票。")
    
    # 提取排名前10的股票
    top_n = 10
    hot_list = []
    
    # 针对 columns 映射：'当前排名', '代码', '股票名称', '最新价', '涨跌额', '涨跌幅'
    for idx, row in df_hot.head(top_n).iterrows():
        # 清洗代码，去掉前缀
        raw_code = str(row['代码'])
        m = re.search(r'\d+', raw_code)
        code = m.group(0).zfill(6) if m else raw_code
        
        hot_list.append({
            'Rank': int(row['当前排名']),
            'Code': code,
            'Name': row['股票名称'],
            'Price': float(row['最新价']),
            'ChangePct': float(row['涨跌幅'])
        })
        
    print(f"  前 {top_n} 名热门股票列表:")
    for h in hot_list:
        print(f"    第 {h['Rank']} 名: {h['Name']} ({h['Code']}) | 价格: {h['Price']} | 涨跌幅: {h['ChangePct']}%")
        
    # Step 2: 遍历股票抓取股吧评论数据
    print("\n[Step 2] 依次爬取热门股票的股吧评论并进行实时情感分析...")
    all_comments = []
    stock_summaries = []
    
    for h in hot_list:
        # 获取评论
        comments = fetch_guba_comments(h['Code'], h['Name'], h['Rank'])
        
        if comments:
            all_comments.extend(comments)
            
            # 计算这一只股票的统计指标
            total_reads = sum(c['ReadCount'] for c in comments)
            total_replies = sum(c['ReplyCount'] for c in comments)
            
            # 情感统计
            bullish_cnt = sum(1 for c in comments if c['SentimentLabel'] == "看多/乐观")
            bearish_cnt = sum(1 for c in comments if c['SentimentLabel'] == "看空/悲观")
            neutral_cnt = sum(1 for c in comments if c['SentimentLabel'] == "中立/理性")
            total_cnt = len(comments)
            
            bullish_pct = round(bullish_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0.0
            bearish_pct = round(bearish_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0.0
            neutral_pct = round(neutral_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0.0
            
            # 舆情态度判定
            if bullish_pct > bearish_pct + 8:
                overall_sentiment = "乐观占优"
            elif bearish_pct > bullish_pct + 8:
                overall_sentiment = "悲观占优"
            else:
                overall_sentiment = "多空对峙/中立"
                
            heat_index = calculate_stock_heat(total_reads, total_replies)
            
            stock_summaries.append({
                'Rank': h['Rank'],
                'Code': h['Code'],
                'Name': h['Name'],
                'Price': h['Price'],
                'ChangePct': h['ChangePct'],
                'HeatIndex': heat_index,
                'TotalReads': total_reads,
                'TotalReplies': total_replies,
                'BullishCount': bullish_cnt,
                'BearishCount': bearish_cnt,
                'NeutralCount': neutral_cnt,
                'BullishPct': bullish_pct,
                'BearishPct': bearish_pct,
                'NeutralPct': neutral_pct,
                'OverallSentiment': overall_sentiment
            })
        else:
            # 抓取失败时的默认占位
            stock_summaries.append({
                'Rank': h['Rank'],
                'Code': h['Code'],
                'Name': h['Name'],
                'Price': h['Price'],
                'ChangePct': h['ChangePct'],
                'HeatIndex': 0.0,
                'TotalReads': 0,
                'TotalReplies': 0,
                'BullishCount': 0,
                'BearishCount': 0,
                'NeutralCount': 0,
                'BullishPct': 0.0,
                'BearishPct': 0.0,
                'NeutralPct': 0.0,
                'OverallSentiment': "获取数据失败"
            })
            
        # 随机延迟，防止被反爬虫策略检测
        sleep_time = random.uniform(1.5, 3.0)
        print(f"    [休眠] 随机等待 {sleep_time:.2f} 秒...")
        time.sleep(sleep_time)
        
    # Step 3: 保存明细数据到 CSV 文件
    print("\n[Step 3] 保存提取的所有评论帖子明细数据到 CSV 文件...")
    if all_comments:
        df_all_comments = pd.DataFrame(all_comments)
        # 用 utf-8-sig 保存，防止用 Excel 打开时中文乱码
        df_all_comments.to_csv(CSV_OUTPUT_PATH, index=False, encoding='utf-8-sig')
        print(f"  已生成 CSV 详细数据: {CSV_OUTPUT_PATH} (包含 {len(df_all_comments)} 行记录)")
    else:
        print("  [警告] 没有收集到任何评论数据，未生成 CSV 文件。")
        
    # Step 4: 汇中并生成 Markdown 分析报告
    print("\n[Step 4] 汇总分析并生成 Markdown 深度研究报告...")
    if stock_summaries:
        generate_report(stock_summaries, all_comments)
    else:
        print("  [错误] 汇总摘要信息为空，无法生成分析报告。")
        
    print("\n" + "=" * 60)
    print(" ✅ 抓取与深度舆情分析任务已全部完成！")
    print(f"  - 原始明细数据: {CSV_OUTPUT_PATH}")
    print(f"  - 分析报告文档: {REPORT_OUTPUT_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    main()
