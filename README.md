# Guba-Sentiment-Quant | 股吧舆情与量化选股系统

本项目是一款针对中国A股市场的量化选股与零售情绪分析工具。通过抓取东方财富网股吧热帖进行情感分析，结合近期大盘量能、主力资金流向、个股利空消息及板块共振等多维度因子，对高活跃股票进行量化评分、走势研判和策略回测，并提供交互式可视化仪表盘。

---

## 核心功能

1. **高活跃股票筛选** (`get_recent_top100.py`)
   - 筛选出近10个交易日中每日成交额/量前100名的股票作为高活跃候选池，自动分类所属行业板块。
2. **股吧舆情分析** (`comments/hot_comments_analyzer.py`)
   - 抓取人气榜前10名热门个股的最新股吧讨论帖子，分析零售投资者看多/看空情绪占比，提取热门讨论话题，预测散户情绪走向。
3. **多因子量化评分** (`pullback_analysis.py`)
   - 基于历史快照序列，识别“回调后反弹”（跌→涨）和“趋势连续上涨”模式。
   - 融合板块资金动量、大盘流动性、个股利空风控和日内新晋抢筹等指标计算综合评分。
4. **历史策略回测** (`backtest_pullback_strategy.py`)
   - 使用历史活跃股数据进行模拟回测，验证不同因子和评分分层在次日的实际胜率与收益表现。
5. **可视化仪表盘** (`dashboard.py`)
   - 启动本地 Web 服务，自动在浏览器中展示黑金主题的交互式界面，直观展现每日推荐日志与评分明细。

---

## 目录结构

```text
├── 100/                          # 存放每日 Top100 活跃股票的 CSV 数据
├── comments/                     # 舆情分析组件
│   ├── hot_comments_analyzer.py  # 股吧评论抓取与情感分析器
│   └── changdian_analyzer.py     # 个股（如长电科技）专项分析器
├── get_recent_top100.py          # 活跃股票池抓取脚本
├── pullback_analysis.py          # 量化多因子选股分析主程序
├── backtest_pullback_strategy.py # 策略历史回测工具
├── dashboard.py                  # 可视化仪表盘服务
└── README.md                     # 项目说明文档
```

---

## 使用方法

### 1. 环境准备
确保已安装 Python 3.8+ 并安装项目所需的依赖库：
```bash
pip install pandas numpy akshare requests beautifulsoup4 lxml tabulate
```

### 2. 快速运行流程

#### **步骤 1：获取近10日活跃股票数据**
运行脚本构建股票候选池，数据将被保存至 `100/` 目录：
```bash
python get_recent_top100.py
```

#### **步骤 2：抓取热门股舆情（可选）**
对最新的人气股票进行股吧热帖抓取和情感倾向分析，并生成舆情报告：
```bash
python comments/hot_comments_analyzer.py
```

#### **步骤 3：执行量化选股与走势分析**
运行核心选股主程序，计算个股评分，并自动对上一次的推荐股进行当日实际表现验证：
```bash
python pullback_analysis.py
```

#### **步骤 4：运行策略历史回测（可选）**
对构建的量化评分体系进行历史效果验证：
```bash
python backtest_pullback_strategy.py
```

#### **步骤 5：启动可视化仪表盘**
运行本地服务以交互式查看分析结果：
```bash
python dashboard.py
```
启动后在浏览器中自动或手动访问 `http://localhost:8050` 即可查看。
