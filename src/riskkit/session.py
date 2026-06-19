"""Session manager.

Enforces the behavioural guardrails that keep a system (and its operator) out of
trouble: daily trade/loss caps, profit-taking stops, minimum spacing between
trades, escalating cooldowns after losing streaks, and tilt detection.

Pure standard library. Feed it closed trades via :meth:`record_trade` and ask
:meth:`can_open` before each new entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from statistics import mean


@dataclass
class TradeRecord:
    ts_open: datetime
    ts_close: datetime
    pnl: float
    pnl_pct: float
    score: int                  # signal-quality score for the trade (0-100)
    position_size_units: float
    duration_minutes: float
    side: str
    symbol: str
    strategy: str


@dataclass
class SessionDecision:
    allowed: bool
    reason: str = ""
    cooldown_until: datetime | None = None
    on_tilt: bool = False


class SessionManager:
    def __init__(
        self,
        max_trades_per_day: int = 5,
        max_losses_per_day: int = 3,
        max_daily_loss_pct: float = 1.5,
        max_daily_profit_pct: float = 5.0,
        min_minutes_between_trades: int = 15,
        consecutive_loss_cooldowns: dict[int, int] | None = None,
        consecutive_loss_halt: int = 5,
        min_score: int = 65,
    ) -> None:
        self.max_trades = max_trades_per_day
        self.max_losses = max_losses_per_day
        self.max_loss_pct = max_daily_loss_pct
        self.max_profit_pct = max_daily_profit_pct
        self.min_minutes_between = min_minutes_between_trades
        # consecutive-loss count -> cooldown minutes
        self.cooldowns = consecutive_loss_cooldowns or {2: 30, 3: 120, 4: 1440}
        self.cl_halt = consecutive_loss_halt
        self.min_score = min_score

        self.day_pnl: float = 0.0
        self.day_pnl_pct: float = 0.0
        self.day_trades: int = 0
        self.day_losses: int = 0
        self.day_anchor: datetime | None = None
        self.consecutive_losses: int = 0
        self.cooldown_until: datetime | None = None
        self.strategy_halts: dict[str, datetime] = {}
        self.last_trade_ts: datetime | None = None
        self.recent_trades: list[TradeRecord] = []

    # ----------------------------------------------------------------- day roll

    def _roll_day(self, now: datetime) -> None:
        if self.day_anchor is None or now.date() != self.day_anchor.date():
            self.day_anchor = datetime.combine(now.date(), time(0, 0, tzinfo=timezone.utc))
            self.day_pnl = 0.0
            self.day_pnl_pct = 0.0
            self.day_trades = 0
            self.day_losses = 0

    # ----------------------------------------------------------------- record

    def record_trade(self, trade: TradeRecord, equity_before: float) -> None:
        self._roll_day(trade.ts_close)
        self.day_pnl += trade.pnl
        self.day_pnl_pct = (self.day_pnl / equity_before * 100.0) if equity_before else 0.0
        self.day_trades += 1
        self.last_trade_ts = trade.ts_close
        if trade.pnl < 0:
            self.day_losses += 1
            self.consecutive_losses += 1
            mins = self.cooldowns.get(self.consecutive_losses)
            if mins:
                self.cooldown_until = trade.ts_close + timedelta(minutes=mins)
            if self.consecutive_losses >= self.cl_halt:
                self.strategy_halts[trade.strategy] = trade.ts_close + timedelta(hours=24)
        else:
            self.consecutive_losses = 0
            self.cooldown_until = None
        self.recent_trades.append(trade)
        if len(self.recent_trades) > 50:
            self.recent_trades = self.recent_trades[-50:]

    # ----------------------------------------------------------------- can_open

    def can_open(
        self,
        strategy: str,
        now: datetime | None = None,
        score: int = 100,
    ) -> SessionDecision:
        now = now or datetime.now(timezone.utc)
        self._roll_day(now)

        if self.day_trades >= self.max_trades:
            return SessionDecision(False, "daily trade cap reached")
        if self.day_losses >= self.max_losses:
            return SessionDecision(False, "daily loss-count cap reached")
        if self.day_pnl_pct <= -self.max_loss_pct:
            return SessionDecision(False, f"daily loss limit {self.max_loss_pct}% reached")
        if self.day_pnl_pct >= self.max_profit_pct:
            return SessionDecision(False, f"daily profit limit {self.max_profit_pct}% reached")
        if self.cooldown_until and now < self.cooldown_until:
            return SessionDecision(False, "consecutive-loss cooldown", cooldown_until=self.cooldown_until)
        if self.last_trade_ts and (now - self.last_trade_ts).total_seconds() < self.min_minutes_between * 60:
            return SessionDecision(False, "min-time-between-trades not elapsed")
        halt_until = self.strategy_halts.get(strategy)
        if halt_until and now < halt_until:
            return SessionDecision(False, f"strategy '{strategy}' halted until {halt_until.isoformat()}")
        if self.detect_tilt(score):
            return SessionDecision(False, "tilt detected", on_tilt=True, cooldown_until=now + timedelta(hours=4))
        return SessionDecision(True)

    # ----------------------------------------------------------------- tilt

    def detect_tilt(self, latest_score: int = 100) -> bool:
        """Flag tilt if recent behaviour matches any of these patterns over the
        last 5 trades:

        - average hold time shrank > 50% vs the prior 20-trade baseline
        - position size increased right after a loss
        - any two trades were spaced less than 5 minutes apart
        - any recent trade was taken on a weak (< ``min_score``) signal
        """
        if len(self.recent_trades) < 5:
            return False
        last5 = self.recent_trades[-5:]
        baseline = self.recent_trades[-25:-5] if len(self.recent_trades) >= 25 else self.recent_trades
        baseline_hold = mean(t.duration_minutes for t in baseline) if baseline else 0
        last5_hold = mean(t.duration_minutes for t in last5)
        if baseline_hold > 0 and last5_hold < 0.5 * baseline_hold:
            return True

        sizes = [t.position_size_units for t in last5]
        for i in range(1, len(sizes)):
            if last5[i - 1].pnl < 0 and sizes[i] > sizes[i - 1] * 1.1:
                return True

        gaps = [
            (last5[i].ts_open - last5[i - 1].ts_close).total_seconds()
            for i in range(1, len(last5))
        ]
        if gaps and min(gaps) < 5 * 60:
            return True

        if any(t.score < self.min_score for t in last5):
            return True

        if latest_score and latest_score < self.min_score:
            return True

        return False
