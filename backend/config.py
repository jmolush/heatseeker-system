"""Heatseeker Trading System — Configuration"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ─── Capture Storage ──────────────────────────────────────
    CAPTURE_BASE_PATH = Path(os.getenv('CAPTURE_BASE_PATH', './captures'))

    # ─── Moomoo OpenD ─────────────────────────────────────────
    OPEND_HOST = os.getenv('OPEND_HOST', '127.0.0.1')
    OPEND_PORT = int(os.getenv('OPEND_PORT', '11111'))
    OPEND_SECURITY_FIRM = os.getenv('OPEND_SECURITY_FIRM', 'FUTUINC')

    # ─── Anthropic ────────────────────────────────────────────
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

    # ─── Server ───────────────────────────────────────────────
    BACKEND_HOST = os.getenv('BACKEND_HOST', '0.0.0.0')
    BACKEND_PORT = int(os.getenv('BACKEND_PORT', '5555'))

    # ─── Trading ──────────────────────────────────────────────
    PAPER_TRADING_ENABLED = os.getenv('PAPER_TRADING_ENABLED', 'true').lower() == 'true'
    LIVE_TRADING_ENABLED = os.getenv('LIVE_TRADING_ENABLED', 'false').lower() == 'true'

    # ─── Tickers ──────────────────────────────────────────────
    # OpenD tickers (equities/options — NOT indices)
    OPEND_TICKERS = ['US.SPY', 'US.QQQ']

    # yfinance tickers (indices — OpenD can't do these)
    INDEX_TICKERS = {
        'VIX': '^VIX',
        'SPX': '^GSPC',
    }

    # ─── Trading Window ───────────────────────────────────────
    # Market hours ET — we focus 9:30 AM to 3:30 PM (no new positions after 3 PM moomoo rule)
    MARKET_OPEN_ET = '09:30'
    MARKET_CLOSE_ET = '15:30'  # Last new position time (moomoo restriction)
    MARKET_HARD_CLOSE_ET = '16:00'

    # ─── Discord ──────────────────────────────────────────────
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')
