"""
Heatseeker Trading System — Cross-Index Confluence Detection

Core principle from Skylit docs: SPX, SPY, QQQ MUST agree.
If one diverges, stand aside.

This module tracks the state of each index and determines
whether there's alignment for high-confidence trades.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Bias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"  # Range-bound / pin
    UNCLEAR = "unclear"  # Rainbow Road / no clear signal


class ConfluenceLevel(Enum):
    STRONG = "strong"       # All 3 agree strongly
    MODERATE = "moderate"   # All 3 agree but mixed strength
    WEAK = "weak"           # 2 of 3 agree
    NONE = "none"           # Divergence — stand aside
    INSUFFICIENT = "insufficient"  # Not enough data


@dataclass
class IndexState:
    """Snapshot of a single index's heatmap state."""
    symbol: str                          # SPX, SPY, QQQ
    timestamp: str = ""
    bias: Bias = Bias.UNCLEAR
    confidence: float = 0.0              # 0.0 - 1.0

    # Key node info (extracted from analysis)
    king_node_strike: Optional[float] = None
    king_node_value: Optional[float] = None
    king_node_type: Optional[str] = None  # "positive" or "negative"

    gatekeeper_strikes: list = field(default_factory=list)

    # Pattern
    pattern: Optional[str] = None        # whipsaw, trend, gatekeeper, rainbow_road, rug_setup

    # Price relationship
    price_vs_king: Optional[str] = None  # "above", "below", "at"
    distance_to_king: Optional[float] = None  # points away

    # Rate of change summary
    nodes_accumulating: bool = False
    nodes_dissipating: bool = False
    direction_of_change: Optional[str] = None  # "bullish_building", "bearish_building", "mixed"

    # Raw analysis text for context
    raw_summary: str = ""

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'bias': self.bias.value,
            'confidence': self.confidence,
            'king_node': {
                'strike': self.king_node_strike,
                'value': self.king_node_value,
                'type': self.king_node_type,
            } if self.king_node_strike else None,
            'gatekeeper_strikes': self.gatekeeper_strikes,
            'pattern': self.pattern,
            'price_vs_king': self.price_vs_king,
            'distance_to_king': self.distance_to_king,
            'rate_of_change': {
                'accumulating': self.nodes_accumulating,
                'dissipating': self.nodes_dissipating,
                'direction': self.direction_of_change,
            },
            'raw_summary': self.raw_summary,
        }


@dataclass
class ConfluenceResult:
    """Result of cross-index confluence check."""
    timestamp: str
    level: ConfluenceLevel
    overall_bias: Bias
    confidence: float            # 0.0 - 1.0

    spx: Optional[IndexState] = None
    spy: Optional[IndexState] = None
    qqq: Optional[IndexState] = None

    agreement_count: int = 0     # How many indices agree on direction
    divergent_index: Optional[str] = None  # Which one disagrees, if any

    trade_eligible: bool = False  # Should we even consider a trade?
    stand_aside_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'level': self.level.value,
            'overall_bias': self.overall_bias.value,
            'confidence': self.confidence,
            'agreement_count': self.agreement_count,
            'divergent_index': self.divergent_index,
            'trade_eligible': self.trade_eligible,
            'stand_aside_reason': self.stand_aside_reason,
            'indices': {
                'spx': self.spx.to_dict() if self.spx else None,
                'spy': self.spy.to_dict() if self.spy else None,
                'qqq': self.qqq.to_dict() if self.qqq else None,
            }
        }

    def summary(self) -> str:
        """Human-readable confluence summary."""
        if self.level == ConfluenceLevel.STRONG:
            emoji = "🟢"
        elif self.level == ConfluenceLevel.MODERATE:
            emoji = "🟡"
        elif self.level == ConfluenceLevel.WEAK:
            emoji = "🟠"
        else:
            emoji = "🔴"

        parts = [f"{emoji} Confluence: {self.level.value.upper()} — {self.overall_bias.value}"]

        if self.spx:
            parts.append(f"  SPX: {self.spx.bias.value} ({self.spx.confidence:.0%})")
        if self.spy:
            parts.append(f"  SPY: {self.spy.bias.value} ({self.spy.confidence:.0%})")
        if self.qqq:
            parts.append(f"  QQQ: {self.qqq.bias.value} ({self.qqq.confidence:.0%})")

        if self.divergent_index:
            parts.append(f"  ⚠️ Divergence: {self.divergent_index}")

        if self.stand_aside_reason:
            parts.append(f"  🚫 {self.stand_aside_reason}")

        return "\n".join(parts)


class ConfluenceDetector:
    """
    Tracks index states and detects cross-index confluence.
    
    Core rules from Skylit:
    - All 3 indices must agree for high-confidence trades
    - "Would my thesis hold if I took this on QQQ instead?"
    - A floor on SPX can prevent a rug on QQQ
    - A ceiling on SPY can prevent a rally on SPX
    - Mixed signals = no confidence = stand aside
    """

    def __init__(self):
        self._states: dict[str, IndexState] = {}
        self._history: list[ConfluenceResult] = []

    def update_index(self, state: IndexState):
        """Update the state of an index from latest analysis."""
        self._states[state.symbol] = state

    def update_from_analysis(self, symbol: str, analysis: dict):
        """
        Build an IndexState from a Claude analysis result.
        
        The analysis dict should have fields like:
        - bias, confidence, king_node, pattern, etc.
        """
        state = IndexState(symbol=symbol)
        state.timestamp = analysis.get('_timestamp', datetime.now(timezone.utc).isoformat())

        # Bias
        bias_str = analysis.get('bias', analysis.get('overall_bias', 'unclear')).lower()
        bias_map = {
            'bullish': Bias.BULLISH,
            'bearish': Bias.BEARISH,
            'neutral': Bias.NEUTRAL,
            'pin': Bias.NEUTRAL,
            'range': Bias.NEUTRAL,
        }
        state.bias = bias_map.get(bias_str, Bias.UNCLEAR)
        state.confidence = float(analysis.get('confidence', 0)) / 10.0  # Convert 1-10 to 0-1

        # King node
        king = analysis.get('king_node', {})
        if isinstance(king, dict):
            state.king_node_strike = king.get('strike')
            state.king_node_value = king.get('value')
            state.king_node_type = king.get('type')

        # Pattern
        state.pattern = analysis.get('pattern', '').lower().replace(' ', '_') or None

        # Gatekeepers
        gatekeepers = analysis.get('gatekeepers', analysis.get('gatekeeper_strikes', []))
        if isinstance(gatekeepers, list):
            state.gatekeeper_strikes = gatekeepers

        # Rate of change
        roc = analysis.get('rate_of_change', {})
        if isinstance(roc, dict):
            state.nodes_accumulating = roc.get('accumulating', False)
            state.nodes_dissipating = roc.get('dissipating', False)
            state.direction_of_change = roc.get('direction')

        # Raw summary
        state.raw_summary = analysis.get('summary', analysis.get('current_state', ''))

        self._states[symbol] = state
        return state

    def check_confluence(self) -> ConfluenceResult:
        """
        Evaluate cross-index confluence based on current states.
        
        Returns a ConfluenceResult with trade eligibility.
        """
        now = datetime.now(timezone.utc).isoformat()

        spx = self._states.get('SPX') or self._states.get('SPXW')
        spy = self._states.get('SPY')
        qqq = self._states.get('QQQ')

        available = [s for s in [spx, spy, qqq] if s is not None]

        # Not enough data
        if len(available) < 2:
            result = ConfluenceResult(
                timestamp=now,
                level=ConfluenceLevel.INSUFFICIENT,
                overall_bias=Bias.UNCLEAR,
                confidence=0.0,
                spx=spx, spy=spy, qqq=qqq,
                trade_eligible=False,
                stand_aside_reason=f"Only {len(available)} of 3 indices available"
            )
            self._history.append(result)
            return result

        # Count biases (exclude UNCLEAR)
        biases = [s.bias for s in available if s.bias != Bias.UNCLEAR]

        if not biases:
            result = ConfluenceResult(
                timestamp=now,
                level=ConfluenceLevel.NONE,
                overall_bias=Bias.UNCLEAR,
                confidence=0.0,
                spx=spx, spy=spy, qqq=qqq,
                trade_eligible=False,
                stand_aside_reason="All indices unclear — Rainbow Road or insufficient signal"
            )
            self._history.append(result)
            return result

        # Find majority bias
        from collections import Counter
        bias_counts = Counter(biases)
        majority_bias, majority_count = bias_counts.most_common(1)[0]

        # Check for rainbow road (no clear consensus)
        rainbow_road = any(
            s.pattern == 'rainbow_road' for s in available if s.pattern
        )

        if rainbow_road:
            result = ConfluenceResult(
                timestamp=now,
                level=ConfluenceLevel.NONE,
                overall_bias=Bias.UNCLEAR,
                confidence=0.0,
                spx=spx, spy=spy, qqq=qqq,
                trade_eligible=False,
                stand_aside_reason="Rainbow Road detected — highly advisable to avoid trading"
            )
            self._history.append(result)
            return result

        # Determine agreement
        total_with_opinion = len(biases)
        agreement_count = majority_count

        # Find divergent index
        divergent = None
        if agreement_count < total_with_opinion:
            for s in available:
                if s.bias != Bias.UNCLEAR and s.bias != majority_bias:
                    divergent = s.symbol
                    break

        # Calculate average confidence of agreeing indices
        agreeing = [s for s in available if s.bias == majority_bias]
        avg_confidence = sum(s.confidence for s in agreeing) / len(agreeing) if agreeing else 0

        # Determine confluence level
        if agreement_count == len(available) and agreement_count >= 3:
            level = ConfluenceLevel.STRONG if avg_confidence >= 0.6 else ConfluenceLevel.MODERATE
        elif agreement_count == len(available) and agreement_count == 2:
            level = ConfluenceLevel.MODERATE if avg_confidence >= 0.5 else ConfluenceLevel.WEAK
        elif agreement_count >= 2:
            level = ConfluenceLevel.WEAK
        else:
            level = ConfluenceLevel.NONE

        # Trade eligibility
        trade_eligible = level in (ConfluenceLevel.STRONG, ConfluenceLevel.MODERATE)
        stand_aside = None

        if not trade_eligible:
            if level == ConfluenceLevel.WEAK:
                stand_aside = f"Only {agreement_count}/{total_with_opinion} agree — {divergent} diverging"
            elif level == ConfluenceLevel.NONE:
                stand_aside = "No confluence — indices disagree on direction"

        result = ConfluenceResult(
            timestamp=now,
            level=level,
            overall_bias=majority_bias,
            confidence=avg_confidence,
            spx=spx, spy=spy, qqq=qqq,
            agreement_count=agreement_count,
            divergent_index=divergent,
            trade_eligible=trade_eligible,
            stand_aside_reason=stand_aside,
        )

        self._history.append(result)
        return result

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent confluence checks."""
        return [r.to_dict() for r in self._history[-limit:]]

    def get_trend(self) -> Optional[dict]:
        """
        Analyze confluence trend over recent checks.
        Are we seeing improving or deteriorating confluence?
        """
        if len(self._history) < 3:
            return None

        recent = self._history[-10:]
        levels = [r.level for r in recent]
        biases = [r.overall_bias for r in recent]

        # Count level distribution
        from collections import Counter
        level_counts = Counter(levels)
        bias_counts = Counter(b for b in biases if b != Bias.UNCLEAR)

        # Is confluence improving or deteriorating?
        if len(recent) >= 5:
            first_half = recent[:len(recent)//2]
            second_half = recent[len(recent)//2:]

            level_score = {
                ConfluenceLevel.STRONG: 3,
                ConfluenceLevel.MODERATE: 2,
                ConfluenceLevel.WEAK: 1,
                ConfluenceLevel.NONE: 0,
                ConfluenceLevel.INSUFFICIENT: -1,
            }

            first_avg = sum(level_score.get(r.level, 0) for r in first_half) / len(first_half)
            second_avg = sum(level_score.get(r.level, 0) for r in second_half) / len(second_half)

            if second_avg > first_avg + 0.5:
                trend = "improving"
            elif second_avg < first_avg - 0.5:
                trend = "deteriorating"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            'checks_analyzed': len(recent),
            'trend': trend,
            'level_distribution': {k.value: v for k, v in level_counts.items()},
            'bias_distribution': {k.value: v for k, v in bias_counts.items()},
            'current_level': recent[-1].level.value if recent else None,
            'current_bias': recent[-1].overall_bias.value if recent else None,
        }


# Singleton
confluence = ConfluenceDetector()