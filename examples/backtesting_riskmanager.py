"""Integration example: the full RiskManager façade inside backtesting.py.

Run it:  pip install "riskkit[backtesting]" && python examples/backtesting_riskmanager.py

`backtesting_py_strategy.py` wires `PositionSizer` in by hand. This does the same
with the *whole* stack via the `RiskkitStrategy` adapter: one `RiskConfig`, and
every entry is sized **and** validated (drawdown laddering, session caps, the
pre-trade checklist), with closed trades fed back so the session state stays live
through the run. The signal is a plain SMA crossover — swap in your own; the risk
layer is unchanged.
"""
from backtesting import Backtest
from backtesting.lib import crossover
from backtesting.test import GOOG, SMA

from riskkit import RiskConfig
from riskkit.adapters.backtesting import RiskkitStrategy


class RiskkitSMA(RiskkitStrategy):
    fast, slow = 10, 30
    risk_config = RiskConfig(
        base_risk_pct=2.0,
        max_notional_pct=15.0,
        drawdown=dict(tier1_pct=3, halt_pct=12),
    )

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.sma_fast, self.sma_slow) and not self.position:
            # One call: riskkit sizes the position and runs the full pre-trade gate.
            self.risk_long(stop_price=price * 0.97, target_price=price * 1.06, score=80)
        elif crossover(self.sma_slow, self.sma_fast) and self.position:
            self.position.close()


if __name__ == "__main__":
    bt = Backtest(GOOG, RiskkitSMA, cash=100_000, commission=0.002)
    stats = bt.run()
    for key in ["Return [%]", "Max. Drawdown [%]", "# Trades", "Win Rate [%]", "Sharpe Ratio"]:
        print(f"{key:>20}: {stats[key]:.2f}")
