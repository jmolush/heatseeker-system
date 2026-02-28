"""
Heatseeker Trading System — Market Regime Classification

Classifies the current trading day into one of three regimes
based on price action delta:

- TREND DAY: Strong directional move. Price stair-steps in one direction.
  Wide range, small pullbacks, nodes in trend direction keep growing.
  Strategy: Trade with the trend, enter on pullbacks, don't fade.

- LEVELS DAY: Price respects key levels (nodes). Bounces between
  floor and ceiling. King Node acts as magnet. Good for fading edges.
  Strategy: Fade reversals at node boundaries, avoid the midpoint.

- WHIPSAW DAY: Choppy, erratic. Price swings between nodes unpredictably.
  Multiple failed tests, reversals don't hold. Often Rainbow Road on Heatseeker.
  Strategy: Reduce size or sit out. Only trade the most obvious setups.

Classification uses:
- Intraday price range (high - low) relative to recent average
- Number of directional reversals
- Price delta from open (net directional move)
- Ratio of directional move to total range (efficiency)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class DayType:
    TREND = "trend"
    LEVELS = "levels"
    WHIPSAW = "whipsaw"
    UNKNOWN = "unknown"


@dataclass
class PriceBar:
    """A single price bar (candle)."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass
class RegimeClassification:
    """Result of market regime classification."""
    timestamp: str
    day_type: str
    confidence: float               # 0.0 - 1.0
    
    # Price metrics
    open_price: float = 0.0
    current_price: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    
    # Derived metrics
    total_range: float = 0.0        # high - low
    net_delta: float = 0.0          # current - open (directional move)
    net_delta_pct: float = 0.0      # as percentage of open
    efficiency: float = 0.0         # |net_delta| / total_range (1.0 = pure trend)
    reversal_count: int = 0         # number of direction changes
    avg_range_ratio: float = 0.0    # today's range vs recent average

    # Guidance
    strategy_guidance: str = ""
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'day_type': self.day_type,
            'confidence': self.confidence,
            'prices': {
                'open': self.open_price,
                'current': self.current_price,
                'high': self.day_high,
                'low': self.day_low,
            },
            'metrics': {
                'total_range': self.total_range,
                'net_delta': self.net_delta,
                'net_delta_pct': self.net_delta_pct,
                'efficiency': self.efficiency,
                'reversal_count': self.reversal_count,
                'avg_range_ratio': self.avg_range_ratio,
            },
            'strategy_guidance': self.strategy_guidance,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        emoji = {
            DayType.TREND: "📈" if self.net_delta > 0 else "📉",
            DayType.LEVELS: "📊",
            DayType.WHIPSAW: "🌊",
            DayType.UNKNOWN: "❓",
        }.get(self.day_type, "❓")
        
        direction = ""
        if self.day_type == DayType.TREND:
            direction = f" ({'bullish' if self.net_delta > 0 else 'bearish'})"
        
        return (
            f"{emoji} {self.day_type.upper()} DAY{direction} "
            f"| Delta: {self.net_delta:+.2f} ({self.net_delta_pct:+.2%}) "
            f"| Range: {self.total_range:.2f} "
            f"| Efficiency: {self.efficiency:.0%} "
            f"| Reversals: {self.reversal_count}"
        )


STRATEGY_GUIDANCE = {
    DayType.TREND: (
        "TREND DAY — Trade with the direction. Enter on pullbacks to node levels. "
        "Don't fade the move. King Node is likely the destination. "
        "Stair-stepping pattern: price hits one node, then selects the next in trend direction. "
        "Nodes away from price should be fading; nodes in trend direction increasing. "
        "If price moves away but node values remain/increase, likely to resume toward them."
    ),
    DayType.LEVELS: (
        "LEVELS DAY — Fade the edges, avoid the midpoint. "
        "Price is respecting node boundaries. Play reversals at King Node and Gatekeepers. "
        "Asymmetric R:R at the edges, ~1:1 at midpoint (bad). "
        "Watch for 1st touch (strongest), 2nd touch (~66%), 3rd+ touch (~33%). "
        "Pin jobs common near close — tight ranges, scalp the edges."
    ),
    DayType.WHIPSAW: (
        "WHIPSAW DAY — Reduce size or sit out entirely. "
        "Price is chopping between nodes with no clear direction. "
        "Multiple failed tests, reversals don't hold. Theta decay kills 0DTE in the middle. "
        "If you must trade, only take the most extreme edge setups with tight stops. "
        "Consider this a Rainbow Road environment — wait for clarity."
    ),
}


class MarketRegimeClassifier:
    """
    Classifies the current trading day based on price action.
    
    Uses intraday candle data to determine if it's a trend day,
    levels day, or whipsaw day.
    """

    # Thresholds (tunable — these are starting points)
    TREND_EFFICIENCY_MIN = 0.60      # >60% of range is directional = trend
    WHIPSAW_REVERSAL_MIN = 4         # 4+ reversals in session = whipsaw
    WHIPSAW_EFFICIENCY_MAX = 0.30    # <30% efficiency with many reversals = whipsaw
    WIDE_RANGE_MULTIPLIER = 1.3      # Today's range > 1.3x average = wide

    def __init__(self):
        self._candles: dict[str, list[PriceBar]] = {}  # symbol → intraday candles
        self._recent_daily_ranges: dict[str, list[float]] = {}  # for average range
        self._classifications: list[RegimeClassification] = []

    def add_candle(self, symbol: str, candle: PriceBar):
        """Add an intraday candle for tracking."""
        if symbol not in self._candles:
            self._candles[symbol] = []
        self._candles[symbol].append(candle)

    def load_candles(self, symbol: str, candles: list[dict]):
        """Load a batch of candles (e.g., from yfinance or OpenD)."""
        self._candles[symbol] = [
            PriceBar(
                timestamp=c.get('timestamp', ''),
                open=c['open'],
                high=c['high'],
                low=c['low'],
                close=c['close'],
                volume=c.get('volume', 0),
            )
            for c in candles
        ]

    def set_recent_ranges(self, symbol: str, ranges: list[float]):
        """Set recent daily ranges for comparison (last 5-20 days)."""
        self._recent_daily_ranges[symbol] = ranges

    def classify(self, symbol: str = 'SPY') -> RegimeClassification:
        """
        Classify current day's price action.
        
        Uses intraday candles to compute:
        - Net delta (directional move from open)
        - Total range (high - low)
        - Efficiency (how much of range is directional)
        - Reversal count (how many times direction changed)
        """
        candles = self._candles.get(symbol, [])
        now = datetime.utcnow().isoformat()

        if not candles:
            return RegimeClassification(
                timestamp=now,
                day_type=DayType.UNKNOWN,
                confidence=0.0,
                strategy_guidance="No price data available."
            )

        # Basic price metrics
        open_price = candles[0].open
        current_price = candles[-1].close
        day_high = max(c.high for c in candles)
        day_low = min(c.low for c in candles)
        total_range = day_high - day_low
        net_delta = current_price - open_price
        net_delta_pct = (net_delta / open_price) if open_price else 0

        # Efficiency: what fraction of the range is the net move?
        efficiency = abs(net_delta) / total_range if total_range > 0 else 0

        # Count reversals (direction changes in close-to-close)
        reversal_count = 0
        if len(candles) >= 3:
            directions = []
            for i in range(1, len(candles)):
                diff = candles[i].close - candles[i-1].close
                if diff > 0:
                    directions.append(1)
                elif diff < 0:
                    directions.append(-1)
                # Skip zero moves

            for i in range(1, len(directions)):
                if directions[i] != directions[i-1]:
                    reversal_count += 1

        # Average range comparison
        recent_ranges = self._recent_daily_ranges.get(symbol, [])
        avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else total_range
        avg_range_ratio = total_range / avg_range if avg_range > 0 else 1.0

        # ─── Classification Logic ────────────────────────────

        day_type = DayType.LEVELS  # Default
        confidence = 0.5

        # TREND: High efficiency, few reversals relative to candle count
        reversals_per_candle = reversal_count / len(candles) if candles else 0

        if efficiency >= self.TREND_EFFICIENCY_MIN and reversals_per_candle < 0.4:
            day_type = DayType.TREND
            confidence = min(0.95, 0.5 + efficiency * 0.5)

        # WHIPSAW: Low efficiency, many reversals
        elif (efficiency <= self.WHIPSAW_EFFICIENCY_MAX and 
              reversal_count >= self.WHIPSAW_REVERSAL_MIN):
            day_type = DayType.WHIPSAW
            confidence = min(0.9, 0.4 + (reversal_count / 10) * 0.3 + (1 - efficiency) * 0.2)

        # Additional whipsaw signal: wide range but no net move
        elif (avg_range_ratio >= self.WIDE_RANGE_MULTIPLIER and 
              efficiency < 0.35 and reversal_count >= 3):
            day_type = DayType.WHIPSAW
            confidence = 0.6

        # LEVELS: Moderate efficiency, moderate reversals (the "normal" case)
        else:
            day_type = DayType.LEVELS
            # Higher confidence if we're clearly in a range
            if 0.25 <= efficiency <= 0.55 and reversal_count >= 2:
                confidence = 0.7
            else:
                confidence = 0.5

        # Early in the session, lower confidence (not enough data)
        if len(candles) < 12:  # Less than ~1 hour of 5-min candles
            confidence *= 0.6
            day_type_note = " (early session — may reclassify)"
        else:
            day_type_note = ""

        guidance = STRATEGY_GUIDANCE.get(day_type, "")

        result = RegimeClassification(
            timestamp=now,
            day_type=day_type,
            confidence=confidence,
            open_price=open_price,
            current_price=current_price,
            day_high=day_high,
            day_low=day_low,
            total_range=total_range,
            net_delta=net_delta,
            net_delta_pct=net_delta_pct,
            efficiency=efficiency,
            reversal_count=reversal_count,
            avg_range_ratio=avg_range_ratio,
            strategy_guidance=guidance + day_type_note,
        )

        self._classifications.append(result)
        return result

    def get_history(self) -> list[dict]:
        """Get classification history (useful for seeing how the day evolved)."""
        return [c.to_dict() for c in self._classifications]

    def has_reclassified(self) -> Optional[dict]:
        """
        Check if the day type has changed since last classification.
        Useful for alerting when a levels day turns into a trend day, etc.
        """
        if len(self._classifications) < 2:
            return None

        prev = self._classifications[-2]
        curr = self._classifications[-1]

        if prev.day_type != curr.day_type:
            return {
                'reclassified': True,
                'from': prev.day_type,
                'to': curr.day_type,
                'timestamp': curr.timestamp,
                'message': f"Day reclassified: {prev.day_type} → {curr.day_type}",
            }
        return None


# Singleton
regime_classifier = MarketRegimeClassifier()
