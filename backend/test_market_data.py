"""
Quick test script to validate market data sources.

Run this to verify:
1. yfinance can fetch VIX and SPX
2. OpenD connection works (if OpenD is running)
3. Option chain retrieval works

Usage:
    python test_market_data.py
"""

import json
from market_data import index_data, opend, get_market_context


def test_yfinance():
    """Test VIX and SPX data via yfinance."""
    print('=' * 60)
    print('Testing yfinance (VIX / SPX)')
    print('=' * 60)

    # VIX
    print('\n--- VIX ---')
    vix = index_data.get_vix()
    if vix:
        print(json.dumps(vix, indent=2))
    else:
        print('❌ Failed to fetch VIX')

    # SPX
    print('\n--- SPX ---')
    spx = index_data.get_spx()
    if spx:
        print(json.dumps(spx, indent=2))
    else:
        print('❌ Failed to fetch SPX')

    # VIX intraday
    print('\n--- VIX Intraday (last 5 candles) ---')
    candles = index_data.get_vix_intraday(period='1d', interval='5m')
    if candles:
        for c in candles[-5:]:
            print(f"  {c['timestamp']}: O={c['open']:.2f} H={c['high']:.2f} L={c['low']:.2f} C={c['close']:.2f}")
    else:
        print('❌ No intraday data (market may be closed)')

    print('\n✅ yfinance tests complete')


def test_opend():
    """Test OpenD connection and data retrieval."""
    print('\n' + '=' * 60)
    print('Testing OpenD Connection')
    print('=' * 60)

    if not opend.connect():
        print('❌ OpenD not available (is it running?)')
        print('   Start OpenD on your desktop, then re-run this test.')
        return

    # Account list
    print('\n--- Trading Accounts ---')
    accounts = opend.get_account_list()
    if accounts:
        for acc in accounts:
            print(f"  ID: {acc.get('acc_id')} | Env: {acc.get('trd_env')} | Type: {acc.get('sim_acc_type', 'REAL')}")
    else:
        print('❌ Could not get account list')

    # Market snapshot
    print('\n--- Market Snapshot (SPY, QQQ) ---')
    snapshot = opend.get_snapshot()
    if snapshot:
        for s in snapshot:
            print(f"  {s.get('code')}: ${s.get('last_price', 'N/A')} | Vol: {s.get('volume', 'N/A')}")
    else:
        print('❌ Could not get snapshot (market may be closed or no quote rights)')

    # Option chain (SPY 0DTE)
    print('\n--- SPY Option Chain (today) ---')
    chain = opend.get_option_chain('US.SPY')
    if chain:
        print(f'  Found {len(chain)} contracts')
        # Show first 5
        for opt in chain[:5]:
            print(f"  {opt.get('code')} | {opt.get('option_type')} | Strike: {opt.get('strike_price')} | Exp: {opt.get('strike_time')}")
    else:
        print('❌ Could not get option chain')

    # Positions
    print('\n--- Paper Trading Positions ---')
    positions = opend.get_positions(paper=True)
    if positions is not None:
        if len(positions) == 0:
            print('  No open positions (clean slate)')
        else:
            for p in positions:
                print(f"  {p.get('code')}: {p.get('qty')} @ {p.get('cost_price')} | P&L: {p.get('pl_ratio', 0):.2f}%")
    else:
        print('❌ Could not query positions')

    opend.disconnect()
    print('\n✅ OpenD tests complete')


def test_combined():
    """Test the combined market context."""
    print('\n' + '=' * 60)
    print('Combined Market Context')
    print('=' * 60)

    context = get_market_context()
    print(json.dumps(context, indent=2, default=str))


if __name__ == '__main__':
    test_yfinance()
    test_opend()
    test_combined()
