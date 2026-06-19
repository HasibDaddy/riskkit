"""riskkit — a framework-agnostic risk-management toolkit for systematic traders.

riskkit is the layer most backtesters and trading bots leave thin: how big a
position to take, when to cut size, and when to stop trading altogether. The
components are pure Python with no dependency on any exchange, data provider, or
backtesting framework — feed them numbers, get back decisions.

Quick start::

    from riskkit import PositionSizer, SizingInputs

    sizer = PositionSizer(base_risk_pct=1.0, max_notional_pct=4.0)
    result = sizer.size(SizingInputs(
        equity=10_000, entry_price=100, stop_price=98,
        atr=2.0, atr_baseline=2.0,
    ))
    print(result.units, result.risk_pct)
"""
from __future__ import annotations

from .drawdown import DrawdownManager, DrawdownState
from .sizing import PositionSizer, SizingInputs, SizingResult

__version__ = "0.1.0"

__all__ = [
    "PositionSizer",
    "SizingInputs",
    "SizingResult",
    "DrawdownManager",
    "DrawdownState",
    "__version__",
]
