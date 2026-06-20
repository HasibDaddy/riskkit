# Quickstart

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

## Wiring it all together

See [`examples/pipeline.py`](https://github.com/HasibDaddy/riskkit/blob/main/examples/pipeline.py)
for the full flow: drawdown posture → sizing → final-gate validation.
