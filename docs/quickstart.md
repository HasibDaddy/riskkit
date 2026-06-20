# Quickstart

## The whole stack, one call

`RiskManager` is the façade over all six components. Build it once from a single
`RiskConfig`, push equity in as your account moves, and ask one question per
trade — it keeps the drawdown, session, and open-position state in sync for you.

```python
from riskkit import RiskManager, RiskConfig, TradeIntent

risk = RiskManager(RiskConfig(
    base_risk_pct=1.0, max_notional_pct=4.0,
    drawdown=dict(tier1_pct=3, halt_pct=10),
    session=dict(max_trades_per_day=5),
    correlation=dict(static_groups={"majors": {"BTC/USDT", "ETH/USDT"}}),
))

risk.on_equity(10_000)                              # refresh drawdown/session state
decision = risk.evaluate(TradeIntent(
    symbol="BTC/USDT", side="long",
    entry_price=100.0, stop_price=98.0, target_price=104.0,
    score=82, atr=2.0, atr_baseline=2.0,
))

if decision.ok:
    place(decision.units, decision.stop)           # your execution layer
    risk.on_fill(decision)                          # tell riskkit it filled
else:
    print("skip:", decision.reasons)                # every gate that vetoed it
```

When a position closes, hand the round-trip back so the session's streak,
daily-loss, and cooldown state stays current:

```python
risk.on_close(trade_record, equity_before=10_000)
```

The full runnable demo is in
[`examples/risk_manager.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/risk_manager.py).
Prefer to wire the components yourself? Everything below still works standalone.

## Sizing a trade

```python
from riskkit import PositionSizer, SizingInputs

sizer = PositionSizer(base_risk_pct=1.0, max_risk_pct=1.5, max_notional_pct=4.0)

result = sizer.size(SizingInputs(
    equity=10_000,
    entry_price=100.0,
    stop_price=98.0,     # the stop distance defines your risk per unit
    atr=2.5,             # current volatility
    atr_baseline=2.0,    # "normal" volatility -> scales risk down when choppy
    consecutive_losses=2,
    drawdown_pct=4.0,
))

if result.units > 0:
    print(f"Buy {result.units:.4f} units (risk {result.risk_pct:.2%})")
    print("adjustments:", result.multipliers_applied)
else:
    print("Skip:", result.reason_for_zero)
```

## Adapting to drawdown

```python
from riskkit import DrawdownManager

dm = DrawdownManager(tier1_pct=3, tier2_pct=5, tier3_pct=7, halt_pct=10)

state = dm.update(current_equity)   # call once per equity refresh
if state.halted:
    print("No new trades:", state.reason)
else:
    size = base_size * state.size_multiplier
```

## Wiring it all together by hand

The [`RiskManager`](#the-whole-stack-one-call) façade above does this wiring for
you. To assemble the flow yourself — drawdown posture → sizing → final-gate
validation — see
[`examples/pipeline.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/pipeline.py).
