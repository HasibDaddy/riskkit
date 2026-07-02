# Integrations

riskkit is framework-agnostic, so it slots into whatever you already use.

## backtesting.py

The first-class way is the **`RiskkitStrategy` adapter**: subclass it, write your
signals in `next()` as usual, and call `risk_long()` / `risk_short()` instead of
`self.buy` / `self.sell`. Every entry is then sized **and** validated by your one
`RiskConfig` — and closed trades are fed back to the session manager, so streaks,
cooldowns, and drawdown halts are live through the backtest.

```bash
pip install "riskkit-quant[backtesting]"
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
[`examples/backtesting_riskmanager.py`](https://github.com/HasibVortex369/riskkit/blob/main/examples/backtesting_riskmanager.py)
(on the bundled GOOG data the risk layer holds max drawdown to ~1.5% while staying
net positive). Prefer to wire a single component yourself?
[`examples/backtesting_py_strategy.py`](https://github.com/HasibVortex369/riskkit/blob/main/examples/backtesting_py_strategy.py)
drives sizing straight from `PositionSizer`. The signal is a plain SMA crossover
in both — the point is that the risk layer is identical no matter what you swap in.

## freqtrade

`FreqtradeRiskManager` adapts riskkit to freqtrade's callbacks — it imports
nothing from freqtrade, so you compose it into your own `IStrategy`:

```python
from riskkit import RiskConfig
from riskkit.adapters.freqtrade import FreqtradeRiskManager

class MyStrategy(IStrategy):
    def bot_start(self):
        self.risk = FreqtradeRiskManager(RiskConfig.balanced())

    def custom_stake_amount(self, pair, current_time, current_rate,
                            proposed_stake, min_stake, max_stake,
                            leverage, entry_tag, side, **kwargs):
        info = self.custom_info[pair]
        return self.risk.stake_amount(
            pair=pair, side=side,
            equity=self.wallets.get_total_stake_amount(),
            current_rate=current_rate, stop_price=info["stop_price"],
            max_stake=max_stake, min_stake=min_stake,
            score=info.get("score", 100), now=current_time,
        )

    def confirm_trade_entry(self, pair, *args, **kwargs):
        allowed = self.risk.confirm_entry(pair)
        if allowed:
            self.risk.on_fill(pair)
        return allowed
```

A returned stake of `0.0` makes freqtrade skip the entry, so sizing and the veto
can both live in `custom_stake_amount`. Call `on_fill()` / `on_exit()` so
cross-pair correlation, exposure, and session state stay current. Full snippet:
[`examples/freqtrade_callbacks.py`](https://github.com/HasibVortex369/riskkit/blob/main/examples/freqtrade_callbacks.py).

## vectorbt

vectorbt is vectorized, so riskkit slots in at the *sizing* step: turn entry
signals into a size array with `size_signals`, then pass it to
`Portfolio.from_signals`:

```python
from riskkit.adapters.vectorbt import size_signals

sizes = size_signals(
    equity=10_000,
    entry_prices=close.where(entries),     # price where entering, else NaN
    stop_prices=close * 0.97,
    atr=atr, atr_baseline=atr.rolling(100).mean(),
)
pf = vbt.Portfolio.from_signals(close, entries, exits,
                                size=sizes, size_type="value")
```

The stateful guards (drawdown halting, session caps) don't vectorize — step
through bars with the `RiskManager` for those. Runnable demo:
[`examples/vectorbt_sizing.py`](https://github.com/HasibVortex369/riskkit/blob/main/examples/vectorbt_sizing.py).

## Your own loop

Nothing about riskkit assumes a framework. The
[`examples/pipeline.py`](https://github.com/HasibVortex369/riskkit/blob/main/examples/pipeline.py)
walkthrough wires drawdown posture → sizing → validation into a single
`decide_trade()` function you can call from any event loop.
