"""
Heatseeker Trading System — Market Data Module

Handles:
- OpenD connection for SPY/QQQ quotes and option chains
- yfinance for VIX/SPX index data (OpenD doesn't support US indices)
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf

from config import Config


# ─── VIX / SPX via yfinance ──────────────────────────────────────

class IndexDataProvider:
    """Fetches VIX and SPX data via yfinance (free, no API key needed)."""

    def __init__(self):
        self._cache = {}
        self._cache_ttl = 60  # seconds

    def get_vix(self) -> Optional[dict]:
        """Get current VIX data."""
        return self._get_index('VIX')

    def get_spx(self) -> Optional[dict]:
        """Get current SPX data."""
        return self._get_index('SPX')

    def _get_index(self, name: str) -> Optional[dict]:
        """Fetch index data with caching."""
        ticker_symbol = Config.INDEX_TICKERS.get(name)
        if not ticker_symbol:
            return None

        # Check cache
        cached = self._cache.get(name)
        if cached and (time.time() - cached['fetched_at']) < self._cache_ttl:
            return cached['data']

        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.fast_info

            data = {
                'symbol': name,
                'price': float(info.last_price) if hasattr(info, 'last_price') else None,
                'previous_close': float(info.previous_close) if hasattr(info, 'previous_close') else None,
                'open': float(info.open) if hasattr(info, 'open') else None,
                'day_high': float(info.day_high) if hasattr(info, 'day_high') else None,
                'day_low': float(info.day_low) if hasattr(info, 'day_low') else None,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

            # Calculate change
            if data['price'] and data['previous_close']:
                data['change'] = data['price'] - data['previous_close']
                data['change_pct'] = (data['change'] / data['previous_close']) * 100

            self._cache[name] = {'data': data, 'fetched_at': time.time()}
            return data

        except Exception as e:
            print(f'[MarketData] Error fetching {name}: {e}')
            return None

    def get_vix_intraday(self, period: str = '1d', interval: str = '5m'):
        """Get VIX intraday candles."""
        return self._get_intraday('^VIX', period, interval)

    def get_spx_intraday(self, period: str = '1d', interval: str = '5m'):
        """Get SPX intraday candles."""
        return self._get_intraday('^GSPC', period, interval)

    def _get_intraday(self, symbol: str, period: str, interval: str):
        """Fetch intraday candle data."""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                return None

            records = []
            for idx, row in df.iterrows():
                records.append({
                    'timestamp': idx.isoformat(),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': int(row['Volume']),
                })
            return records

        except Exception as e:
            print(f'[MarketData] Error fetching intraday {symbol}: {e}')
            return None


# ─── OpenD Quote Provider ─────────────────────────────────────────

class OpenDProvider:
    """
    Connects to moomoo OpenD for SPY/QQQ quotes and option chains.
    
    Requires OpenD running locally (or on Tailscale network).
    """

    def __init__(self):
        self._quote_ctx = None
        self._trade_ctx = None
        self._connected = False

    def connect(self) -> bool:
        """Establish connection to OpenD. Returns True if successful."""
        try:
            from moomoo import OpenQuoteContext, OpenSecTradeContext, TrdMarket, SecurityFirm

            # Quote context
            self._quote_ctx = OpenQuoteContext(
                host=Config.OPEND_HOST,
                port=Config.OPEND_PORT
            )

            # Trade context (for paper trading)
            security_firm = getattr(SecurityFirm, Config.OPEND_SECURITY_FIRM, SecurityFirm.FUTUINC)
            self._trade_ctx = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.US,
                host=Config.OPEND_HOST,
                port=Config.OPEND_PORT,
                security_firm=security_firm
            )

            self._connected = True
            print(f'[OpenD] Connected to {Config.OPEND_HOST}:{Config.OPEND_PORT}')
            return True

        except ImportError:
            print('[OpenD] moomoo-api not installed. Run: pip install moomoo-api')
            return False
        except Exception as e:
            print(f'[OpenD] Connection failed: {e}')
            return False

    def disconnect(self):
        """Close OpenD connections."""
        if self._quote_ctx:
            self._quote_ctx.close()
        if self._trade_ctx:
            self._trade_ctx.close()
        self._connected = False
        print('[OpenD] Disconnected')

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_snapshot(self, codes: list = None) -> Optional[list]:
        """Get market snapshot for given codes (or default tickers)."""
        if not self._connected or not self._quote_ctx:
            print('[OpenD] Not connected')
            return None

        codes = codes or Config.OPEND_TICKERS

        try:
            from moomoo import RET_OK
            ret, data = self._quote_ctx.get_market_snapshot(codes)
            if ret == RET_OK:
                return data.to_dict('records')
            else:
                print(f'[OpenD] Snapshot error: {data}')
                return None
        except Exception as e:
            print(f'[OpenD] Snapshot failed: {e}')
            return None

    def get_option_chain(self, underlying: str, start: str = None, end: str = None) -> Optional[list]:
        """
        Get option chain for an underlying (e.g., 'US.SPY').
        Returns list of option contracts with strikes, types, etc.
        """
        if not self._connected or not self._quote_ctx:
            return None

        try:
            from moomoo import RET_OK

            # Get expiration dates first
            ret, exp_data = self._quote_ctx.get_option_expiration_date(code=underlying)
            if ret != RET_OK:
                print(f'[OpenD] Option expiry error: {exp_data}')
                return None

            # Default to today's 0DTE if no dates specified
            if not start:
                start = datetime.now().strftime('%Y-%m-%d')
            if not end:
                end = start

            # Get chain for the date range
            ret, chain_data = self._quote_ctx.get_option_chain(
                code=underlying, start=start, end=end
            )
            if ret == RET_OK:
                return chain_data.to_dict('records')
            else:
                print(f'[OpenD] Option chain error: {chain_data}')
                return None

        except Exception as e:
            print(f'[OpenD] Option chain failed: {e}')
            return None

    def subscribe_quotes(self, codes: list = None) -> bool:
        """Subscribe to real-time quotes for given codes."""
        if not self._connected or not self._quote_ctx:
            return False

        codes = codes or Config.OPEND_TICKERS

        try:
            from moomoo import RET_OK, SubType
            ret, err = self._quote_ctx.subscribe(codes, [SubType.QUOTE])
            if ret == RET_OK:
                print(f'[OpenD] Subscribed to quotes: {codes}')
                return True
            else:
                print(f'[OpenD] Subscribe error: {err}')
                return False
        except Exception as e:
            print(f'[OpenD] Subscribe failed: {e}')
            return False

    def get_account_list(self) -> Optional[list]:
        """Get trading accounts (to find paper trading account IDs)."""
        if not self._connected or not self._trade_ctx:
            return None

        try:
            from moomoo import RET_OK
            ret, data = self._trade_ctx.get_acc_list()
            if ret == RET_OK:
                return data.to_dict('records')
            else:
                print(f'[OpenD] Account list error: {data}')
                return None
        except Exception as e:
            print(f'[OpenD] Account list failed: {e}')
            return None

    def get_positions(self, paper: bool = True) -> Optional[list]:
        """Get current positions (defaults to paper trading)."""
        if not self._connected or not self._trade_ctx:
            return None

        try:
            from moomoo import RET_OK, TrdEnv
            trd_env = TrdEnv.SIMULATE if paper else TrdEnv.REAL
            ret, data = self._trade_ctx.position_list_query(trd_env=trd_env)
            if ret == RET_OK:
                return data.to_dict('records')
            else:
                print(f'[OpenD] Positions error: {data}')
                return None
        except Exception as e:
            print(f'[OpenD] Positions failed: {e}')
            return None

    def place_paper_order(self, code: str, price: float, qty: int, side: str = 'BUY') -> Optional[dict]:
        """
        Place a paper trade order.
        
        Args:
            code: Option code (e.g., 'US.SPY240301C500000')
            price: Limit price
            qty: Number of contracts
            side: 'BUY' or 'SELL'
        """
        if not Config.PAPER_TRADING_ENABLED:
            print('[OpenD] Paper trading disabled in config')
            return None

        if not self._connected or not self._trade_ctx:
            return None

        try:
            from moomoo import RET_OK, TrdEnv, TrdSide

            trd_side = TrdSide.BUY if side.upper() == 'BUY' else TrdSide.SELL

            ret, data = self._trade_ctx.place_order(
                price=price,
                qty=qty,
                code=code,
                trd_side=trd_side,
                trd_env=TrdEnv.SIMULATE
            )

            if ret == RET_OK:
                result = data.to_dict('records')[0] if len(data) > 0 else {}
                print(f'[OpenD] Paper order placed: {side} {qty}x {code} @ {price}')
                return result
            else:
                print(f'[OpenD] Order error: {data}')
                return None

        except Exception as e:
            print(f'[OpenD] Order failed: {e}')
            return None


# ─── Convenience ──────────────────────────────────────────────────

# Singleton instances
index_data = IndexDataProvider()
opend = OpenDProvider()


def get_market_context() -> dict:
    """
    Get a combined market context snapshot for analysis.
    Returns VIX, SPX, and OpenD data in one dict.
    """
    context = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'vix': index_data.get_vix(),
        'spx': index_data.get_spx(),
    }

    if opend.is_connected:
        context['spy_qqq'] = opend.get_snapshot()
    else:
        context['spy_qqq'] = None
        context['opend_status'] = 'disconnected'

    return context
