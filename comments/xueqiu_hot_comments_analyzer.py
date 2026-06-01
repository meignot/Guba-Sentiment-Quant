# -*- coding: utf-8 -*-
"""
雪球人气股票评论抓取与情感分析器
数据源: 雪球 (xueqiu.com) 人气关注榜 + 个股讨论区
功能: 抓取雪球人气榜 Top N 股票的最新评论，进行看多/看空/中立情感分析并生成报告
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
from datetime import datetime
from collections import Counter

# Windows GBK终端兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_OUTPUT_PATH = os.path.join(BASE_DIR, "xueqiu_hot_comments.csv")
REPORT_OUTPUT_PATH = os.path.join(BASE_DIR, "xueqiu_hot_sentiment_report.md")

# 抓取配置
TOP_N_STOCKS = 10             # 抓取前N只人气股票
COMMENTS_PER_STOCK = 30       # 每只股票抓取的评论数
COMMENTS_PER_PAGE = 10        # 每页评论数 (雪球默认)
MARKET_TYPE = 12              # 10=全球, 11=美股, 12=A股(沪深), 13=港股

# 情感分析关键词字典
BULLISH_KEYWORDS = [
    "涨", "牛", "买", "好", "多", "突破", "强势", "主力流入", "加仓",
    "主升浪", "抄底", "封板", "看多", "龙头", "起飞", "吸筹", "上攻",
    "大牛", "稳了", "补仓", "满仓", "吃肉", "看好", "暴涨", "拉升",
    "低估", "便宜", "长期持有", "价值", "优秀", "护城河", "安全边际",
    "分红", "回购", "增长", "利好", "机会", "翻倍", "新高", "放量"
]

BEARISH_KEYWORDS = [
    "跌", "熊", "卖", "垃圾", "割肉", "空", "出货", "跑路", "清仓",
    "退潮", "跌停", "见顶", "亏损", "诱多", "做空", "砸盘", "破位",
    "离场", "凉了", "减仓", "套牢", "崩盘", "暴跌", "看空", "骗局",
    "高估", "泡沫", "风险", "利空", "危险", "贵了", "缩量", "新低"
]


def analyze_sentiment(text):
    """基于情感词典对文本进行情感打分和分类"""
    if not text:
        return 0, "中立/理性"
    score = 0
    bullish_matched = []
    bearish_matched = []
    for kw in BULLISH_KEYWORDS:
        if kw in text:
            score += 1
            bullish_matched.append(kw)
    for kw in BEARISH_KEYWORDS:
        if kw in text:
            score -= 1
            bearish_matched.append(kw)

    if score > 0:
        label = "看多/乐观"
    elif score < 0:
        label = "看空/悲观"
    else:
        label = "中立/理性"
    return score, label, bullish_matched, bearish_matched


def clean_html(html_text):
    """清理HTML标签，提取纯文本"""
    if not html_text:
        return ""
    text = re.sub(r'<[^>]+>', '', str(html_text))
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    return text


def create_session():
    """创建带有有效cookie的requests会话"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://xueqiu.com/',
    })

    print("  正在获取雪球Session Cookie...")
    try:
        resp = session.get('https://xueqiu.com/', timeout=15)
        if resp.status_code == 200:
            cookies = session.cookies.get_dict()
            token_keys = [k for k in cookies.keys() if 'xq' in k.lower() or 'token' in k.lower()]
            print(f"    获取到 {len(cookies)} 个Cookie, 关键Token: {token_keys}")
            return session
        else:
            print(f"    [警告] 主页访问返回状态码: {resp.status_code}")
            return session
    except Exception as e:
        print(f"    [错误] 获取Cookie失败: {e}")
        return session


def fetch_hot_stocks(session):
    """
    获取雪球人气关注榜 Top N 股票
    API: https://stock.xueqiu.com/v5/stock/hot_stock/list.json
    type: 10=全球, 11=美股, 12=A股(沪深), 13=港股
    """
    url = "https://stock.xueqiu.com/v5/stock/hot_stock/list.json"
    params = {
        'size': TOP_N_STOCKS,
        '_type': 'follow',
        'type': MARKET_TYPE,
    }

    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"    [错误] 人气榜API返回: {resp.status_code}")
            return []

        data = resp.json()
        items = data.get('data', {}).get('items', [])

        hot_stocks = []
        for rank, item in enumerate(items, 1):
            hot_stocks.append({
                'Rank': rank,
                'Symbol': item.get('symbol', ''),
                'Name': item.get('name', ''),
                'Price': item.get('current', 0),
                'ChangePct': item.get('percent', 0),
                'Exchange': item.get('exchange', ''),
            })
        return hot_stocks

    except Exception as e:
        print(f"    [错误] 获取人气榜失败: {e}")
        return []


def fetch_stock_comments(session, symbol, stock_name, pages=3):
    """
    获取指定股票的雪球讨论区评论
    API: https://xueqiu.com/query/v1/symbol/search/status.json
    """
    all_comments = []

    for page in range(1, pages + 1):
        url = "https://xueqiu.com/query/v1/symbol/search/status.json"
        params = {
            'symbol': symbol,
            'count': COMMENTS_PER_PAGE,
            'comment': 0,
            'page': page,
            'source': 'all',
        }

        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"      第{page}页获取失败 (状态码: {resp.status_code})")
                break

            data = resp.json()
            items = data.get('list', [])
            if not items:
                break

            for item in items:
                text = clean_html(item.get('text', ''))
                title = clean_html(item.get('title', ''))
                full_text = f"{title} {text}" if title else text

                user = item.get('user', {}) or {}
                created_at = item.get('created_at', 0)

                # 时间转换
                if created_at:
                    try:
                        dt = datetime.fromtimestamp(created_at / 1000)
                        time_str = dt.strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        time_str = "未知"
                else:
                    time_str = "未知"

                # 情感分析
                score, label, bull_kws, bear_kws = analyze_sentiment(full_text)

                # 帖子链接
                post_id = item.get('id', '')
                user_id = item.get('user_id', user.get('id', ''))
                post_url = f"https://xueqiu.com/{user_id}/{post_id}" if user_id and post_id else ""

                all_comments.append({
                    'Symbol': symbol,
                    'StockName': stock_name,
                    'Title': (title if title else text[:80]).replace('\n', ' '),
                    'Content': text[:300],
                    'Link': post_url,
                    'Author': user.get('screen_name', '未知'),
                    'AuthorFollowers': user.get('followers_count', 0),
                    'PublishTime': time_str,
                    'ReplyCount': item.get('reply_count', 0),
                    'RetweetCount': item.get('retweet_count', 0),
                    'LikeCount': item.get('like_count', 0),
                    'SentimentScore': score,
                    'SentimentLabel': label,
                    'BullishKeywords': ', '.join(bull_kws[:4]),
                    'BearishKeywords': ', '.join(bear_kws[:4]),
                })

            if len(items) < COMMENTS_PER_PAGE:
                break

        except Exception as e:
            print(f"      第{page}页获取异常: {e}")
            break

        # 翻页间隔
        if page < pages:
            time.sleep(random.uniform(0.5, 1.5))

    return all_comments


def calculate_heat(total_replies, total_retweets, total_likes):
    """根据互动量计算热度指数 (0-100)"""
    if total_replies == 0 and total_retweets == 0 and total_likes == 0:
        return 0.0
    log_replies = math.log1p(total_replies)
    log_retweets = math.log1p(total_retweets)
    log_likes = math.log1p(total_likes)
    # 回复40%、转发30%、点赞30%
    replies_score = min(1.0, log_replies / 7.0) * 40.0
    retweets_score = min(1.0, log_retweets / 6.0) * 30.0
    likes_score = min(1.0, log_likes / 8.0) * 30.0
    return round(replies_score + retweets_score + likes_score, 1)


def _fmt_title(title, max_len=45):
    t = title.replace('|', '丨').replace('\n', ' ')
    return t[:max_len-1] + '...' if len(t) > max_len else t


def generate_report(stock_summaries, all_comments):
    """生成Markdown分析报告"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_bullish = sum(s['BullishCount'] for s in stock_summaries)
    total_bearish = sum(s['BearishCount'] for s in stock_summaries)
    total_neutral = sum(s['NeutralCount'] for s in stock_summaries)
    total_comments = total_bullish + total_bearish + total_neutral

    bullish_pct = round(total_bullish / total_comments * 100, 1) if total_comments > 0 else 0
    bearish_pct = round(total_bearish / total_comments * 100, 1) if total_comments > 0 else 0
    neutral_pct = round(total_neutral / total_comments * 100, 1) if total_comments > 0 else 0

    market_type_name = {10: '全球', 11: '美股', 12: 'A股(沪深)', 13: '港股'}.get(MARKET_TYPE, '未知')

    # 市场情绪判定
    if bullish_pct > bearish_pct + 10:
        market_sentiment = "乐观/多头情绪占优"
    elif bearish_pct > bullish_pct + 10:
        market_sentiment = "悲观/看空情绪占优"
    elif bullish_pct > 40:
        market_sentiment = "高度活跃/分歧较大"
    else:
        market_sentiment = "中立偏乐观"

    md = []
    md.append("# 雪球人气股票社区评论情感分析报告")
    md.append(f"\n> **报告生成时间**: {now_str}")
    md.append(f"> **数据源**: 雪球 (xueqiu.com) 人气关注榜 ({market_type_name})")
    md.append(f"> **分析样本**: 前 {TOP_N_STOCKS} 名人气股票的最新讨论 (共 {len(all_comments)} 条评论)")
    md.append(f"> **看多评论**: {total_bullish} 条 ({bullish_pct}%) | **看空评论**: {total_bearish} 条 ({bearish_pct}%) | **中立评论**: {total_neutral} 条 ({neutral_pct}%)")

    # 一、市场整体舆情
    md.append("\n## 一、 雪球社区整体舆情大盘")
    md.append("\n> [!NOTE]")
    md.append(f"> 以下是雪球 {market_type_name} 人气榜前 {TOP_N_STOCKS} 只股票在社区中呈现的情感分布：")

    bar_len = 30
    bullish_bar = "🔴" * int(round(bullish_pct / 100 * bar_len))
    neutral_bar = "⚪" * int(round(neutral_pct / 100 * bar_len))
    bearish_bar = "🟢" * int(round(bearish_pct / 100 * bar_len))

    md.append(f"\n- **看多比例 (Bullish)**: {bullish_pct}% ({total_bullish}条)")
    md.append(f"- **看空比例 (Bearish)**: {bearish_pct}% ({total_bearish}条)")
    md.append(f"- **中立比例 (Neutral)**: {neutral_pct}% ({total_neutral}条)")
    md.append(f"- **情绪能量条**: {bullish_bar}{neutral_bar}{bearish_bar}")
    md.append(f"- **市场核心情绪判定**: **{market_sentiment}**")

    # 二、热门话题
    md.append("\n## 二、 雪球讨论最热话题")
    md.append("\n> [!TIP]")
    md.append("> 通过关键词匹配提取散户讨论频次最高的话题：")

    TOPIC_KEYWORDS = {
        '华为': '华为/鸿蒙', '鸿蒙': '华为/鸿蒙',
        '半导体': '半导体板块', '芯片': '半导体板块', '封测': '半导体板块',
        'AI': 'AI/人工智能', '人工智能': 'AI/人工智能', '算力': 'AI/人工智能', '大模型': 'AI/人工智能',
        '涨停': '涨停板', '封板': '涨停板', '打板': '涨停板',
        '减持': '股东减持', '解禁': '股东减持',
        '主力': '主力资金动向', '北向': '主力资金动向', '游资': '主力资金动向', '机构': '主力资金动向',
        '大跌': '暴跌恐慌', '暴跌': '暴跌恐慌', '杀跌': '暴跌恐慌', '跳水': '暴跌恐慌',
        '抄底': '抄底/逢低布局', '低吸': '抄底/逢低布局', '补仓': '抄底/逢低布局',
        '见顶': '见顶/出货信号', '出货': '见顶/出货信号', '套牢': '见顶/出货信号',
        '龙头': '龙头股讨论', '妖股': '龙头股讨论',
        '业绩': '基本面/业绩', '财报': '基本面/业绩', '利润': '基本面/业绩',
        '利好': '利好消息', '政策': '利好消息',
        '利空': '利空消息',
        '茅台': '贵州茅台/白酒', '白酒': '贵州茅台/白酒',
        '新能源': '新能源', '光伏': '新能源', '锂电': '新能源',
        '消费': '消费板块', '旅游': '消费板块', '免税': '消费板块',
        '银行': '银行/金融', '券商': '银行/金融',
    }
    topic_counter = Counter()
    topic_examples = {}
    for c in all_comments:
        full_text = f"{c['Title']} {c['Content']}"
        matched_topics = set()
        for kw, topic in TOPIC_KEYWORDS.items():
            if kw in full_text:
                matched_topics.add(topic)
        for topic in matched_topics:
            topic_counter[topic] += 1
            if topic not in topic_examples or c['ReplyCount'] > topic_examples[topic]['ReplyCount']:
                topic_examples[topic] = c

    top_topics = topic_counter.most_common(15)
    if top_topics:
        md.append("\n| 排名 | 热门话题 | 讨论次数 | 最热帖子 (点击跳转) | 回复 | 转发 |")
        md.append("| :---: | :--- | :---: | :--- | :---: | :---: |")
        for rank, (topic, count) in enumerate(top_topics, 1):
            ex = topic_examples.get(topic)
            if ex:
                ex_title = _fmt_title(ex['Title'], 35)
                md.append(f"| {rank} | **{topic}** | {count} | [{ex_title}]({ex['Link']}) | {ex['ReplyCount']} | {ex['RetweetCount']} |")

    # 三、人气股票排行榜
    md.append("\n## 三、 人气股票情绪排行榜")
    md.append("\n| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | 热度 | 评论数 | 乐观 | 悲观 | 中立 | 核心态度 |")
    md.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for s in stock_summaries:
        md.append(f"| {s['Rank']} | {s['Symbol']} | {s['Name']} | {s['Price']} | {s['ChangePct']}% | **{s['HeatIndex']}** | {s['TotalComments']} | {s['BullishPct']}% | {s['BearishPct']}% | {s['NeutralPct']}% | **{s['OverallSentiment']}** |")

    # 四、看多评论 TOP 20
    md.append("\n## 四、 看多 (Bullish) 评论 TOP 20")
    md.append("\n> [!IMPORTANT]")
    md.append("> 以下是所有人气股票中**情绪最看涨**的评论汇总，按回复量排序：")

    bullish_comments = sorted(
        [c for c in all_comments if c['SentimentLabel'] == '看多/乐观'],
        key=lambda x: x['ReplyCount'], reverse=True
    )

    md.append("\n| 序号 | 股票 | 评论内容 (点击跳转) | 作者 | 发布时间 | 回复 | 转发 | 看多关键词 |")
    md.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
    for idx, c in enumerate(bullish_comments[:20]):
        title = _fmt_title(c['Title'], 40)
        kw_str = c['BullishKeywords'][:20] if c['BullishKeywords'] else '-'
        md.append(f"| {idx+1} | {c['StockName']} | [{title}]({c['Link']}) | {c['Author']} | {c['PublishTime']} | {c['ReplyCount']} | {c['RetweetCount']} | {kw_str} |")

    # 五、看空评论 TOP 20
    md.append("\n## 五、 看空 (Bearish) 评论 TOP 20")
    md.append("\n> [!WARNING]")
    md.append("> 以下是所有人气股票中**情绪最看空**的评论汇总，按回复量排序：")

    bearish_comments = sorted(
        [c for c in all_comments if c['SentimentLabel'] == '看空/悲观'],
        key=lambda x: x['ReplyCount'], reverse=True
    )

    md.append("\n| 序号 | 股票 | 评论内容 (点击跳转) | 作者 | 发布时间 | 回复 | 转发 | 看空关键词 |")
    md.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
    for idx, c in enumerate(bearish_comments[:20]):
        title = _fmt_title(c['Title'], 40)
        kw_str = c['BearishKeywords'][:20] if c['BearishKeywords'] else '-'
        md.append(f"| {idx+1} | {c['StockName']} | [{title}]({c['Link']}) | {c['Author']} | {c['PublishTime']} | {c['ReplyCount']} | {c['RetweetCount']} | {kw_str} |")

    # 六、个股深度分析
    md.append("\n## 六、 个股舆情深度穿透与走势研判")

    for s in stock_summaries:
        symbol = s['Symbol']
        name = s['Name']

        md.append("\n---")
        md.append(f"\n### {name} ({symbol}) - 人气榜第 {s['Rank']}")
        md.append(f"\n- **基本指标**: 最新价 `{s['Price']}` | 今日涨跌 `{s['ChangePct']}%` | 社区热度 `{s['HeatIndex']}/100`")
        md.append(f"- **舆情倾向**: 乐观 `{s['BullishPct']}%` | 悲观 `{s['BearishPct']}%` | 中立 `{s['NeutralPct']}%` | 核心态度: **{s['OverallSentiment']}**")

        stock_comments = [c for c in all_comments if c['Symbol'] == symbol]
        stock_sorted = sorted(stock_comments, key=lambda x: x['ReplyCount'], reverse=True)
        stock_bullish = sorted([c for c in stock_comments if c['SentimentLabel'] == '看多/乐观'], key=lambda x: x['ReplyCount'], reverse=True)
        stock_bearish = sorted([c for c in stock_comments if c['SentimentLabel'] == '看空/悲观'], key=lambda x: x['ReplyCount'], reverse=True)

        md.append("\n#### 讨论最热评论 (Top 5)")
        md.append("| 序号 | 评论内容 (点击跳转) | 作者 | 粉丝数 | 回复 | 转发 | 点赞 | 情感 |")
        md.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for idx, c in enumerate(stock_sorted[:5]):
            title = _fmt_title(c['Title'], 38)
            md.append(f"| {idx+1} | [{title}]({c['Link']}) | {c['Author']} | {c['AuthorFollowers']} | {c['ReplyCount']} | {c['RetweetCount']} | {c['LikeCount']} | {c['SentimentLabel']} |")

        if stock_bullish:
            md.append("\n#### 看多评论 (Top 3)")
            md.append("| 序号 | 评论内容 | 回复 | 看多关键词 |")
            md.append("| :---: | :--- | :---: | :--- |")
            for idx, c in enumerate(stock_bullish[:3]):
                title = _fmt_title(c['Title'], 40)
                md.append(f"| {idx+1} | [{title}]({c['Link']}) | {c['ReplyCount']} | {c['BullishKeywords']} |")

        if stock_bearish:
            md.append("\n#### 看空评论 (Top 3)")
            md.append("| 序号 | 评论内容 | 回复 | 看空关键词 |")
            md.append("| :---: | :--- | :---: | :--- |")
            for idx, c in enumerate(stock_bearish[:3]):
                title = _fmt_title(c['Title'], 40)
                md.append(f"| {idx+1} | [{title}]({c['Link']}) | {c['ReplyCount']} | {c['BearishKeywords']} |")

        # 走势研判
        md.append("\n#### 散户情绪分析与走势预测")
        bp = s['BullishPct']
        bep = s['BearishPct']
        hi = s['HeatIndex']
        chg = s['ChangePct']

        if hi > 80 and bp > 40 and chg > 5:
            prediction = (
                f"**散户情绪判定**: 极度狂热追涨，乐观占比 {bp}%。\n"
                "**未来走势研判**: 散户看多情绪高度一致且股价大涨放量。历史规律表明，散户一致看多+放天量往往意味着**短期冲顶风险**加剧。"
                "主力可能借利好出货，建议逢高分批止盈，不宜盲目追涨。"
            )
        elif hi > 70 and bp > bep + 10 and bp <= 40:
            prediction = (
                f"**散户情绪判定**: 乐观情绪主导，看涨 {bp}% vs 看跌 {bep}%。\n"
                "**未来走势研判**: 散户整体偏乐观但尚未极度狂热，说明市场信心较强。"
                "短期内有望**延续上升趋势**，但需关注量能配合。若放量滞涨则需警惕。"
            )
        elif hi > 60 and bep > 35:
            prediction = (
                f"**散户情绪判定**: 恐慌抛售，看跌占比 {bep}%。\n"
                "**未来走势研判**: 社区中充斥着割肉和看空言论，洗盘较为彻底。"
                "若股价已连续下跌，这通常是**阶段性底部信号**，可关注企稳后的超跌反弹机会。"
            )
        elif abs(bp - bep) < 10 and hi > 60:
            prediction = (
                f"**散户情绪判定**: 多空激烈对峙，看涨 {bp}% vs 看跌 {bep}%。\n"
                "**未来走势研判**: 散户意见严重分裂，主力资金正在剧烈博弈。"
                "股价通常会**大幅震荡**，方向选择在即。建议等待放量突破或跌破关键位后再做方向性操作。"
            )
        elif bp > 25 and bp > bep:
            prediction = (
                f"**散户情绪判定**: 温和乐观，看涨 {bp}% > 看跌 {bep}%。\n"
                "**未来走势研判**: 散户关注度适中、情绪偏暖。这种'未完全狂热'状态往往最有利于**震荡上行**，"
                "主力可能正在悄悄拉升。短期趋势看好。"
            )
        else:
            prediction = (
                f"**散户情绪判定**: 态度中立观望，看涨 {bp}% / 看跌 {bep}%。\n"
                "**未来走势研判**: 市场关注度一般，股价可能受大盘或板块联动影响。"
                "短期内倾向于**横盘整理**，建议配合技术面进行高抛低吸。"
            )

        md.append(prediction)

    # 免责声明
    md.append("\n---")
    md.append("\n## 七、 免责声明")
    md.append("\n> [!CAUTION]")
    md.append("> 本报告基于雪球社区公开评论数据进行的情感词匹配分析与情绪热度计算，代表散户心理与舆情热度，并不构成任何投资决策建议。股市有风险，投资需谨慎。")

    with open(REPORT_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    print(f"\n[成功] 已生成 Markdown 分析报告: {REPORT_OUTPUT_PATH}")


def main():
    market_type_name = {10: '全球', 11: '美股', 12: 'A股(沪深)', 13: '港股'}.get(MARKET_TYPE, '未知')

    print("=" * 60)
    print(f" 雪球人气股票评论抓取与情感分析器")
    print(f" 市场: {market_type_name} | 抓取Top {TOP_N_STOCKS} 只人气股票")
    print(f" 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Step 1: 初始化Session
    print("\n[Step 1] 初始化网络会话...")
    session = create_session()

    # Step 2: 获取人气榜
    print(f"\n[Step 2] 获取雪球{market_type_name}人气关注榜 Top {TOP_N_STOCKS}...")
    hot_stocks = fetch_hot_stocks(session)

    if not hot_stocks:
        print("[!] 人气榜获取失败，程序退出。")
        return

    print(f"  成功获取 {len(hot_stocks)} 只人气股票:")
    for h in hot_stocks:
        print(f"    第 {h['Rank']} 名: {h['Name']} ({h['Symbol']}) | 价格: {h['Price']} | 涨跌幅: {h['ChangePct']}%")

    # Step 3: 抓取每只股票的评论
    pages_per_stock = max(1, COMMENTS_PER_STOCK // COMMENTS_PER_PAGE)
    print(f"\n[Step 3] 依次抓取人气股票的雪球讨论区评论 (每只约{COMMENTS_PER_STOCK}条)...")

    all_comments = []
    stock_summaries = []

    for h in hot_stocks:
        print(f"\n  正在抓取 [{h['Name']}({h['Symbol']})] 的讨论区评论...")
        comments = fetch_stock_comments(session, h['Symbol'], h['Name'], pages=pages_per_stock)

        if comments:
            all_comments.extend(comments)
            print(f"    成功获取 {len(comments)} 条评论。")

            # 统计
            bullish_cnt = sum(1 for c in comments if c['SentimentLabel'] == "看多/乐观")
            bearish_cnt = sum(1 for c in comments if c['SentimentLabel'] == "看空/悲观")
            neutral_cnt = sum(1 for c in comments if c['SentimentLabel'] == "中立/理性")
            total_cnt = len(comments)

            bullish_pct = round(bullish_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0
            bearish_pct = round(bearish_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0
            neutral_pct = round(neutral_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0

            if bullish_pct > bearish_pct + 8:
                overall_sentiment = "乐观占优"
            elif bearish_pct > bullish_pct + 8:
                overall_sentiment = "悲观占优"
            else:
                overall_sentiment = "多空对峙/中立"

            total_replies = sum(c['ReplyCount'] for c in comments)
            total_retweets = sum(c['RetweetCount'] for c in comments)
            total_likes = sum(c['LikeCount'] for c in comments)
            heat_index = calculate_heat(total_replies, total_retweets, total_likes)

            stock_summaries.append({
                'Rank': h['Rank'],
                'Symbol': h['Symbol'],
                'Name': h['Name'],
                'Price': h['Price'],
                'ChangePct': h['ChangePct'],
                'HeatIndex': heat_index,
                'TotalComments': total_cnt,
                'TotalReplies': total_replies,
                'TotalRetweets': total_retweets,
                'BullishCount': bullish_cnt,
                'BearishCount': bearish_cnt,
                'NeutralCount': neutral_cnt,
                'BullishPct': bullish_pct,
                'BearishPct': bearish_pct,
                'NeutralPct': neutral_pct,
                'OverallSentiment': overall_sentiment,
            })
        else:
            print(f"    [警告] 未获取到评论数据。")
            stock_summaries.append({
                'Rank': h['Rank'], 'Symbol': h['Symbol'], 'Name': h['Name'],
                'Price': h['Price'], 'ChangePct': h['ChangePct'],
                'HeatIndex': 0, 'TotalComments': 0, 'TotalReplies': 0, 'TotalRetweets': 0,
                'BullishCount': 0, 'BearishCount': 0, 'NeutralCount': 0,
                'BullishPct': 0, 'BearishPct': 0, 'NeutralPct': 0,
                'OverallSentiment': '数据获取失败',
            })

        # 随机延迟
        sleep_time = random.uniform(1.5, 3.0)
        print(f"    [休眠] 随机等待 {sleep_time:.2f} 秒...")
        time.sleep(sleep_time)

    # Step 4: 保存CSV
    print(f"\n[Step 4] 保存评论明细数据到 CSV 文件...")
    if all_comments:
        df = pd.DataFrame(all_comments)
        df.to_csv(CSV_OUTPUT_PATH, index=False, encoding='utf-8-sig')
        print(f"  已生成 CSV 数据: {CSV_OUTPUT_PATH} (包含 {len(df)} 行记录)")

    # Step 5: 生成报告
    print("\n[Step 5] 汇总分析并生成 Markdown 分析报告...")
    if stock_summaries:
        generate_report(stock_summaries, all_comments)

    print("\n" + "=" * 60)
    print(" ✅ 雪球人气股票评论抓取与情感分析任务完成！")
    print(f"  - 评论明细数据: {CSV_OUTPUT_PATH}")
    print(f"  - 分析报告文档: {REPORT_OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
