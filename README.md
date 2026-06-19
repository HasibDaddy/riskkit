# riskkit

**A framework-agnostic risk-management toolkit for systematic traders.**

Most open-source trading tools focus on the fun part — signals, indicators,
backtesting engines. They leave the part that actually decides whether you
survive thin or absent: *how big a position to take, when to cut size, and when
to stop trading altogether.* That's what blows up retail algo traders, not a
bad entry signal.

`riskkit` is that missing layer. The components are pure Python with **no
dependency on any exchange, data provider, or backtesting framework**. They
don't know what CCXT is. You feed them numbers; they hand back decisions you can
audit. Drop them into [backtesting.py](https://github.com/kernc/backtesting.py),
[vectorbt](https://github.com/polakowo/vectorbt), [backtrader](https://github.com/mementum/backtrader),
[freqtrade](https://github.com/freqtrade/freqtrade), or your own loop.

> ⚠️ **Not financial advice.** `riskkit` helps you *implement* a risk policy you
> have chosen. It does not choose one for you, and it cannot make a losing
> strategy profitable. Test everything on paper first.

---

## Install

```bash
pip install riskkit
```

Zero runtime dependencies. Python 3.9+.

---

## What's in the box

| Component | What it does |
|---|---|
| `PositionSizer` | Volatility-adjusted fixed-fractional sizing with an optional half-Kelly ceiling, a reduction ladder for losing streaks / drawdowns, and a hard notional cap. |
| `DrawdownManager` | Tracks high-water-mark drawdown, maps it onto a tier ladder (cut size → raise the bar → halt), with a recovery ramp and a rolling weekly-loss pause. |
| `StopEngine` | A composable stop *stack* per position — initial, break-even, ATR trailing, EMA trailing, time, and volatility stops. The tightest one wins; stops only ever move closer. |
| `CorrelationGuard` | At most one open position per correlation group. Groups can be static (you define them) or computed dynamically from a rolling return-correlation matrix. |
| `SessionManager` | Daily trade/loss caps, profit-taking stops, minimum spacing, escalating cooldowns after losing streaks, and tilt detection. |
| `PreTradeValidator` | The composable final gate: runs every rule against a proposed trade and vetoes it if any fails — returning exactly which checks passed and failed. |

Every decision is **auditable** — the sizer returns which multipliers fired,
the stop engine logs each adjustment, and the validator returns a pass/fail line
for every single check.

---

## Quick start

### Sizing a trade

```python
from riskkit import PositionSizer, SizingInputs

sizer = PositionSizer(
    base_risk_pct=1.0,      # risk 1% of equity per trade, before adjustments
    max_risk_pct=1.5,       # never risk more than 1.5%
    max_notional_pct=4.0,   # never let a position exceed 4% of equity
)

result = sizer.size(SizingInputs(
    equity=10_000,
    entry_price=100.0,
    stop_price=98.0,        # the stop distance defines your risk per unit
    atr=2.5,                # current volatility
    atr_baseline=2.0,       # "normal" volatility -> scales risk down when choppy
    consecutive_losses=2,   # reduction ladder kicks in
    drawdown_pct=4.0,
))

if result.units > 0:
    print(f"Buy {result.units:.4f} units (risk {result.risk_pct:.2%})")
    print("adjustments:", result.multipliers_applied)
else:
    print("Skip:", result.reason_for_zero)
```

### Adapting to drawdown

```python
from riskkit import DrawdownManager

dm = DrawdownManager(tier1_pct=3, tier2_pct=5, tier3_pct=7, halt_pct=10)

state = dm.update(current_equity)   # call once per equity refresh
if state.halted:
    print("No new trades:", state.reason)
else:
    size = base_size * state.size_multiplier   # scale every position by the tier
```

The two compose naturally: feed `DrawdownManager`'s `drawdown_pct` and
`size_multiplier` straight into the sizer.

---

## Design principles

- **Framework-agnostic.** No exchange SDK, no pandas requirement in the core,
  no global state. Just dataclasses in, dataclasses out.
- **Auditable, not magic.** Every adjustment is named and returned. You can log
  the exact reason a trade was sized down or skipped.
- **Conservative by default.** Floors, ceilings, and hard caps bound every knob.
  The math can recommend; it can never exceed the limits you set.
- **Anti-martingale.** Size goes *down* after losses and during drawdowns, never
  up. There is no "average down" path anywhere in this library.

---

## Roadmap

`riskkit` is extracted and generalized from a working risk-first trading bot.
The core six components are in place; next up is making them effortless to drop
into the popular frameworks:

- [x] `PositionSizer`, `DrawdownManager`, `StopEngine`
- [x] `CorrelationGuard`, `SessionManager`, `PreTradeValidator`
- [ ] First-class adapters / examples for backtesting.py, vectorbt, and freqtrade
- [ ] A hosted docs site with end-to-end recipes
- [ ] A single `RiskManager` façade that wires all six together with one config

Feedback on the API is genuinely welcome — open an issue. See
[CONTRIBUTING.md](CONTRIBUTING.md) and the [examples](examples/).

---

## License

MIT © 2026 Hasib. See [LICENSE](LICENSE).
