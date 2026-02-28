# Heatseeker Trading System

Automated options trading pipeline using Skylit Heatseeker dealer positioning data.

## Architecture

```
Chrome Extension (capture) → Backend (analysis + data) → Paper Trading (moomoo OpenD)
```

## Components

### `/chrome-extension`
Chrome extension for capturing Heatseeker Trinity Mode screenshots.
- Dynamic window-size capture
- Configurable capture interval
- Date-based subfolder organization
- Saves to local filesystem via configurable path

### `/backend`
Python backend for data pipeline, analysis, and trading.
- Market data via moomoo OpenD (SPY, QQQ options)
- VIX/SPX index data via yfinance
- Claude API integration for heatmap analysis
- Paper trading execution and P&L tracking

### `/docs`
Project documentation and research.

## Setup

See individual component READMEs for setup instructions.

## Status

🚧 Phase 2 — Data Pipeline Development
