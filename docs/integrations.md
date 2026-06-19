# Integrations

riskkit is framework-agnostic, so it slots into whatever you already use.

## backtesting.py

[`examples/backtesting_py_strategy.py`](https://github.com/USERNAME/riskkit/blob/main/examples/backtesting_py_strategy.py)
is a runnable strategy where **every entry is sized by riskkit's `PositionSizer`**
from live equity and a volatility estimate, with the stop coming from the same
risk model:

```bash
pip install backtesting
python examples/backtesting_py_strategy.py
```

The signal logic is a plain SMA crossover — the point is that the risk layer is
identical no matter what signals you swap in.

## freqtrade

[`examples/freqtrade_callbacks.py`](https://github.com/USERNAME/riskkit/blob/main/examples/freqtrade_callbacks.py)
shows riskkit driving `custom_stake_amount` so freqtrade stakes each trade
according to your risk model instead of a flat amount.

## Your own loop

Nothing about riskkit assumes a framework. The
[`examples/pipeline.py`](https://github.com/USERNAME/riskkit/blob/main/examples/pipeline.py)
walkthrough wires drawdown posture → sizing → validation into a single
`decide_trade()` function you can call from any event loop.
