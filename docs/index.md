# riskkit

**A framework-agnostic risk-management toolkit for systematic traders.**

Most open-source trading tools focus on the fun part — signals, indicators,
backtesting engines. They leave the part that decides whether you survive thin:
*how big a position to take, where stops live, when to cut size, and when to
stop trading altogether.* That's what blows up retail algo traders, not a bad
entry signal.

riskkit is that missing layer. Every component is pure Python with **no
dependency on any exchange, data provider, or backtesting framework**. You feed
it numbers; it hands back auditable decisions you can drop into
[backtesting.py](https://github.com/kernc/backtesting.py),
[vectorbt](https://github.com/polakowo/vectorbt),
[freqtrade](https://github.com/freqtrade/freqtrade), or your own loop.

!!! warning "Not financial advice"
    riskkit helps you *implement* a risk policy you have chosen. It cannot make a
    losing strategy profitable. Test everything on paper first.

## Install

```bash
# Until the PyPI release lands, install from GitHub:
pip install "git+https://github.com/HasibVortex369/riskkit.git"
# with dynamic correlation (adds pandas):
pip install "riskkit[pandas] @ git+https://github.com/HasibVortex369/riskkit.git"
```

## The six components

| Component | What it does |
|---|---|
| `PositionSizer` | Volatility-adjusted sizing with a half-Kelly ceiling and a reduction ladder. |
| `DrawdownManager` | Drawdown tier ladder: cut size → raise the bar → halt, with a recovery ramp. |
| `StopEngine` | Composable per-position stop stack; tightest stop wins, stops only tighten. |
| `CorrelationGuard` | One open position per correlation group (static + dynamic). |
| `SessionManager` | Daily caps, cooldowns, and tilt detection. |
| `PreTradeValidator` | The composable final gate that vetoes a trade if any rule fails. |

Want all six working together? The **`RiskManager`** façade wires them from one
config and turns a single `TradeIntent` into a sized, validated decision — see
[Quickstart](quickstart.md).
