# Integrations

riskkit is framework-agnostic, so it slots into whatever you already use.

## backtesting.py

The first-class way is the **`RiskkitStrategy` adapter**: subclass it, write your
signals in `next()` as usual, and call `risk_long()` / `risk_short()` instead of
`self.buy` / `self.sell`. Every entry is then sized **and** validated by your one
`RiskConfig` — and closed trades are fed back to the session manager, so streaks,
cooldowns, and drawdown halts are live through the backtest.

```bash
pip install "riskkit[backtesting]"
```

```python
from riskkit import RiskConfig
from riskkit.adapters.backtesting import RiskkitStrategy
from backtesting.lib import crossover
from backtesting.test import SMA

class SmaCross(RiskkitStrategy):
    risk_config = RiskConfig(base_risk_pct=2.0, max_notional_pct=15.0,
                             drawdown=dict(tier1_pct=3, halt_pct=12))

    def init(self):
        self.fast = self.I(SMA, self.data.Close, 10)
        self.slow = self.I(SMA, self.data.Close, 30)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.fast, self.slow) and not self.position:
            self.risk_long(stop_price=price * 0.97, target_price=price * 1.06)
        elif crossover(self.slow, self.fast) and self.position:
            self.position.close()
```

The full runnable demo is
[`examples/backtesting_riskmanager.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/backtesting_riskmanager.py)
(on the bundled GOOG data the risk layer holds max drawdown to ~1.5% while staying
net positive). Prefer to wire a single component yourself?
[`examples/backtesting_py_strategy.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/backtesting_py_strategy.py)
drives sizing straight from `PositionSizer`. The signal is a plain SMA crossover
in both — the point is that the risk layer is identical no matter what you swap in.

## freqtrade

[`examples/freqtrade_callbacks.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/freqtrade_callbacks.py)
shows riskkit driving `custom_stake_amount` so freqtrade stakes each trade
according to your risk model instead of a flat amount.

## Your own loop

Nothing about riskkit assumes a framework. The
[`examples/pipeline.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/pipeline.py)
walkthrough wires drawdown posture → sizing → validation into a single
`decide_trade()` function you can call from any event loop.
