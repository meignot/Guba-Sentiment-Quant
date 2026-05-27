# -*- coding: utf-8 -*-
"""
长电科技 (600584) 股吧舆情深度抓取与交互式可视化分析器
"""

import os
import sys
import io
import time
import random
import re
import math
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from collections import Counter

# Windows GBK终端兼容，强制设置标准输出为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_OUTPUT_PATH = os.path.join(BASE_DIR, "changdian_comments.csv")
HTML_OUTPUT_PATH = os.path.join(BASE_DIR, "changdian_sentiment.html")

# 针对半导体/封测及长电科技优化的情感分析关键词
BULLISH_KEYWORDS = [
    "涨", "牛", "买", "好", "多", "突破", "强势", "主力流入", "加仓", 
    "主升浪", "抄底", "封板", "看多", "龙头", "起飞", "吸筹", "上攻", 
    "大牛", "稳了", "补仓", "满仓", "吃肉", "看好", "暴涨", "拉升",
    "先进封装", "Chiplet", "小芯片", "封测龙头", "重组", "收购",
    "大基金三期", "卡脖子突破", "设备国产化", "订单爆满", "三期大基金",
    "华为封装", "海思封测", "科技牛", "大白马", "金股", "见底信号"
]

BEARISH_KEYWORDS = [
    "跌", "熊", "卖", "垃圾", "割肉", "空", "出货", "跑路", "清仓", 
    "退潮", "跌停", "见顶", "亏损", "诱多", "做空", "砸盘", "破位", 
    "离场", "凉了", "减仓", "套牢", "崩盘", "暴跌", "看空", "骗局",
    "大流出", "主力跑路", "高位接盘", "散户接盘", "被套", "业绩暴雷",
    "解禁大潮", "股东减持", "清仓式减持", "利空来袭", "泡沫破裂"
]

# 针对长电科技/半导体板块的核心讨论话题分类
TOPICS_DICT = {
    "先进封装/Chiplet": ["先进封装", "封装", "封测", "Chiplet", "小芯片", "扇出", "系统级封装", "SiP", "2.5D", "3D", "甬矽", "华天", "通富"],
    "半导体板块与芯片": ["半导体", "芯片", "集成电路", "板块", "概念股", "硬件", "科技股", "行业周期"],
    "华为与海思协作": ["华为", "海思", "算力", "鸿蒙", "韬定律", "韬", "麒麟"],
    "大基金三期与国资": ["大基金", "国资", "三期", "政策利好", "国家队", "大基金三期"],
    "资金动向与洗盘": ["主力", "资金", "洗盘", "出货", "吸筹", "庄家", "游资", "大单", "净流入", "净流出", "大笔", "拉升", "砸盘"],
    "散户情绪与加减仓": ["抄底", "抄", "低吸", "补仓", "加仓", "买入", "持股", "满仓", "建仓", "割肉", "跑路", "减仓", "清仓", "离场", "被套"],
    "股价大跌与恐慌": ["大跌", "暴跌", "跳水", "崩了", "凉了", "绿了", "垃圾", "跌停", "套牢", "骗局", "亏损"],
    "业绩预期与季报": ["业绩", "中报", "季报", "年报", "分红", "营收", "利润", "净利", "毛利", "订单", "产能", "稼动率"]
}

def analyze_sentiment(title):
    """
    基于词典匹配分析评论标题的情感倾向
    """
    score = 0
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
    解析并清理整数，如将 '1.2万' 转为 12000
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

def detect_topics(title):
    """
    匹配标题中所讨论的核心话题类别
    """
    matched = []
    for topic, keywords in TOPICS_DICT.items():
        for kw in keywords:
            if kw in title:
                matched.append(topic)
                break
    if not matched:
        return ["其他讨论"]
    return matched

def fetch_jcet_comments(pages=4):
    """
    抓取长电科技股吧多页评论数据
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://guba.eastmoney.com/',
    }
    
    all_comments = []
    
    for page in range(1, pages + 1):
        if page == 1:
            url = "https://guba.eastmoney.com/list,600584.html"
        else:
            url = f"https://guba.eastmoney.com/list,600584_{page}.html"
            
        print(f"  正在抓取第 {page}/{pages} 页: {url} ...")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"    [警告] 状态码异常: {response.status_code}")
                continue
                
            html = response.content.decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.find_all('tr', class_='listitem')
            if not rows:
                print(f"    [警告] 未解析到评论行，可能被触发了防爬规则。")
                continue
                
            page_comments = []
            for row in rows:
                tds = row.find_all('td')
                if len(tds) < 5:
                    continue
                    
                read_count = clean_and_parse_int(tds[0].text)
                reply_count = clean_and_parse_int(tds[1].text)
                
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
                    
                author_td = tds[3]
                author_a = author_td.find('a')
                author_name = author_a.text.strip() if author_a else author_td.text.strip()
                
                time_text = tds[4].text.strip()
                
                score, label = analyze_sentiment(title_text)
                topics = detect_topics(title_text)
                
                page_comments.append({
                    'Title': title_text,
                    'Link': full_url,
                    'ReadCount': read_count,
                    'ReplyCount': reply_count,
                    'Author': author_name,
                    'UpdateTime': time_text,
                    'SentimentScore': score,
                    'SentimentLabel': label,
                    'Topics': topics
                })
            
            print(f"    成功解析出 {len(page_comments)} 条评论记录。")
            all_comments.extend(page_comments)
            
            # 随机延迟，减缓请求频率
            if page < pages:
                sleep_time = random.uniform(1.5, 3.0)
                print(f"    [防封封禁机制] 等待 {sleep_time:.2f} 秒...")
                time.sleep(sleep_time)
                
        except Exception as e:
            print(f"    [错误] 抓取第 {page} 页异常: {e}")
            
    return all_comments

def calculate_heat(total_reads, total_replies):
    """
    根据总阅读量和回复数计算热度评分 (0-100)
    """
    if total_reads == 0 and total_replies == 0:
        return 0.0
    log_reads = math.log1p(total_reads)
    log_replies = math.log1p(total_replies)
    
    # 假设 4 页总阅读量上限约 80万 (log ≈ 13.6), 总回复量约 2000 (log ≈ 7.6)
    reads_score = min(1.0, log_reads / 13.6) * 20.0
    replies_score = min(1.0, log_replies / 7.6) * 80.0
    return round(reads_score + replies_score, 1)

def format_large_number(num):
    if num >= 10000:
        return f"{num / 10000:.1f}万"
    return str(num)

def generate_interactive_html(comments):
    """
    动态生成嵌入数据的交互式 HTML 页面
    """
    total_comments = len(comments)
    if total_comments == 0:
        print("[错误] 没有评论数据，无法生成 HTML。")
        return
        
    # 计算统计数据
    total_reads = sum(c['ReadCount'] for c in comments)
    total_replies = sum(c['ReplyCount'] for c in comments)
    
    bullish_count = sum(1 for c in comments if c['SentimentLabel'] == "看多/乐观")
    bearish_count = sum(1 for c in comments if c['SentimentLabel'] == "看空/悲观")
    neutral_count = sum(1 for c in comments if c['SentimentLabel'] == "中立/理性")
    
    bullish_pct = round(bullish_count / total_comments * 100, 1) if total_comments > 0 else 0.0
    bearish_pct = round(bearish_count / total_comments * 100, 1) if total_comments > 0 else 0.0
    neutral_pct = round(neutral_count / total_comments * 100, 1) if total_comments > 0 else 0.0
    
    avg_score = round(sum(c['SentimentScore'] for c in comments) / total_comments, 2) if total_comments > 0 else 0.0
    heat_index = calculate_heat(total_reads, total_replies)
    
    # 情绪评级计算
    if bullish_pct > bearish_pct + 15:
        sentiment_rating = "乐观占优 / 多头强劲"
        rating_color = "#ef4444"
    elif bearish_pct > bullish_pct + 15:
        sentiment_rating = "悲观占优 / 空头势盛"
        rating_color = "#10b981"
    elif abs(bullish_pct - bearish_pct) <= 15 and heat_index > 75:
        sentiment_rating = "分歧加剧 / 多空博弈"
        rating_color = "#f59e0b"
    else:
        sentiment_rating = "情绪中立 / 观望气氛"
        rating_color = "#94a3b8"
        
    # 话题计数
    topic_counter = Counter()
    for c in comments:
        for t in c['Topics']:
            topic_counter[t] += 1
            
    # 构建嵌入的 JS 数据
    # 添加一个原初索引 index，供前端排序使用
    for idx, c in enumerate(comments):
        c['index'] = total_comments - idx # 确保第一个爬取的最新帖有最大的 index
        
    comments_json = json.dumps(comments, ensure_ascii=False)
    
    stats_json = json.dumps({
        'bullish': bullish_count,
        'bearish': bearish_count,
        'neutral': neutral_count,
        'topics': dict(topic_counter)
    }, ensure_ascii=False)
    
    # HTML 模版内容
    html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>长电科技 (600584) 舆情与情绪深度可视化分析</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #0b0f19;
            --bg-gradient: linear-gradient(135deg, #0b0f19 0%, #111827 50%, #1e293b 100%);
            --card-bg: rgba(17, 24, 39, 0.6);
            --card-border: rgba(255, 255, 255, 0.08);
            --card-hover-border: rgba(99, 102, 241, 0.4);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --text-muted: #6b7280;
            --bullish-color: #ef4444;
            --bearish-color: #10b981;
            --neutral-color: #64748b;
            --primary: #6366f1;
            --primary-gradient: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
            --glow-shadow: 0 0 15px rgba(99, 102, 241, 0.15);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--bg-color);
            background-image: var(--bg-gradient);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2rem 1.5rem;
            line-height: 1.5;
            overflow-x: hidden;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .glass-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .glass-card:hover {
            border-color: var(--card-hover-border);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4), var(--glow-shadow);
            transform: translateY(-2px);
        }
        
        header {
            margin-bottom: 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.5rem;
            padding: 1.5rem 2rem;
            position: relative;
            overflow: hidden;
        }
        
        header::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
        }
        
        .header-title-area h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 800;
            letter-spacing: -0.025em;
            background: linear-gradient(120deg, #ffffff 30%, #a5b4fc 90%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .header-title-area p {
            color: var(--text-secondary);
            font-size: 0.95rem;
            margin-top: 0.25rem;
        }
        
        .stock-badge {
            background: var(--primary-gradient);
            color: #ffffff;
            font-size: 0.9rem;
            padding: 0.2rem 0.8rem;
            border-radius: 9999px;
            font-weight: 600;
            border: 1px solid rgba(255, 255, 255, 0.2);
            font-family: 'Outfit', sans-serif;
        }
        
        .header-meta {
            text-align: right;
        }
        
        .header-meta .time {
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-weight: 500;
        }
        
        .header-meta .source {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.2rem;
        }
        
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .kpi-card {
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
        }
        
        .kpi-card .label {
            font-size: 0.85rem;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.75rem;
        }
        
        .kpi-card .value {
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 700;
            line-height: 1.1;
            margin-bottom: 0.75rem;
        }
        
        .kpi-card .sub-info {
            font-size: 0.85rem;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .kpi-card.heat .value {
            color: #fbbf24;
        }
        .kpi-card.bullish .value {
            color: var(--bullish-color);
        }
        .kpi-card.bearish .value {
            color: var(--bearish-color);
        }
        
        .sentiment-bar-container {
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 9999px;
            overflow: hidden;
            margin-top: 0.5rem;
            display: flex;
        }
        .sentiment-bar-fill {
            height: 100%;
        }
        .bullish-fill { background-color: var(--bullish-color); }
        .neutral-fill { background-color: var(--neutral-color); }
        .bearish-fill { background-color: var(--bearish-color); }
        
        .dashboard-main {
            display: grid;
            grid-template-columns: 1fr;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        @media(min-width: 1024px) {
            .dashboard-main {
                grid-template-columns: 4fr 5fr;
            }
        }
        
        .chart-box {
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            min-height: 340px;
        }
        
        .chart-box h2 {
            font-size: 1.1rem;
            font-weight: 700;
            margin-bottom: 1.25rem;
            color: var(--text-primary);
            border-left: 4px solid var(--primary);
            padding-left: 0.75rem;
        }
        
        .chart-container {
            position: relative;
            flex-grow: 1;
            width: 100%;
            height: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        .comments-section {
            padding: 2rem;
        }
        
        .comments-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        
        .comments-header h2 {
            font-size: 1.3rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .comments-controls {
            display: flex;
            align-items: center;
            gap: 1rem;
            flex-wrap: wrap;
            width: 100%;
        }
        
        @media(min-width: 768px) {
            .comments-controls {
                width: auto;
            }
        }
        
        .filter-group {
            display: flex;
            background: rgba(255, 255, 255, 0.05);
            padding: 0.25rem;
            border-radius: 9999px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        .filter-btn {
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 0.85rem;
            font-weight: 600;
            padding: 0.4rem 1.1rem;
            border-radius: 9999px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .filter-btn:hover {
            color: var(--text-primary);
        }
        
        .filter-btn.active {
            background: var(--primary);
            color: #ffffff;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
        }
        
        .filter-btn[data-sentiment="bullish"].active {
            background: var(--bullish-color);
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.25);
        }
        
        .filter-btn[data-sentiment="bearish"].active {
            background: var(--bearish-color);
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25);
        }
        
        .filter-btn[data-sentiment="neutral"].active {
            background: var(--neutral-color);
            box-shadow: 0 4px 12px rgba(100, 116, 139, 0.25);
        }
        
        .search-wrapper {
            position: relative;
            flex-grow: 1;
            min-width: 250px;
        }
        
        .search-input {
            width: 100%;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-primary);
            font-size: 0.85rem;
            padding: 0.55rem 1rem 0.55rem 2.2rem;
            border-radius: 9999px;
            outline: none;
            transition: all 0.3s;
        }
        
        .search-input:focus {
            border-color: var(--primary);
            background: rgba(255, 255, 255, 0.08);
            box-shadow: 0 0 10px rgba(99, 102, 241, 0.15);
        }
        
        .search-icon {
            position: absolute;
            left: 0.8rem;
            top: 50%;
            transform: translateY(-50%);
            width: 0.95rem;
            height: 0.95rem;
            color: var(--text-secondary);
            pointer-events: none;
        }
        
        .sort-select {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-primary);
            font-size: 0.85rem;
            padding: 0.55rem 2rem 0.55rem 1rem;
            border-radius: 9999px;
            outline: none;
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%239ca3af'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 0.75rem center;
            background-size: 0.9rem;
        }
        
        .sort-select:focus {
            border-color: var(--primary);
        }
        
        .comments-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            margin-bottom: 1.5rem;
            max-height: 700px;
            overflow-y: auto;
            padding-right: 0.5rem;
        }
        
        .comments-list::-webkit-scrollbar {
            width: 6px;
        }
        .comments-list::-webkit-scrollbar-track {
            background: transparent;
        }
        .comments-list::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.15);
            border-radius: 9999px;
        }
        .comments-list::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.3);
        }
        
        .comment-item {
            padding: 1.1rem;
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
        }
        
        .comment-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        .comment-author {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 500;
        }
        
        .avatar-placeholder {
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: var(--primary-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            font-size: 0.7rem;
            font-weight: 700;
        }
        
        .comment-time {
            color: var(--text-muted);
        }
        
        .comment-title {
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-primary);
            text-decoration: none;
            line-height: 1.4;
            transition: color 0.2s;
            cursor: pointer;
        }
        
        .comment-title:hover {
            color: var(--primary);
        }
        
        .comment-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin-top: 0.2rem;
        }
        
        .sentiment-badge {
            font-size: 0.7rem;
            font-weight: 700;
            padding: 0.15rem 0.6rem;
            border-radius: 9999px;
            display: inline-flex;
            align-items: center;
        }
        
        .sentiment-badge.bullish {
            background: rgba(239, 68, 68, 0.12);
            color: #ff6b6b;
            border: 1px solid rgba(239, 68, 68, 0.2);
        }
        
        .sentiment-badge.bearish {
            background: rgba(16, 185, 129, 0.12);
            color: #4eedb5;
            border: 1px solid rgba(16, 185, 129, 0.2);
        }
        
        .sentiment-badge.neutral {
            background: rgba(100, 116, 139, 0.12);
            color: #94a3b8;
            border: 1px solid rgba(100, 116, 139, 0.2);
        }
        
        .stats-group {
            display: flex;
            align-items: center;
            gap: 0.9rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        .stat-item {
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }
        
        .stat-icon {
            width: 0.85rem;
            height: 0.85rem;
            color: var(--text-muted);
        }
        
        .topics-group {
            display: flex;
            gap: 0.3rem;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .topic-tag {
            font-size: 0.68rem;
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-secondary);
            padding: 0.1rem 0.4rem;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .topic-tag:hover {
            background: rgba(99, 102, 241, 0.12);
            border-color: rgba(99, 102, 241, 0.25);
            color: #a5b4fc;
        }
        
        .topic-tag.active {
            background: rgba(99, 102, 241, 0.2);
            border-color: rgba(99, 102, 241, 0.45);
            color: #a5b4fc;
            font-weight: 500;
        }
        
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-secondary);
        }
        .empty-state-icon {
            width: 2.5rem;
            height: 2.5rem;
            color: var(--text-muted);
            margin: 0 auto 1rem auto;
        }
        
        .pagination-controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 1.25rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 1rem;
        }
        
        .page-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: var(--text-primary);
            padding: 0.4rem 0.9rem;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .page-btn:hover:not(:disabled) {
            background: rgba(255, 255, 255, 0.1);
            border-color: var(--primary);
        }
        
        .page-btn:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }
        
        .page-info {
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-weight: 500;
        }
        
        footer.page-footer {
            margin-top: 3rem;
            text-align: center;
            font-size: 0.78rem;
            color: var(--text-muted);
            padding: 1.5rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="glass-card">
            <div class="header-title-area">
                <h1>长电科技 <span class="stock-badge">600584</span> 舆情与情绪深度分析</h1>
                <p>基于东方财富股吧讨论社区的实时文本挖掘与情感分类</p>
            </div>
            <div class="header-meta">
                <div class="time">分析时间: <span>UPDATE_TIME_PLACEHOLDER</span></div>
                <div class="source">数据源: 东方财富个股讨论社区 (最新 <span>TOTAL_COMMENTS_PLACEHOLDER</span> 条)</div>
            </div>
        </header>
        
        <div class="kpi-grid">
            <div class="kpi-card glass-card heat">
                <div class="label">社区讨论热度指数</div>
                <div class="value"><span>HEAT_INDEX_PLACEHOLDER</span> <span style="font-size: 1.1rem; color: var(--text-secondary);">/ 100</span></div>
                <div class="sub-info">
                    <span>总阅读: <span>TOTAL_READS_PLACEHOLDER</span></span>
                    <span>•</span>
                    <span>总回复: <span>TOTAL_REPLIES_PLACEHOLDER</span></span>
                </div>
            </div>
            
            <div class="kpi-card glass-card bullish">
                <div class="label">看涨言论占比 (Bullish)</div>
                <div class="value"><span>BULLISH_PCT_PLACEHOLDER</span>%</div>
                <div class="sub-info">
                    <span><span>BULLISH_COUNT_PLACEHOLDER</span> 条乐观讨论</span>
                </div>
                <div class="sentiment-bar-container">
                    <div class="sentiment-bar-fill bullish-fill" style="width: BULLISH_PCT_PLACEHOLDER%"></div>
                </div>
            </div>
            
            <div class="kpi-card glass-card bearish">
                <div class="label">看跌言论占比 (Bearish)</div>
                <div class="value"><span>BEARISH_PCT_PLACEHOLDER</span>%</div>
                <div class="sub-info">
                    <span><span>BEARISH_COUNT_PLACEHOLDER</span> 条悲观讨论</span>
                </div>
                <div class="sentiment-bar-container">
                    <div class="sentiment-bar-fill bearish-fill" style="width: BEARISH_PCT_PLACEHOLDER%"></div>
                </div>
            </div>
            
            <div class="kpi-card glass-card">
                <div class="label">社区散户情绪评级</div>
                <div class="value" style="color: RATING_COLOR_PLACEHOLDER; font-size: 1.65rem; padding: 0.2rem 0; font-family: system-ui, -apple-system, sans-serif;">SENTIMENT_RATING_PLACEHOLDER</div>
                <div class="sub-info">
                    <span>平均情感倾向得分: <span>AVG_SENTIMENT_PLACEHOLDER</span></span>
                </div>
            </div>
        </div>
        
        <div class="dashboard-main">
            <div class="chart-box glass-card">
                <h2>情感倾向分布</h2>
                <div class="chart-container">
                    <canvas id="sentimentChart"></canvas>
                </div>
            </div>
            
            <div class="chart-box glass-card">
                <h2>核心热门话题频次 (Top 8)</h2>
                <div class="chart-container">
                    <canvas id="topicChart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="comments-section glass-card">
            <div class="comments-header">
                <h2>股吧最新讨论列表 <span id="totalItems" style="font-size: 0.9rem; color: var(--text-secondary); font-weight: 500;">(0)</span></h2>
                <div class="comments-controls">
                    <div class="search-wrapper">
                        <svg class="search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                        </svg>
                        <input type="text" id="searchInput" class="search-input" placeholder="检索帖子关键词/发布作者...">
                    </div>
                    
                    <div class="filter-group">
                        <button class="filter-btn active" data-sentiment="all">全部</button>
                        <button class="filter-btn" data-sentiment="bullish">看多</button>
                        <button class="filter-btn" data-sentiment="bearish">看空</button>
                        <button class="filter-btn" data-sentiment="neutral">中立</button>
                    </div>
                    
                    <select id="sortSelect" class="sort-select">
                        <option value="time">按发布时间排序</option>
                        <option value="reads">按阅读量排序</option>
                        <option value="replies">按回复数排序</option>
                        <option value="sentiment">按情感评分排序</option>
                    </select>
                </div>
            </div>
            
            <div id="commentsList" class="comments-list">
                <!-- 动态渲染 -->
            </div>
            
            <div class="pagination-controls">
                <button id="pagePrev" class="page-btn" disabled>上一页</button>
                <div id="pageInfo" class="page-info">1 / 1</div>
                <button id="pageNext" class="page-btn" disabled>下一页</button>
            </div>
        </div>
        
        <footer class="page-footer">
            <p>免责声明：本页面是基于社区公开评论通过中文匹配提取获得的情感打分，仅用于辅助了解散户注意力与市场热度，不包含任何正式投资指引。</p>
            <p style="margin-top: 0.5rem; color: var(--text-muted);">© 2026 量化舆情监测工作站 • 长电科技 (600584) 分析视图</p>
        </footer>
    </div>

    <script>
        // 序列化的评论数据
        const comments = COMMENTS_JSON_PLACEHOLDER;
        const stats = STATS_JSON_PLACEHOLDER;

        let activeSentiment = 'all';
        let activeTopic = null;
        let searchQuery = '';
        let sortBy = 'time';
        let currentPage = 1;
        const itemsPerPage = 15;

        let filteredComments = [...comments];

        // DOM nodes
        const commentsList = document.getElementById('commentsList');
        const searchInput = document.getElementById('searchInput');
        const sortSelect = document.getElementById('sortSelect');
        const filterBtns = document.querySelectorAll('.filter-btn');
        const pagePrev = document.getElementById('pagePrev');
        const pageNext = document.getElementById('pageNext');
        const pageInfo = document.getElementById('pageInfo');
        const totalItemsText = document.getElementById('totalItems');

        function init() {
            searchInput.addEventListener('input', (e) => {
                searchQuery = e.target.value.toLowerCase().trim();
                currentPage = 1;
                applyFiltersAndRender();
            });
            
            sortSelect.addEventListener('change', (e) => {
                sortBy = e.target.value;
                applyFiltersAndRender();
            });
            
            filterBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    filterBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    activeSentiment = btn.dataset.sentiment;
                    currentPage = 1;
                    applyFiltersAndRender();
                });
            });
            
            pagePrev.addEventListener('click', () => {
                if (currentPage > 1) {
                    currentPage--;
                    renderComments();
                }
            });
            
            pageNext.addEventListener('click', () => {
                const totalPages = Math.ceil(filteredComments.length / itemsPerPage);
                if (currentPage < totalPages) {
                    currentPage++;
                    renderComments();
                }
            });
            
            initCharts();
            applyFiltersAndRender();
        }

        function applyFiltersAndRender() {
            filteredComments = comments.filter(c => {
                const matchSentiment = activeSentiment === 'all' || 
                    (activeSentiment === 'bullish' && c.SentimentLabel === '看多/乐观') ||
                    (activeSentiment === 'bearish' && c.SentimentLabel === '看空/悲观') ||
                    (activeSentiment === 'neutral' && c.SentimentLabel === '中立/理性');
                    
                const matchTopic = !activeTopic || c.Topics.includes(activeTopic);
                
                const matchSearch = !searchQuery || 
                    c.Title.toLowerCase().includes(searchQuery) ||
                    c.Author.toLowerCase().includes(searchQuery);
                    
                return matchSentiment && matchTopic && matchSearch;
            });
            
            filteredComments.sort((a, b) => {
                if (sortBy === 'time') {
                    return b.index - a.index; 
                } else if (sortBy === 'reads') {
                    return b.ReadCount - a.ReadCount;
                } else if (sortBy === 'replies') {
                    return b.ReplyCount - a.ReplyCount;
                } else if (sortBy === 'sentiment') {
                    return b.SentimentScore - a.SentimentScore;
                }
                return 0;
            });
            
            totalItemsText.innerText = `(共 ${filteredComments.length} 条)`;
            renderComments();
        }

        function renderComments() {
            commentsList.innerHTML = '';
            
            if (filteredComments.length === 0) {
                commentsList.innerHTML = `
                    <div class="empty-state">
                        <svg class="empty-state-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <p>没有找到符合当前筛选条件的帖子</p>
                    </div>
                `;
                pagePrev.disabled = true;
                pageNext.disabled = true;
                pageInfo.innerText = '0 / 0';
                return;
            }
            
            const totalPages = Math.ceil(filteredComments.length / itemsPerPage);
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;
            
            const startIndex = (currentPage - 1) * itemsPerPage;
            const endIndex = Math.min(startIndex + itemsPerPage, filteredComments.length);
            const pageItems = filteredComments.slice(startIndex, endIndex);
            
            pageItems.forEach((c) => {
                const itemEl = document.createElement('div');
                itemEl.className = 'comment-item glass-card';
                
                let sentimentClass = 'neutral';
                if (c.SentimentLabel === '看多/乐观') sentimentClass = 'bullish';
                else if (c.SentimentLabel === '看空/悲观') sentimentClass = 'bearish';
                
                const topicsHtml = c.Topics.map(t => {
                    const isActive = activeTopic === t;
                    return `<span class="topic-tag ${isActive ? 'active' : ''}" onclick="toggleTopic(event, '${t}')">${t}</span>`;
                }).join('');
                
                const shortName = c.Author ? c.Author.substring(0, 1) : '?';
                
                itemEl.innerHTML = `
                    <div class="comment-meta">
                        <div class="comment-author">
                            <div class="avatar-placeholder">${shortName}</div>
                            <span>${c.Author}</span>
                        </div>
                        <div class="comment-time">${c.UpdateTime}</div>
                    </div>
                    <a class="comment-title" href="${c.Link}" target="_blank" rel="noopener noreferrer">${c.Title}</a>
                    <div class="comment-footer">
                        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center;">
                            <span class="sentiment-badge ${sentimentClass}">
                                ${c.SentimentLabel}
                            </span>
                            <div class="topics-group">
                                ${topicsHtml}
                            </div>
                        </div>
                        <div class="stats-group">
                            <div class="stat-item" title="阅读">
                                <svg class="stat-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                </svg>
                                <span>${formatNumber(c.ReadCount)}</span>
                            </div>
                            <div class="stat-item" title="回复">
                                <svg class="stat-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                                </svg>
                                <span>${formatNumber(c.ReplyCount)}</span>
                            </div>
                        </div>
                    </div>
                `;
                commentsList.appendChild(itemEl);
            });
            
            pageInfo.innerText = `${currentPage} / ${totalPages}`;
            pagePrev.disabled = currentPage === 1;
            pageNext.disabled = currentPage === totalPages;
        }

        function formatNumber(num) {
            if (num >= 10000) {
                return (num / 10000).toFixed(1) + '万';
            }
            return num;
        }

        function toggleTopic(e, topic) {
            e.stopPropagation();
            if (activeTopic === topic) {
                activeTopic = null;
            } else {
                activeTopic = topic;
            }
            currentPage = 1;
            applyFiltersAndRender();
        }

        function initCharts() {
            const ctxSentiment = document.getElementById('sentimentChart').getContext('2d');
            new Chart(ctxSentiment, {
                type: 'doughnut',
                data: {
                    labels: ['看多/乐观', '中立/理性', '看空/悲观'],
                    datasets: [{
                        data: [stats.bullish, stats.neutral, stats.bearish],
                        backgroundColor: ['#ef4444', '#64748b', '#10b981'],
                        borderWidth: 0,
                        hoverOffset: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: '#f3f4f6',
                                padding: 12,
                                font: {
                                    family: 'Inter',
                                    size: 11
                                }
                            }
                        }
                    },
                    cutout: '72%'
                }
            });

            const ctxTopic = document.getElementById('topicChart').getContext('2d');
            const sortedTopics = Object.entries(stats.topics)
                .sort((a, b) => b[1] - a[1])
                .filter(t => t[0] !== '其他讨论')
                .slice(0, 8);
            
            const labels = sortedTopics.map(t => t[0]);
            const counts = sortedTopics.map(t => t[1]);

            new Chart(ctxTopic, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: '讨论频次',
                        data: counts,
                        backgroundColor: 'rgba(99, 102, 241, 0.75)',
                        borderColor: '#6366f1',
                        borderWidth: 1.5,
                        borderRadius: 4
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.05)'
                            },
                            ticks: {
                                color: '#9ca3af',
                                stepSize: 1
                            }
                        },
                        y: {
                            grid: {
                                display: false
                            },
                            ticks: {
                                color: '#f3f4f6',
                                font: {
                                    family: 'Inter',
                                    size: 11
                                }
                            }
                        }
                    }
                }
            });
        }

        window.onload = init;
    </script>
</body>
</html>"""

    # 替换变量
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_content = html_template.replace("UPDATE_TIME_PLACEHOLDER", now_str)
    html_content = html_content.replace("TOTAL_COMMENTS_PLACEHOLDER", str(total_comments))
    html_content = html_content.replace("HEAT_INDEX_PLACEHOLDER", str(heat_index))
    html_content = html_content.replace("TOTAL_READS_PLACEHOLDER", format_large_number(total_reads))
    html_content = html_content.replace("TOTAL_REPLIES_PLACEHOLDER", format_large_number(total_replies))
    html_content = html_content.replace("BULLISH_PCT_PLACEHOLDER", str(bullish_pct))
    html_content = html_content.replace("BEARISH_PCT_PLACEHOLDER", str(bearish_pct))
    html_content = html_content.replace("BULLISH_COUNT_PLACEHOLDER", str(bullish_count))
    html_content = html_content.replace("BEARISH_COUNT_PLACEHOLDER", str(bearish_count))
    html_content = html_content.replace("RATING_COLOR_PLACEHOLDER", rating_color)
    html_content = html_content.replace("SENTIMENT_RATING_PLACEHOLDER", sentiment_rating)
    html_content = html_content.replace("AVG_SENTIMENT_PLACEHOLDER", str(avg_score))
    html_content = html_content.replace("COMMENTS_JSON_PLACEHOLDER", comments_json)
    html_content = html_content.replace("STATS_JSON_PLACEHOLDER", stats_json)
    
    with open(HTML_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"\n[成功] 已成功输出交互式可视化 HTML 页面: {HTML_OUTPUT_PATH}")

def main():
    print("=" * 60)
    print(" 长电科技股吧评论多页抓取及可视化面板生成器启动")
    print(f" 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 抓取 4 页数据 (约 320 条记录)
    pages_to_scrape = 4
    print(f"\n[Step 1] 开始抓取长电科技 (600584) 股吧，目标页数: {pages_to_scrape} 页...")
    comments = fetch_jcet_comments(pages_to_scrape)
    
    if not comments:
        print("[错误] 未能成功爬取到长电科技评论，请确认网络或稍后重试。")
        return
        
    print(f"\n[Step 2] 抓取完成，共获得 {len(comments)} 条有效帖子数据。")
    
    # 保存原始明细至 CSV
    print(f"\n[Step 3] 保存原始数据至 CSV 文件: {CSV_OUTPUT_PATH} ...")
    # 为了方便后续导出，展开Topics列表为逗号分隔字符串
    df_save = pd.DataFrame(comments).copy()
    df_save['Topics'] = df_save['Topics'].apply(lambda x: ",".join(x))
    df_save.to_csv(CSV_OUTPUT_PATH, index=False, encoding='utf-8-sig')
    print("  CSV 数据导出完毕。")
    
    # 组装并生成 HTML 可视化面板
    print("\n[Step 4] 计算情感与话题统计，并编译生成精美可视化 HTML...")
    generate_interactive_html(comments)
    
    print("\n" + "=" * 60)
    print(" ✅ 舆情抓取与可视化分析处理已完美结束！")
    print(f"  - 原始明细 CSV 路径: {CSV_OUTPUT_PATH}")
    print(f"  - 可视化 HTML 路径: {HTML_OUTPUT_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    main()
