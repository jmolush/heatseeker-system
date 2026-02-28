"""
Heatseeker Trading System — VIX Monitor

VIX is critical for understanding market movement context.
Since OpenD doesn't support US index data, we use yfinance.

VIX context for trading decisions:
- VIX < 15: Low vol environment — small moves, tight ranges, pin jobs more likely
- VIX 15-20: Normal — standard setups apply
- VIX 20-25: Elevated — wider ranges, nodes may overshoot
- VIX 25-30: High — fast moves, gatekeepers less reliable, air pockets dangerous
- VIX > 30: Extreme — Heatseeker less reliable, protect capital mode
- VIX spike (>10% intraday): Market stress event — reshuffles likely

Key VIX behaviors:
- VIX mean-reverts over time
- VIX spikes fast, decays slowly
- Rising VIX = put demand increasing = bearish sentiment
- Falling VIX = complacency building = bullish drift
- VIX term structure (contango vs backwardation) signals regime
"""

import time
from datetime import datetime, timedelta
from typing import Optional

from market_data import index_data


class VIXRegime:
    """Classifies current VIX environment."""
    LOW = "low"             # < 15
    NORMAL = "normal"       # 15-20
    ELEVATED = "elevated"   # 20-25
    HIGH = "high"           # 25-30
    EXTREME = "extreme"     # > 30


class VIXMonitor:
    """
    Monitors VIX state and provides context for trade decisions.
    
    Tracks:
    - Current VIX level and regime
    - Intraday VIX movement (direction, velocity)
    - VIX spike detection
    - Historical context (where is VIX relative to recent range)
    """

    # Thresholds
    SPIKE_THRESHOLD = 0.10      # 10% intraday move = spike
    RAPID_MOVE_THRESHOLD = 0.05 # 5% move in short period
    REGIME_BOUNDARIES = {
        VIXRegime.LOW: (0, 15),
        VIXRegime.NORMAL: (15, 20),
        VIXRegime.ELEVATED: (20, 25),
        VIXRegime.HIGH: (25, 30),
        VIXRegime.EXTREME: (30, float('inf')),
    }

    def __init__(self):
        self._readings: list[dict] = []
        self._alerts: list[dict] = []
        self._poll_interval = 60  # seconds between checks

    def get_current(self) -> Optional[dict]:
        """Get current VIX state with regime classification."""
        vix = index_data.get_vix()
        if not vix or not vix.get('price'):
            return None

        price = vix['price']
        prev_close = vix.get('previous_close', price)

        # Regime
        regime = self._classify_regime(price)

        # Intraday change
        intraday_change = price - prev_close
        intraday_change_pct = (intraday_change / prev_close) if prev_close else 0

        # Spike detection
        is_spike = abs(intraday_change_pct) >= self.SPIKE_THRESHOLD

        reading = {
            'timestamp': datetime.utcnow().isoformat(),
            'price': price,
            'previous_close': prev_close,
            'open': vix.get('open'),
            'high': vix.get('day_high'),
            'low': vix.get('day_low'),
            'intraday_change': intraday_change,
            'intraday_change_pct': intraday_change_pct,
            'regime': regime,
            'is_spike': is_spike,
            'direction': 'rising' if intraday_change > 0 else 'falling' if intraday_change < 0 else 'flat',
        }

        # Add velocity if we have history
        if self._readings:
            last = self._readings[-1]
            time_diff = (
                datetime.fromisoformat(reading['timestamp']) -
                datetime.fromisoformat(last['timestamp'])
            ).total_seconds()

            if time_diff > 0 and last.get('price'):
                price_diff = price - last['price']
                velocity = price_diff / (time_diff / 60)  # points per minute
                reading['velocity'] = velocity
                reading['velocity_direction'] = 'accelerating' if abs(velocity) > 0.05 else 'steady'

        self._readings.append(reading)

        # Generate alerts
        if is_spike:
            direction = "spiking up" if intraday_change > 0 else "crashing down"
            self._alerts.append({
                'timestamp': reading['timestamp'],
                'type': 'vix_spike',
                'severity': 'critical',
                'message': (
                    f"🚨 VIX {direction}: {price:.2f} ({intraday_change_pct:+.1%}) — "
                    f"Map reshuffles likely, protect capital"
                ),
                'data': reading,
            })

        # Regime change alert
        if len(self._readings) >= 2:
            prev_regime = self._readings[-2].get('regime')
            if prev_regime and prev_regime != regime:
                self._alerts.append({
                    'timestamp': reading['timestamp'],
                    'type': 'regime_change',
                    'severity': 'warning',
                    'message': f"VIX regime change: {prev_regime} → {regime} (VIX at {price:.2f})",
                    'data': reading,
                })

        # Trim history
        if len(self._readings) > 500:
            self._readings = self._readings[-500:]

        return reading

    def _classify_regime(self, price: float) -> str:
        """Classify VIX level into a regime."""
        for regime, (low, high) in self.REGIME_BOUNDARIES.items():
            if low <= price < high:
                return regime
        return VIXRegime.EXTREME

    def get_intraday_history(self) -> Optional[list]:
        """Get VIX intraday candle data via yfinance."""
        return index_data.get_vix_intraday(period='1d', interval='5m')

    def get_context_for_analysis(self) -> dict:
        """
        Build VIX context dict for inclusion in Claude analysis prompts.
        
        Returns a human-readable context block.
        """
        current = self.get_current()
        if not current:
            return {
                'available': False,
                'note': 'VIX data unavailable (market may be closed)'
            }

        regime = current['regime']

        # Regime-specific trading guidance
        guidance = {
            VIXRegime.LOW: (
                "Low volatility environment. Expect tight ranges, pin jobs, "
                "and slow grinds. Theta decay fast on 0DTE. "
                "Good for selling premium, scalping edges."
            ),
            VIXRegime.NORMAL: (
                "Normal volatility. Standard Heatseeker setups apply. "
                "Nodes should behave predictably. Good environment for the system."
            ),
            VIXRegime.ELEVATED: (
                "Elevated volatility. Wider intraday ranges expected. "
                "Nodes may overshoot before reversing — use wider margins. "
                "R:R setups can be excellent but timing matters more."
            ),
            VIXRegime.HIGH: (
                "High volatility. Fast, violent moves likely. "
                "Gatekeepers less reliable — price can blow through. "
                "Air pockets extremely dangerous. Reduce position sizes. "
                "Consider wider stops or sitting out marginal setups."
            ),
            VIXRegime.EXTREME: (
                "Extreme volatility. Heatseeker less reliable — maps will reshuffle "
                "frequently. Protect capital above all else. Only the most obvious "
                "setups with extreme R:R asymmetry. Many pros go flat in this regime."
            ),
        }

        context = {
            'available': True,
            'price': current['price'],
            'regime': regime,
            'direction': current['direction'],
            'intraday_change_pct': current['intraday_change_pct'],
            'is_spike': current['is_spike'],
            'guidance': guidance.get(regime, ''),
        }

        # Add velocity if available
        if 'velocity' in current:
            context['velocity'] = current['velocity']
            context['velocity_direction'] = current['velocity_direction']

        # Add recent trend
        if len(self._readings) >= 3:
            recent = self._readings[-3:]
            prices = [r['price'] for r in recent if r.get('price')]
            if len(prices) >= 2:
                short_trend = prices[-1] - prices[0]
                context['short_trend'] = 'rising' if short_trend > 0.2 else 'falling' if short_trend < -0.2 else 'stable'

        return context

    def get_alerts(self, limit: int = 20) -> list[dict]:
        """Get recent VIX alerts."""
        return self._alerts[-limit:]


# Singleton
vix_monitor = VIXMonitor()
