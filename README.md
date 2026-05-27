# Guba-Sentiment-Quant

A quantitative trading and sentiment analysis tool for Chinese A-share stocks. This project fetches and analyzes Eastmoney Guba (股吧) comments to perform sentiment analysis and backtests pullback trading strategies combined with stock trend metrics.

## Features

- **Top 100 Stock Discovery**: Discovers active stocks based on market parameters.
- **Eastmoney Guba Sentiment Analysis**: Crawls and processes comments for target stocks, using NLP/sentiment analysis to measure retail investor sentiment.
- **Pullback Strategy Backtesting**: Backtests trading strategies based on stock pullbacks and sentiment triggers.
- **Interactive Dashboard**: Visualizes analysis results, strategy performance, and sentiment indicators.

## Project Structure

- `comments/`: Analyzers and reports for comments.
  - `hot_comments_analyzer.py`: Analyzes comments and computes sentiment scores.
  - `changdian_analyzer.py`: Dedicated analysis script.
- `get_recent_top100.py`: Identifies top active stocks.
- `stock_trend_analyzer.py`: Analyzes stock price trends and technical indicators.
- `backtest_pullback_strategy.py`: Implements pullback strategy simulation.
- `pullback_analysis.py`: Technical analysis script for stock pullback patterns.
- `dashboard.py`: Visual representation of trends, sentiment, and strategy backtest results.
