"""backtesting.py adapter — risk-managed entries via a Strategy mixin.

`RiskkitStrategy` wires a :class:`riskkit.RiskManager` into a
`backtesting.py <https://kernc.github.io/backtesting.py/>`_ strategy. Subclass it,
write your signal logic in ``next()`` as usual, and call :meth:`risk_long` /
:meth:`risk_short` instead of ``self.buy`` / ``self.sell``. Every entry is then
sized and validated by your single ``RiskConfig`` — drawdown laddering, session
caps, correlation/exposure limits, and the pre-trade checklist all apply, and the
result is converted into a backtesting.py order for you.

Closed trades are fed back into the session manager automatically, so streaks,
cooldowns, and the daily-loss state are live during the backtest — a drawdown
that crosses your halt threshold will stop new entries, exactly as it would in
production.

Requires backtesting.py:  ``pip install "riskkit[backtesting]"``

Example::

    from riskkit import RiskConfig
    from riskkit.adapters.backtesting import RiskkitStrategy
    from backtesting import Backtest
    from backtesting.lib import crossover
    from backtesting.test import GOOG, SMA

    class SmaCross(RiskkitStrategy):
        risk_config = RiskConfig(base_risk_pct=2.0, max_notional_pct=15.0)

        def init(self):
            self.fast = self.I(SMA, self.data.Close, 10)
            self.slow = self.I(SMA, self.data.Close, 30)

        def next(self):
            price = self.data.Close[-1]
            if crossover(self.fast, self.slow) and not self.position:
                self.risk_long(stop_price=price * 0.97, target_price=price * 1.06)
            elif crossover(self.slow, self.fast) and self.position:
                self.position.close()

    Backtest(GOOG, SmaCross, cash=100_000, commission=0.002).run()
"""
from __future__ import annotations

from datetime import datetime

from backtesting import Strategy

from ..manager import RiskConfig, RiskDecision, RiskManager, TradeIntent
from ..session import TradeRecord


class RiskkitStrategy(Strategy):
    """A backtesting.py ``Strategy`` mixin that routes entries through riskkit.

    Override these class attributes to configure it:

    - ``risk_config``       — the :class:`~riskkit.RiskConfig` for this strategy.
    - ``risk_symbol``       — symbol used for correlation grouping (default ``"ASSET"``).
    - ``risk_strategy``     — strategy name recorded on trades (default ``"default"``).
    - ``risk_max_fraction`` — cap on the equity fraction sent to one order
      (default ``0.99``; backtesting.py cannot invest more than available cash).
    """

    risk_config: RiskConfig | None = None
    risk_symbol: str = "ASSET"
    risk_strategy: str = "default"
    risk_max_fraction: float = 0.99

    def init(self) -> None:
        """No-op by default — override to declare your indicators."""

    # ------------------------------------------------------------------ internals

    @property
    def risk(self) -> RiskManager:
        """The :class:`~riskkit.RiskManager`, created lazily on first use."""
        mgr = getattr(self, "_risk_mgr", None)
        if mgr is None:
            mgr = self._risk_mgr = RiskManager(self.risk_config or RiskConfig())
            self._closed_seen = 0
        return mgr

    def _now(self) -> datetime | None:
        ts = self.data.index[-1]
        return ts if isinstance(ts, datetime) else None

    def _ingest_closed(self) -> None:
        """Feed any newly-closed backtesting.py trades into the session manager."""
        mgr = self.risk
        trades = self.closed_trades
        equity = float(self.equity)
        while self._closed_seen < len(trades):
            t = trades[self._closed_seen]
            self._closed_seen += 1
            duration = 0.0
            if isinstance(t.entry_time, datetime) and isinstance(t.exit_time, datetime):
                duration = (t.exit_time - t.entry_time).total_seconds() / 60.0
            mgr.on_close(
                TradeRecord(
                    ts_open=t.entry_time, ts_close=t.exit_time,
                    pnl=float(t.pl), pnl_pct=float(t.pl_pct) * 100.0,
                    score=100, position_size_units=abs(float(t.size)),
                    duration_minutes=duration,
                    side="long" if t.is_long else "short",
                    symbol=self.risk_symbol, strategy=self.risk_strategy,
                ),
                equity_before=equity,
            )

    def _enter(
        self, side: str, entry_price, stop_price, target_price,
        score: int, atr: float, atr_baseline: float, intent_kwargs: dict,
    ) -> RiskDecision:
        now = self._now()
        self._ingest_closed()                  # reflect any closes before we size
        equity = float(self.equity)
        self.risk.on_equity(equity, now=now)
        price = float(self.data.Close[-1] if entry_price is None else entry_price)

        decision = self.risk.evaluate(
            TradeIntent(
                symbol=self.risk_symbol, side=side,
                entry_price=price, stop_price=float(stop_price),
                target_price=float(target_price), score=score,
                atr=atr, atr_baseline=atr_baseline, **intent_kwargs,
            ),
            now=now,
        )

        if decision.ok and equity > 0:
            fraction = min(self.risk_max_fraction, decision.notional / equity)
            if fraction > 0:
                place = self.buy if side == "long" else self.sell
                place(size=fraction, sl=float(stop_price), tp=float(target_price))
                self.risk.on_fill(decision, strategy=self.risk_strategy)
        return decision

    # ------------------------------------------------------------------ public API

    def risk_long(
        self, *, stop_price, target_price, entry_price=None,
        score: int = 100, atr: float = 0.0, atr_baseline: float = 0.0,
        **intent_kwargs,
    ) -> RiskDecision:
        """Attempt a risk-sized, validated long. Returns the :class:`RiskDecision`.

        ``entry_price`` defaults to the current close. Extra keyword arguments are
        forwarded to :class:`~riskkit.TradeIntent` (e.g. ``win_rate`` for Kelly,
        ``spread_pct`` for the market-quality gate).
        """
        return self._enter(
            "long", entry_price, stop_price, target_price,
            score, atr, atr_baseline, intent_kwargs,
        )

    def risk_short(
        self, *, stop_price, target_price, entry_price=None,
        score: int = 100, atr: float = 0.0, atr_baseline: float = 0.0,
        **intent_kwargs,
    ) -> RiskDecision:
        """Attempt a risk-sized, validated short. Returns the :class:`RiskDecision`."""
        return self._enter(
            "short", entry_price, stop_price, target_price,
            score, atr, atr_baseline, intent_kwargs,
        )
