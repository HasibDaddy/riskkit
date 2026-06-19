"""Integration example: riskkit driving position size inside backtesting.py.

Run it:  pip install backtesting && python examples/backtesting_py_strategy.py

The strategy logic (an SMA crossover) is deliberately boring — the point is that
*every* entry is sized by riskkit's PositionSizer from live equity and a
volatility estimate, and the stop comes from the same risk model. Swap in your
own signals; the risk layer stays identical.
"""
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import GOOG, SMA
import pandas as pd

from riskkit import PositionSizer, SizingInputs


def rolling_std(values, n):
    """A cheap volatility proxy standing in for ATR."""
    return pd.Series(values).rolling(n).std().bfill().values


class RiskkitSMA(Strategy):
    fast, slow = 10, 30

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)
        self.vol = self.I(rolling_std, close, 14)
        self.vol_base = self.I(rolling_std, close, 100)
        # One sizer for the whole run; risk policy lives here, not in the signal.
        self.sizer = PositionSizer(base_risk_pct=2.0, max_notional_pct=15.0)

    def next(self):
        price = self.data.Close[-1]
        vol, base = self.vol[-1], self.vol_base[-1]

        if crossover(self.sma_fast, self.sma_slow) and not self.position and vol > 0:
            stop = price - 2 * vol
            sized = self.sizer.size(SizingInputs(
                equity=self.equity,
                entry_price=price,
                stop_price=stop,
                atr=vol,
                atr_baseline=base if base > 0 else vol,
            ))
            if sized.units > 0:
                fraction = min(0.99, sized.notional / self.equity)
                if fraction > 0:
                    self.buy(size=fraction, sl=stop)

        elif crossover(self.sma_slow, self.sma_fast) and self.position:
            self.position.close()


if __name__ == "__main__":
    bt = Backtest(GOOG, RiskkitSMA, cash=100_000, commission=0.002)
    stats = bt.run()
    for key in ["Return [%]", "Max. Drawdown [%]", "# Trades", "Win Rate [%]", "Sharpe Ratio"]:
        print(f"{key:>20}: {stats[key]:.2f}")
