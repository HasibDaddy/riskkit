"""Tests for the backtesting.py adapter.

Skipped automatically when backtesting.py isn't installed (it's an optional
extra: ``pip install "riskkit[backtesting]"``).
"""
import pytest

pytest.importorskip("backtesting")

from backtesting import Backtest
from backtesting.lib import crossover
from backtesting.test import GOOG, SMA

from riskkit import RiskConfig
from riskkit.adapters.backtesting import RiskkitStrategy


class _SmaCross(RiskkitStrategy):
    risk_config = RiskConfig(base_risk_pct=2.0, max_notional_pct=15.0)

    def init(self):
        self.fast = self.I(SMA, self.data.Close, 10)
        self.slow = self.I(SMA, self.data.Close, 30)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.fast, self.slow) and not self.position:
            self.risk_long(stop_price=price * 0.97, target_price=price * 1.06, score=80)
        elif crossover(self.slow, self.fast) and self.position:
            self.position.close()


def _bt():
    return Backtest(GOOG, _SmaCross, cash=100_000, commission=0.002)


def test_adapter_sizes_and_trades():
    stats = _bt().run()
    assert stats["# Trades"] > 0                      # riskkit sized real entries
    assert stats["Max. Drawdown [%]"] > -25           # notional cap keeps DD modest


def test_riskkit_gates_entries_in_the_loop():
    # An impossible score floor must veto every entry → zero trades, proving the
    # validator runs inside the backtest loop.
    blocked = _bt().run(risk_config=RiskConfig(
        max_notional_pct=15.0, validator=dict(min_score=101),
    ))
    assert int(blocked["# Trades"]) == 0


def test_closed_trades_feed_the_session():
    stats = _bt().run()
    strat = stats["_strategy"]
    # Closed round-trips were ingested back into the session manager.
    assert len(strat.risk.session.recent_trades) > 0
