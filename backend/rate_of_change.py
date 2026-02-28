"""
Heatseeker Trading System — Rate of Change Tracker

Tracks how node values change over time to detect:
- Rapid accumulation (strong magnet pulling price)
- Rapid unwinding (levels weakening, potential explosive moves)
- Rolling ceilings (bearish: upside ceiling decreasing)
- Rolling floors (bullish: downside floor increasing)
- Map reshuffles (wholesale node changes — invalidates prior thesis)

From Skylit docs:
- "Watch rate of change for urgency and intent"
- "Fast changes → volatility spikes, sharp reversals"
- Rapid accumulation = strong pull, rapid dissipation = weakening
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class NodeSnapshot:
    """A single node's state at a point in time."""
    strike: float
    value: float                    # Absolute dollar value
    gamma_type: str                 # "positive" or "negative"
    expiry: Optional[str] = None
    timestamp: str = ""

    @property
    def is_positive(self) -> bool:
        return self.gamma_type == "positive"

    @property
    def is_negative(self) -> bool:
        return self.gamma_type == "negative"


@dataclass
class MapSnapshot:
    """Complete heatmap state at a point in time."""
    symbol: str                     # SPX, SPY, QQQ
    timestamp: str
    nodes: list[NodeSnapshot] = field(default_factory=list)
    king_node_strike: Optional[float] = None
    king_node_value: Optional[float] = None
    spot_price: Optional[float] = None

    @property
    def top_nodes(self) -> list[NodeSnapshot]:
        """Top 5 nodes by absolute value."""
        return sorted(self.nodes, key=lambda n: abs(n.value), reverse=True)[:5]

    @property
    def positive_nodes(self) -> list[NodeSnapshot]:
        return [n for n in self.nodes if n.is_positive]

    @property
    def negative_nodes(self) -> list[NodeSnapshot]:
        return [n for n in self.nodes if n.is_negative]

    @property
    def total_positive_value(self) -> float:
        return sum(n.value for n in self.positive_nodes)

    @property
    def total_negative_value(self) -> float:
        return sum(abs(n.value) for n in self.negative_nodes)

    @property
    def gamma_ratio(self) -> Optional[float]:
        """Ratio of positive to negative gamma. >1 = absorption dominant."""
        neg = self.total_negative_value
        if neg == 0:
            return None
        return self.total_positive_value / neg

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'node_count': len(self.nodes),
            'king_node': {
                'strike': self.king_node_strike,
                'value': self.king_node_value,
            },
            'spot_price': self.spot_price,
            'total_positive': self.total_positive_value,
            'total_negative': self.total_negative_value,
            'gamma_ratio': self.gamma_ratio,
            'top_nodes': [
                {'strike': n.strike, 'value': n.value, 'type': n.gamma_type}
                for n in self.top_nodes
            ],
        }


@dataclass
class RateOfChangeAlert:
    """Alert generated when significant rate of change detected."""
    timestamp: str
    symbol: str
    alert_type: str         # "accumulation", "dissipation", "reshuffle",
                            # "rolling_ceiling", "rolling_floor", "king_shift"
    severity: str           # "info", "warning", "critical"
    description: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'symbol': self.symbol,
            'alert_type': self.alert_type,
            'severity': self.severity,
            'description': self.description,
            'data': self.data,
        }


class RateOfChangeTracker:
    """
    Tracks heatmap changes over time and generates alerts.
    
    Maintains a rolling window of MapSnapshots per symbol
    and compares them to detect meaningful changes.
    """

    # Thresholds (tunable)
    ACCUMULATION_THRESHOLD = 0.25   # 25% increase in node value = significant
    DISSIPATION_THRESHOLD = 0.25    # 25% decrease
    RESHUFFLE_THRESHOLD = 0.50      # 50% of top nodes changed = reshuffle
    KING_SHIFT_THRESHOLD = 5.0      # King node moved 5+ strikes = significant

    def __init__(self, window_size: int = 20):
        self._snapshots: dict[str, list[MapSnapshot]] = defaultdict(list)
        self._alerts: list[RateOfChangeAlert] = []
        self._window_size = window_size

    def add_snapshot(self, snapshot: MapSnapshot) -> list[RateOfChangeAlert]:
        """
        Add a new map snapshot and check for rate-of-change alerts.
        Returns list of any alerts generated.
        """
        symbol = snapshot.symbol
        history = self._snapshots[symbol]
        history.append(snapshot)

        # Trim to window size
        if len(history) > self._window_size:
            self._snapshots[symbol] = history[-self._window_size:]

        # Need at least 2 snapshots to compare
        if len(history) < 2:
            return []

        alerts = []
        prev = history[-2]
        curr = snapshot

        # Check for king node shift
        king_alert = self._check_king_shift(prev, curr)
        if king_alert:
            alerts.append(king_alert)

        # Check accumulation / dissipation
        value_alerts = self._check_value_changes(prev, curr)
        alerts.extend(value_alerts)

        # Check for map reshuffle
        reshuffle_alert = self._check_reshuffle(prev, curr)
        if reshuffle_alert:
            alerts.append(reshuffle_alert)

        # Check rolling ceiling/floor (need 3+ snapshots)
        if len(history) >= 3:
            roll_alerts = self._check_rolling_levels(history[-3:])
            alerts.extend(roll_alerts)

        self._alerts.extend(alerts)
        return alerts

    def _check_king_shift(self, prev: MapSnapshot, curr: MapSnapshot) -> Optional[RateOfChangeAlert]:
        """Detect if the King Node has moved significantly."""
        if not prev.king_node_strike or not curr.king_node_strike:
            return None

        shift = abs(curr.king_node_strike - prev.king_node_strike)
        if shift >= self.KING_SHIFT_THRESHOLD:
            severity = "critical" if shift >= self.KING_SHIFT_THRESHOLD * 2 else "warning"
            return RateOfChangeAlert(
                timestamp=curr.timestamp,
                symbol=curr.symbol,
                alert_type="king_shift",
                severity=severity,
                description=(
                    f"King Node shifted {shift:.0f} points: "
                    f"{prev.king_node_strike:.0f} → {curr.king_node_strike:.0f}"
                ),
                data={
                    'previous_strike': prev.king_node_strike,
                    'current_strike': curr.king_node_strike,
                    'shift_points': shift,
                    'previous_value': prev.king_node_value,
                    'current_value': curr.king_node_value,
                }
            )
        return None

    def _check_value_changes(self, prev: MapSnapshot, curr: MapSnapshot) -> list[RateOfChangeAlert]:
        """Detect significant accumulation or dissipation of node values."""
        alerts = []

        # Overall value changes
        prev_total = prev.total_positive_value + prev.total_negative_value
        curr_total = curr.total_positive_value + curr.total_negative_value

        if prev_total > 0:
            total_change = (curr_total - prev_total) / prev_total

            if total_change >= self.ACCUMULATION_THRESHOLD:
                alerts.append(RateOfChangeAlert(
                    timestamp=curr.timestamp,
                    symbol=curr.symbol,
                    alert_type="accumulation",
                    severity="warning",
                    description=(
                        f"Rapid node accumulation: total values up {total_change:.0%} "
                        f"(${prev_total:,.0f} → ${curr_total:,.0f})"
                    ),
                    data={
                        'change_pct': total_change,
                        'previous_total': prev_total,
                        'current_total': curr_total,
                    }
                ))

            elif total_change <= -self.DISSIPATION_THRESHOLD:
                alerts.append(RateOfChangeAlert(
                    timestamp=curr.timestamp,
                    symbol=curr.symbol,
                    alert_type="dissipation",
                    severity="warning",
                    description=(
                        f"Rapid node dissipation: total values down {abs(total_change):.0%} "
                        f"(${prev_total:,.0f} → ${curr_total:,.0f})"
                    ),
                    data={
                        'change_pct': total_change,
                        'previous_total': prev_total,
                        'current_total': curr_total,
                    }
                ))

        # Gamma ratio shift (positive vs negative gamma balance)
        if prev.gamma_ratio and curr.gamma_ratio:
            ratio_change = curr.gamma_ratio - prev.gamma_ratio
            if abs(ratio_change) > 0.3:
                direction = "positive gamma building" if ratio_change > 0 else "negative gamma building"
                alerts.append(RateOfChangeAlert(
                    timestamp=curr.timestamp,
                    symbol=curr.symbol,
                    alert_type="gamma_shift",
                    severity="info",
                    description=(
                        f"Gamma balance shifting: {direction} "
                        f"(ratio {prev.gamma_ratio:.2f} → {curr.gamma_ratio:.2f})"
                    ),
                    data={
                        'previous_ratio': prev.gamma_ratio,
                        'current_ratio': curr.gamma_ratio,
                        'direction': direction,
                    }
                ))

        return alerts

    def _check_reshuffle(self, prev: MapSnapshot, curr: MapSnapshot) -> Optional[RateOfChangeAlert]:
        """Detect a map reshuffle (wholesale node changes)."""
        prev_strikes = set(n.strike for n in prev.top_nodes)
        curr_strikes = set(n.strike for n in curr.top_nodes)

        if not prev_strikes:
            return None

        # How many of the top nodes changed?
        overlap = prev_strikes & curr_strikes
        changed_pct = 1 - (len(overlap) / len(prev_strikes)) if prev_strikes else 0

        if changed_pct >= self.RESHUFFLE_THRESHOLD:
            return RateOfChangeAlert(
                timestamp=curr.timestamp,
                symbol=curr.symbol,
                alert_type="reshuffle",
                severity="critical",
                description=(
                    f"Map reshuffle detected: {changed_pct:.0%} of top nodes changed. "
                    f"Previous thesis may be invalidated."
                ),
                data={
                    'changed_pct': changed_pct,
                    'previous_top_strikes': sorted(prev_strikes),
                    'current_top_strikes': sorted(curr_strikes),
                    'retained': sorted(overlap),
                    'lost': sorted(prev_strikes - overlap),
                    'gained': sorted(curr_strikes - overlap),
                }
            )
        return None

    def _check_rolling_levels(self, snapshots: list[MapSnapshot]) -> list[RateOfChangeAlert]:
        """
        Detect rolling ceilings (bearish) and rolling floors (bullish).
        
        Rolling ceiling: the highest significant node strike is decreasing over time
        Rolling floor: the lowest significant node strike is increasing over time
        """
        alerts = []

        # Get highest positive node (ceiling proxy) across snapshots
        ceilings = []
        floors = []

        for snap in snapshots:
            if snap.positive_nodes:
                highest_pos = max(snap.positive_nodes, key=lambda n: n.strike)
                ceilings.append(highest_pos.strike)

                lowest_pos = min(snap.positive_nodes, key=lambda n: n.strike)
                floors.append(lowest_pos.strike)

        # Rolling ceiling: each ceiling lower than previous
        if len(ceilings) >= 3:
            if ceilings[0] > ceilings[1] > ceilings[2]:
                drop = ceilings[0] - ceilings[2]
                alerts.append(RateOfChangeAlert(
                    timestamp=snapshots[-1].timestamp,
                    symbol=snapshots[-1].symbol,
                    alert_type="rolling_ceiling",
                    severity="warning",
                    description=(
                        f"Rolling ceiling detected (bearish): "
                        f"top strike declining {ceilings[0]:.0f} → {ceilings[1]:.0f} → {ceilings[2]:.0f} "
                        f"({drop:.0f} points)"
                    ),
                    data={
                        'ceiling_progression': ceilings,
                        'total_drop': drop,
                    }
                ))

        # Rolling floor: each floor higher than previous
        if len(floors) >= 3:
            if floors[0] < floors[1] < floors[2]:
                rise = floors[2] - floors[0]
                alerts.append(RateOfChangeAlert(
                    timestamp=snapshots[-1].timestamp,
                    symbol=snapshots[-1].symbol,
                    alert_type="rolling_floor",
                    severity="warning",
                    description=(
                        f"Rolling floor detected (bullish): "
                        f"bottom strike rising {floors[0]:.0f} → {floors[1]:.0f} → {floors[2]:.0f} "
                        f"({rise:.0f} points)"
                    ),
                    data={
                        'floor_progression': floors,
                        'total_rise': rise,
                    }
                ))

        return alerts

    def get_alerts(self, symbol: str = None, limit: int = 50) -> list[dict]:
        """Get recent alerts, optionally filtered by symbol."""
        alerts = self._alerts
        if symbol:
            alerts = [a for a in alerts if a.symbol == symbol]
        return [a.to_dict() for a in alerts[-limit:]]

    def get_summary(self, symbol: str) -> Optional[dict]:
        """
        Get a summary of rate-of-change state for an index.
        Useful for feeding into analysis prompts.
        """
        history = self._snapshots.get(symbol, [])
        if len(history) < 2:
            return None

        first = history[0]
        last = history[-1]
        recent_alerts = [a for a in self._alerts if a.symbol == symbol][-5:]

        # Value trend
        first_total = first.total_positive_value + first.total_negative_value
        last_total = last.total_positive_value + last.total_negative_value
        value_change = ((last_total - first_total) / first_total) if first_total > 0 else 0

        # King node movement
        king_moved = (
            first.king_node_strike is not None and
            last.king_node_strike is not None and
            first.king_node_strike != last.king_node_strike
        )

        # Gamma balance trend
        first_ratio = first.gamma_ratio
        last_ratio = last.gamma_ratio

        return {
            'symbol': symbol,
            'snapshots': len(history),
            'time_span': {
                'first': first.timestamp,
                'last': last.timestamp,
            },
            'value_trend': {
                'total_change_pct': value_change,
                'direction': 'accumulating' if value_change > 0.05 else 'dissipating' if value_change < -0.05 else 'stable',
                'first_total': first_total,
                'last_total': last_total,
            },
            'king_node': {
                'moved': king_moved,
                'first_strike': first.king_node_strike,
                'last_strike': last.king_node_strike,
            },
            'gamma_balance': {
                'first_ratio': first_ratio,
                'last_ratio': last_ratio,
                'trend': (
                    'positive_building' if (last_ratio or 0) > (first_ratio or 0) + 0.2
                    else 'negative_building' if (last_ratio or 0) < (first_ratio or 0) - 0.2
                    else 'stable'
                ),
            },
            'recent_alerts': [a.to_dict() for a in recent_alerts],
        }

    def save_session(self, filepath: str):
        """Save all snapshot history and alerts to a JSON file."""
        data = {
            'saved_at': datetime.now(timezone.utc).isoformat(),
            'snapshots': {
                symbol: [s.to_dict() for s in snaps]
                for symbol, snaps in self._snapshots.items()
            },
            'alerts': [a.to_dict() for a in self._alerts],
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def clear(self):
        """Reset all state."""
        self._snapshots.clear()
        self._alerts.clear()


# Singleton
roc_tracker = RateOfChangeTracker()