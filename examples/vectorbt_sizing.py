"""Integration example: sizing vectorbt signals with riskkit.

Run it:  python examples/vectorbt_sizing.py   (no vectorbt needed for this demo)

vectorbt is vectorized, so riskkit slots in at the *sizing* step: turn your entry
signals into an array of position sizes with `size_signals`, then hand that to
`vbt.Portfolio.from_signals(..., size=sizes, size_type="value")`. The helper is
plain Python — this script runs without vectorbt installed to show the sizes it
produces; the vectorbt call is shown at the bottom.
"""
from riskkit import PositionSizer
from riskkit.adapters.vectorbt import size_signals

# A tiny synthetic series: enter when price closes above a threshold.
close = [100.0, 101.5, 99.0, 103.0, 98.5, 105.0]
entries_mask = [c > 102 for c in close]

# Entry price where we enter, else NaN; a fixed 3%-below stop on every bar.
nan = float("nan")
entry_prices = [c if m else nan for c, m in zip(close, entries_mask)]
stop_prices = [c * 0.97 for c in close]

sizer = PositionSizer(base_risk_pct=1.0, max_notional_pct=5.0)
sizes = size_signals(
    equity=10_000,
    entry_prices=entry_prices,
    stop_prices=stop_prices,
    sizer=sizer,
    return_fraction=True,          # fraction of equity -> vectorbt size_type="value"
)

print("bar  close   entry?   size(frac of equity)")
for i, c in enumerate(close):
    print(f"{i:>3}  {c:>6.1f}   {str(entries_mask[i]):<6}   {sizes[i]:.4f}")

# With vectorbt installed you would then run:
#
#   import vectorbt as vbt
#   import pandas as pd
#   px = pd.Series(close)
#   pf = vbt.Portfolio.from_signals(
#       px, entries=pd.Series(entries_mask), exits=~pd.Series(entries_mask),
#       size=pd.Series(sizes), size_type="value", init_cash=10_000,
#   )
#   print(pf.stats())
