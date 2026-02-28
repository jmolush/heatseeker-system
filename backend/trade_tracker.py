"""
Heatseeker Trading System — Trade Tracker

Logs all trade recommendations and their outcomes.
Tracks win rate, P&L, pattern performance.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import Config


class TradeRecord:
    """A single trade recommendation and its outcome."""

    def __init__(self, recommendation: dict):
        self.id = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.timestamp = datetime.utcnow().isoformat()
        self.recommendation = recommendation
        self.status = 'pending'  # pending → entered → closed | expired | skipped
        self.entry_price = None
        self.entry_time = None
        self.exit_price = None
        self.exit_time = None
        self.pnl = None
        self.pnl_pct = None
        self.fees = 0.0
        self.order_id = None
        self.notes = ''

    def enter(self, price: float, order_id: str = None):
        self.entry_price = price
        self.entry_time = datetime.utcnow().isoformat()
        self.order_id = order_id
        self.status = 'entered'

    def close(self, price: float, fees: float = 0.0, notes: str = ''):
        self.exit_price = price
        self.exit_time = datetime.utcnow().isoformat()
        self.fees = fees
        self.notes = notes
        self.status = 'closed'

        if self.entry_price and self.entry_price > 0:
            self.pnl = (self.exit_price - self.entry_price) - self.fees
            self.pnl_pct = ((self.exit_price - self.entry_price) / self.entry_price) * 100

    def skip(self, reason: str = ''):
        self.status = 'skipped'
        self.notes = reason

    def expire(self):
        self.status = 'expired'
        self.pnl = -(self.entry_price or 0)  # Total loss if expired worthless
        self.pnl_pct = -100.0 if self.entry_price else 0

    @property
    def is_win(self) -> Optional[bool]:
        if self.status != 'closed':
            return None
        return self.pnl is not None and self.pnl > 0

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'recommendation': self.recommendation,
            'status': self.status,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time,
            'exit_price': self.exit_price,
            'exit_time': self.exit_time,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'fees': self.fees,
            'order_id': self.order_id,
            'notes': self.notes,
            'is_win': self.is_win,
        }


class TradeTracker:
    """Manages trade records and computes performance stats."""

    def __init__(self, log_dir: str = None):
        self.log_dir = Path(log_dir or Config.CAPTURE_BASE_PATH / 'trade_logs')
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.trades: list[TradeRecord] = []
        self._load_today()

    def _log_file(self, date: str = None) -> Path:
        date = date or datetime.utcnow().strftime('%Y-%m-%d')
        return self.log_dir / f'trades_{date}.json'

    def _load_today(self):
        """Load today's trades from disk."""
        path = self._log_file()
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                # Don't reconstruct full objects — just load for stats
                # New trades are appended fresh
                print(f'[TradeTracker] Loaded {len(data)} trades from {path.name}')

    def _save(self):
        """Persist current trades to disk."""
        path = self._log_file()
        records = [t.to_dict() for t in self.trades]
        with open(path, 'w') as f:
            json.dump(records, f, indent=2)

    def new_trade(self, recommendation: dict) -> TradeRecord:
        """Create a new trade record from an analysis recommendation."""
        trade = TradeRecord(recommendation)
        self.trades.append(trade)
        self._save()
        return trade

    def enter_trade(self, trade_id: str, price: float, order_id: str = None):
        """Mark a trade as entered."""
        trade = self._find(trade_id)
        if trade:
            trade.enter(price, order_id)
            self._save()

    def close_trade(self, trade_id: str, price: float, fees: float = 0.0, notes: str = ''):
        """Close a trade with exit price."""
        trade = self._find(trade_id)
        if trade:
            trade.close(price, fees, notes)
            self._save()

    def skip_trade(self, trade_id: str, reason: str = ''):
        """Skip a recommended trade."""
        trade = self._find(trade_id)
        if trade:
            trade.skip(reason)
            self._save()

    def _find(self, trade_id: str) -> Optional[TradeRecord]:
        for t in self.trades:
            if t.id == trade_id:
                return t
        return None

    def get_stats(self) -> dict:
        """Calculate performance statistics."""
        closed = [t for t in self.trades if t.status == 'closed']
        wins = [t for t in closed if t.is_win]
        losses = [t for t in closed if not t.is_win]

        total_pnl = sum(t.pnl or 0 for t in closed)
        avg_win = (sum(t.pnl or 0 for t in wins) / len(wins)) if wins else 0
        avg_loss = (sum(t.pnl or 0 for t in losses) / len(losses)) if losses else 0

        return {
            'total_trades': len(self.trades),
            'entered': len([t for t in self.trades if t.status == 'entered']),
            'closed': len(closed),
            'skipped': len([t for t in self.trades if t.status == 'skipped']),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': (len(wins) / len(closed) * 100) if closed else 0,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_win_pct': (sum(t.pnl_pct or 0 for t in wins) / len(wins)) if wins else 0,
            'avg_loss_pct': (sum(t.pnl_pct or 0 for t in losses) / len(losses)) if losses else 0,
            'best_trade': max((t.pnl or 0 for t in closed), default=0),
            'worst_trade': min((t.pnl or 0 for t in closed), default=0),
        }

    def get_daily_summary(self) -> str:
        """Generate a human-readable daily summary."""
        stats = self.get_stats()
        return (
            f"📊 Daily Trading Summary\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total recommendations: {stats['total_trades']}\n"
            f"Trades entered: {stats['closed'] + stats['entered']}\n"
            f"Trades closed: {stats['closed']}\n"
            f"Trades skipped: {stats['skipped']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Wins: {stats['wins']} | Losses: {stats['losses']}\n"
            f"Win Rate: {stats['win_rate']:.1f}%\n"
            f"Total P&L: ${stats['total_pnl']:.2f}\n"
            f"Avg Win: ${stats['avg_win']:.2f} ({stats['avg_win_pct']:.1f}%)\n"
            f"Avg Loss: ${stats['avg_loss']:.2f} ({stats['avg_loss_pct']:.1f}%)\n"
            f"Best: ${stats['best_trade']:.2f} | Worst: ${stats['worst_trade']:.2f}\n"
        )


# Singleton
tracker = TradeTracker()
